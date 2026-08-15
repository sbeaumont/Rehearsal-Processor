"""Launch screen: what is on the Zoom card, what is already local, and what to do next."""

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from .audio import discover
from .card import scan

KEYS = "enter pull or open   up/down move   q quit"

STYLE = Style.from_dict({
    "title": "bold",
    "section": "bold",
    "current": "reverse",
    "new": "ansigreen",
    "muted": "ansibrightblack",
    "status": "ansiyellow",
    "keys": "ansibrightblack",
})


def spaced(date):
    """YYMMDD as the archive writes it."""
    return f"20{date[:2]} {date[2:4]} {date[4:6]}"


@dataclass
class OnCard:
    date: str
    files: int = 0
    size: int = 0
    new: int = 0

    @property
    def label(self):
        state = f"{self.new} new" if self.new else "already local"
        return (f"  {spaced(self.date)}   {self.files:2d} file(s)   "
                f"{self.size / 1024 ** 3:5.2f} GB   {state}")


@dataclass
class OnDisk:
    date: str
    takes: int = 0
    minutes: float = 0.0

    @property
    def label(self):
        return (f"  {spaced(self.date)}   {self.takes:2d} take(s)   "
                f"{self.minutes:5.1f} min")


def survey(inbox, card_path):
    """What the card holds and what the inbox holds, oldest first."""
    on_card = {}
    if card_path.is_dir():
        for source, _, size, already in scan(card_path, inbox):
            entry = on_card.setdefault(source.name[:6], OnCard(source.name[:6]))
            entry.files += 1
            entry.size += size
            entry.new += 0 if already else 1

    on_disk = [OnDisk(session.date, len(session.takes), session.duration / 60)
               for session in discover(inbox)]
    return (sorted(on_card.values(), key=lambda item: item.date),
            sorted(on_disk, key=lambda item: item.date))


class Picker:
    """Two tables — the card above, the inbox below — with one cursor through both."""

    def __init__(self, card_items, disk_items, card_path, status=""):
        self.card_items = card_items
        self.disk_items = disk_items
        self.card_path = card_path
        self.status = status
        self.action = None

        self.choices = ([("pull", item) for item in card_items]
                        + [("process", item) for item in disk_items])
        pullable = [index for index, (kind, item) in enumerate(self.choices)
                    if kind == "pull" and item.new]
        self.index = pullable[0] if pullable else max(len(self.choices) - 1, 0)
        self.app = self._build()

    def lines(self):
        """Every rendered line, with the choice index it belongs to or None."""
        out = [(None, "class:section", " ZOOM CARD")]
        if not self.card_path.is_dir():
            out.append((None, "class:muted", f"  no card mounted at {self.card_path}"))
        elif not self.card_items:
            out.append((None, "class:muted", "  no recordings on the card"))
        for index, item in enumerate(self.card_items):
            style = "class:new" if item.new else "class:muted"
            out.append((index, style, item.label))

        out.append((None, "", ""))
        out.append((None, "class:section", " LOCAL"))
        if not self.disk_items:
            out.append((None, "class:muted", "  no recordings pulled yet"))
        for index, item in enumerate(self.disk_items):
            out.append((len(self.card_items) + index, "", item.label))
        return out

    def rows(self):
        return [("class:current" if index == self.index else style, text.ljust(72) + "\n")
                for index, style, text in self.lines()]

    def cursor(self):
        for row, (index, _, _) in enumerate(self.lines()):
            if index == self.index:
                return Point(0, row)
        return Point(0, 0)

    def _build(self):
        self.list_window = Window(
            FormattedTextControl(self.rows, focusable=True,
                                 get_cursor_position=self.cursor),
            wrap_lines=False)
        body = HSplit([
            Window(FormattedTextControl(
                lambda: [("class:title", " Rehearsal Processor")]), height=1),
            Window(height=1),
            self.list_window,
            Window(FormattedTextControl(
                lambda: [("class:status", f" {self.status}")]), height=1),
            Window(FormattedTextControl(lambda: [("class:keys", " " + KEYS)]), height=1),
        ])
        return Application(layout=Layout(body, focused_element=self.list_window),
                           key_bindings=self._bindings(), style=STYLE, full_screen=True)

    def _bindings(self):
        keys = KeyBindings()

        @keys.add("up")
        @keys.add("k")
        def _(event):
            self.index = max(self.index - 1, 0)

        @keys.add("down")
        @keys.add("j")
        def _(event):
            self.index = min(self.index + 1, max(len(self.choices) - 1, 0))

        @keys.add("enter")
        @keys.add("p")
        def _(event):
            if not self.choices:
                return
            kind, item = self.choices[self.index]
            if kind == "pull" and not item.new:
                self.status = f"{spaced(item.date)} is already local"
                return
            self.action = kind
            event.app.exit()

        @keys.add("q")
        @keys.add("c-c")
        def _(event):
            self.action = None
            event.app.exit()

        return keys

    def run(self):
        self.app.run()
        if self.action is None or not self.choices:
            return None, None
        return self.action, self.choices[self.index][1].date
