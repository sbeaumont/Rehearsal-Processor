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

RECORDERS = _settings["recorders"]
AUDIO = _settings["audio"]
REVIEW = _settings["review"]
EXPORT = _settings["export"]

DETECT = {name: value for name, value in _settings["detect"].items()
          if not isinstance(value, dict)}
OVERRIDES = {name: value for name, value in _settings["detect"].items()
             if isinstance(value, dict)}


def path(name):
    """A configured location, with ~ expanded."""
    return Path(_paths["paths"][name]).expanduser()
