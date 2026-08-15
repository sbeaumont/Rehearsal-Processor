"""Candidate song titles used to complete names during review."""

from difflib import get_close_matches
from pathlib import Path

TITLE_COLUMN = "nummer"
MATCH_CUTOFF = 0.6


def _table_titles(text):
    """Titles from every markdown table that has a title column."""
    titles = []
    column = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            column = None
            continue

        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue
        if column is None:
            lowered = [cell.lower() for cell in cells]
            column = lowered.index(TITLE_COLUMN) if TITLE_COLUMN in lowered else None
            continue
        if column < len(cells) and cells[column]:
            titles.append(cells[column])
    return titles


def load(source):
    """Song titles from a markdown songlist, a directory of them, or a plain list."""
    path = Path(source)
    files = sorted(path.glob("*.md")) + sorted(path.glob("*.txt")) if path.is_dir() else [path]

    titles = []
    for file in files:
        text = file.read_text(encoding="utf-8")
        if file.suffix == ".md":
            titles += _table_titles(text)
        else:
            titles += [line.strip() for line in text.splitlines() if line.strip()]
    return sorted(dict.fromkeys(titles))


def suggest(typed, titles):
    """The known title closest to what was typed, or None."""
    lowered = {title.lower(): title for title in titles}
    if typed.lower() in lowered:
        return lowered[typed.lower()]
    prefix = [title for title in titles if title.lower().startswith(typed.lower())]
    if len(prefix) == 1:
        return prefix[0]
    close = get_close_matches(typed.lower(), lowered, n=1, cutoff=MATCH_CUTOFF)
    return lowered[close[0]] if close else None