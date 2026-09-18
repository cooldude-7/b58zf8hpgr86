"""The application's own art: present, loadable, and the right shape."""
from PySide6.QtGui import QIcon, QPixmap

from tuner.ui.assets import asset


def test_assets_exist():
    for name in ("icon.png", "splash.png", "torquetune.ico"):
        assert asset(name).exists(), name


def test_images_load(qapp):
    icon = QPixmap(str(asset("icon.png")))
    assert not icon.isNull() and icon.width() == icon.height()
    splash = QPixmap(str(asset("splash.png")))
    assert not splash.isNull() and splash.width() > splash.height()


def test_icon_has_no_tile(qapp):
    """The mark is the surface itself. Anything behind it -- a dark square,
    a rounded tile -- is a bug, so the corners must be fully transparent."""
    im = QPixmap(str(asset("icon.png"))).toImage()
    w, h = im.width(), im.height()
    for x, y in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)):
        assert im.pixelColor(x, y).alpha() == 0, (x, y)
    assert im.pixelColor(w // 2, h // 2).alpha() == 255


def test_ico_frames_are_drawn_not_downscaled(qapp):
    """Each frame is rendered at its own size with a grid that size can
    resolve, so the 16 px frame is not the 256 px one shrunk."""
    from PIL import IcoImagePlugin
    from tools.make_cover import ICON_FRAMES, mark
    fh = open(asset("torquetune.ico"), "rb")          # IcoFile reads lazily
    ico = IcoImagePlugin.IcoFile(fh)
    for n in (16, 64):
        cols, rows, stroke = ICON_FRAMES[n]
        want = mark(n, cols, rows, stroke)
        got = ico.getimage((n, n)).convert("RGBA")
        diff = max(abs(want.pixelColor(x, y).alpha() - got.getpixel((x, y))[3])
                   for x in range(n) for y in range(n))
        assert diff == 0, (n, diff)
    fh.close()


def test_ico_carries_small_sizes(qapp):
    """Windows draws the title bar at 16 px; an .ico with only a 256 px
    frame gets downscaled badly by the shell."""
    sizes = {s.width() for s in QIcon(str(asset("torquetune.ico"))).availableSizes()}
    assert {16, 32, 256} <= sizes, sizes
