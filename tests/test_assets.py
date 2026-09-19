"""The application's own art: present, loadable, and the right shape."""
from PySide6.QtGui import QIcon, QPixmap

from tuner.ui.assets import asset


def test_assets_exist():
    for name in ("icon.png", "splash.png", "intro.png", "lambdaone.ico",
                 "brand-mark.png", "brand-word.png", "brand-formula.png"):
        assert asset(name).exists(), name


def test_brand_art_is_transparent(qapp):
    """The mark and the wordmark are drawn over the animating surface, so
    anything opaque behind them -- a tile, a card -- is a bug."""
    for name in ("brand-mark.png", "brand-word.png", "brand-formula.png"):
        im = QPixmap(str(asset(name))).toImage()
        assert not im.isNull(), name
        w, h = im.width(), im.height()
        for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
            assert im.pixelColor(x, y).alpha() == 0, (name, x, y)


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
    fh = open(asset("lambdaone.ico"), "rb")          # IcoFile reads lazily
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
    sizes = {s.width() for s in QIcon(str(asset("lambdaone.ico"))).availableSizes()}
    assert {16, 32, 256} <= sizes, sizes


def test_icon_helper_returns_none_rather_than_a_null_icon(qapp, monkeypatch, tmp_path):
    """Setting a null QIcon as the window icon overrides the one Windows
    takes from the exe, so a blank taskbar button is worse than not setting
    one at all."""
    from tuner.ui import assets as A

    assert A.icon("lambdaone.ico") is not None
    monkeypatch.setattr(A, "_roots", lambda: iter([tmp_path]))
    assert A.icon("lambdaone.ico") is None
    assert A.found("lambdaone.ico") is False


def test_asset_search_covers_the_frozen_layouts(monkeypatch, tmp_path):
    """PyInstaller 6 unpacks data under _internal; older layouts put it
    beside the exe. Look in both rather than assume one."""
    from tuner.ui import assets as A

    exe = tmp_path / "app" / "LambdaOne.exe"
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
    for name in ("lambdaone.ico", "icon.png", "splash.png"):
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


def test_replay_shows_it_without_relaunching(qapp):
    """Distinguishes "this build has no start-up screen" from "it came and
    went before the window appeared"."""
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    intro = win.replay_intro()
    assert intro is not None and intro.isVisible()
    intro.dismiss(0)
    win.close()


def test_report_names_the_build(qapp):
    from tuner.ui.assets import report

    text = report()
    assert "Lambda One" in text
    assert "start-up screen:" in text


def test_brand_arrives_after_the_surface_has_built(qapp):
    """The lambda fades up once the surface is there, then the wordmark is
    uncovered from its left edge. Checked as geometry rather than pixels so
    the sequence is pinned even if the art changes."""
    from tuner.ui import intro as I
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.resize(1600, 900)
    win.show()
    ov = I.show_intro(win, hold_ms=30_000)
    w, h = 1600, 900

    # nothing of the brand while the surface is still rising
    mark_in, _, word_in, _, _, form_in, _ = ov.brand_frame(w, h, t_ms=I.BUILD_MS)
    assert mark_in == 0.0 and word_in == 0.0 and form_in == 0.0

    # the mark is nearly there when the wordmark starts -- they overlap on
    # purpose, so the two read as one movement -- and is full shortly after
    mark_in, _, word_in, _, _, _, _ = ov.brand_frame(w, h, t_ms=I.WORD_AT_MS)
    assert word_in == 0.0 and mark_in > 0.9
    mark_in, _, _, _, _, _, _ = ov.brand_frame(w, h, t_ms=I.MARK_AT_MS + I.MARK_IN_MS)
    assert mark_in == 1.0

    # and the wordmark finishes within the hold, so it is actually seen
    mark_in, mark_rect, word_in, word_rect, base, _, _ = ov.brand_frame(
        w, h, t_ms=I.WORD_AT_MS + I.WORD_IN_MS)
    assert word_in == 1.0
    assert I.WORD_AT_MS + I.WORD_IN_MS < I.HOLD_MS

    # wordmark sits to the right of the mark, on the same baseline
    assert word_rect.left() > mark_rect.right()
    assert abs(word_rect.bottom() - base) < 1.0
    assert abs(mark_rect.bottom() - base) < 1.0
    ov.dismiss(0)
    win.close()


def test_brand_falls_back_to_text_when_art_is_missing(qapp):
    """A build made before the art existed must still name the application
    rather than drawing an empty corner."""
    from PySide6.QtGui import QPixmap as _QPixmap

    from tuner.ui import intro as I
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    ov = I.show_intro(win, hold_ms=30_000)
    ov._mark, ov._word = _QPixmap(), _QPixmap()      # as a failed load leaves them
    assert ov.brand_frame(1600, 900, t_ms=3000) is None
    ov.grab()                                        # must not raise
    ov.dismiss(0)
    win.close()


def test_the_equation_arrives_last_and_is_seen(qapp):
    """It fades in under the lockup, after the wordmark, and has to finish
    well inside the hold or it is animation nobody watches."""
    from tuner.ui import intro as I
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.resize(1600, 900)
    win.show()
    ov = I.show_intro(win, hold_ms=30_000)

    _, _, _, _, _, form_in, _ = ov.brand_frame(1600, 900, t_ms=I.WORD_AT_MS)
    assert form_in == 0.0, "must not start before the wordmark does"

    _, _, _, word_rect, base, form_in, form_rect = ov.brand_frame(
        1600, 900, t_ms=I.FORM_AT_MS + I.FORM_IN_MS)
    assert form_in == 1.0
    assert I.FORM_AT_MS + I.FORM_IN_MS < I.HOLD_MS - I.FADE_MS

    # under the lockup, left-aligned with the mark, clear of the baseline
    assert form_rect.top() > base
    assert form_rect.left() < word_rect.left()
    ov.dismiss(0)
    win.close()


def test_the_equation_fits_a_small_window(qapp):
    """It is the widest thing on the screen, so it is the one that runs out
    of room first."""
    from tuner.ui import intro as I
    from tuner.ui.main_window import MainWindow

    win = MainWindow(None, persist_layout=False)
    win.show()
    ov = I.show_intro(win, hold_ms=30_000)
    for w, h in ((1600, 900), (1280, 720), (1024, 640)):
        *_, form_rect = ov.brand_frame(w, h, t_ms=3000)
        assert form_rect.right() < w * 0.75, (w, h, form_rect.right())
        assert form_rect.bottom() < h * 0.93, (w, h, form_rect.bottom())
    ov.dismiss(0)
    win.close()
