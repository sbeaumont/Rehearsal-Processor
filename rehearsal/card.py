"""Copying recordings off the H6 card into the inbox."""

import shutil
import time

from .audio import NAME


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

    copied = []
    for source, destination, size, _ in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        print(f"    {source.name:38} {size / 1024 ** 2:7.0f} MB ", end="", flush=True)
        started = time.monotonic()
        shutil.copy2(source, destination)
        elapsed = time.monotonic() - started

        landed = destination.stat().st_size
        if landed != size:
            raise IOError(f"{destination} is {landed} bytes, expected {size}")
        print(f"{elapsed:5.1f}s  {size / 1024 ** 2 / max(elapsed, 0.001):5.0f} MB/s")
        copied.append(destination)
    return copied
