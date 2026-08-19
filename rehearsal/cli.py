"""Detect, review and export songs from rehearsal recordings."""

import argparse
import sys
from pathlib import Path

from . import card, picker, setlist, settings, state, tools
from .audio import discover, envelopes
from .detect import calibrate, count_ins, loud_spans, songs, tuning
from .export import already_filed, archive_folder, publish, stage
from .review import review_session

INBOX = settings.path("inbox")
ARCHIVE = settings.path("archive")
SONGLIST = settings.path("songlist")
CARD = settings.path("card")
WORK = "work"


def clock(seconds):
    hours, rest = divmod(seconds, 3600)
    minutes, remainder = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{remainder:05.2f}"


def analyse(session):
    thresholds = tuning(session.recorder)
    measured = [(take, *envelopes(take)) for take in session.takes]
    calibration = calibrate([level for _, level, _ in measured], thresholds)
    found = {}
    for take, level, onset in measured:
        spans = loud_spans(level, calibration)
        marks = count_ins(onset, level, calibration)
        found[take.name] = songs(spans, marks, take.duration, thresholds)
    return calibration, found


def report(session, calibration, found, verbose):
    print(f"\n=== {session.date}  {session.recorder}  {len(session.takes)} take(s)  "
          f"{session.duration / 60:.1f} min ===")
    print(f"    silence < {calibration.floor:.1f} dB < talking "
          f"({calibration.quiet_mean:.1f}) < {calibration.split:.1f} dB < playing "
          f"({calibration.loud_mean:.1f})")
    if not calibration.reliable:
        print("    WARNING: level classes are not well separated; treat results as guesses")

    for take in session.takes:
        detected = found[take.name]
        if verbose:
            print(f"\n  {take.name}  {take.duration / 60:5.1f} min  "
                  f"{len(take.paths)} part(s)  {len(detected)} segment(s)")
        for song in detected:
            bpm = f"{song.bpm:5.1f} BPM" if song.bpm else "         "
            print(f"    {clock(song.start)} - {clock(song.end)}  "
                  f"{song.duration:6.1f}s  {song.confidence:6}  {song.origin:7}  {bpm}")
    total = sum(len(v) for v in found.values())
    print(f"\n  {total} song(s) detected for {session.date}")


def process(session, args):
    """Review one rehearsal. Returns a line for the launch screen's status."""
    if not sys.stdin.isatty():
        raise RuntimeError(
            "naming needs an interactive terminal, and stdin is not one.\n"
            "Run this from a terminal. In PyCharm, tick "
            "'Emulate terminal in output console' in the run configuration.\n"
            "To only see the boundaries, use the detect command instead."
        )
    when = picker.spaced(session.date)
    calibration, found = analyse(session)
    if not sum(len(segments) for segments in found.values()):
        note = "" if calibration.reliable else ", and its levels never separate"
        return f"{when}: no songs detected{note}"

    titles = setlist.load(args.songlist)
    scratch = args.inbox / WORK / session.date
    scratch.mkdir(parents=True, exist_ok=True)

    named, verdict = review_session(session, found, titles, scratch,
                                    state.load(scratch),
                                    lambda entries: state.save(scratch, session.date, entries))
    if verdict != "encode":
        return f"{when}: {len(named)} name(s) saved, nothing encoded"
    if not named:
        return f"{when}: nothing named"

    folder = archive_folder(args.archive, session.date)
    start, seen = already_filed(folder)
    if start > 1:
        print(f"\n  {folder.name} already holds {start - 1} song(s); "
              f"numbering continues at {start:02d}")

    print(f"\n  encoding {len(named)} song(s) locally")
    built = stage(named, scratch, start, seen)
    if args.dry_run:
        return f"{when}: {len(built)} song(s) staged in {scratch}, not archived"

    print(f"\n  copy {len(built)} file(s) to {folder}? [y/N] ", end="", flush=True)
    if input().strip().lower() not in ("y", "yes"):
        return f"{when}: {len(built)} song(s) left in {scratch}, not archived"

    publish(built, args.archive, session.date)
    return f"{when}: {len(built)} song(s) archived to {folder.name}"


def choose(args):
    """Launch screen: pick a rehearsal, or pull one off the card first."""
    status = ""
    while True:
        on_card, on_disk = picker.survey(args.inbox, args.card)
        action, date = picker.Picker(on_card, on_disk, args.card, status).run()
        if action is None:
            return

        if action == "pull":
            copied = card.pull(args.card, args.inbox, {date})
            status = f"pulled {len(copied)} file(s) for {picker.spaced(date)}"
            continue

        session = next(s for s in discover(args.inbox) if s.date == date)
        status = process(session, args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="detect",
                        choices=["detect", "process", "pull"])
    parser.add_argument("--inbox", type=Path, default=INBOX)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--songlist", type=Path, default=SONGLIST)
    parser.add_argument("--card", type=Path, default=CARD)
    parser.add_argument("--date", help="only this recording date, YYMMDD or YYYYMMDD")
    parser.add_argument("--dry-run", action="store_true",
                        help="review and name, but do not write to the archive")
    args = parser.parse_args()

    if args.command == "pull":
        dates = {args.date[-6:]} if args.date else None
        copied = card.pull(args.card, args.inbox, dates)
        print(f"\n  {len(copied)} file(s) -> {args.inbox}" if copied
              else "\n  nothing to copy")
        return

    if args.command == "process":
        tools.check()
        if not args.date:
            choose(args)
            return

    sessions = discover(args.inbox)
    if not sessions:
        parser.error(f"no recordings found in {args.inbox}")

    if args.date:
        wanted = args.date[-6:]
        matched = [session for session in sessions if session.date == wanted]
        if not matched:
            parser.error(f"no recording dated {args.date}. Available: "
                         + ", ".join(session.date for session in sessions))
        sessions = matched

    for session in sessions:
        if args.command == "process":
            process(session, args)
        else:
            calibration, found = analyse(session)
            report(session, calibration, found, verbose=True)


if __name__ == "__main__":
    main()