"""TQ-101: the course page.

Lists the labs, states what each one asks for, and marks the current
tune against the simulator's hidden plant. The grading lives in
tuner/core/course.py; this is only the desk it is handed in at.
"""
from PySide6.QtCore import Qt, QSettings, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QProgressBar, QPushButton,
                               QSplitter, QTextEdit, QVBoxLayout, QWidget)

from .. import APP_NAME, ORG_NAME
from ..core import course

PASS_MARK = "✓"          # tick
FAIL_MARK = "•"          # bullet


class CoursePage(QWidget):
    load_student_tune = Signal()

    def __init__(self, get_tune, get_plant, parent=None):
        super().__init__(parent)
        self._get_tune = get_tune
        self._get_plant = get_plant
        self._results = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        head = QLabel(
            "<b>TQ-101 &mdash; Engine Calibration</b><br>"
            "Six graded labs. Each one is marked against the engine the "
            "simulator is actually running, which is not the engine your "
            "tables describe.<br>"
            "Lectures: <tt>docs/course/</tt> &nbsp;·&nbsp; "
            "Start each session at the "
            "<a href=\"https://claude.ai/artifact/LnNL2zyGuDTLqQrn2sx3Vr\">Calibration Bench</a>, "
            "which tells you which sitting you are on.")
        head.setOpenExternalLinks(True)
        head.setTextFormat(Qt.RichText)
        head.setWordWrap(True)
        root.addWidget(head)

        bar = QHBoxLayout()
        self.b_load = QPushButton("Load the course tune")
        self.b_load.setToolTip(
            "Replaces the current tune with the TQ-101 starting tune, which "
            "is wrong in the specific ways the labs ask you to fix.")
        self.b_load.clicked.connect(self.load_student_tune.emit)
        self.b_all = QPushButton("Mark everything")
        self.b_all.clicked.connect(self.check_all)
        bar.addWidget(self.b_load)
        bar.addWidget(self.b_all)
        bar.addStretch(1)
        self.l_overall = QLabel()
        bar.addWidget(self.l_overall)
        root.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        for lab in course.LABS:
            QListWidgetItem(f"{FAIL_MARK}  {lab.title}", self.list)
        self.list.currentRowChanged.connect(self._show)
        split.addWidget(self.list)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.l_title = QLabel()
        f = self.l_title.font(); f.setBold(True); self.l_title.setFont(f)
        self.l_brief = QLabel(); self.l_brief.setWordWrap(True)
        self.l_crit = QLabel(); self.l_crit.setWordWrap(True)
        self.l_crit.setObjectName("dim")
        self.bar = QProgressBar(); self.bar.setRange(0, 100)
        self.b_check = QPushButton("Mark this lab")
        self.b_check.clicked.connect(self.check_current)
        self.out = QTextEdit(); self.out.setReadOnly(True)
        self.out.setLineWrapMode(QTextEdit.NoWrap)
        for w in (self.l_title, self.l_brief, self.l_crit, self.bar,
                  self.b_check):
            rl.addWidget(w)
        rl.addWidget(self.out, 1)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self._restore()
        self.list.setCurrentRow(0)

    # -- state ----------------------------------------------------------
    def _restore(self):
        s = QSettings(ORG_NAME, APP_NAME)
        for lab in course.LABS:
            if s.value(f"course/{lab.key}", False, type=bool):
                self._results[lab.key] = None      # passed previously
        self._refresh_marks()

    def _remember(self, key: str, passed: bool):
        QSettings(ORG_NAME, APP_NAME).setValue(f"course/{key}", passed)

    def _refresh_marks(self):
        done = 0
        for row, lab in enumerate(course.LABS):
            r = self._results.get(lab.key, False)
            passed = (r is None) or (r is not False and r.passed)
            done += bool(passed)
            mark = PASS_MARK if passed else FAIL_MARK
            self.list.item(row).setText(f"{mark}  {lab.title}")
        self.l_overall.setText(f"<b>{done} of {len(course.LABS)} passed</b>")

    # -- marking --------------------------------------------------------
    def _show(self, row: int):
        if not 0 <= row < len(course.LABS):
            return
        lab = course.LABS[row]
        self.l_title.setText(lab.title)
        self.l_brief.setText(lab.brief)
        self.l_crit.setText("Pass mark: " + lab.criterion)
        r = self._results.get(lab.key)
        if r is None or r is False:
            self.out.clear()
            self.bar.setValue(0)
        else:
            self._render(r)

    def _render(self, r):
        self.bar.setValue(int(round(r.score * 100)))
        colour = "#1F7A34" if r.passed else "#A00000"
        lines = [f"<p style='color:{colour}'><b>"
                 f"{'PASS' if r.passed else 'NOT YET'}</b> &mdash; "
                 f"{r.summary}</p>"]
        if r.findings:
            lines.append("<pre>")
            for f in r.findings[:40]:
                lines.append(str(f))
            if len(r.findings) > 40:
                lines.append(f"... and {len(r.findings) - 40} more")
            lines.append("</pre>")
        self.out.setHtml("\n".join(lines))

    def check_current(self):
        row = self.list.currentRow()
        if 0 <= row < len(course.LABS):
            self._mark(course.LABS[row])
            self._show(row)

    def check_all(self):
        for lab in course.LABS:
            self._mark(lab)
        self._show(self.list.currentRow())

    def _mark(self, lab):
        try:
            r = lab.run(self._get_tune(), self._get_plant())
        except Exception as e:                    # noqa: BLE001
            r = course.Result(False, f"the marker could not run: {e}", [], 0.0)
        self._results[lab.key] = r
        self._remember(lab.key, r.passed)
        self._refresh_marks()
        return r
