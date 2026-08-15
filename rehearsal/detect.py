"""Song boundary detection from level classes and drumstick count-ins."""

from dataclasses import dataclass

import numpy as np

from .audio import LEVEL_HOP_S, ONSET_HOP_S
from .settings import DETECT

SMOOTH_S = DETECT["smooth_seconds"]
HYSTERESIS_DB = DETECT["hysteresis_db"]
MIN_GAP_S = DETECT["min_gap_seconds"]
MIN_SONG_S = DETECT["min_song_seconds"]
TAIL_S = DETECT["tail_seconds"]

CLICK_BASELINE_S = DETECT["click_baseline_seconds"]
CLICK_RATIO = DETECT["click_ratio"]
CLICK_MIN_SEP_S = DETECT["click_min_separation_seconds"]
BEAT_RANGE_S = tuple(DETECT["beat_range_seconds"])
EVENNESS = DETECT["evenness"]
LEAD_QUIET_S = tuple(DETECT["lead_quiet_seconds"])
LEAD_PERCENTILE = DETECT["lead_percentile"]
FOLLOW_LOUD_S = tuple(DETECT["follow_loud_seconds"])
RISE_DB = DETECT["rise_db"]

MIN_CLASS_GAP_DB = DETECT["min_class_gap_db"]
MIN_FLOOR_GAP_DB = DETECT["min_floor_gap_db"]
COUNTIN_REACH_S = DETECT["countin_reach_seconds"]
MERGE_BEATS = DETECT["merge_beats"]


@dataclass
class Calibration:
    """Level thresholds separating room silence, talking and playing."""

    floor: float
    split: float
    quiet_mean: float
    loud_mean: float

    @property
    def enter(self):
        return self.split + HYSTERESIS_DB / 2

    @property
    def exit(self):
        return self.split - HYSTERESIS_DB / 2

    @property
    def reliable(self):
        return (self.loud_mean - self.quiet_mean >= MIN_CLASS_GAP_DB
                and self.split - self.floor >= MIN_FLOOR_GAP_DB)


@dataclass
class CountIn:
    clicks: np.ndarray
    beat: float
    downbeat: float
    ratio: float


@dataclass
class Song:
    start: float
    end: float
    origin: str
    bpm: float = None

    @property
    def duration(self):
        return self.end - self.start

    @property
    def confidence(self):
        if self.duration < MIN_SONG_S:
            return "low"
        return "high" if self.origin == "countin" else "medium"


def median_smooth(values, window_s, hop_s):
    window = max(int(window_s / hop_s), 1)
    padded = np.pad(values, (window // 2, window - window // 2 - 1), mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(padded, window), axis=1)


def rolling_mean(values, window_s, hop_s):
    window = max(int(window_s / hop_s), 1)
    padded = np.pad(values, (window // 2, window - window // 2 - 1), mode="edge")
    cumulative = np.cumsum(np.concatenate([[0.0], padded]))
    return (cumulative[window:] - cumulative[:-window]) / window


def otsu(values, bins=256):
    histogram, edges = np.histogram(values, bins=bins)
    weights = histogram / histogram.sum()
    centres = (edges[:-1] + edges[1:]) / 2
    mass = np.cumsum(weights)
    mean = np.cumsum(weights * centres)
    spread = mass * (1 - mass)
    between = np.where(spread > 1e-12, (mean[-1] * mass - mean) ** 2 / np.maximum(spread, 1e-12), 0)
    return centres[np.argmax(between)]


def calibrate(level_arrays):
    """Derive thresholds from every take in a session pooled together.

    Calibrating per file breaks down: a file holding only music splits the music
    itself, and a silent file invents a music class out of the noise floor.
    """
    pooled = np.concatenate([median_smooth(db, SMOOTH_S, LEVEL_HOP_S) for db in level_arrays])
    floor = otsu(pooled)
    audible = pooled[pooled > floor]
    split = otsu(audible)
    return Calibration(
        floor=floor,
        split=split,
        quiet_mean=audible[audible <= split].mean(),
        loud_mean=audible[audible > split].mean(),
    )


def loud_spans(db, calibration):
    loud = np.zeros(len(db), dtype=bool)
    active = False
    for index, value in enumerate(db):
        active = value > calibration.exit if active else value > calibration.enter
        loud[index] = active

    edges = np.diff(np.concatenate([[0], loud.view(np.int8), [0]]))
    spans = [[start * LEVEL_HOP_S, stop * LEVEL_HOP_S]
             for start, stop in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1))]
    if not spans:
        return []

    merged = [spans[0]]
    for start, stop in spans[1:]:
        if start - merged[-1][1] < MIN_GAP_S:
            merged[-1][1] = stop
        else:
            merged.append([start, stop])
    return merged


def _click_peaks(onset):
    baseline = rolling_mean(onset, CLICK_BASELINE_S, ONSET_HOP_S)
    ratio = onset / np.maximum(baseline, 1e-12)
    separation = int(CLICK_MIN_SEP_S / ONSET_HOP_S)

    candidates = np.flatnonzero(ratio > CLICK_RATIO)
    peaks = []
    for index in candidates:
        if peaks and index - peaks[-1] < separation:
            if onset[index] > onset[peaks[-1]]:
                peaks[-1] = index
            continue
        peaks.append(index)
    return np.array(peaks, dtype=int), ratio


def count_ins(onset, db, calibration):
    """Four evenly spaced transients that rise out of quiet into sustained playing."""
    peaks, ratio = _click_peaks(onset)
    if len(peaks) < 4:
        return []

    times = peaks * ONSET_HOP_S
    gaps = np.diff(times)

    def level_between(lo, hi, percentile=50):
        window = db[max(int(lo / LEVEL_HOP_S), 0):max(int(hi / LEVEL_HOP_S), 1)]
        return np.percentile(window, percentile) if len(window) else -np.inf

    found = []
    index = 0
    while index < len(gaps) - 2:
        window = gaps[index:index + 3]
        even = (BEAT_RANGE_S[0] <= window.min() and window.max() <= BEAT_RANGE_S[1]
                and window.max() / window.min() < EVENNESS)
        if not even:
            index += 1
            continue

        beat = window.mean()
        start, downbeat = times[index], times[index + 3] + beat
        before = level_between(start - LEAD_QUIET_S[0], start - LEAD_QUIET_S[1],
                               LEAD_PERCENTILE)
        after = level_between(downbeat + FOLLOW_LOUD_S[0], downbeat + FOLLOW_LOUD_S[1])
        if after - before >= RISE_DB and after > calibration.floor:
            found.append(CountIn(
                clicks=times[index:index + 4],
                beat=beat,
                downbeat=downbeat,
                ratio=ratio[peaks[index:index + 4]].mean(),
            ))
            index += 3
        else:
            index += 1

    merged = []
    for mark in found:
        if not merged or mark.downbeat - merged[-1].downbeat >= merged[-1].beat * MERGE_BEATS:
            merged.append(mark)
    return merged


def songs(spans, marks, total_duration):
    """Cut loud regions at count-ins; each count-in begins a song."""
    result = []
    for span_start, span_stop in spans:
        inside = [m for m in marks
                  if span_start - COUNTIN_REACH_S <= m.downbeat < span_stop - MIN_SONG_S]
        if not inside:
            if span_stop - span_start >= MIN_SONG_S:
                result.append(Song(span_start, min(span_stop + TAIL_S, total_duration), "level"))
            continue

        starts = [(inside[0].downbeat, inside[0])]
        if inside[0].downbeat - span_start > MIN_SONG_S:
            starts.insert(0, (span_start, None))
        starts += [(m.downbeat, m) for m in inside[1:]]

        for position, (start, mark) in enumerate(starts):
            stop = starts[position + 1][0] if position + 1 < len(starts) else span_stop + TAIL_S
            result.append(Song(
                start=start,
                end=min(stop, total_duration),
                origin="countin" if mark else "level",
                bpm=60 / mark.beat if mark else None,
            ))
    return result