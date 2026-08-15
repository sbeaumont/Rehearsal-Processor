import numpy as np
import pytest

from rehearsal.audio import LEVEL_HOP_S, ONSET_HOP_S
from rehearsal.detect import (Calibration, count_ins, loud_spans, otsu, songs)

QUIET_DB = -50.0
LOUD_DB = -28.0
BEAT_S = 0.5


@pytest.fixture
def calibration():
    return Calibration(floor=-45.0, split=-38.0, quiet_mean=-50.0, loud_mean=-28.0)


def level(duration_s, loud_spans_s):
    db = np.full(int(duration_s / LEVEL_HOP_S), QUIET_DB)
    for start, stop in loud_spans_s:
        db[int(start / LEVEL_HOP_S):int(stop / LEVEL_HOP_S)] = LOUD_DB
    return db


def onsets(duration_s, click_times, baseline=0.01):
    signal = np.full(int(duration_s / ONSET_HOP_S), baseline)
    for time in click_times:
        signal[int(time / ONSET_HOP_S)] = 1.0
    return signal


def test_otsu_splits_a_bimodal_distribution():
    values = np.concatenate([np.full(500, -50.0), np.full(500, -20.0)])
    assert -50 < otsu(values) < -20


def test_loud_spans_close_short_gaps_but_not_long_ones(calibration):
    db = level(400, [(10, 100), (105, 200), (260, 380)])
    spans = loud_spans(db, calibration)
    assert len(spans) == 2
    assert spans[0][0] == pytest.approx(10, abs=0.5)
    assert spans[0][1] == pytest.approx(200, abs=0.5)


def test_count_in_found_when_quiet_precedes_a_sustained_rise(calibration):
    clicks = [10.0, 10.5, 11.0, 11.5]
    marks = count_ins(onsets(60, clicks), level(60, [(12.0, 60.0)]), calibration)
    assert len(marks) == 1
    assert marks[0].downbeat == pytest.approx(12.0, abs=0.05)
    assert 60 / marks[0].beat == pytest.approx(120.0, abs=1.0)


def test_steady_playing_is_not_a_count_in(calibration):
    """Four even transients inside continuous loud playing are a drum groove."""
    clicks = np.arange(10.0, 20.0, BEAT_S)
    marks = count_ins(onsets(60, clicks), level(60, [(0.0, 60.0)]), calibration)
    assert marks == []


def test_clicks_running_on_into_the_song_still_mark_one_start(calibration):
    """A count-in is 4 clicks; further beats are the band, so the first group wins.

    Keeping a later group would start the song after its first bar had begun.
    """
    clicks = [10.0 + i * BEAT_S for i in range(8)]
    marks = count_ins(onsets(60, clicks), level(60, [(12.0, 60.0)]), calibration)
    assert len(marks) == 1
    assert marks[0].downbeat == pytest.approx(12.0, abs=0.05)


def test_restart_survives_as_its_own_segment(calibration):
    """An aborted take is real information, not noise to be merged away."""
    clicks = [10.0, 10.5, 11.0, 11.5] + [24.0, 24.5, 25.0, 25.5]
    db = level(300, [(12.0, 22.0), (26.0, 290.0)])
    marks = count_ins(onsets(300, clicks), db, calibration)
    assert len(marks) == 2

    found = songs(loud_spans(db, calibration), marks, 300)
    assert [song.confidence for song in found] == ["low", "high"]


def test_short_level_only_spans_are_dropped(calibration):
    db = level(300, [(10, 20), (60, 200)])
    found = songs(loud_spans(db, calibration), [], 300)
    assert len(found) == 1
    assert found[0].origin == "level"


def test_unreliable_calibration_is_flagged():
    assert not Calibration(-45.0, -43.0, -44.0, -42.0).reliable
    assert Calibration(-45.0, -38.0, -50.0, -28.0).reliable