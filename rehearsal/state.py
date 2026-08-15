"""Review progress, kept as JSON in the local work directory."""

import json

FILENAME = "session.json"


def path(work_dir):
    return work_dir / FILENAME


def key(take_name, detected_start):
    """Identity of a segment: where detection put it, never where the user moved it."""
    return f"{take_name}@{detected_start:.1f}"


def load(work_dir):
    """Titles and start adjustments from an earlier run, keyed by detected start."""
    stored = path(work_dir)
    if not stored.exists():
        return {}
    record = json.loads(stored.read_text(encoding="utf-8"))
    return {entry["key"]: entry for entry in record["segments"]}


def save(work_dir, date, entries):
    """Write every reviewed segment so a run can be resumed."""
    record = {
        "date": date,
        "segments": [
            {
                "key": key(take.name, detected_start),
                "take": take.name,
                "detected_start": round(detected_start, 2),
                "start": round(song.start, 2),
                "end": round(song.end, 2),
                "confidence": song.confidence,
                "origin": song.origin,
                "title": title,
            }
            for take, song, title, detected_start in entries
        ],
    }
    path(work_dir).write_text(json.dumps(record, indent=2, ensure_ascii=False),
                              encoding="utf-8")
