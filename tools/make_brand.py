"""Render the Lambda One brand art used by the start-up screen.

    python tools/make_brand.py

Unlike make_cover.py, this art is not derived from the model -- it is a
letterform and a wordmark -- so the sources are the two SVGs in
tools/brand/ rather than a surface computed here. Edit those, then
regenerate; do not hand-edit the PNGs.

The mark carries the application's own heat-map scale, the three stops of
tuner/ui/colors.py, so the logo is painted in the colours of the thing it
teaches. The wordmark is Cormorant (SIL Open Font License) converted to
outlines, so no font has to be installed on a user's machine.

Outputs:
    tuner/ui/assets/brand-mark.png       512 px tall, transparent
    tuner/ui/assets/brand-word.png      1400 px wide, transparent
    tuner/ui/assets/brand-formula.png   1800 px wide, transparent
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF                       # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter   # noqa: E402
from PySide6.QtSvg import QSvgRenderer                  # noqa: E402

MARK_H = 512
WORD_W = 1400
FORMULA_W = 1800


def render(src: Path, dest: Path, width=None, height=None):
    """Rasterise an SVG at a size fixed by one dimension, keeping aspect."""
    r = QSvgRenderer(str(src))
    if not r.isValid():
        raise SystemExit(f"cannot read {src}")
    box = r.viewBoxF()
    if box.isEmpty():
        raise SystemExit(f"{src} has no viewBox")
    aspect = box.width() / box.height()
    if width is None:
        width = int(round(height * aspect))
    if height is None:
        height = int(round(width / aspect))

    img = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    img.fill(0)                       # transparent: these sit on the surface
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    r.render(p, QRectF(0, 0, width, height))
    p.end()
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest))
    print(f"{dest.relative_to(ROOT)}  {width}x{height}")


def main():
    QGuiApplication(sys.argv)
    src = ROOT / "tools" / "brand"
    assets = ROOT / "tuner" / "ui" / "assets"
    render(src / "lambda-mark.svg", assets / "brand-mark.png", height=MARK_H)
    render(src / "lambda-word.svg", assets / "brand-word.png", width=WORD_W)
    render(src / "lambda-formula.svg", assets / "brand-formula.png", width=FORMULA_W)


if __name__ == "__main__":
    main()
