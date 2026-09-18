"""The start-up screen the application shows in its own window.

Not a QSplashScreen: that is a small card floating on the desktop before
the window exists. This is an overlay filling the whole window -- docks,
toolbar and all -- which holds for a couple of seconds and then reveals
the application underneath it.
"""
from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from .. import APP_VERSION
from .assets import asset

BG = QColor("#202020")
DIM = QColor("#6A6A6A")
HOLD_MS = 2000
FADE_MS = 280


class IntroOverlay(QWidget):
    """Covers its parent and paints the start-up art, centred."""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self._pm = pixmap
        self._scaled = None
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self.setFocus()

    # keep covering the window however it is resized
    def eventFilter(self, obj, ev):
        if obj is self.parent() and ev.type() in (QEvent.Resize, QEvent.Show):
            self.setGeometry(self.parent().rect())
            self.raise_()
        return False

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), BG)
        if not self._pm.isNull():
            box = self.size() * 0.92
            if self._scaled is None or self._scaled.size() != box:
                self._scaled = self._pm.scaled(box, Qt.KeepAspectRatio,
                                               Qt.SmoothTransformation)
            s = self._scaled
            p.drawPixmap((self.width() - s.width()) // 2,
                         (self.height() - s.height()) // 2, s)
        f = QFont("Segoe UI")
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(DIM)
        p.drawText(QRect(0, self.height() - 40, self.width() - 28, 20),
                   Qt.AlignRight | Qt.AlignVCenter, f"version {APP_VERSION}")

    # a click or a key gets you past it -- nobody should have to wait
    def mousePressEvent(self, _ev):
        self.dismiss(0)

    def keyPressEvent(self, _ev):
        self.dismiss(0)

    def dismiss(self, fade_ms=FADE_MS):
        if not self.isVisible():
            return
        if fade_ms <= 0:
            self.close()
            return
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade = QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(fade_ms)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.setEasingCurve(QEasingCurve.InQuad)
        self._fade.finished.connect(self.close)
        self._fade.start()


def show_intro(window, hold_ms=HOLD_MS, name="intro.png"):
    """Cover `window` with the start-up art for hold_ms. Returns the
    overlay, or None when there is no art to show."""
    path = asset(name)
    if not path.exists():
        path = asset("splash.png")        # older builds shipped only this
    if not path.exists():
        return None
    pm = QPixmap(str(path))
    if pm.isNull():
        return None
    overlay = IntroOverlay(window, pm)
    QTimer.singleShot(max(hold_ms, 0), overlay.dismiss)
    return overlay
