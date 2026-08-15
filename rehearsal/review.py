"""Full-screen review of a rehearsal's detected songs: listen, name, encode."""

import subprocess
from dataclasses import replace

import soundfile as sf
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import FuzzyWordCompleter
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.styles import Style

from .settings import REVIEW
from .setlist import suggest
from .state import key as state_key

PREVIEW_S = REVIEW["preview_seconds"]
LONG_PREVIEW_S = REVIEW["long_preview_seconds"]

PREVIEWS = {
    "1": ("before", PREVIEW_S),
    "2": ("start", PREVIEW_S),
    "3": ("start", LONG_PREVIEW_S),
    "4": ("middle", PREVIEW_S),
    "5": ("middle", LONG_PREVIEW_S),
}

KEYS = [
    "1 before 12s   2 start 12s   3 start 45s   4 mid 12s   5 mid 45s   t set start",
    "enter name     s skip        up/down move  o open in Fission   e encode   q quit",
]

EDITOR = REVIEW["editor"]

STYLE = Style.from_dict({
    "header": "bold",
    "current": "reverse",
    "named": "ansigreen",
    "status": "ansiyellow",
    "keys": "ansibrightblack",
    "label": "bold",
})


def clock(seconds):
    """A position in the take, to the same hundredth of a second Fission shows."""
    hours, rest = divmod(seconds, 3600)
    minutes, remainder = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{remainder:05.2f}"


def length(seconds):
    """A duration, which never needs an hours field here."""
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}:{remainder:04.1f}"


def wall_clock(take):
    """When the recorder was started, read off the take name."""
    stamp = take.time
    return f"{stamp[:2]}:{stamp[2:4]}"


def parse_time(text):
    """Seconds from 'm:ss', 'h:mm:ss' or a plain number. None if unparsable."""
    parts = text.split(":")
    if len(parts) > 3 or not all(part.replace(".", "", 1).isdigit() for part in parts):
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def part_holding(take, position):
    """Which file of a take a position falls in, and where within that file.

    Only differs from the take itself once the H6 has rolled over at 2 GB.
    """
    if len(take.paths) == 1:
        return take.paths[0], position

    offset = 0.0
    for path in take.paths:
        info = sf.info(path)
        span = info.frames / info.samplerate
        if position < offset + span or path is take.paths[-1]:
            return path, position - offset
        offset += span
    return take.paths[-1], position


def window(song, anchor, seconds):
    """The stretch of take timeline a preview key refers to."""
    if anchor == "before":
        return max(song.start - seconds, 0.0), song.start
    if anchor == "start":
        return song.start, min(song.start + seconds, song.end)
    begin = song.start + max((song.duration - seconds) / 2, 0)
    return begin, min(begin + seconds, song.end)


class Review:
    """Every segment of one rehearsal, across all its takes, in a single list."""

    def __init__(self, date, segments, titles, scratch, known, remember):
        self.date = date
        self.segments = segments
        self.titles = titles
        self.scratch = scratch
        self.remember = remember
        self.detected = [song.start for _, song in segments]
        self.multi_take = len({take.name for take, _ in segments}) > 1

        self.starts = {}
        self.chosen = {}
        for index, (take, song) in enumerate(segments):
            stored = known.get(state_key(take.name, song.start))
            if not stored:
                continue
            if stored["title"]:
                self.chosen[index] = stored["title"]
            if abs(stored["start"] - song.start) > 0.05:
                self.starts[index] = stored["start"]

        self.index = next((i for i in range(len(segments)) if i not in self.chosen), 0)
        self.player = None
        self.status = f"resumed {len(self.chosen)} name(s)" if self.chosen else ""
        self.mode = "browse"
        self.verdict = "quit"
        self.app = self._build()

    # ---- segments

    def take_at(self, index):
        return self.segments[index][0]

    def song_at(self, index):
        """The segment as it stands, including any start the user corrected."""
        song = self.segments[index][1]
        if index not in self.starts:
            return song
        return replace(song, start=self.starts[index], origin="manual")

    def entries(self):
        return [(self.take_at(i), self.song_at(i), self.chosen.get(i, ""), self.detected[i])
                for i in sorted(set(self.chosen) | set(self.starts))]

    # ---- rendering

    def rows(self):
        out = []
        for index in range(len(self.segments)):
            song = self.song_at(index)
            title = self.chosen.get(index, "")
            bpm = f"{song.bpm:5.1f} BPM" if song.bpm else "         "
            take = f"{wall_clock(self.take_at(index))} " if self.multi_take else ""
            text = (f" {index + 1:2d}  {take}{clock(song.start):>9} - {clock(song.end):>9} "
                    f"{length(song.duration):>7}  {song.confidence:6} {song.origin:7} "
                    f"{bpm}  {title}")
            style = "class:current" if index == self.index else (
                "class:named" if title else "")
            out.append((style, text.ljust(104) + "\n"))
        return out

    def header(self):
        takes = len({take.name for take, _ in self.segments})
        return [("class:header",
                 f" 20{self.date}   {len(self.segments)} segments over {takes} take(s)   "
                 f"{len(self.chosen)} named   segment {self.index + 1}")]

    def status_line(self):
        if self.player and self.player.poll() is None:
            return [("class:status", " playing, any key stops")]
        return [("class:status", f" {self.status}")]

    def _build(self):
        self.list_window = Window(
            FormattedTextControl(self.rows, focusable=True,
                                 get_cursor_position=lambda: Point(0, self.index)),
            wrap_lines=False)

        self.title_buffer = Buffer(completer=FuzzyWordCompleter(self.titles),
                                   complete_while_typing=True, multiline=False,
                                   accept_handler=self._accept_title)
        self.time_buffer = Buffer(multiline=False, accept_handler=self._accept_time)

        naming = Condition(lambda: self.mode == "title")
        timing = Condition(lambda: self.mode == "time")

        body = HSplit([
            Window(FormattedTextControl(self.header), height=1),
            self.list_window,
            Window(FormattedTextControl(self.status_line), height=1),
            ConditionalContainer(
                HSplit([Window(FormattedTextControl(
                    lambda: [("class:label", " title> ")]), height=1),
                    Window(BufferControl(self.title_buffer), height=1)]),
                filter=naming),
            ConditionalContainer(
                HSplit([Window(FormattedTextControl(
                    lambda: [("class:label", " set start to (h:mm:ss.xx, or just 12.34)> ")]), height=1),
                    Window(BufferControl(self.time_buffer), height=1)]),
                filter=timing),
            Window(FormattedTextControl(
                lambda: [("class:keys", "\n".join(" " + line for line in KEYS))]),
                height=len(KEYS)),
        ])

        return Application(layout=Layout(body, focused_element=self.list_window),
                           key_bindings=self._bindings(), style=STYLE,
                           full_screen=True, refresh_interval=0.3)

    # ---- playback

    def stop_playback(self):
        if self.player and self.player.poll() is None:
            self.player.terminate()
            self.player.wait()
            self.player = None
            return True
        self.player = None
        return False

    def play(self, begin, end):
        take = self.take_at(self.index)
        path = self.scratch / "preview.wav"
        sf.write(path, take.read(begin, end), take.samplerate)
        self.player = subprocess.Popen(["afplay", str(path)])
        self.status = f"playing {end - begin:.0f}s from {clock(begin)}"

    # ---- input handlers

    def _accept_title(self, buffer):
        text = buffer.text.strip()
        if text:
            match = suggest(text, self.titles)
            self.chosen[self.index] = match or text
            self.remember(self.entries())
            self.status = f'named "{self.chosen[self.index]}"'
            self.index = min(self.index + 1, len(self.segments) - 1)
        self.mode = "browse"
        self.app.layout.focus(self.list_window)
        return False

    def _accept_time(self, buffer):
        """Move this segment's start to a time the user worked out by listening."""
        text = buffer.text.strip()
        self.mode = "browse"
        self.app.layout.focus(self.list_window)
        if not text:
            return False

        song = self.song_at(self.index)
        start = parse_time(text)
        if start is None:
            self.status = f"cannot read {text!r} as a time"
        elif start >= song.end:
            self.status = f"start must be before the segment end ({clock(song.end)})"
        elif abs(start - self.detected[self.index]) < 0.05:
            self.starts.pop(self.index, None)
            self.status = "start reset to where detection put it"
            self.remember(self.entries())
        else:
            self.starts[self.index] = start
            self.status = (f"start moved to {clock(start)} "
                           f"({start - self.detected[self.index]:+.1f}s)")
            self.remember(self.entries())
        return False

    # ---- keys

    def _bindings(self):
        keys = KeyBindings()
        browsing = Condition(lambda: self.mode == "browse")
        editing = Condition(lambda: self.mode != "browse")

        @keys.add("<any>", filter=browsing)
        def _(event):
            """Any unbound key just stops playback."""
            self.stop_playback()

        for digit, preview in PREVIEWS.items():
            @keys.add(digit, filter=browsing)
            def _(event, preview=preview):
                if self.stop_playback():
                    return
                self.play(*window(self.song_at(self.index), *preview))

        @keys.add("up", filter=browsing)
        @keys.add("k", filter=browsing)
        @keys.add("b", filter=browsing)
        def _(event):
            self.stop_playback()
            self.index = max(self.index - 1, 0)

        @keys.add("down", filter=browsing)
        @keys.add("j", filter=browsing)
        def _(event):
            self.stop_playback()
            self.index = min(self.index + 1, len(self.segments) - 1)

        @keys.add("s", filter=browsing)
        def _(event):
            self.stop_playback()
            self.chosen.pop(self.index, None)
            self.remember(self.entries())
            self.status = "skipped"
            self.index = min(self.index + 1, len(self.segments) - 1)

        @keys.add("enter", filter=browsing)
        def _(event):
            self.stop_playback()
            self.mode = "title"
            self.title_buffer.text = self.chosen.get(self.index, "")
            self.title_buffer.cursor_position = len(self.title_buffer.text)
            event.app.layout.focus(self.title_buffer)

        @keys.add("t", filter=browsing)
        def _(event):
            self.stop_playback()
            self.mode = "time"
            self.time_buffer.text = ""
            event.app.layout.focus(self.time_buffer)

        @keys.add("o", filter=browsing)
        def _(event):
            self.stop_playback()
            song = self.song_at(self.index)
            path, offset = part_holding(self.take_at(self.index), song.start)
            opened = subprocess.run(["open", "-a", EDITOR, str(path)],
                                    capture_output=True, text=True)
            if opened.returncode != 0:
                self.status = f"could not open {EDITOR}: {opened.stderr.strip()}"
            else:
                self.status = f"opened {path.name} in {EDITOR}, segment starts at {clock(offset)}"

        @keys.add("e", filter=browsing)
        def _(event):
            self.stop_playback()
            self.verdict = "encode"
            event.app.exit()

        @keys.add("q", filter=browsing)
        @keys.add("c-c")
        def _(event):
            self.stop_playback()
            self.verdict = "quit"
            event.app.exit()

        @keys.add("escape", filter=editing)
        def _(event):
            self.mode = "browse"
            event.app.layout.focus(self.list_window)

        return keys

    def run(self):
        self.app.run()
        self.stop_playback()
        return self.entries(), self.verdict


def review_session(session, detections, titles, scratch, known, remember):
    """One list for the whole rehearsal, however many takes it was recorded in."""
    segments = [(take, song)
                for take in session.takes
                for song in detections[take.name]]
    if not segments:
        return [], "quit"

    reviewed, verdict = Review(session.date, segments, titles, scratch,
                               known, remember).run()
    named = [(take, song, title) for take, song, title, _ in reviewed if title]
    return named, verdict
