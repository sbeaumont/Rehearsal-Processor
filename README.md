# Rehearsal Processor

Splits a band-rehearsal recording into per-song mp3s.

A rehearsal gets recorded as one long file, or a handful of them. Somewhere inside are a
dozen songs, separated by talking, tuning, false starts and restarts. Cutting that up by
hand in an audio editor is an hour of scrubbing and naming per rehearsal. This does the
scrubbing; you still do the naming, because nothing in the audio says which song it is.

It is built around one specific habit: **the drummer counts the band in with four
drumstick clicks.** That gives a reliable marker for where a song starts, which a level
meter alone does not.

The tool aims for *partial help at high precision*: it would rather mark ten boundaries it
is sure of and flag the rest than guess at all fourteen.

## Requirements

macOS, Python 3.14, [uv](https://docs.astral.sh/uv/), and `ffmpeg` built with
`libmp3lame`:

```sh
brew install ffmpeg
```

Preview playback uses `afplay`, which ships with macOS. [Fission](https://rogueamoeba.com/fission/)
is optional — one key opens the source file in it for a closer look.

Written for a Zoom H6, whose files are named `YYMMDD_HHMMSS[_NNN]_Mic.wav`. Other
recorders will need the pattern in `rehearsal/audio.py` adjusted.

## Setup

```sh
uv sync
cp paths.example.toml paths.toml     # then edit it
```

`paths.toml` names four locations — where recordings are pulled to, where finished mp3s
are filed, the recorder's card, and a list of song titles for tab completion. It is
gitignored, being specific to one machine. Everything tunable lives in `settings.toml`,
which is shared.

## Use

```sh
./process        # launch screen: pull from the card, or review a rehearsal
./pull           # copy new recordings off the card, non-interactively
uv run python -m rehearsal.cli --date 260518    # print detected boundaries only
uv run pytest
```

`./process` opens a launch screen with two tables — what is on the recorder's card, and
what is already local. Enter pulls from the card, or opens a rehearsal for review.

Review shows every detected segment of that date in one list:

```
 2026 05 18   14 segments over 1 take(s)   3 named   segment 4

  1  0:01:15.40 - 0:07:21.00  6:05.6  high   countin 115.8 BPM  Creep
  2  0:07:38.70 - 0:08:35.50  0:56.8  medium level
  3  0:15:44.92 - 0:21:44.60  5:59.7  high   countin 121.6 BPM  Vertigo
> 4  0:26:47.00 - 0:29:45.10  2:58.1  medium level
```

| key | |
|---|---|
| `1` `2` `3` | play 12 s before the start, 12 s from the start, 45 s from the start |
| `4` `5` | play 12 s or 45 s from the middle |
| enter | type a title, with tab completion against the songlist |
| `t` | correct this segment's start time |
| `s` | skip this segment |
| `o` | open the source file in Fission |
| `e` | encode what has been named |
| `q` | quit without encoding |

`high` means the start came from a detected count-in and is accurate. `medium` means it
came from the level envelope, so it sits where the band got loud and may run late by the
length of the intro — press `1` to hear what came before, then `t` to correct it.

Progress is saved after every change, so quitting costs nothing and the next run picks up
where you left off. Encoding stages files locally first and asks before anything is copied
to the archive.

Output is `YYYY MM DD/NN Title.mp3`, loudness-normalised to EBU R128 and encoded at
roughly 100 kbps — these are copies for relistening, not masters.

## How it works

Two weak signals that cover each other's failures: a three-class level model separating
room silence, talking and playing, and a detector for the drummer's count-in clicks.
Neither works alone. See [docs/detection.md](docs/detection.md).

The interface has a number of decisions that look arbitrary until you know what went wrong
without them — see [docs/design.md](docs/design.md). Storage constraints, some of them
unpleasant, are in [docs/storage.md](docs/storage.md).

## Layout

```
rehearsal/
  audio.py      finding recordings, joining 2 GB rollovers, level and onset envelopes
  detect.py     level calibration, count-in detection, segment assembly
  review.py     the full-screen review app
  picker.py     the launch screen
  card.py       copying off the recorder
  export.py     cutting, normalising, encoding, filing
  setlist.py    song titles for completion
  state.py      resumable per-date progress
  settings.py   loads settings.toml and paths.toml
  cli.py        entry point
```
