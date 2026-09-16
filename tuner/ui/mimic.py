"""Live powertrain mimic -- SCADA-style animated process graphics.

Two graphics drawn from the live channel dictionary: an engine cylinder
cutaway running the four-stroke cycle in slow motion, and a ZF 8HP schematic
with its five shift elements. Nothing here computes physics; it shows what
the simulator (or later a real ECU) reports.
"""
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

BG = QColor("#F6F6F2"); INK = QColor("#202020"); LINE = QColor("#3A3A3A"); DIM = QColor("#6A6A6A")
STEEL = QColor("#C4C8CE"); STEEL_DK = QColor("#8D939B"); STEEL_LT = QColor("#E6E8EB")
FRICTION = QColor("#7A5230"); TAG_BG = QColor("#FFFFFF"); TAG_BD = QColor("#9A9A9A")
LED_ON = QColor("#1FA83A"); LED_OFF = QColor("#BDBDBD"); LED_WARN = QColor("#E08A1E")
FILL = QColor("#2F7ED8"); CHARGE = QColor("#4F9BE8"); CHARGE_RICH = QColor("#2C6FC4")
CHARGE_LEAN = QColor("#9CC7F0"); FLAME = QColor("#F5B400"); BURN = QColor("#EE5A1A"); EXH = QColor("#8C8C8C")
ELEMENTS = "ABCDE"
ENGAGED = {1: "ABC", 2: "ABE", 3: "BCE", 4: "BDE", 5: "BCD", 6: "CDE", 7: "ACD", 8: "ADE"}
P_MAX = 18.0
NM_PER_BAR = 38.0


FONT_SCALE = 1.35        # logical canvases are drawn at 0.5-0.8 scale in a docked window


def _font(size, bold=False, mono=False):
    f = QFont("Consolas" if mono else "Segoe UI"); f.setStyleHint(QFont.Monospace if mono else QFont.SansSerif)
    f.setPointSizeF(size * FONT_SCALE); f.setBold(bold); return f


def text(p, x, y, w, h, s, size=8, color=INK, bold=False, align=Qt.AlignLeft | Qt.AlignVCenter, mono=False):
    p.setFont(_font(size, bold, mono)); p.setPen(color)
    p.drawText(QRectF(x, y, w, h), align, s)


def led(p, cx, cy, on, r=4.0, warn=False):
    p.setPen(QPen(QColor("#555555"), 0.8)); p.setBrush(LED_WARN if warn else (LED_ON if on else LED_OFF))
    p.drawEllipse(QPointF(cx, cy), r, r)


def tag(p, x, y, w, name, value, unit="", state=None, h=20):
    """SCADA value tag: bordered box, grey name, monospace value, optional LED."""
    p.setPen(QPen(TAG_BD, 1)); p.setBrush(TAG_BG); p.drawRect(QRectF(x, y, w, h))
    text(p, x + 4, y, w * 0.42, h, name, 6.5, DIM)
    right = w - 4 - (14 if state is not None else 0)
    text(p, x, y, right, h, f"{value} {unit}".strip(), 7.5, INK, True, Qt.AlignRight | Qt.AlignVCenter, mono=True)
    if state is not None:
        led(p, x + w - 9, y + h / 2, bool(state))


def fit(p, w, h, W, H):
    s = min(w / W, h / H)
    p.translate((w - W * s) / 2, (h - H * s) / 2); p.scale(s, s)


def lerp(a: QColor, b: QColor, f: float) -> QColor:
    f = min(max(f, 0.0), 1.0)
    return QColor(int(a.red() + (b.red() - a.red()) * f), int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


# ===========================================================================
class EngineCutaway(QWidget):
    """One cylinder in section, four-stroke cycle in slow motion."""
    W, H = 520, 600
    R, L, CX, CY = 80.0, 200.0, 200.0, 430.0          # crank radius, rod, crank centre
    BL, BR, DECK, BOT = 120.0, 280.0, 110.0, 335.0    # bore, deck line, wall bottom
    PLUG = QPointF(200.0, 96.0)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ch = {}
        self.theta = 352.0
        self.setMinimumSize(260, 300)

    def advance(self, dt):
        rpm = self.ch.get("rpm", 0.0)
        if rpm < 50:
            return
        period = min(max(2.4 * 3000.0 / rpm, 1.2), 8.0)     # seconds per 720 degrees, slowed right down
        self.theta = (self.theta + 720.0 * dt / period) % 720.0

    def pin_y(self, th):
        a = math.radians(th)
        return self.CY - (self.R * math.cos(a) + math.sqrt(self.L ** 2 - (self.R * math.sin(a)) ** 2))

    def chamber_path(self, crown):
        path = QPainterPath()
        path.moveTo(self.BL, self.DECK); path.lineTo(165, 88); path.lineTo(235, 88); path.lineTo(self.BR, self.DECK)
        path.lineTo(self.BR, crown); path.lineTo(self.BL, crown); path.closeSubpath()
        return path

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), BG)
        fit(p, self.width(), self.height(), self.W, self.H)
        ch, th = self.ch, self.theta
        spark, mbt, knock = ch.get("spark", 20.0), ch.get("mbt", 20.0), ch.get("knock", 30.0)
        lam, map_kpa = ch.get("lambda", 1.0), ch.get("map", 30.0)
        th_spark = 360.0 - spark
        crown = self.pin_y(th) - 32.0
        stroke = ("INTAKE", "COMPRESSION", "POWER", "EXHAUST")[int(th // 180) % 4]
        dens = min(max(map_kpa / 200.0, 0.12), 1.0)

        # ---- head, ports, valves ---------------------------------------------
        head = QPainterPath(); head.moveTo(90, 40); head.lineTo(310, 40); head.lineTo(310, self.DECK)
        head.lineTo(self.BR, self.DECK); head.lineTo(235, 88); head.lineTo(165, 88); head.lineTo(self.BL, self.DECK)
        head.lineTo(90, self.DECK); head.closeSubpath()
        p.setPen(QPen(LINE, 1.2)); p.setBrush(STEEL_LT); p.drawPath(head)
        in_lift = 14.0 * math.sin(math.pi * ((th + 10) % 720) / 200.0) if (th + 10) % 720 < 200 else 0.0
        ex_lift = 14.0 * math.sin(math.pi * (th - 530) / 200.0) if 530 < th < 730 else 0.0
        for px, lift, colour, is_in in ((160, in_lift, CHARGE, True), (240, ex_lift, EXH, False)):
            p.setPen(Qt.NoPen); p.setBrush(BG); p.drawRect(QRectF(px - 12, 40, 24, 46))      # port passage
            p.setPen(QPen(LINE, 1)); p.setBrush(STEEL_DK)
            p.drawRect(QRectF(px - 3, 38, 6, 52 + lift))                                    # stem
            p.drawRect(QRectF(px - 14, 86 + lift, 28, 5))                                   # valve head
            if lift > 2:                                                                     # flow arrow
                p.setPen(QPen(colour, 2.2)); y0, y1 = (44, 84) if is_in else (84, 44)
                p.drawLine(QPointF(px, y0), QPointF(px, y1))
                d = 1 if is_in else -1
                p.drawLine(QPointF(px, y1), QPointF(px - 5, y1 - 7 * d)); p.drawLine(QPointF(px, y1), QPointF(px + 5, y1 - 7 * d))
        text(p, 118, 24, 84, 14, "INTAKE", 7, DIM, align=Qt.AlignCenter); text(p, 198, 24, 84, 14, "EXHAUST", 7, DIM, align=Qt.AlignCenter)

        # ---- cylinder walls --------------------------------------------------
        p.setPen(QPen(LINE, 1)); p.setBrush(STEEL_DK)
        p.drawRect(QRectF(self.BL - 12, self.DECK, 12, self.BOT - self.DECK)); p.drawRect(QRectF(self.BR, self.DECK, 12, self.BOT - self.DECK))

        # ---- charge ------------------------------------------------------------
        chamber = self.chamber_path(crown)
        base_col = CHARGE_RICH if lam < 0.95 else (CHARGE_LEAN if lam > 1.05 else CHARGE)
        p.setPen(Qt.NoPen)
        if th < 180:
            c = QColor(base_col); c.setAlphaF(0.18 + 0.55 * dens * th / 180.0); p.setBrush(c); p.drawPath(chamber)
        elif th < th_spark:
            f = (th - 180.0) / max(th_spark - 180.0, 1.0)
            c = QColor(lerp(base_col, QColor("#1D4F9C"), f)); c.setAlphaF(0.35 + 0.55 * dens); p.setBrush(c); p.drawPath(chamber)
        elif th < th_spark + 45:
            c = QColor(QColor("#1D4F9C")); c.setAlphaF(0.9); p.setBrush(c); p.drawPath(chamber)
            f = (th - th_spark) / 45.0
            p.save(); p.setClipPath(chamber)
            g = QRadialGradient(self.PLUG, 30 + 200 * f); g.setColorAt(0, FLAME); g.setColorAt(0.7, BURN); g.setColorAt(1, QColor(BURN.red(), BURN.green(), BURN.blue(), 200))
            p.setBrush(QBrush(g)); p.drawEllipse(self.PLUG, 30 + 200 * f, 30 + 200 * f); p.restore()
        elif th < 540:
            f = (th - th_spark - 45.0) / max(540.0 - th_spark - 45.0, 1.0)
            c = QColor(lerp(BURN, EXH, f)); c.setAlphaF(0.85); p.setBrush(c); p.drawPath(chamber)
        else:
            c = QColor(EXH); c.setAlphaF(0.65 * (1.0 - (th - 540.0) / 180.0)); p.setBrush(c); p.drawPath(chamber)

        # ---- piston, rod, crank ------------------------------------------------
        pin = QPointF(self.CX, crown + 32)
        a = math.radians(th); crank_pin = QPointF(self.CX + self.R * math.sin(a), self.CY - self.R * math.cos(a))
        p.setPen(QPen(LINE, 1)); p.setBrush(STEEL); p.drawRect(QRectF(self.BL + 2, crown, self.BR - self.BL - 4, 58))
        for gy in (crown + 8, crown + 15): p.drawLine(QPointF(self.BL + 2, gy), QPointF(self.BR - 2, gy))
        p.setBrush(STEEL_DK); p.drawEllipse(QPointF(self.CX, self.CY), self.R + 6, self.R + 6)
        wedge = QPainterPath(); wedge.moveTo(self.CX, self.CY)
        wedge.arcTo(QRectF(self.CX - self.R - 6, self.CY - self.R - 6, 2 * (self.R + 6), 2 * (self.R + 6)),
                    -math.degrees(a) + 90 + 180 - 55, 110); wedge.closeSubpath()
        p.setBrush(QColor("#6E747B")); p.drawPath(wedge)
        p.setPen(QPen(STEEL_DK, 14)); p.drawLine(pin, crank_pin)
        p.setPen(QPen(LINE, 1)); p.setBrush(STEEL_LT); p.drawEllipse(pin, 8, 8); p.drawEllipse(crank_pin, 10, 10)
        p.setBrush(STEEL_DK); p.drawEllipse(QPointF(self.CX, self.CY), 12, 12)

        # ---- spark plug and flash ------------------------------------------------
        p.setPen(QPen(LINE, 1)); p.setBrush(QColor("#F0F0F0")); p.drawRect(QRectF(193, 60, 14, 12))
        p.setBrush(STEEL_DK); p.drawRect(QRectF(196, 72, 8, 18)); p.drawLine(QPointF(200, 90), self.PLUG)
        d_flash = (th - th_spark) % 720
        if d_flash < 12 or d_flash > 708:
            p.setPen(QPen(FLAME, 2.2))
            for k in range(8):
                ang = k * math.pi / 4
                p.drawLine(self.PLUG, QPointF(self.PLUG.x() + 14 * math.cos(ang), self.PLUG.y() + 14 * math.sin(ang)))
        text(p, 90, 6, 220, 16, stroke, 10, INK, True, Qt.AlignCenter)
        text(p, 90, 520, 220, 14, f"crank {th:5.0f}°   {'TDC' if abs((th % 360)) < 8 or abs((th % 360) - 360) < 8 else ''}", 8, DIM, align=Qt.AlignCenter, mono=True)

        # ---- crank-angle dial: BTDC to the left of TDC, ATDC to the right ------------
        cx, cy, r = 440.0, 470.0, 52.0
        p.setPen(QPen(LINE, 1.2)); p.setBrush(QColor("#FFFFFF")); p.drawEllipse(QPointF(cx, cy), r, r)

        def pt(deg_atdc, rad):
            aa = math.radians(deg_atdc); return QPointF(cx + rad * math.sin(aa), cy - rad * math.cos(aa))
        for k in range(-60, 61, 10):
            p.setPen(QPen(LINE, 1.4 if k % 20 == 0 else 0.8)); p.drawLine(pt(k, r - (8 if k % 20 == 0 else 4)), pt(k, r))
            if k % 20 == 0: text(p, pt(k, r - 18).x() - 12, pt(k, r - 18).y() - 7, 24, 14, f"{abs(k)}", 6, DIM, align=Qt.AlignCenter)
        text(p, cx - 60, cy + r + 2, 48, 12, "BTDC", 6, DIM, align=Qt.AlignCenter); text(p, cx + 12, cy + r + 2, 48, 12, "ATDC", 6, DIM, align=Qt.AlignCenter)
        text(p, cx - 20, cy - r - 14, 40, 12, "TDC", 7, INK, True, Qt.AlignCenter)
        arc = QRectF(cx - r + 9, cy - r + 9, 2 * (r - 9), 2 * (r - 9))
        p.setPen(QPen(LED_ON, 5, Qt.SolidLine, Qt.FlatCap)); p.setBrush(Qt.NoBrush)
        p.drawArc(arc, int(90 * 16), int(mbt * 16))                                # TDC back to MBT
        if spark < mbt - 0.5:
            p.setPen(QPen(BURN, 5, Qt.SolidLine, Qt.FlatCap)); p.drawArc(arc, int((90 + spark) * 16), int((mbt - spark) * 16))
        p.setPen(QPen(INK, 2)); p.drawLine(pt(-spark, r - 16), pt(-spark, r - 2))        # spark marker
        needle = pt((th - 360.0 + 180) % 360 - 180, r - 6)
        p.setPen(QPen(QColor("#C0392B"), 2)); p.drawLine(QPointF(cx, cy), needle)
        p.setPen(QPen(LINE, 1)); p.setBrush(QColor("#404040")); p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
        text(p, cx - 60, cy + r + 14, 120, 12, f"MBT {mbt:.1f}°   spark {spark:.1f}°", 7, DIM, align=Qt.AlignCenter, mono=True)

        # ---- pressure vs crank angle -------------------------------------------------
        px0, py0, pw, ph = 24.0, 540.0, 300.0, 52.0
        p.setPen(QPen(TAG_BD, 1)); p.setBrush(QColor("#FFFFFF")); p.drawRect(QRectF(px0, py0, pw, ph))
        cr = 11.0
        ths = np.arange(180.0, 541.0, 4.0)
        vol = 1.0 + (cr - 1.0) / 2.0 * (1.0 - np.cos(np.radians(ths - 360.0)))
        pm = (cr / vol) ** 1.3
        xb = np.where(ths >= th_spark, 1.0 - np.exp(-5.0 * np.clip((ths - th_spark) / 45.0, 0, None) ** 3), 0.0)
        pr = pm * (1.0 + 2.8 * xb)
        pk = pr.max(); xs = px0 + (ths - 180.0) / 360.0 * pw; ys = py0 + ph - 3 - (pr / pk) * (ph - 8)
        p.setPen(QPen(FILL, 1.4)); p.drawPolyline(QPolygonF([QPointF(x, y) for x, y in zip(xs, ys)]))
        x_tdc = px0 + pw / 2; x_sp = px0 + (th_spark - 180.0) / 360.0 * pw
        p.setPen(QPen(DIM, 0.8, Qt.DashLine)); p.drawLine(QPointF(x_tdc, py0), QPointF(x_tdc, py0 + ph))
        p.setPen(QPen(FLAME, 1.2)); p.drawLine(QPointF(x_sp, py0), QPointF(x_sp, py0 + ph))
        i_pk = int(np.argmax(pr)); p.setPen(QPen(BURN, 1)); p.setBrush(BURN); p.drawEllipse(QPointF(xs[i_pk], ys[i_pk]), 2.5, 2.5)
        if 180 <= th <= 540:
            xt = px0 + (th - 180.0) / 360.0 * pw; p.setPen(QPen(QColor("#C0392B"), 1.5)); p.drawLine(QPointF(xt, py0 + ph - 8), QPointF(xt, py0 + ph))
        text(p, px0 + 3, py0 + 1, 120, 12, "cylinder pressure", 6, DIM)
        text(p, xs[i_pk] + 4, ys[i_pk] - 6, 60, 12, f"peak {ths[i_pk] - 360:+.0f}°", 6, BURN)
        text(p, x_sp - 30, py0 + ph - 12, 28, 12, "spark", 6, DIM, align=Qt.AlignRight | Qt.AlignVCenter)

        # ---- value tags --------------------------------------------------------------
        x, y, w = 380.0, 40.0, 134.0
        rows = [("RPM", f"{ch.get('rpm', 0):.0f}", ""), ("BOOST", f"{ch.get('boost', 0):.1f}", "psi"),
                ("MAP", f"{map_kpa:.0f}", "kPa"), ("AIR", f"{ch.get('air', 0):.3f}", "g"),
                ("VE", f"{ch.get('ve', 0):.3f}", ""), ("λ", f"{lam:.3f}", "rich" if lam < 0.97 else ("lean" if lam > 1.03 else "")),
                ("SPARK", f"{spark:.1f}", "°"), ("MBT", f"{mbt:.1f}", "°"), ("KNOCK", f"{knock:.1f}", "°"),
                ("TORQUE", f"{ch.get('torque', 0):.0f}", "Nm"), ("REQ", f"{ch.get('torque_req', 0):.0f}", "Nm"),
                ("AUTH", f"{ch.get('authority', 0):.0f}", "Nm")]
        for name, val, unit in rows:
            tag(p, x, y, w, name, val, unit); y += 23
        cut = spark < (min(mbt, knock) - 1.5)
        tag(p, x, y + 4, w, "CUT", "ACTIVE" if cut else "—", "", state=cut)


# ===========================================================================
class TransmissionMimic(QWidget):
    """ZF 8HP schematic: converter, four gearsets, five shift elements."""
    W, H = 1000, 540
    BRAKES = {"A": 240.0, "B": 372.0}          # hang from the case top
    CLUTCHES = {"C": 517.0, "D": 662.0, "E": 807.0}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ch = {}
        self.setMinimumSize(420, 200)

    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), BG)
        fit(p, self.width(), self.height(), self.W, self.H)
        ch = self.ch
        gear = int(ch.get("gear", 1)) or 1
        line = max(ch.get("line_bar", 4.0), 1.0)
        phase = int(ch.get("shift_phase", 0)); shifting = phase > 0
        g_from, g_to = int(ch.get("shift_from", 0)), int(ch.get("shift_to", 0))

        # ---- header ------------------------------------------------------------
        p.setPen(QPen(LINE, 1.2)); p.setBrush(QColor("#FFFFFF")); p.drawRect(QRectF(30, 14, 84, 58))
        text(p, 30, 14, 84, 40, f"D{gear}", 22, INK, True, Qt.AlignCenter)
        text(p, 30, 50, 84, 18, f"ratio {ch.get('ratio', 0):.3f}", 7, DIM, align=Qt.AlignCenter, mono=True)
        hx = 130.0
        for name, val, unit, st in (("INPUT", f"{ch.get('rpm', 0):.0f}", "rpm", None), ("TURBINE", f"{ch.get('turbine_rpm', 0):.0f}", "rpm", None),
                                    ("OUTPUT", f"{ch.get('output_rpm', 0):.0f}", "rpm", None), ("SPEED", f"{ch.get('speed', 0):.0f}", "km/h", None),
                                    ("TC", "LOCKED" if ch.get("tc_lock", 0) else "SLIP", "", bool(ch.get("tc_lock", 0)))):
            tag(p, hx, 14, 160, name, val, unit, st); hx += 168
        hx = 130.0
        phase_name = ("idle", "fill", "torque", "inertia")[min(phase, 3)]
        for name, val, unit, st in (("LINE", f"{line:.1f}", "bar", None), ("TQ IN", f"{ch.get('torque', 0):.0f}", "Nm", None),
                                    ("TQ REQ", f"{ch.get('torque_req', 0):.0f}", "Nm", None),
                                    ("SHIFT", f"{g_from}→{g_to} {phase_name}" if shifting else "idle", "", shifting),
                                    ("CUT", ("idle", "cutting", "holding", "restoring")[min(int(ch.get("coord_phase", 0)), 3)], "", int(ch.get("coord_phase", 0)) > 0)):
            tag(p, hx, 40, 160, name, val, unit, st); hx += 168

        # ---- bell housing, converter --------------------------------------------
        p.save(); p.translate(0, 40)                      # everything mechanical sits below the tag rows
        bell = QPainterPath(); bell.moveTo(180, 95); bell.lineTo(180, 325); bell.lineTo(70, 325)
        bell.arcTo(QRectF(30, 95, 80, 230), 270, -180); bell.lineTo(180, 95); bell.closeSubpath()
        p.setPen(QPen(LINE, 1.2)); p.setBrush(STEEL_LT); p.drawPath(bell)
        tc = QPointF(108, 210)
        p.setBrush(STEEL_DK); p.drawEllipse(tc, 60, 60)
        pump = QPainterPath(); pump.moveTo(tc.x() - 3, tc.y() - 52); pump.arcTo(QRectF(tc.x() - 55, tc.y() - 52, 104, 104), 90, 180); pump.closeSubpath()
        turb = QPainterPath(); turb.moveTo(tc.x() + 3, tc.y() - 52); turb.arcTo(QRectF(tc.x() - 49, tc.y() - 52, 104, 104), 90, -180); turb.closeSubpath()
        p.setBrush(STEEL); p.drawPath(pump); p.setBrush(QColor("#D8DBDF")); p.drawPath(turb)
        locked = bool(ch.get("tc_lock", 0))
        p.setBrush(FILL if locked else STEEL_LT); p.drawRect(QRectF(tc.x() - 22, tc.y() - 64, 44, 8))       # lock-up clutch
        text(p, tc.x() - 40, tc.y() + 66, 80, 14, "CONVERTER", 7, DIM, align=Qt.AlignCenter)
        text(p, tc.x() - 40, tc.y() - 82, 80, 14, "LOCK-UP", 7, FILL if locked else DIM, locked, Qt.AlignCenter)
        text(p, tc.x() - 40, tc.y() - 8, 36, 16, "P", 8, INK, True, Qt.AlignCenter); text(p, tc.x() + 4, tc.y() - 8, 36, 16, "T", 8, INK, True, Qt.AlignCenter)

        # ---- case and shaft ---------------------------------------------------------
        p.setPen(QPen(LINE, 1.2)); p.setBrush(STEEL_LT)
        p.drawRoundedRect(QRectF(180, 120, 720, 180), 10, 10); p.drawRect(QRectF(300, 299, 400, 16))     # case + pan
        p.setPen(QPen(STEEL_DK, 8)); p.drawLine(QPointF(180, 210), QPointF(895, 210))
        p.setPen(QPen(QColor("#6E747B"), 1)); p.drawLine(QPointF(180, 206), QPointF(895, 206))

        # ---- gearsets -----------------------------------------------------------------
        for n, gx in enumerate((300.0, 445.0, 590.0, 735.0), 1):
            p.setPen(QPen(LINE, 1)); p.setBrush(STEEL); p.drawRoundedRect(QRectF(gx - 24, 150, 48, 120), 6, 6)
            p.setBrush(STEEL_DK); p.drawEllipse(QPointF(gx, 210), 11, 11)
            p.setBrush(QColor("#A9AEB5")); p.drawEllipse(QPointF(gx, 178), 8, 8); p.drawEllipse(QPointF(gx, 242), 8, 8)
            text(p, gx - 20, 274, 40, 14, f"P{n}", 7, DIM, align=Qt.AlignCenter)

        # ---- shift elements ------------------------------------------------------------
        engaged = set(ENGAGED.get(gear, "")) | (set(ENGAGED.get(g_to, "")) if shifting else set())
        for el in ELEMENTS:
            pres = ch.get(f"p_{el.lower()}", 0.0)
            frac = min(max(pres / P_MAX, 0.0), 1.0)
            applied = pres > 0.5 * line
            brake = el in self.BRAKES
            x = self.BRAKES[el] if brake else self.CLUTCHES[el]
            y0, y1 = (126.0, 176.0) if brake else (168.0, 252.0)
            gap = 1.0 + 3.0 * (1.0 - min(pres / max(line, 1.0), 1.0))
            n_pl, pw_ = 7, 4.0
            total = n_pl * pw_ + (n_pl - 1) * gap
            px = x - total / 2
            for k in range(n_pl):
                p.setPen(QPen(LINE, 0.6)); p.setBrush(FRICTION if k % 2 else STEEL)
                p.drawRect(QRectF(px + k * (pw_ + gap), y0, pw_, y1 - y0))
            if brake:                                                        # tie to the housing
                p.setPen(QPen(LINE, 1)); p.drawLine(QPointF(x - 18, 120), QPointF(x + 18, 120))
            # the hollow arrow, filling with apply pressure
            tip_x, yc = px - 5, (y0 + y1) / 2
            L_, sh, hw, hh = 62.0, 9.0, 18.0, 17.0
            tail_x = tip_x - L_
            arrow = QPolygonF([QPointF(tail_x, yc - sh), QPointF(tip_x - hw, yc - sh), QPointF(tip_x - hw, yc - hh),
                               QPointF(tip_x, yc), QPointF(tip_x - hw, yc + hh), QPointF(tip_x - hw, yc + sh), QPointF(tail_x, yc + sh)])
            path = QPainterPath(); path.addPolygon(arrow); path.closeSubpath()
            p.setPen(QPen(INK, 1.2)); p.setBrush(QColor("#FFFFFF")); p.drawPath(path)
            if frac > 0.01:
                clip = QPainterPath(); clip.addRect(QRectF(tail_x, yc - hh - 1, L_ * frac, 2 * hh + 2))
                p.setPen(Qt.NoPen); p.setBrush(FILL); p.drawPath(path.intersected(clip))
                p.setPen(QPen(INK, 1.2)); p.setBrush(Qt.NoBrush); p.drawPath(path)
            ty = 74.0 if brake else 324.0
            tag(p, x - 66, ty, 132, el, f"{pres:.1f}", "bar", applied)
            tag(p, x - 66, ty + 21, 132, "BRAKE" if brake else "CLUTCH", f"{pres * NM_PER_BAR:.0f}", "Nm")
            if el in engaged and shifting and el in (set(ENGAGED.get(g_to, "")) ^ set(ENGAGED.get(g_from, ""))):
                p.setPen(QPen(LED_WARN, 1.5, Qt.DashLine)); p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(px - 4, y0 - 4, total + 8, y1 - y0 + 8))

        # ---- output --------------------------------------------------------------------
        p.setPen(QPen(LINE, 1.2)); p.setBrush(STEEL_DK); p.drawRect(QRectF(895, 180, 36, 60))
        p.setBrush(STEEL); p.drawEllipse(QPointF(913, 210), 10, 10)
        p.setPen(QPen(STEEL_DK, 8)); p.drawLine(QPointF(931, 210), QPointF(975, 210))
        text(p, 890, 246, 90, 14, "OUTPUT", 7, DIM, align=Qt.AlignCenter)
        p.restore()

        # ---- element matrix ---------------------------------------------------------------
        mx, my = 640.0, 428.0
        text(p, mx, my - 14, 200, 14, "SHIFT ELEMENTS PER GEAR", 7, DIM, True)
        cw, rh = 40.0, 15.0
        for gi in range(1, 9):
            cx_ = mx + 30 + (gi - 1) * cw
            if gi == gear or (shifting and gi == g_to):
                p.setPen(Qt.NoPen); p.setBrush(QColor("#DCE9F7") if gi == gear else QColor("#FCEBD2"))
                p.drawRect(QRectF(cx_ - cw / 2, my, cw, rh * 6))
            text(p, cx_ - cw / 2, my, cw, rh, str(gi), 7, INK, gi == gear, Qt.AlignCenter)
        for ri, el in enumerate(ELEMENTS):
            yy = my + rh * (ri + 1)
            text(p, mx, yy, 28, rh, el, 7, INK, True, Qt.AlignCenter)
            for gi in range(1, 9):
                if el in ENGAGED[gi]:
                    cx_ = mx + 30 + (gi - 1) * cw
                    p.setPen(QPen(INK, 0.8)); p.setBrush(INK if el in ENGAGED[gear] else QColor("#7A7A7A"))
                    p.drawEllipse(QPointF(cx_, yy + rh / 2), 3.2, 3.2)
        text(p, 30, 430, 600, 14, "ZF 8HP  ·  4 planetary gearsets  ·  5 shift elements, 3 applied in every gear", 7, DIM)
        text(p, 30, 446, 600, 14, "A, B brakes to the housing  ·  C, D, E clutches on the shaft", 7, DIM)
        text(p, 30, 462, 600, 14, "arrows fill with apply pressure; the Nm tag is torque capacity at that pressure  ·  dashed outline = exchanging", 7, DIM)
        text(p, 30, 486, 600, 14, "shift schedule and element pressures are the simulator's model, published as channels", 6.5, DIM)


# ===========================================================================
class MimicPage(QWidget):
    maximize_toggled = Signal(bool)      # hide the other docks so the graphics get the room

    def __init__(self, parent=None):
        super().__init__(parent)
        self.engine = EngineCutaway(); self.trans = TransmissionMimic()
        head = QWidget(); head.setStyleSheet(f"background: {BG.name()}; border-bottom: 1px solid #C8C8C8;")
        hl = QHBoxLayout(head); hl.setContentsMargins(8, 3, 8, 3)
        t = QLabel("POWERTRAIN — LIVE"); f = t.font(); f.setBold(True); f.setPointSize(9); t.setFont(f)
        sub = QLabel("mimic diagram · values from the connected ECU · engine cycle shown in slow motion"); sub.setObjectName("dim")
        self.b_max = QPushButton("Maximize"); self.b_max.setCheckable(True); self.b_max.setFixedWidth(80)
        self.b_max.setToolTip("Hide the gauge and datalog docks while this view is open")
        self.b_max.toggled.connect(self._max)
        hl.addWidget(t); hl.addStretch(); hl.addWidget(sub); hl.addSpacing(10); hl.addWidget(self.b_max)
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        body.addWidget(self.engine, 5); body.addWidget(self.trans, 9)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addWidget(head); lay.addLayout(body, 1)
        self.setStyleSheet(f"background: {BG.name()};")
        # the cutaway animates on its own clock; the transmission only changes
        # when new channels arrive, so it repaints on update_channels instead
        self._timer = QTimer(self); self._timer.setInterval(40); self._timer.timeout.connect(self._frame); self._timer.start()

    def _max(self, on):
        self.b_max.setText("Restore" if on else "Maximize"); self.maximize_toggled.emit(on)

    def _frame(self):
        self.engine.advance(0.040); self.engine.update()

    def update_channels(self, ch: dict):
        self.engine.ch = ch; self.trans.ch = ch; self.trans.update()
