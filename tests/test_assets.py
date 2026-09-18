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


def test_icon_helper_returns_none_rather_than_a_null_icon(qapp, monkeypatch, tmp_path):
    """Setting a null QIcon as the window icon overrides the one Windows
    takes from the exe, so a blank taskbar button is worse than not setting
    one at all."""
    from tuner.ui import assets as A

    assert A.icon("torquetune.ico") is not None
    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    assert A.icon("torquetune.ico") is None
    assert A.found("torquetune.ico") is False


def test_asset_search_covers_the_frozen_layouts(monkeypatch, tmp_path):
    """PyInstaller 6 unpacks data under _internal; older layouts put it
    beside the exe. Look in both rather than assume one."""
    from tuner.ui import assets as A

    exe = tmp_path / "app" / "TorqueTune.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    target = tmp_path / "app" / "_internal" / "tuner" / "ui" / "assets"
    target.mkdir(parents=True)
    (target / "splash.png").write_bytes(b"x")

    monkeypatch.setattr(A.sys, "frozen", True, raising=False)
    monkeypatch.setattr(A.sys, "executable", str(exe))
    monkeypatch.setattr(A, "_HERE", tmp_path / "nowhere")
    assert A.asset("splash.png") == target / "splash.png"


def test_report_names_every_image(qapp):
    from tuner.ui import assets as A

    text = A.report()
    for name in ("torquetune.ico", "icon.png", "splash.png"):
        assert name in text
    assert "MISSING" not in text, text


def test_splash_appears_and_is_the_right_shape(qapp):
    from tuner.app import make_splash

    sp = make_splash(qapp)
    assert sp is not None
    pm = sp.pixmap()
    assert not pm.isNull()
    assert pm.width() > pm.height(), "the splash is a banner, not a square"
    sp.close()


def test_splash_is_skipped_when_asked(qapp):
    from tuner.app import make_splash

    assert make_splash(qapp, enabled=False) is None


def test_splash_missing_file_is_not_fatal(qapp, monkeypatch, tmp_path):
    """A build without the art must still start, just without a banner."""
    from tuner.ui import assets as A
    from tuner.app import make_splash

    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    assert make_splash(qapp) is None


def test_screenshot_runs_carry_no_splash(qapp, tmp_path, monkeypatch):
    """It would sit on top of the window and land in the picture."""
    import tuner.app as app_mod

    seen = []
    monkeypatch.setattr(app_mod, "make_splash",
                        lambda app, enabled=True: seen.append(enabled) or None)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.exec", lambda self: 0)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__new__",
                        lambda cls, *a, **k: qapp)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__init__", lambda self, *a, **k: None)
    app_mod.main(["--screenshot", str(tmp_path / "s.png")])
    assert seen == [False]


def test_splash_is_sized_to_the_screen(qapp):
    from tuner.app import make_splash

    sp = make_splash(qapp)
    w = sp.pixmap().width() / max(sp.pixmap().devicePixelRatio(), 1.0)
    assert 560 <= w <= 1100, w
    sp.close()


def test_splash_is_held_long_enough_to_read(qapp):
    """Startup from a checkout is a few hundred milliseconds; without a
    floor the banner appears and vanishes in the same blink."""
    import time

    from tuner.app import hold_splash, make_splash

    sp = make_splash(qapp)
    sp.shown_at = time.monotonic()      # loading the image is itself slow here
    t0 = time.monotonic()
    hold_splash(qapp, sp, min_ms=300)
    assert (time.monotonic() - t0) * 1000 >= 250
    sp.close()


def test_holding_an_already_old_splash_returns_at_once(qapp):
    import time

    from tuner.app import hold_splash, make_splash

    sp = make_splash(qapp)
    sp.shown_at = time.monotonic() - 10.0      # as if startup had been slow
    t0 = time.monotonic()
    hold_splash(qapp, sp, min_ms=1400)
    assert (time.monotonic() - t0) < 0.1, "a slow start must not be padded"
    sp.close()


def test_hold_tolerates_no_splash(qapp):
    from tuner.app import hold_splash

    assert hold_splash(qapp, None) == 0.0
