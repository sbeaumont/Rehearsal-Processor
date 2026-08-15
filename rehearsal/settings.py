"""Settings: tunable behaviour in settings.toml, local paths in paths.toml."""

import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = PROJECT / "settings.toml"
PATHS_FILE = PROJECT / "paths.toml"


def _read(path, hint):
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing. {hint}")
    return tomllib.loads(path.read_text(encoding="utf-8"))


_settings = _read(SETTINGS_FILE, "It is part of the repository; restore it with git.")
_paths = _read(PATHS_FILE,
               f"Copy {PATHS_FILE.with_name('paths.example.toml').name} to "
               f"{PATHS_FILE.name} and fill in your own locations.")

AUDIO = _settings["audio"]
DETECT = _settings["detect"]
REVIEW = _settings["review"]
EXPORT = _settings["export"]


def path(name):
    """A configured location, with ~ expanded."""
    return Path(_paths["paths"][name]).expanduser()
