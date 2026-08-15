"""Cut, loudness-normalise and encode named songs, then publish them to the archive."""

import re
import shutil
import subprocess

import soundfile as sf

from .settings import EXPORT

LOUDNORM = EXPORT["loudnorm"]
MP3_QUALITY = EXPORT["mp3_quality"]


def archive_folder(archive_root, date):
    """Folder for a YYMMDD date, as 'YYYY MM DD'.

    Spaced rather than the bare digits it used to be: a purely numeric name followed by
    anything the backend can read as a decimal point never syncs, and the spaces make the
    name unambiguously a string.
    """
    return archive_root / f"20{date[:2]} {date[2:4]} {date[4:6]}"


def safe(name):
    """A filename the archive can actually hold.

    Trailing dots are stripped because they are invalid on Windows and get normalised
    away somewhere in the WebDAV path, leaving local and remote names permanently
    disagreeing — the folder then never syncs and renaming it destroys its contents.
    """
    return name.replace("/", "-").strip().rstrip(". ")


FILED = re.compile(r"^(?P<order>\d+)\s+(?P<title>.+?)(?:\s+(?P<take>\d+))?$")


def already_filed(folder):
    """What a target folder holds: next free order number, and takes per title."""
    if not folder.is_dir():
        return 1, {}

    order = 0
    seen = {}
    for path in folder.glob("*.mp3"):
        match = FILED.match(path.stem)
        if not match:
            continue
        order = max(order, int(match["order"]))
        title = match["title"]
        seen[title] = max(seen.get(title, 0), int(match["take"] or 1))
    return order + 1, seen


def numbered(named, start=1, seen=None):
    """Playing order, then the title, then ' 2' onwards for repeat takes.

    Order and repeat counts continue from whatever the target folder already holds,
    so a rehearsal reviewed in several sittings does not collide with itself.
    """
    seen = dict(seen or {})
    out = []
    for order, (take, song, title) in enumerate(named, start):
        seen[title] = seen.get(title, 0) + 1
        count = seen[title]
        label = title if count == 1 else f"{title} {count}"
        out.append((take, song, safe(f"{order:02d} {label}")))
    return out


def encode(take, song, name, work_dir):
    raw = work_dir / f"{name}.source.wav"
    sf.write(raw, take.read(song.start, song.end), take.samplerate)
    destination = work_dir / f"{name}.mp3"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
         "-af", LOUDNORM, "-c:a", "libmp3lame", "-q:a", MP3_QUALITY, str(destination)],
        check=True,
    )
    raw.unlink()
    return destination


def stage(named, work_dir, start=1, seen=None):
    """Encode every named song locally. Nothing leaves the machine here."""
    work_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.mp3", "*.source.wav"):
        for stale in work_dir.glob(pattern):
            stale.unlink()

    built = []
    for take, song, name in numbered(named, start, seen):
        path = encode(take, song, name, work_dir)
        built.append(path)
        print(f"    {path.name:45} {path.stat().st_size / 1024 / 1024:5.1f} MB")
    return built


def publish(built, archive_root, date):
    """Copy finished files to the archive in one pass."""
    if not archive_root.is_dir():
        raise FileNotFoundError(f"archive root does not exist: {archive_root}. "
                                f"Pass --archive or set REHEARSAL_ARCHIVE.")
    folder = archive_folder(archive_root, date)
    folder.mkdir(parents=True, exist_ok=True)
    for path in built:
        shutil.copy2(path, folder / path.name)
    return folder
