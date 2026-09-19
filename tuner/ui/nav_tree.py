"""Left-hand navigation tree."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

# (group, [(label, kind, key)])   kinds: table, settings, page, curve, todo
# Every entry opens something. Items that used to open a "not available in
# this build" page are gone rather than greyed: in software somebody has
# paid for, a dead end is worse than an absence. What they stood for lives
# in docs/tuning-app-plan.md, where unbuilt things belong.
TREE = [
    ("TQ-101 Course", [("Labs and progress", "course", "course")]),
    ("Engine Setup", [("Engine Constants", "settings", "engine"),
                      ("Injectors", "settings", "injectors"),
                      ("Trigger / Sensors", "settings", "trigger")]),
    ("Fuel", [("VE Table", "table", "ve"),
              ("Lambda Target", "table", "lambda")]),
    ("Direct Injection", [("Rail Pressure Target", "table", "rail_target"),
                          ("Injection Timing", "table", "soi"),
                          ("Pilot Fraction", "table", "inj_split"),
                          ("Injector & Pump", "settings", "di")]),
    ("Ignition", [("MBT Spark", "table", "mbt"),
                  ("Knock Limit", "table", "knock")]),
    ("Torque", [("Base Torque", "table", "base_torque"),
                ("Friction Model", "settings", "friction")]),
    ("Safety", [("Limits", "settings", "limits")]),
    ("Boost", [("Boost Target", "table", "boost")]),
    ("Datalogging", [("Log Viewer", "page", "datalog")]),
    ("Simulator", [("Live Powertrain", "page", "mimic"),
                   ("Controls", "page", "simdock")]),
]


class NavTree(QTreeWidget):
    activated_item = Signal(str, str, str)      # kind, key, label

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setRootIsDecorated(True)
        for group, children in TREE:
            g = QTreeWidgetItem([group])
            g.setFlags(g.flags() & ~Qt.ItemIsSelectable)
            f = g.font(0); f.setBold(True); g.setFont(0, f)
            for label, kind, key in children:
                c = QTreeWidgetItem([label])
                c.setData(0, Qt.UserRole, (kind, key, label))
                g.addChild(c)
            self.addTopLevelItem(g)
        self.expandAll()
        self.itemClicked.connect(self._clicked)
        self.itemActivated.connect(self._clicked)

    def _clicked(self, item, col):
        d = item.data(0, Qt.UserRole)
        if d:
            self.activated_item.emit(*d)
