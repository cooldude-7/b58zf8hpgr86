"""Classic theme: the grey that every tuning application is made of.

Native style where available (windowsvista on Windows), Fusion with a
matching palette elsewhere. Colour is reserved for data -- heat-map cells,
gauge faces, the connection dot. The chrome stays grey.
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

WINDOW = "#F0F0F0"
BASE = "#FFFFFF"
TEXT = "#000000"
MID = "#C8C8C8"
DARK = "#A0A0A0"
HIGHLIGHT = "#0078D7"

QSS = """
QMainWindow::separator { background: %(mid)s; width: 3px; height: 3px; }
QDockWidget::title { background: #E4E4E4; padding: 3px 5px; border: 1px solid %(mid)s; }
QDockWidget { font-weight: normal; }
QToolBar { border-bottom: 1px solid %(mid)s; spacing: 2px; padding: 1px; }
QToolButton { padding: 2px 5px; }
QStatusBar { border-top: 1px solid %(mid)s; }
QStatusBar QLabel { padding: 0 6px; }
QTabBar::tab { padding: 3px 9px; }
QTableView { gridline-color: #C0C0C0; selection-background-color: %(hl)s; }
QHeaderView::section { background: #F0F0F0; border: 1px solid #C0C0C0; padding: 2px 3px; }
QTableCornerButton::section { background: #F0F0F0; border: 1px solid #C0C0C0; }
QTreeWidget { border: none; }
QGroupBox { border: 1px solid %(mid)s; margin-top: 8px; padding-top: 4px; }
QGroupBox::title { subcontrol-origin: margin; left: 6px; padding: 0 3px; }
QLabel#dim { color: #6A6A6A; }
"""


def apply_classic(app: QApplication):
    keys = QStyleFactory.keys()
    for name in ("windowsvista", "Fusion", "Windows"):
        if name in keys:
            app.setStyle(name)
            break

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(WINDOW))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(BASE))
    pal.setColor(QPalette.AlternateBase, QColor("#F7F7F7"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(WINDOW))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(HIGHLIGHT))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Mid, QColor(MID))
    pal.setColor(QPalette.Dark, QColor(DARK))
    pal.setColor(QPalette.ToolTipBase, QColor("#FFFFE1"))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#8A8A8A"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#8A8A8A"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8A8A8A"))
    app.setPalette(pal)

    font = QFont("Segoe UI", 9)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)
    app.setStyleSheet(QSS % dict(mid=MID, hl=HIGHLIGHT))
