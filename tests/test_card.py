import pytest

from rehearsal import card


def test_pull_copies_recordings_not_yet_in_the_inbox(tmp_path):
    disk = (tmp_path / "card")
    disk.mkdir()
    content = b"RIFF" + b"\x00" * 1000
    (disk / "260518_193000_Mic.wav").write_bytes(content)

    inbox = tmp_path / "inbox"
    copied = card.pull(disk, inbox)

    destination, = copied
    assert destination == inbox / "260518_193000_Mic.wav"
    assert destination.read_bytes() == content


def test_pull_skips_recordings_already_in_the_inbox(tmp_path):
    disk = tmp_path / "card"
    disk.mkdir()
    content = b"RIFF" + b"\x00" * 1000
    (disk / "260518_193000_Mic.wav").write_bytes(content)

    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "260518_193000_Mic.wav").write_bytes(content)

    assert card.pull(disk, inbox) == []


def test_copy_raises_when_the_destination_lands_the_wrong_size(tmp_path):
    source = tmp_path / "260518_193000_Mic.wav"
    source.write_bytes(b"RIFF" + b"\x00" * 1000)
    destination = tmp_path / "inbox" / "260518_193000_Mic.wav"
    destination.parent.mkdir()

    with pytest.raises(IOError):
        card._copy(source, destination, size=source.stat().st_size + 1, live=False)
