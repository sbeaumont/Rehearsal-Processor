"""Discovery of recordings and extraction of their level and onset envelopes."""

import json
import re
import subprocess
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import numpy as np
import soundfile as sf

from .settings import AUDIO, RECORDERS

ONSET_HOP_S = AUDIO["onset_hop_seconds"]
LEVEL_HOP_S = AUDIO["level_hop_seconds"]
BLOCK_S = AUDIO["read_block_seconds"]

NAME = re.compile(
    r"^(?P<date>\d{6})_(?P<time>\d{6})(?:_(?P<part>\d{3}))?_(?P<track>[A-Za-z0-9]+)\.wav$"
)

FOLDER_DATE = re.compile(r"^(?P<year>\d{4}) (?P<month>\d{2}) (?P<day>\d{2})$")

NATIVE = {f".{name.lower()}" for name in sf.available_formats()}


def natural(text):
    """Sort key reading digit runs as numbers, so 'Memo 5' comes before 'Memo 43'."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def probe(path):
    """Samplerate, channels and frame count, read from the header without decoding."""
    if path.suffix.lower() in NATIVE:
        info = sf.info(path)
        return info.samplerate, info.channels, info.frames

    described = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-of", "json",
         "-show_entries", "stream=sample_rate,channels:format=duration", str(path)],
        capture_output=True, text=True, check=True).stdout)
    stream = described["streams"][0]
    samplerate = int(stream["sample_rate"])
    return (samplerate, int(stream["channels"]),
            round(float(described["format"]["duration"]) * samplerate))


def _read_file(path, start_s, duration_s, samplerate, channels):
    if path.suffix.lower() in NATIVE:
        with sf.SoundFile(path) as handle:
            handle.seek(int(start_s * handle.samplerate))
            return handle.read(int(duration_s * handle.samplerate),
                               dtype="float32", always_2d=True)

    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{start_s:.6f}", "-i", str(path),
         "-t", f"{duration_s:.6f}", "-f", "f32le", "-ac", str(channels),
         "-ar", str(samplerate), "-"],
        capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, channels)


def _stream_file(path, samplerate):
    """One file as mono float32 blocks, so a take is never held whole in memory."""
    if path.suffix.lower() in NATIVE:
        with sf.SoundFile(path) as handle:
            size = int(BLOCK_S * handle.samplerate)
            while True:
                block = handle.read(size, dtype="float32", always_2d=True)
                if len(block) == 0:
                    return
                yield block.mean(axis=1)

    decoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1",
         "-ar", str(samplerate), "-"], stdout=subprocess.PIPE)
    with decoder.stdout as pipe:
        while raw := pipe.read(int(BLOCK_S * samplerate) * 4):
            yield np.frombuffer(raw, dtype="<f4")
    if decoder.wait() != 0:
        raise IOError(f"ffmpeg could not decode {path}")


@dataclass
class Take:
    """One recording, possibly spread over several files the recorder split it into."""

    date: str
    name: str
    label: str
    recorder: str
    paths: list[Path] = field(default_factory=list)

    @cached_property
    def probes(self):
        return [probe(path) for path in self.paths]

    @property
    def samplerate(self):
        return self.probes[0][0]

    @property
    def duration(self):
        return sum(frames / rate for rate, _, frames in self.probes)

    def blocks(self):
        for path in self.paths:
            yield from _stream_file(path, self.samplerate)

    def read(self, start_s, end_s):
        """Samples between two offsets in the take's continuous timeline, all channels."""
        out = []
        offset = 0.0
        for path, (rate, channels, frames) in zip(self.paths, self.probes):
            length = frames / rate
            lo, hi = max(start_s, offset), min(end_s, offset + length)
            if lo < hi:
                out.append(_read_file(path, lo - offset, hi - lo, rate, channels))
            offset += length
        return np.concatenate(out) if out else np.zeros((0, 1), dtype=np.float32)


@dataclass
class Session:
    """All takes recorded on one date."""

    date: str
    takes: list[Take]

    @property
    def duration(self):
        return sum(take.duration for take in self.takes)

    @property
    def recorder(self):
        names = {take.recorder for take in self.takes}
        if len(names) > 1:
            raise ValueError(
                f"{self.date} holds {' and '.join(sorted(names))} recordings, and "
                f"calibration pools a whole date. Move all but one recorder's files "
                f"out of the inbox.")
        return names.pop()


def _recordings(root):
    """Every file under root whose extension names a recorder."""
    for suffix, recorder in RECORDERS.items():
        for path in Path(root).rglob(f"*{suffix}"):
            yield path, recorder


def discover(root):
    """Group the recordings under root into sessions by date.

    A Zoom filename carries its own date and time. Any other recorder takes its date
    from a folder named the way the archive names its folders, and its order from the
    filename, a voice memo having no timestamp worth trusting.
    """
    parts = {}
    loose = []
    for path, recorder in _recordings(root):
        stamped = NAME.match(path.name)
        if stamped:
            key = (stamped["date"], stamped["time"], recorder)
            parts.setdefault(key, []).append((int(stamped["part"] or 1), path))
            continue
        dated = FOLDER_DATE.match(path.parent.name)
        if dated:
            loose.append((f"{dated['year'][2:]}{dated['month']}{dated['day']}",
                          path, recorder))

    takes = [Take(date, f"{date}_{time}", f"{time[:2]}:{time[2:4]}", recorder,
                  [path for _, path in sorted(items)])
             for (date, time, recorder), items in parts.items()]
    takes += [Take(date, path.stem, path.stem, recorder, [path])
              for date, path, recorder in loose]

    sessions = {}
    for take in takes:
        sessions.setdefault(take.date, []).append(take)
    return [Session(date, sorted(items, key=lambda take: natural(take.name)))
            for date, items in sorted(sessions.items())]


def envelopes(take):
    """Level in dBFS at LEVEL_HOP_S, and onset strength at ONSET_HOP_S."""
    samplerate = take.samplerate
    frame = int(samplerate * ONSET_HOP_S)
    group = int(LEVEL_HOP_S / ONSET_HOP_S)

    power, onset = [], []
    carry = np.zeros(1, dtype=np.float32)
    for x in take.blocks():
        count = len(x) // frame
        if count == 0:
            continue
        body = x[:count * frame].reshape(count, frame).astype(np.float64)
        power.append((body ** 2).mean(axis=1))
        highpass = np.abs(np.diff(np.concatenate([carry, x])))[:count * frame]
        onset.append(highpass.reshape(count, frame).mean(axis=1))
        carry = x[count * frame - 1:count * frame]

    power = np.concatenate(power)
    usable = len(power) // group * group
    level = np.sqrt(power[:usable].reshape(-1, group).mean(axis=1))
    return 20 * np.log10(np.maximum(level, 1e-10)), np.concatenate(onset)