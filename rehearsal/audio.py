"""Discovery of Zoom H6 recordings and extraction of their level and onset envelopes."""

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from .settings import AUDIO

ONSET_HOP_S = AUDIO["onset_hop_seconds"]
LEVEL_HOP_S = AUDIO["level_hop_seconds"]
BLOCK_S = AUDIO["read_block_seconds"]

NAME = re.compile(
    r"^(?P<date>\d{6})_(?P<time>\d{6})(?:_(?P<part>\d{3}))?_(?P<track>[A-Za-z0-9]+)\.wav$"
)


@dataclass
class Take:
    """One continuous H6 recording, possibly spread over several 2 GB parts."""

    date: str
    time: str
    paths: list[Path] = field(default_factory=list)

    @property
    def name(self):
        return f"{self.date}_{self.time}"

    @property
    def samplerate(self):
        return sf.info(self.paths[0]).samplerate

    @property
    def duration(self):
        return sum(sf.info(p).frames for p in self.paths) / self.samplerate

    def blocks(self):
        for path in self.paths:
            with sf.SoundFile(path) as handle:
                size = int(BLOCK_S * handle.samplerate)
                while True:
                    block = handle.read(size, dtype="float32", always_2d=True)
                    if len(block) == 0:
                        break
                    yield block.mean(axis=1)

    def read(self, start_s, end_s):
        """Samples between two offsets in the take's continuous timeline, all channels."""
        out = []
        offset = 0.0
        for path in self.paths:
            info = sf.info(path)
            length = info.frames / info.samplerate
            lo, hi = max(start_s, offset), min(end_s, offset + length)
            if lo < hi:
                with sf.SoundFile(path) as handle:
                    handle.seek(int((lo - offset) * info.samplerate))
                    out.append(handle.read(int((hi - lo) * info.samplerate),
                                           dtype="float32", always_2d=True))
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


def discover(root):
    """Group the .wav files under root into sessions by recording date."""
    parts = {}
    for path in sorted(Path(root).rglob("*.wav")):
        match = NAME.match(path.name)
        if not match:
            continue
        key = (match["date"], match["time"])
        parts.setdefault(key, []).append((int(match["part"] or 1), path))

    takes = {}
    for (date, time), items in sorted(parts.items()):
        take = Take(date, time, [path for _, path in sorted(items)])
        takes.setdefault(date, []).append(take)
    return [Session(date, sorted(items, key=lambda t: t.time))
            for date, items in sorted(takes.items())]


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