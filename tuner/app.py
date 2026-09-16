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
    ap.add_argument("tune", nargs="?", help="tune file to open")
    args = ap.parse_args(argv)

    if args.screenshot:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from . import APP_NAME, ORG_NAME
    from .core.tune import Tune
    from .ui.main_window import MainWindow
    from .ui.theme import apply_classic

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME); app.setOrganizationName(ORG_NAME)
    apply_classic(app)

    tune = Tune.load(args.tune) if args.tune else None
    win = MainWindow(tune, persist_layout=not args.screenshot)
    if args.demo or args.screenshot:
        win.conn.connect_ecu()
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
