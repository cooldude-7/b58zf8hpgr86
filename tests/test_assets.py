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


def test_intro_ignores_input_until_it_has_been_seen(qapp):
    """A double-click on the desktop icon lands its second click on the new
    window, and Start-menu launches end with Enter. Either one used to skip
    the screen before it had drawn a frame."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=10_000)
    qapp.processEvents()                      # first paint starts the clock
    click = QMouseEvent(QEvent.MouseButtonPress, QPoint(10, 10), Qt.LeftButton,
                        Qt.LeftButton, Qt.NoModifier)
    intro.mousePressEvent(click)
    assert intro.isVisible(), "a click in the first moment must not dismiss it"

    intro.clock.restart()
    intro._painted = True
    import time
    time.sleep(0.05)
    intro._skippable = lambda: True           # as if the grace had passed
    intro.mousePressEvent(click)
    assert not intro.isVisible()
    win.close()


def test_intro_needs_no_image_files(qapp, monkeypatch, tmp_path):
    """The animation draws the surface itself, so a build with no PNGs
    still gets a start-up screen."""
    from tuner.ui import assets as A
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=5000)
    assert intro is not None and intro.base is not None
    intro.dismiss(0)
    assert show_intro(win, animate=False) is None      # nothing left to draw
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
    """With the animation off, the painted art is used instead."""
    import shutil

    from tuner.ui import assets as A
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    shutil.copy(A.asset("splash.png"), tmp_path / "splash.png")
    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = show_intro(win, hold_ms=10_000, animate=False)
    assert intro is not None and intro.base is None
    intro.dismiss(0)
    win.close()


def test_intro_covers_a_window_shown_after_it(qapp):
    """It is created before the window is shown, so the window's first
    painted frame already carries it -- otherwise you see a flash of the
    application and then the cover landing on top."""
    from tuner.ui.intro import show_intro
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    intro = show_intro(win, hold_ms=10_000)      # before show, as main() does
    win.showMaximized()
    qapp.processEvents()
    assert intro.geometry() == win.rect()
    assert intro.isVisible()
    intro.dismiss(0)
    win.close()


def test_first_run_opens_filled(qapp, tmp_path, monkeypatch):
    """With no saved geometry the window opened at 1400x860 and the user
    had to maximise it every time -- and a small window means a small
    start-up screen."""
    import tuner.app as app_mod
    from tuner.ui.main_window import MainWindow

    shown = []
    monkeypatch.setattr(MainWindow, "showMaximized", lambda self: shown.append("max"))
    monkeypatch.setattr(MainWindow, "show", lambda self: shown.append("normal"))
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.exec", lambda self: 0)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__new__", lambda cls, *a, **k: qapp)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__init__", lambda self, *a, **k: None)
    app_mod.main(["--no-splash", "--screenshot", str(tmp_path / "s.png")])
    assert shown == ["max"], shown


def test_intro_animates(qapp):
    """The whole point: the surface at the start is not the surface a
    second later."""
    import numpy as np

    from tuner.ui.intro import IntroOverlay
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.resize(900, 600)
    intro = IntroOverlay(win, hold_ms=5000)
    early, _ = intro.frame(150)
    mid, _ = intro.frame(1500)
    late, _ = intro.frame(3000)
    assert np.ptp(early) < np.ptp(mid) * 0.5, "it should start near flat and rise"
    assert not np.allclose(mid, late), "the values should keep moving"
    assert intro.camera(0.0) < intro.camera(4.0), "the camera should drift"
    intro.dismiss(0)
    win.close()


def test_intro_settles_before_it_goes(qapp):
    """Motion eases out, so the app is not revealed mid-wobble."""
    import numpy as np

    from tuner.ui.intro import IntroOverlay
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    intro = IntroOverlay(win, hold_ms=5000)
    settled, _ = intro.frame(4990)
    assert np.allclose(settled, intro.base, atol=1e-6)
    intro.dismiss(0)
    win.close()


def test_intro_frame_is_cheap_enough_for_30fps(qapp):
    """A stuttering loading screen is worse than a still one."""
    import time

    from tuner.ui.intro import IntroOverlay
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.resize(1280, 800)
    intro = IntroOverlay(win, hold_ms=5000)
    win.show()
    qapp.processEvents()
    t0 = time.perf_counter()
    for _ in range(20):
        intro.grab()
    mean_ms = (time.perf_counter() - t0) / 20 * 1000
    assert mean_ms < 30, f"{mean_ms:.1f} ms a frame"
    intro.dismiss(0)
    win.close()


def test_intro_timer_dies_with_the_overlay(qapp):
    """A repaint timer left running after dismissal burns CPU for the life
    of the session."""
    from tuner.ui.intro import IntroOverlay
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    intro = IntroOverlay(win, hold_ms=5000)
    assert intro._timer is not None and intro._timer.isActive()
    intro.dismiss(0)
    assert intro._timer is None
    win.close()


def test_startup_work_runs_behind_the_screen(qapp):
    """Deferred so the screen covers real work instead of padding time."""
    from tuner.ui.main_window import MainWindow

    plain = MainWindow(None, persist_layout=False)
    assert plain.startup_steps == []          # the log was loaded inline
    plain.close()

    deferred = MainWindow(None, persist_layout=False, defer_startup=True)
    assert [label for label, _ in deferred.startup_steps]
    for _, step in deferred.startup_steps:
        step()
    deferred.close()


def test_intro_can_be_turned_off_for_good(qapp, monkeypatch):
    from PySide6.QtCore import QSettings

    from tuner.ui.intro import intro_enabled, set_intro_enabled

    store = {}
    monkeypatch.setattr(QSettings, "value",
                        lambda self, k, d=None: store.get(k, d))
    monkeypatch.setattr(QSettings, "setValue",
                        lambda self, k, v: store.__setitem__(k, v))
    assert intro_enabled() is True
    set_intro_enabled(False)
    assert intro_enabled() is False
    set_intro_enabled(True)
    assert intro_enabled() is True


def test_hold_is_measured_from_the_first_visible_frame(qapp):
    """Unpacking, window mapping and the maximise all happen before the
    first paint. Time eaten there is animation nobody watched."""
    from tuner.ui.intro import IntroOverlay
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    intro = IntroOverlay(win, hold_ms=5000)
    assert intro._painted is False
    win.show()
    qapp.processEvents()
    assert intro._painted is True
    assert intro.clock.elapsed() < 500, "the clock should restart at that frame"
    intro.dismiss(0)
    win.close()


def test_window_is_sized_before_it_is_shown(qapp, tmp_path, monkeypatch):
    """Show first and maximise after and you get a frame at 1400x860 then a
    jump -- which looks like a small splash that grows."""
    import tuner.app as app_mod
    from tuner.ui.main_window import MainWindow

    order = []
    monkeypatch.setattr(MainWindow, "setGeometry", lambda self, g: order.append("geometry"))
    monkeypatch.setattr(MainWindow, "showMaximized", lambda self: order.append("show"))
    monkeypatch.setattr(MainWindow, "show", lambda self: order.append("show-normal"))
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.exec", lambda self: 0)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__new__", lambda cls, *a, **k: qapp)
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.__init__", lambda self, *a, **k: None)
    app_mod.main(["--no-splash", "--screenshot", str(tmp_path / "s.png")])
    assert order == ["geometry", "show"], order
