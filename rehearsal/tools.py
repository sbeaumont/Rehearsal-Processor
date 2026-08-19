"""External programs this app shells out to."""

import shutil
import subprocess

NEEDED = {
    "ffmpeg": "normalises and encodes the mp3s, and decodes what libsndfile "
              "cannot read.  brew install ffmpeg",
    "ffprobe": "reads the length of those files.  It ships with ffmpeg.",
    "afplay": "plays the previews.  It ships with macOS.",
}

ENCODER = "libmp3lame"


def check():
    """Fail before a rehearsal is reviewed, not after, when a tool is missing."""
    missing = [f"  {name}  —  {why}" for name, why in NEEDED.items() if not shutil.which(name)]
    if missing:
        raise RuntimeError("missing required program(s):\n" + "\n".join(missing))

    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                              capture_output=True, text=True, check=True).stdout
    if ENCODER not in encoders:
        raise RuntimeError(
            f"this ffmpeg has no {ENCODER} encoder, so it cannot write mp3s.\n"
            f"  Reinstall a build with mp3 support:  brew install ffmpeg")
