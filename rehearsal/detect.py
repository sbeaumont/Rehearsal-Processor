"""Song boundary detection from level classes and drumstick count-ins."""

from dataclasses import dataclass, field

import numpy as np

from .audio import LEVEL_HOP_S, ONSET_HOP_S
from .settings import DETECT, OVERRIDES


@dataclass(frozen=True)
class Tuning:
    """The thresholds detection runs on, for one kind of recorder."""

    smooth_seconds: float
    hysteresis_db: float
    min_gap_seconds: float
    min_song_seconds: float
    tail_seconds: float
    min_class_gap_db: float
    min_floor_gap_db: float
    click_baseline_seconds: float
    click_ratio: float
    click_min_separation_seconds: float
    beat_range_seconds: list
    evenness: float
    merge_beats: float
    countin_reach_seconds: float
    lead_quiet_seconds: list
    lead_percentile: float
    follow_loud_seconds: list
    rise_db: float


def tuning(recorder):
    """The shared thresholds with this recorder's overrides applied."""
    return Tuning(**(DETECT | OVERRIDES[recorder]))


@dataclass
class Calibration:
    """Level thresholds separating room silence, talking and playing."""

    floor: float
    split: float
    quiet_mean: float
    loud_mean: float
    tuning: Tuning = field(repr=False)

    @property
    def enter(self):
        return self.split + self.tuning.hysteresis_db / 2

    @property
    def exit(self):
        return self.split - self.tuning.hysteresis_db / 2

    @property
    def reliable(self):
        return (self.loud_mean - self.quiet_mean >= self.tuning.min_class_gap_db
                and self.split - self.floor >= self.tuning.min_floor_gap_db)


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
    tuning: Tuning = field(repr=False)
    bpm: float = None

    @property
    def duration(self):
        return self.end - self.start

    @property
    def confidence(self):
        if self.duration < self.tuning.min_song_seconds:
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


def calibrate(level_arrays, tuning):
    """Derive thresholds from every take in a session pooled together.

    Calibrating per file breaks down: a file holding only music splits the music
    itself, and a silent file invents a music class out of the noise floor.
    """
    pooled = np.concatenate([median_smooth(db, tuning.smooth_seconds, LEVEL_HOP_S)
                             for db in level_arrays])
    floor = otsu(pooled)
    audible = pooled[pooled > floor]
    split = otsu(audible)
    return Calibration(
        floor=floor,
        split=split,
        quiet_mean=audible[audible <= split].mean(),
        loud_mean=audible[audible > split].mean(),
        tuning=tuning,
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
        if start - merged[-1][1] < calibration.tuning.min_gap_seconds:
            merged[-1][1] = stop
        else:
            merged.append([start, stop])
    return merged


def _click_peaks(onset, tuning):
    baseline = rolling_mean(onset, tuning.click_baseline_seconds, ONSET_HOP_S)
    ratio = onset / np.maximum(baseline, 1e-12)
    separation = int(tuning.click_min_separation_seconds / ONSET_HOP_S)

    candidates = np.flatnonzero(ratio > tuning.click_ratio)
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
    tuning = calibration.tuning
    peaks, ratio = _click_peaks(onset, tuning)
    if len(peaks) < 4:
        return []

    times = peaks * ONSET_HOP_S
    gaps = np.diff(times)
    shortest_beat, longest_beat = tuning.beat_range_seconds
    lead_from, lead_to = tuning.lead_quiet_seconds
    follow_from, follow_to = tuning.follow_loud_seconds

    def level_between(lo, hi, percentile=50):
        window = db[max(int(lo / LEVEL_HOP_S), 0):max(int(hi / LEVEL_HOP_S), 1)]
        return np.percentile(window, percentile) if len(window) else -np.inf

    found = []
    index = 0
    while index < len(gaps) - 2:
        window = gaps[index:index + 3]
        even = (shortest_beat <= window.min() and window.max() <= longest_beat
                and window.max() / window.min() < tuning.evenness)
        if not even:
            index += 1
            continue

        beat = window.mean()
        start, downbeat = times[index], times[index + 3] + beat
        before = level_between(start - lead_from, start - lead_to, tuning.lead_percentile)
        after = level_between(downbeat + follow_from, downbeat + follow_to)
        if after - before >= tuning.rise_db and after > calibration.floor:
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
        if not merged or mark.downbeat - merged[-1].downbeat >= merged[-1].beat * tuning.merge_beats:
            merged.append(mark)
    return merged


def songs(spans, marks, total_duration, tuning):
    """Cut loud regions at count-ins; each count-in begins a song."""
    result = []
    for span_start, span_stop in spans:
        inside = [m for m in marks
                  if span_start - tuning.countin_reach_seconds <= m.downbeat
                  < span_stop - tuning.min_song_seconds]
        if not inside:
            if span_stop - span_start >= tuning.min_song_seconds:
                result.append(Song(span_start,
                                   min(span_stop + tuning.tail_seconds, total_duration),
                                   "level", tuning))
            continue

        starts = [(inside[0].downbeat, inside[0])]
        if inside[0].downbeat - span_start > tuning.min_song_seconds:
            starts.insert(0, (span_start, None))
        starts += [(m.downbeat, m) for m in inside[1:]]

        for position, (start, mark) in enumerate(starts):
            stop = (starts[position + 1][0] if position + 1 < len(starts)
                    else span_stop + tuning.tail_seconds)
            result.append(Song(
                start=start,
                end=min(stop, total_duration),
                origin="countin" if mark else "level",
                tuning=tuning,
                bpm=60 / mark.beat if mark else None,
            ))
    return result