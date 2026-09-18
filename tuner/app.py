"""Entry point.

    python -m tuner                 normal start
    python -m tuner --demo          start already connected to the demo ECU
    python -m tuner --screenshot out.png   render offscreen and exit
"""
import argparse
import os
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="torquetune")
    ap.add_argument("--demo", action="store_true", help="connect to the demo ECU on start")
    ap.add_argument("--screenshot", metavar="PNG", help="render the main window to a file and exit")
    ap.add_argument("--three-d", action="store_true", help="with --screenshot: show the 3D surface")
    ap.add_argument("--sim", type=float, metavar="PEDAL", help="connect to the simulator with the pedal at PEDAL %%")
    ap.add_argument("--advance", type=float, default=0.0, metavar="SEC", help="step the simulator SEC seconds first")
    ap.add_argument("--open", metavar="KEY", help="open a navigator item, e.g. mimic")
    ap.add_argument("--max", action="store_true", help="with --open mimic: maximize the live view")
    ap.add_argument("tune", nargs="?", help="tune file to open")
    args = ap.parse_args(argv)

    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from . import APP_NAME, ORG_NAME
    from .core.tune import Tune
    from .ui.assets import asset
    from .ui.main_window import MainWindow
    from .ui.theme import apply_classic

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME); app.setOrganizationName(ORG_NAME)
    # the .ico carries a frame drawn for each size; a single large PNG would
    # be downscaled by the shell and lose the ridgelines
    app.setWindowIcon(QIcon(str(asset("torquetune.ico"))))
    apply_classic(app)

    tune = Tune.load(args.tune) if args.tune else None
    win = MainWindow(tune, persist_layout=not args.screenshot)
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
    win.show()

    if args.screenshot:
        def snap():
            app.processEvents()
            win.grab().save(args.screenshot)
            app.quit()
        QTimer.singleShot(400, snap)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
