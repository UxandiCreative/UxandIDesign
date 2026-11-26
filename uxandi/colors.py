"""Colour picking: a hue / saturation wheel with brightness and opacity, a hex box,
the last 12 colours picked, and an eyedropper that takes a colour from anywhere on screen."""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QObject, Signal, QPointF, QRectF, QRect, QSize, QPoint
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QGuiApplication, QCursor, QFont
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLineEdit, QPushButton, QCheckBox,
                               QLabel, QFrame, QSizePolicy)

from . import theme
from .widgets import WrapCheck, slider_row

MAX_RECENT = 12


def hex_of(c: QColor) -> str:
    return c.name(QColor.NameFormat.HexArgb) if c.alpha() < 255 else c.name(QColor.NameFormat.HexRgb)


# ----------------------------------------------------------------------------- recent colours (kept between runs)
class Recents(QObject):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.lists: dict[str, list[str]] = {}

    def get(self, key: str) -> list[str]:
        return self.lists.setdefault(key, [])

    def add(self, key: str, color: str):
        lst = self.get(key)
        c = color.upper()
        if c in lst:
            lst.remove(c)
        lst.insert(0, c)
        del lst[MAX_RECENT:]
        self.changed.emit(key)

    def load(self, d):
        if isinstance(d, dict):
            self.lists = {k: [str(c) for c in v][:MAX_RECENT] for k, v in d.items() if isinstance(v, list)}


RECENTS = Recents()


# ----------------------------------------------------------------------------- the wheel
class HueSatWheel(QWidget):
    """Hue around the circle, saturation from the middle (white) to the rim."""
    changed = Signal(bool)          # final?

    def __init__(self):
        super().__init__()
        self.h, self.s, self.v = 0.0, 0.0, 1.0
        self._img = None
        self._img_d = 0
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.apply_scale()

    def apply_scale(self):
        d = theme.px(132)
        self.setFixedSize(d, d)

    def _wheel(self, d: int) -> QImage:
        dpr = self.devicePixelRatioF() or 1.0
        n = max(8, int(d * dpr))
        if self._img is not None and self._img_d == n:
            return self._img
        img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        rad = n / 2
        c = QColor()
        for y in range(n):
            dy = rad - (y + 0.5)
            for x in range(n):
                dx = (x + 0.5) - rad
                r = math.hypot(dx, dy) / rad
                if r > 1.0:
                    continue
                hue = (math.degrees(math.atan2(dy, dx)) % 360) / 360
                c.setHsvF(hue, min(1.0, r), 1.0)
                img.setPixelColor(x, y, c)
        img.setDevicePixelRatio(dpr)
        self._img, self._img_d = img, n
        return img

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = min(self.width(), self.height())
        r = QRectF(0.5, 0.5, d - 1, d - 1)
        p.drawImage(r, self._wheel(d))
        if self.v < 1.0:                         # darker = the whole wheel dims
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(255 * (1 - self.v))))
            p.drawEllipse(r)
        p.setPen(QPen(QColor(0, 0, 0, 60), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r)
        R = d / 2
        a = math.radians(self.h * 360)
        mx, my = R + math.cos(a) * self.s * (R - 1), R - math.sin(a) * self.s * (R - 1)
        k = theme.px(6)
        p.setPen(QPen(QColor("#FFFFFF"), 2.5)); p.drawEllipse(QPointF(mx, my), k, k)
        p.setPen(QPen(QColor("#111418"), 1)); p.drawEllipse(QPointF(mx, my), k + 1.5, k + 1.5)
        p.end()

    def _set_from(self, pos, final):
        d = min(self.width(), self.height())
        R = d / 2
        dx, dy = pos.x() - R, R - pos.y()
        self.s = min(1.0, math.hypot(dx, dy) / R)
        self.h = (math.degrees(math.atan2(dy, dx)) % 360) / 360
        self.update()
        self.changed.emit(final)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._set_from(e.position(), False)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._set_from(e.position(), False)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._set_from(e.position(), True)


# ----------------------------------------------------------------------------- eyedropper
class ScreenPicker(QWidget):
    """Covers every screen with a still picture of it; click anywhere to take that colour. Esc cancels."""

    def __init__(self, on_pick):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.on_pick = on_pick
        self.shots = []
        virt = QRect()
        for scr in QGuiApplication.screens():
            g = scr.geometry()
            pm = scr.grabWindow(0)
            self.shots.append((g, pm, pm.toImage()))
            virt = virt.united(g)
        self.virt = virt
        self.setGeometry(virt)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.pos_ = None

    def color_at(self, gpos: QPoint) -> QColor | None:
        for g, pm, img in self.shots:
            if g.contains(gpos) and not img.isNull():
                sx, sy = img.width() / max(1, g.width()), img.height() / max(1, g.height())
                x = min(img.width() - 1, max(0, int((gpos.x() - g.x()) * sx)))
                y = min(img.height() - 1, max(0, int((gpos.y() - g.y()) * sy)))
                return img.pixelColor(x, y)
        return None

    def start(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.grabKeyboard()

    def paintEvent(self, _):
        p = QPainter(self)
        for g, pm, _img in self.shots:
            p.drawPixmap(QRect(g.topLeft() - self.virt.topLeft(), g.size()), pm)
        if self.pos_ is not None:
            gp = self.pos_ + self.virt.topLeft()
            c = self.color_at(gp)
            # magnifier: 11 x 11 screen pixels, 9 times bigger
            n, z = 11, 9
            box = QRectF(self.pos_.x() + 18, self.pos_.y() + 18, n * z, n * z)
            if box.right() > self.width():
                box.moveRight(self.pos_.x() - 18)
            if box.bottom() + 26 > self.height():
                box.moveBottom(self.pos_.y() - 44)
            for j in range(n):
                for i in range(n):
                    cc = self.color_at(gp + QPoint(i - n // 2, j - n // 2))
                    if cc is not None:
                        p.fillRect(QRectF(box.x() + i * z, box.y() + j * z, z, z), cc)
            p.setPen(QPen(QColor("#FFFFFF"), 2)); p.drawRect(box)
            p.setPen(QPen(QColor("#111418"), 1))
            p.drawRect(QRectF(box.x() + (n // 2) * z, box.y() + (n // 2) * z, z, z))
            if c is not None:
                lab = QRectF(box.x(), box.bottom() + 4, box.width(), 22)
                p.fillRect(lab, QColor("#111418"))
                p.fillRect(QRectF(lab.x() + 4, lab.y() + 4, 14, 14), c)
                f = QFont(self.font()); f.setPixelSize(12); p.setFont(f)
                p.setPen(QColor("#FFFFFF"))
                p.drawText(lab.adjusted(22, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, c.name().upper())
        p.end()

    def mouseMoveEvent(self, e):
        self.pos_ = e.position().toPoint()
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            c = self.color_at(e.globalPosition().toPoint())
            self.releaseKeyboard()
            self.close()
            if c is not None:
                self.on_pick(c.name())
        else:
            self.releaseKeyboard()
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.releaseKeyboard()
            self.close()


def eyedropper(on_pick):
    sp = ScreenPicker(on_pick)
    sp.start()
    return sp


# ----------------------------------------------------------------------------- the whole picker
class ColorPicker(QWidget):
    """Wheel + brightness + opacity + hex + eyedropper + the last 12 colours.
    `changed(hex, final)`: final is True when a pick is finished (mouse released, Enter, swatch, eyedropper)."""
    changed = Signal(str, bool)
    none_toggled = Signal(bool)

    def __init__(self, key: str, none_text: str | None = None):
        super().__init__()
        self.key = key
        self._busy = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.v = v
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.wheel = HueSatWheel()
        self.wheel.changed.connect(self._from_wheel)
        top.addWidget(self.wheel, 0, Qt.AlignmentFlag.AlignTop)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(theme.px(4))
        self.preview = QLabel()
        self.preview.setFixedHeight(theme.px(26))
        self.hex = QLineEdit()
        self.hex.setPlaceholderText("#RRGGBB")
        self.hex.editingFinished.connect(self._from_hex)
        self.drop = QPushButton("⌖")
        self.drop.setObjectName("Ic")
        self.drop.setToolTip("Eyedropper: click anywhere on the screen to take that colour (Esc cancels)")
        self.drop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.drop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop.clicked.connect(self._eyedrop)
        r1 = QHBoxLayout(); r1.setContentsMargins(0, 0, 0, 0); r1.setSpacing(theme.px(4))
        r1.addWidget(self.preview, 1); r1.addWidget(self.drop)
        right.addLayout(r1)
        right.addWidget(self.hex)
        self.val = self._slider("brightness")
        self.alpha = self._slider("opacity")
        for lab, sl in ((QLabel("brightness"), self.val), (QLabel("opacity"), self.alpha)):
            lab.setObjectName("FieldLabel")
            right.addWidget(lab)
            right.addWidget(slider_row(sl, 10, lab.text() + " 1%"))
        self.none = None
        if none_text:
            self.none = WrapCheck(none_text)
            self.none.toggled.connect(self.none_toggled.emit)
            right.addWidget(self.none)
        right.addStretch(1)
        top.addLayout(right, 1)
        v.addLayout(top)
        lab = QLabel("recent"); lab.setObjectName("FieldLabel")
        v.addWidget(lab)
        self.rec = QWidget()
        from .panels import FlowLayout          # the squares wrap onto a second row in a narrow column
        self.rec_l = FlowLayout(self.rec, theme.px(3))
        sp = self.rec.sizePolicy(); sp.setHeightForWidth(True); self.rec.setSizePolicy(sp)
        v.addWidget(self.rec)
        RECENTS.changed.connect(lambda k: k == self.key and self._recents())
        self._color = QColor("#000000")
        self._recents()
        self.set_color("#000000")
        self._sp = None

    def _slider(self, tip):
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(0, 1000)
        s.setToolTip(tip)
        s.valueChanged.connect(lambda _v: self._from_sliders(not s.isSliderDown()))
        s.sliderReleased.connect(lambda: self._from_sliders(True))
        return s

    def _recents(self):
        while self.rec_l.count():
            it = self.rec_l.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        d = theme.px(18)
        cols = RECENTS.get(self.key)
        for c in cols:
            b = QPushButton()
            b.setFixedSize(d, d)
            b.setToolTip(c)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(f"QPushButton{{background:{c};border:1px solid rgba(0,0,0,70);border-radius:3px;"
                            f"min-height:0;max-height:{d}px;padding:0;}}QPushButton:hover{{border:2px solid {theme.ACCENT};}}")
            b.clicked.connect(lambda _=False, c=c: self._pick(c))
            self.rec_l.addWidget(b)
        if not cols:
            e = QLabel("—"); e.setObjectName("Hint")
            self.rec_l.addWidget(e)
        self.rec_l.invalidate()

    # -- state
    def color(self) -> str:
        return hex_of(self._color)

    def set_color(self, c: str, emit: bool = False, final: bool = True):
        col = QColor(c) if c else QColor("#FFFFFF")
        if not col.isValid():
            return
        self._color = col
        self._busy = True
        h, s, v, a = col.getHsvF()
        if h >= 0:
            self.wheel.h = h
        self.wheel.s, self.wheel.v = s, v
        self.wheel.update()
        self.val.setValue(int(round(v * 1000)))
        self.alpha.setValue(int(round(col.alphaF() * 1000)))
        if not self.hex.hasFocus():
            self.hex.setText(hex_of(col).upper())
        self._busy = False
        self._paint_preview()
        if emit:
            self._emit(final)

    def set_none(self, on: bool):
        if self.none is not None:
            self.none.blockSignals(True)
            self.none.setChecked(on)
            self.none.blockSignals(False)

    def _paint_preview(self):
        c = hex_of(self._color)
        css = f"background:{c};border:1px solid rgba(0,0,0,70);border-radius:{theme.px(4)}px;"
        if css != self.preview.styleSheet():         # re-styling costs: only when it changes
            self.preview.setStyleSheet(css)

    def _emit(self, final):
        if final:
            RECENTS.add(self.key, self.color())
        self.changed.emit(self.color(), final)

    # -- inputs
    def _from_wheel(self, final):
        c = QColor.fromHsvF(self.wheel.h, self.wheel.s, max(0.0, min(1.0, self.val.value() / 1000)),
                            self.alpha.value() / 1000)
        self._color = c
        if not self.hex.hasFocus():
            self.hex.setText(hex_of(c).upper())
        self._paint_preview()
        self._emit(final)

    def _from_sliders(self, final):
        if self._busy:
            return
        self.wheel.v = self.val.value() / 1000
        self.wheel.update()
        self._from_wheel(final)

    def _from_hex(self):
        t = self.hex.text().strip()
        if t and not t.startswith("#"):
            t = "#" + t
        col = QColor(t)
        if col.isValid() and hex_of(col).upper() != self.color().upper():
            self.set_color(hex_of(col), emit=True)

    def _pick(self, c):
        self.set_color(c, emit=True)

    def _eyedrop(self):
        self._sp = eyedropper(lambda c: self.set_color(c, emit=True))

    def apply_scale(self):
        self.wheel.apply_scale()
        self.preview.setFixedHeight(theme.px(26))
        self._recents()


class ColorPopup(QFrame):
    """A small window under a colour square with the full picker in it."""

    def __init__(self, color: str, on_pick, key="general"):
        super().__init__(None, Qt.WindowType.Popup)
        self.setObjectName("Panel")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        m = theme.px(10)
        lay.setContentsMargins(m, m, m, m)
        self.picker = ColorPicker(key)
        self.picker.set_color(color)
        self.picker.changed.connect(lambda c, final: final and on_pick(c))
        lay.addWidget(self.picker)
        self.setFixedWidth(theme.px(320))
        self.setStyleSheet(f"QFrame#Panel{{background:{theme.SURFACE};border:1px solid rgba(0,0,0,66);border-radius:{theme.px(8)}px;}}")
