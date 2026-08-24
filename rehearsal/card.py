"""Copying recordings off the H6 card into the inbox."""

import shutil
import sys
import threading
import time

from .audio import NAME

POLL_SECONDS = 0.1


def scan(card, inbox):
    """Every recording on the card, paired with where it belongs in the inbox."""
    found = []
    for source in sorted(card.rglob("*.wav")):
        if not NAME.match(source.name):
            continue
        destination = inbox / source.relative_to(card)
        size = source.stat().st_size
        already = destination.exists() and destination.stat().st_size == size
        found.append((source, destination, size, already))
    return found


def _bar(fraction, width):
    filled = round(fraction * width)
    return "#" * filled + "-" * (width - filled)


def _copy(source, destination, size, live):
    """Copy one file, showing a live progress bar when stdout is a terminal."""
    prefix = f"    {source.name:38} {size / 1024 ** 2:7.0f} MB "
    started = time.monotonic()

    thread = None
    if live:
        columns = shutil.get_terminal_size((80, 24)).columns
        # 21 fixed chars wrap the bar: "[", "] ", "100%", "  ", "9999/9999 MB".
        bar_width = max(10, columns - len(prefix) - 22)
        width = len(prefix) + bar_width + 21
        stop = threading.Event()

        def watch():
            while not stop.wait(POLL_SECONDS):
                landed = destination.stat().st_size if destination.exists() else 0
                fraction = landed / size
                line = (f"{prefix}[{_bar(fraction, bar_width)}] {fraction:4.0%}  "
                        f"{landed / 1024 ** 2:4.0f}/{size / 1024 ** 2:4.0f} MB")
                print(f"\r{line:<{width}}", end="", flush=True)

        thread = threading.Thread(target=watch, daemon=True)
        thread.start()
    else:
        print(prefix, end="", flush=True)

    try:
        shutil.copy2(source, destination)
    finally:
        if thread:
            stop.set()
            thread.join()

    elapsed = time.monotonic() - started
    landed = destination.stat().st_size
    if landed != size:
        raise IOError(f"{destination} is {landed} bytes, expected {size}")

    suffix = f"{elapsed:5.1f}s  {size / 1024 ** 2 / max(elapsed, 0.001):5.0f} MB/s"
    print(f"\r{(prefix + suffix):<{width}}" if live else suffix)


def pull(card, inbox, dates=None):
    """Copy recordings that are not already in the inbox. Returns what was copied."""
    if not card.is_dir():
        raise FileNotFoundError(f"card not mounted at {card}")

    found = scan(card, inbox)
    if dates:
        found = [item for item in found if item[0].name[:6] in dates]
    if not found:
        raise FileNotFoundError(f"no H6 recordings found on {card}")

    pending = [item for item in found if not item[3]]
    skipped = len(found) - len(pending)
    print(f"  {len(found)} recording(s) on card, {skipped} already in the inbox")
    if not pending:
        return []

    total = sum(size for _, _, size, _ in pending) / 1024 ** 3
    print(f"  copying {len(pending)} file(s), {total:.1f} GB\n")

    live = sys.stdout.isatty()
    copied = []
    for source, destination, size, _ in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _copy(source, destination, size, live)
        copied.append(destination)
    return copied
