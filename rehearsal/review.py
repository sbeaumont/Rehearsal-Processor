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

from .audio import probe
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
    "enter name     s skip        m merge up    up/down move  o open in Fission   "
    "e encode   q quit",
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
        samplerate, _, frames = probe(path)
        span = frames / samplerate
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
        self.label_width = max(len(take.label) for take, _ in segments)

        self.starts = {}
        self.chosen = {}
        self.absorbed = set()
        for index, (take, song) in enumerate(segments):
            stored = known.get(state_key(take.name, song.start))
            if not stored:
                continue
            if stored.get("absorbed"):
                self.absorbed.add(index)
                continue
            if stored["title"]:
                self.chosen[index] = stored["title"]
            if abs(stored["start"] - song.start) > 0.05:
                self.starts[index] = stored["start"]

        shown = self.visible()
        self.index = next((i for i in shown if i not in self.chosen), shown[0])
        self.player = None
        resumed = [f"{len(self.chosen)} name(s)" if self.chosen else "",
                   f"{len(self.absorbed)} merge(s)" if self.absorbed else ""]
        self.status = ("resumed " + ", ".join(part for part in resumed if part)
                       if any(resumed) else "")
        self.mode = "browse"
        self.verdict = "quit"
        self.app = self._build()

    # ---- segments

    def take_at(self, index):
        return self.segments[index][0]

    def visible(self):
        """Segments still on their own row; a merged one lives inside the row above."""
        return [index for index in range(len(self.segments)) if index not in self.absorbed]

    def step(self, forward):
        """Move to the next visible segment in that direction, or stay put."""
        beyond = [index for index in self.visible()
                  if (index > self.index if forward else index < self.index)]
        if beyond:
            self.index = beyond[0] if forward else beyond[-1]

    def merge_up(self):
        """Fold this segment into the one above, when detection split one song."""
        above = [index for index in self.visible() if index < self.index]
        if not above:
            self.status = "nothing above to merge into"
            return
        target = above[-1]
        if self.take_at(target).name != self.take_at(self.index).name:
            self.status = "cannot merge across takes"
            return

        self.absorbed.add(self.index)
        self.chosen.pop(self.index, None)
        self.starts.pop(self.index, None)
        self.index = target
        self.remember(self.entries())
        self.status = (f"merged; segment above now runs "
                       f"{length(self.song_at(target).duration)}")

    def song_at(self, index):
        """The segment as it stands, with any correction and anything merged into it."""
        song = self.segments[index][1]
        end = song.end
        following = index + 1
        while following in self.absorbed:
            end = self.segments[following][1].end
            following += 1

        changes = {}
        if index in self.starts:
            changes.update(start=self.starts[index], origin="manual")
        if end != song.end:
            changes.update(end=end)
        return replace(song, **changes) if changes else song

    def entries(self):
        return [(self.take_at(i), self.song_at(i), self.chosen.get(i, ""),
                 self.detected[i], i in self.absorbed)
                for i in sorted(set(self.chosen) | set(self.starts) | self.absorbed)]

    # ---- rendering

    def rows(self):
        out = []
        for position, index in enumerate(self.visible(), start=1):
            song = self.song_at(index)
            title = self.chosen.get(index, "")
            bpm = f"{song.bpm:5.1f} BPM" if song.bpm else "         "
            take = (f"{self.take_at(index).label:{self.label_width}} "
                    if self.multi_take else "")
            text = (f" {position:2d}  {take}{clock(song.start):>9} - {clock(song.end):>9} "
                    f"{length(song.duration):>7}  {song.confidence:6} {song.origin:7} "
                    f"{bpm}  {title}")
            style = "class:current" if index == self.index else (
                "class:named" if title else "")
            out.append((style, text.ljust(104 + self.label_width) + "\n"))
        return out

    def header(self):
        shown = self.visible()
        takes = len({self.take_at(index).name for index in shown})
        merged = f"   {len(self.absorbed)} merged" if self.absorbed else ""
        return [("class:header",
                 f" 20{self.date}   {len(shown)} segments over {takes} take(s)   "
                 f"{len(self.chosen)} named{merged}   "
                 f"segment {shown.index(self.index) + 1}")]

    def status_line(self):
        if self.player and self.player.poll() is None:
            return [("class:status", " playing, any key stops")]
        return [("class:status", f" {self.status}")]

    def _build(self):
        self.list_window = Window(
            FormattedTextControl(self.rows, focusable=True,
                                 get_cursor_position=lambda: Point(
                                     0, self.visible().index(self.index))),
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
            self.step(forward=True)
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
            self.step(forward=False)

        @keys.add("down", filter=browsing)
        @keys.add("j", filter=browsing)
        def _(event):
            self.stop_playback()
            self.step(forward=True)

        @keys.add("s", filter=browsing)
        def _(event):
            self.stop_playback()
            self.chosen.pop(self.index, None)
            self.remember(self.entries())
            self.status = "skipped"
            self.step(forward=True)

        @keys.add("m", filter=browsing)
        def _(event):
            self.stop_playback()
            self.merge_up()

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
    named = [(take, song, title) for take, song, title, _, absorbed in reviewed
             if title and not absorbed]
    return named, verdict
