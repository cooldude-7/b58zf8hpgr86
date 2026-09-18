"""Entry point.

    python -m tuner                 normal start
    python -m tuner --demo          start already connected to the demo ECU
    python -m tuner --screenshot out.png   render offscreen and exit
"""
import argparse
import os
import sys


def _set_windows_app_id():
    """Give Windows an explicit application identity.

    Without one the shell attributes the window to whatever launched it --
    python.exe when running from source -- so the taskbar shows the Python
    icon, windows group under the wrong button, and a pinned shortcut opens
    a second entry instead of lighting up the first one.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TorqueTune.Tuner")
    except Exception:
        pass            # cosmetic only; never worth failing a launch over


def open_tune(path):
    """Load a tune named on the command line, or report why not.

    Double-clicking a .tune file lands here, and the frozen build has no
    console, so an uncaught exception would be a silent death. Say what is
    wrong and start empty instead.
    """
    from . import APP_NAME
    from .core.tune import Tune
    try:
        return Tune.load(path)
    except Exception as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, f"{APP_NAME} — cannot open", f"{path}\n\n{exc}")
        return None


SPLASH_MIN_MS = 1400          # long enough to read; short enough not to annoy
SPLASH_SCREEN_FRACTION = 0.42  # of the screen's width


def make_splash(app, enabled=True):
    """The startup banner, or None.

    Sized against the screen rather than fixed, so it is a presence on a
    1080p laptop and does not become a stamp on a 4K monitor. It is
    deliberately not window-sized: a splash is a card in the middle of the
    screen, shown before there is a window to cover.
    """
    if not enabled:
        return None
    import time

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QSplashScreen

    from .ui.assets import asset

    path = asset("splash.png")
    if not path.exists():
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None

    ratio = max(app.devicePixelRatio() if hasattr(app, "devicePixelRatio") else 1.0, 1.0)
    screen = app.primaryScreen()
    avail = screen.availableGeometry().width() if screen else 1280
    width = int(min(max(avail * SPLASH_SCREEN_FRACTION, 560), 1100))
    pm = pm.scaledToWidth(int(width * ratio), Qt.SmoothTransformation)
    pm.setDevicePixelRatio(ratio)

    splash = QSplashScreen(pm)
    splash.shown_at = time.monotonic()
    splash.show()
    splash.raise_()
    app.processEvents()          # paint it before the slow part starts
    return splash


def hold_splash(app, splash, min_ms=SPLASH_MIN_MS):
    """Keep the splash up until it has been readable for min_ms.

    Startup from a checkout takes a couple of hundred milliseconds, so
    without this the banner appears and vanishes in the same blink -- which
    looks like a glitch rather than a start-up screen. Events keep being
    processed while waiting, so the splash paints and the app stays
    responsive.
    """
    import time

    if splash is None:
        return 0.0
    start = getattr(splash, "shown_at", None) or time.monotonic()
    waited = 0.0
    while True:
        elapsed = (time.monotonic() - start) * 1000.0
        if elapsed >= min_ms:
            return waited
        app.processEvents()
        time.sleep(0.02)
        waited += 0.02


def main(argv=None):
    ap = argparse.ArgumentParser(prog="torquetune")
    ap.add_argument("--demo", action="store_true", help="connect to the demo ECU on start")
    ap.add_argument("--screenshot", metavar="PNG", help="render the main window to a file and exit")
    ap.add_argument("--three-d", action="store_true", help="with --screenshot: show the 3D surface")
    ap.add_argument("--sim", type=float, metavar="PEDAL", help="connect to the simulator with the pedal at PEDAL %%")
    ap.add_argument("--advance", type=float, default=0.0, metavar="SEC", help="step the simulator SEC seconds first")
    ap.add_argument("--open", metavar="KEY", help="open a navigator item, e.g. mimic")
    ap.add_argument("--max", action="store_true", help="with --open mimic: maximize the live view")
    ap.add_argument("--no-splash", action="store_true",
                    help="skip the startup splash")
    ap.add_argument("--check-assets", action="store_true",
                    help="report where the application found its images, and exit")
    ap.add_argument("tune", nargs="?", help="tune file to open")
    args = ap.parse_args(argv)

    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    if args.check_assets:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from .ui import assets
        text = assets.report()
        print(text)
        # the frozen build has no console, so say it in a window too
        QApplication(sys.argv[:1])
        QMessageBox.information(None, "TorqueTune — images", text)
        return 0

    from PySide6.QtCore import QTimer

    from PySide6.QtWidgets import QApplication
    from . import APP_NAME, ORG_NAME
    from .core.tune import Tune
    from .ui import assets
    from .ui.main_window import MainWindow
    from .ui.theme import apply_classic

    _set_windows_app_id()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME); app.setOrganizationName(ORG_NAME)
    # The .ico carries a frame drawn for each size; a single large PNG
    # would be downscaled by the shell and lose the grid. Set it only if it
    # really loaded -- a null icon overrides the one Windows takes from the
    # exe and leaves a blank taskbar button.
    app_icon = assets.icon("torquetune.ico") or assets.icon("icon.png")
    if app_icon is not None:
        app.setWindowIcon(app_icon)
    apply_classic(app)

    # Offscreen runs have no one to show it to, and it would land in the
    # screenshot.
    splash = make_splash(app, enabled=not (args.no_splash or args.screenshot))

    tune = open_tune(args.tune) if args.tune else None
    win = MainWindow(tune, persist_layout=not args.screenshot)
    if app_icon is not None:
        win.setWindowIcon(app_icon)      # some shells read the window, not the app
    if args.sim is not None:
        win.use_simulator()
        win.sim.pedal = args.sim / 100.0
        win.sim_dock.pedal.setValue(int(args.sim))
        win.conn.connect_ecu()
        for _ in range(int(args.advance / win.sim.dt)):
            win.sim._step()
        win.sim.channels_updated.emit(win.sim.channels())
    elif args.demo or args.screenshot:
        win.conn.connect_ecu()
    if args.open:
        win.open_key(args.open)
        if args.max and args.open == "mimic":
            win.set_mimic_maximized(True)
    if args.three_d and "ve" in win.editors:
        win.editors["ve"].show_3d()
    # Hold the banner before the window appears, not after: a splash that
    # is dismissed by the thing it was covering looks like a flicker.
    hold_splash(app, splash)
    win.show()
    if splash is not None:
        splash.finish(win)

    if args.screenshot:
        def snap():
            app.processEvents()
            win.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(400, snap)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
