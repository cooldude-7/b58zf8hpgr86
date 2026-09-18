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
                    help="skip the start-up screen")
    ap.add_argument("--splash-ms", type=int, default=2000, metavar="MS",
                    help="how long the start-up screen holds (default 2000)")
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
    # Put the start-up screen up BEFORE the window is shown, so the window's
    # first painted frame already carries it. Showing the window first meant
    # a flash of the application, then the cover over the top.
    if not (args.no_splash or args.screenshot):
        from .ui.intro import show_intro
        show_intro(win, hold_ms=args.splash_ms)

    # First run has no saved geometry. Open filled rather than at an
    # arbitrary 1400x860 that the user then has to maximise -- and the
    # start-up screen is the window, so a small window is a small one.
    if getattr(win, "restored_layout", False):
        win.show()
    else:
        win.showMaximized()

    if args.screenshot:
        def snap():
            app.processEvents()
            win.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(400, snap)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
