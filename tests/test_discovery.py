import pytest

from rehearsal.audio import discover, natural


def touch(folder, *names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).touch()


def test_h6_names_carry_their_own_date_and_time(tmp_path):
    touch(tmp_path, "260518_193000_Mic.wav", "260518_211500_Mic.wav")
    session, = discover(tmp_path)
    assert session.date == "260518"
    assert session.recorder == "zoom"
    assert [take.name for take in session.takes] == ["260518_193000", "260518_211500"]
    assert [take.label for take in session.takes] == ["19:30", "21:15"]


def test_rollover_parts_join_into_one_take(tmp_path):
    touch(tmp_path, "260518_193000_Mic.wav", "260518_193000_002_Mic.wav")
    session, = discover(tmp_path)
    take, = session.takes
    assert [path.name for path in take.paths] == ["260518_193000_Mic.wav",
                                                  "260518_193000_002_Mic.wav"]


def test_a_dated_folder_supplies_the_date_a_voice_memo_lacks(tmp_path):
    touch(tmp_path / "2026 08 18", "New Recording 43.m4a", "New Recording 44.m4a")
    session, = discover(tmp_path)
    assert session.date == "260818"
    assert session.recorder == "iphone"
    assert [take.name for take in session.takes] == ["New Recording 43",
                                                     "New Recording 44"]


def test_takes_order_by_number_not_by_text(tmp_path):
    """Voice Memos does not zero-pad, so 'Memo 5' must not sort after 'Memo 43'."""
    touch(tmp_path / "2026 08 18", "Memo 5.m4a", "Memo 43.m4a", "Memo 6.m4a")
    session, = discover(tmp_path)
    assert [take.name for take in session.takes] == ["Memo 5", "Memo 6", "Memo 43"]
    assert natural("Memo 5") < natural("Memo 43")


def test_a_recording_outside_a_dated_folder_is_ignored(tmp_path):
    touch(tmp_path, "voice note.m4a")
    touch(tmp_path / "work" / "260818", "preview.wav")
    assert discover(tmp_path) == []


def test_one_date_may_not_mix_recorders(tmp_path):
    """Calibration pools a whole date, so two level distributions cannot share one."""
    touch(tmp_path / "2026 05 18", "New Recording 43.m4a")
    touch(tmp_path, "260518_193000_Mic.wav")
    session, = discover(tmp_path)
    with pytest.raises(ValueError, match="iphone and zoom"):
        session.recorder