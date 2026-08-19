from pathlib import Path
from types import SimpleNamespace

from rehearsal import state
from rehearsal.detect import Song, tuning
from rehearsal.review import Review

ZOOM = tuning("zoom")


def take(name="260518_193000"):
    return SimpleNamespace(name=name, label="19:30", paths=[Path("/nowhere.wav")])


def build(segments, known=None, remember=lambda entries: None):
    return Review("260518", segments, [], Path("/nowhere"), known or {}, remember)


def three_segments():
    only = take()
    return [(only, Song(10.0, 200.0, "countin", ZOOM, bpm=110.0)),
            (only, Song(200.0, 260.0, "countin", ZOOM, bpm=60.0)),
            (only, Song(400.0, 700.0, "level", ZOOM))]


def test_merging_extends_the_segment_above_and_hides_this_one():
    review = build(three_segments())
    review.index = 1
    review.merge_up()

    assert review.visible() == [0, 2]
    assert review.index == 0
    merged = review.song_at(0)
    assert (merged.start, merged.end) == (10.0, 260.0)
    assert merged.bpm == 110.0
    assert len(review.rows()) == 2


def test_the_first_segment_has_nothing_to_merge_into():
    review = build(three_segments())
    review.index = 0
    review.merge_up()

    assert review.visible() == [0, 1, 2]
    assert review.status == "nothing above to merge into"


def test_segments_from_different_takes_never_merge():
    first, second = take("260518_193000"), take("260518_211500")
    review = build([(first, Song(10.0, 200.0, "countin", ZOOM)),
                    (second, Song(0.0, 300.0, "level", ZOOM))])
    review.index = 1
    review.merge_up()

    assert review.visible() == [0, 1]
    assert review.status == "cannot merge across takes"


def test_a_merge_survives_quitting_and_resuming(tmp_path):
    review = build(three_segments(),
                   remember=lambda entries: state.save(tmp_path, "260518", entries))
    review.index = 1
    review.merge_up()

    resumed = build(three_segments(), known=state.load(tmp_path))
    assert resumed.visible() == [0, 2]
    assert resumed.song_at(0).end == 260.0


def test_a_merged_segment_is_never_exported():
    review = build(three_segments())
    review.chosen[1] = "Creep"
    review.index = 1
    review.merge_up()

    assert [title for _, _, title, _, absorbed in review.entries() if not absorbed] == []


def test_navigation_steps_over_a_merged_segment():
    review = build(three_segments())
    review.index = 1
    review.merge_up()

    review.index = 0
    review.step(forward=True)
    assert review.index == 2
    review.step(forward=False)
    assert review.index == 0
