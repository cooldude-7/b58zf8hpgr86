"""Where the application's own images live.

Running from the repo they sit next to this module. Frozen, PyInstaller
unpacks them under _MEIPASS with the same relative path (see
packaging/tuner.spec), so one lookup covers both.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def asset(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "tuner" / "ui" / "assets" / name
    return _HERE / "assets" / name
