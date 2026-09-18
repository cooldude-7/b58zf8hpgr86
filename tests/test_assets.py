"""The application's own art: present, loadable, and the right shape."""
from PySide6.QtGui import QIcon, QPixmap

from tuner.ui.assets import asset


def test_assets_exist():
    for name in ("icon.png", "splash.png", "intro.png", "torquetune.ico"):
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


def test_intro_covers_the_whole_window(qapp):
    """The point of it: the window itself is the start-up screen, not a
    card floating in front of one."""
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.resize(900, 600)
    win.show()
    intro = show_intro(win, hold_ms=10_000)
    assert intro is not None
    assert intro.geometry() == win.rect()
    assert intro.isVisible()
    intro.dismiss(0)
    win.close()


def test_intro_follows_a_resize(qapp):
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=10_000)
    win.resize(1100, 700)
    qapp.processEvents()
    assert intro.geometry() == win.rect()
    intro.dismiss(0)
    win.close()


def test_intro_goes_away_on_its_own(qapp):
    from PySide6.QtCore import QEventLoop, QTimer

    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=60)
    gone = []
    intro.destroyed.connect(lambda: gone.append(True))   # it deletes itself
    loop = QEventLoop()
    QTimer.singleShot(900, loop.quit)
    loop.exec()
    assert gone or not intro.isVisible()
    win.close()


def test_intro_can_be_clicked_away(qapp):
    """Waiting two seconds every launch is a cost; a click skips it."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=10_000)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPoint(10, 10), Qt.LeftButton,
                     Qt.LeftButton, Qt.NoModifier)
    intro.mousePressEvent(ev)
    assert not intro.isVisible()
    win.close()


def test_intro_without_art_is_not_fatal(qapp, monkeypatch, tmp_path):
    from tuner.ui import assets as A
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    win = MainWindow(None, persist_layout=False)
    win.show()
    assert show_intro(win) is None
    win.close()


def test_screenshot_runs_carry_no_intro(qapp, tmp_path, monkeypatch):
    """It would sit on top of the window and land in the picture."""
    import tuner.ui.intro as intro_mod

    seen = []
    monkeypatch.setattr(intro_mod, "show_intro", lambda *a, **k: seen.append(a) or None)
    import tuner.app as app_mod

    monkeypatch.setattr("PySide6.QtWidgets.QApplication.exec", lambda self: 0)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__new__", lambda cls, *a, **k: qapp)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__init__", lambda self, *a, **k: None)
    app_mod.main(["--screenshot", str(tmp_path / "s.png")])
    assert seen == []


def test_intro_uses_the_window_shaped_art(qapp):
    """splash.png is a wide card for the About box; scaled up to fill a
    window it floats in the middle with the wordmark adrift. intro.png is
    drawn at window proportions."""
    from tuner.ui.assets import asset

    intro = asset("intro.png")
    assert intro.exists()
    from PySide6.QtGui import QPixmap

    pm = QPixmap(str(intro))
    assert abs(pm.width() / pm.height() - 16 / 9) < 0.02, (pm.width(), pm.height())


def test_intro_falls_back_to_the_banner(qapp, monkeypatch, tmp_path):
    """A build made before intro.png existed still gets a start-up screen."""
    import shutil

    from tuner.ui import assets as A
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    shutil.copy(A.asset("splash.png"), tmp_path / "splash.png")
    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=10_000)
    assert intro is not None
    intro.dismiss(0)
    win.close()
