from pathlib import Path
from types import SimpleNamespace

from rehearsal import review, setlist
from rehearsal.export import already_filed, numbered, safe

SONGLIST = """# Songlijst

| # | Nummer | Artiest | Status |
|---|--------|---------|--------|
| 1 | Vertigo | U2 | |
| 2 | Sweet Child o' Mine | Guns N' Roses | |

## Andere bands

| Nummer | Artiest | Opmerkingen |
|--------|---------|-------------|
| Black Velvet | Delta Goodrem | |
"""


def test_titles_come_from_the_named_column_in_every_table(tmp_path):
    (tmp_path / "list.md").write_text(SONGLIST, encoding="utf-8")
    assert setlist.load(tmp_path) == ["Black Velvet", "Sweet Child o' Mine", "Vertigo"]


def test_plain_text_setlist_is_one_title_per_line(tmp_path):
    (tmp_path / "played.txt").write_text("Creep\nRadio\n\nZombie\n", encoding="utf-8")
    assert setlist.load(tmp_path) == ["Creep", "Radio", "Zombie"]


def test_suggest_completes_partial_and_misspelled_input():
    titles = ["Sweet Child o' Mine", "Somewhere Only We Know", "Creep"]
    assert setlist.suggest("sweet child", titles) == "Sweet Child o' Mine"
    assert setlist.suggest("creep", titles) == "Creep"
    assert setlist.suggest("Bye Boys Improv", titles) is None


def test_names_carry_playing_order_and_number_repeat_takes():
    entries = [(None, None, t) for t in ["Creep", "Vertigo", "Creep", "Radio", "Creep"]]
    assert [name for _, _, name in numbered(entries)] == [
        "01 Creep", "02 Vertigo", "03 Creep 2", "04 Radio", "05 Creep 3"]


def test_path_separators_never_reach_a_filename():
    assert safe("AC/DC Medley") == "AC-DC Medley"

def test_parse_time_accepts_clock_and_plain_seconds():
    assert review.parse_time("26:47") == 1607.0
    assert review.parse_time("1:02:03") == 3723.0
    assert review.parse_time("90") == 90.0
    assert review.parse_time("90.5") == 90.5
    assert review.parse_time("nonsense") is None
    assert review.parse_time("1:2:3:4") is None


def test_preview_windows_anchor_correctly():
    song = SimpleNamespace(start=100.0, end=340.0, duration=240.0)
    assert review.window(song, "before", 12) == (88.0, 100.0)
    assert review.window(song, "start", 12) == (100.0, 112.0)
    assert review.window(song, "middle", 12) == (214.0, 226.0)


def test_before_window_never_reads_past_the_file_start():
    song = SimpleNamespace(start=5.0, end=200.0, duration=195.0)
    assert review.window(song, "before", 12) == (0.0, 5.0)


def test_preview_never_runs_past_the_segment_end():
    song = SimpleNamespace(start=100.0, end=110.0, duration=10.0)
    assert review.window(song, "start", 45) == (100.0, 110.0)


def test_clock_shows_hours_like_fission():
    assert review.clock(65.0) == "0:01:05.00"
    assert review.clock(3937.64) == "1:05:37.64"
    assert review.clock(0.0) == "0:00:00.00"


def test_durations_omit_the_hours_field():
    assert review.length(365.6) == "6:05.6"
    assert review.length(56.8) == "0:56.8"


def test_clock_and_parse_time_round_trip():
    assert review.parse_time(review.clock(3937.64)) == 3937.64


def test_short_time_forms_need_no_leading_zeros():
    assert review.parse_time("12.34") == 12.34
    assert review.parse_time("2:03.45") == 123.45
    assert review.parse_time("1:02:03.45") == 3723.45


def test_numbering_continues_from_what_the_archive_already_holds(tmp_path):
    for name in ["01 Creep.mp3", "02 Vertigo.mp3", "03 Creep 2.mp3"]:
        (tmp_path / name).touch()
    start, seen = already_filed(tmp_path)
    assert (start, seen) == (4, {"Creep": 2, "Vertigo": 1})

    more = [(None, None, t) for t in ["Creep", "Radio"]]
    assert [name for _, _, name in numbered(more, start, seen)] == ["04 Creep 3", "05 Radio"]


def test_an_empty_or_missing_archive_folder_starts_at_one(tmp_path):
    assert already_filed(tmp_path / "nope") == (1, {})
    assert already_filed(tmp_path) == (1, {})


def test_files_not_matching_the_convention_are_ignored(tmp_path):
    (tmp_path / "stray.mp3").touch()
    (tmp_path / "07 Radio.mp3").touch()
    assert already_filed(tmp_path) == (8, {"Radio": 1})


def test_part_holding_finds_the_file_a_position_falls_in(tmp_path):
    import numpy as np
    import soundfile as sf

    paths = []
    for index, seconds in enumerate((2.0, 3.0), start=1):
        path = tmp_path / f"part{index}.wav"
        sf.write(path, np.zeros((int(8000 * seconds), 1), dtype="float32"), 8000)
        paths.append(path)
    take = SimpleNamespace(paths=paths)

    assert review.part_holding(take, 0.5) == (paths[0], 0.5)
    assert review.part_holding(take, 3.0) == (paths[1], 1.0)
    assert review.part_holding(take, 99.0)[0] == paths[1]


def test_part_holding_is_the_only_file_for_a_single_part_take(tmp_path):
    take = SimpleNamespace(paths=[tmp_path / "only.wav"])
    assert review.part_holding(take, 123.4) == (take.paths[0], 123.4)


def test_names_never_end_in_a_dot_or_space():
    assert safe("Etc.") == "Etc"
    assert safe("Radio ") == "Radio"
    assert safe("Mr. Brightside") == "Mr. Brightside"
    assert safe("Waiting...") == "Waiting"


def test_archive_folder_name_is_spaced_and_never_purely_numeric():
    from rehearsal.export import archive_folder
    name = archive_folder(Path("/tmp"), "260518").name
    assert name == "2026 05 18"
    assert not name.replace(" ", "").isdigit() or " " in name
    assert not name.endswith(".")
