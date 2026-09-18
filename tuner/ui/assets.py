"""Where the application's own images live, and how to load them safely.

From a checkout they sit next to this module. Frozen, PyInstaller unpacks
them under _MEIPASS with the same relative path (see packaging/tuner.spec)
-- but a build made before the images were added, or a layout change in a
future PyInstaller, leaves them somewhere else or nowhere. So look in every
plausible place and report what was found, rather than handing Qt a path
that is not there.

That matters more than it sounds: QIcon of a missing file is a null icon,
and setting a null window icon overrides the icon Windows would otherwise
have taken from the exe. A failed lookup does not fall back to the exe
icon, it erases it -- a blank taskbar button.
"""
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _roots():
    yield _HERE / "assets"
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        yield base / "tuner" / "ui" / "assets"
        yield base / "assets"
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        yield exe / "_internal" / "tuner" / "ui" / "assets"
        yield exe / "tuner" / "ui" / "assets"
        yield exe / "assets"


def asset(name: str) -> Path:
    """The first existing copy, or the most likely path if there is none --
    callers that draw must still check, and the returned path makes a
    missing file legible in an error message."""
    first = None
    for root in _roots():
        p = root / name
        if first is None:
            first = p
        if p.exists():
            return p
    return first


def found(name: str) -> bool:
    return asset(name).exists()


def icon(name: str = "torquetune.ico"):
    """A QIcon, or None when the file is missing or unreadable. Never a null
    icon: setting one blanks the window and taskbar icon."""
    from PySide6.QtGui import QIcon

    path = asset(name)
    if not path.exists():
        return None
    ic = QIcon(str(path))
    return None if ic.isNull() or not ic.availableSizes() else ic


def report() -> str:
    """Which images resolved and where -- for --check-assets."""
    lines = []
    for name in ("torquetune.ico", "icon.png", "splash.png", "intro.png"):
        p = asset(name)
        lines.append(f"{'found  ' if p.exists() else 'MISSING'}  {name}\n          {p}")
    lines.append("")
    lines.append(f"frozen: {bool(getattr(sys, 'frozen', False))}")
    lines.append(f"_MEIPASS: {getattr(sys, '_MEIPASS', '(none)')}")
    return "\n".join(lines)
