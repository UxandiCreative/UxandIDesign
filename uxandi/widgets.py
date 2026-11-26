"""Small widgets that never force a panel wider than its column."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPushButton, QSizePolicy, QStyle, QStyleOptionButton, QWidget

from . import theme


class WrapCheck(QCheckBox):
    """A checkbox whose label wraps onto more lines when the column is narrow,
    instead of pushing the panel wider (Qt's own checkbox never wraps)."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._t = text
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    # -- the text lives here, not in QCheckBox (so Qt does not size by it)
    def text(self) -> str:
        return self._t

    def setText(self, t: str) -> None:
        self._t = t
        self.updateGeometry()
        self.update()

    def _indicator(self) -> QRect:
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        return self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, opt, self)

    def _text_x(self) -> int:
        return self._indicator().width() + theme.px(8)

    def _line_h(self) -> int:
        return max(self.fontMetrics().height(), self._indicator().height())

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        tw = max(10, w - self._text_x())
        r = self.fontMetrics().boundingRect(QRect(0, 0, tw, 100000), int(Qt.TextFlag.TextWordWrap), self._t)
        return max(self._line_h(), r.height()) + 2

    def sizeHint(self) -> QSize:
        w = self._text_x() + self.fontMetrics().horizontalAdvance(self._t) + 2
        return QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self) -> QSize:
        return QSize(self._text_x() + theme.px(40), self._line_h())

    def hitButton(self, pos) -> bool:          # clicking the words ticks it too
        return self.rect().contains(pos)

    def paintEvent(self, _):
        p = QPainter(self)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.rect = QRect(0, 0, self._indicator().width() + 2, self._line_h())
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, opt, p, self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        x = self._text_x()
        top = max(0, (self._line_h() - self.fontMetrics().height()) // 2)
        p.drawText(QRect(x, top, self.width() - x, self.height() - top),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap), self._t)
        p.end()


# ------------------------------------------------------------------ step arrows
OFF = (17, 20, 24, 60)          # arrow colour at a limit or disabled (theme.LINE_2 is an rgba() string QColor cannot read)
def chevron(p: QPainter, r: QRect, direction: str, color) -> None:
    """A small chevron centred in r, pointing up / down / left / right."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QColor, QPen
    s = max(2.0, min(r.width(), r.height()) * 0.24)
    c = QPointF(r.center()) + QPointF(0.5, 0.5)
    d = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
    tip = c + QPointF(d[0] * s * 0.5, d[1] * s * 0.5)
    back = c - QPointF(d[0] * s * 0.5, d[1] * s * 0.5)
    side = QPointF(d[1] * s, d[0] * s)
    pen = QPen(QColor(*color) if isinstance(color, tuple) else QColor(color), max(1.3, theme.px(1.6)))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.drawPolyline([back + side, tip, back - side])


class _Arrows:
    """Mixin for spin boxes: draws the up / down arrows in the button areas the stylesheet makes."""

    def _arrows_init(self):
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() in (QEvent.Type.HoverMove, QEvent.Type.HoverLeave, QEvent.Type.HoverEnter):
            self.update()
        return super().event(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QStyleOptionSpinBox
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        mouse = self.mapFromGlobal(QCursor.pos()) if self.underMouse() else None
        p = QPainter(self)
        for sc, way, ok in ((QStyle.SubControl.SC_SpinBoxUp, "up", self.value() < self.maximum()),
                            (QStyle.SubControl.SC_SpinBoxDown, "down", self.value() > self.minimum())):
            r = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, sc, self)
            if r.width() < 4 or r.height() < 4:
                continue
            ok = ok and self.isEnabled() and not self.isReadOnly()
            col = OFF if not ok else theme.ACCENT if mouse is not None and r.contains(mouse) else theme.MUTE
            chevron(p, r, way, col)
        p.end()


def _spin_classes():
    from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox

    class Spin(_Arrows, QDoubleSpinBox):
        """Number box with small up / down arrows at its right end (click or hold to step)."""
        def __init__(self, parent=None):
            super().__init__(parent)
            self._arrows_init()

    class ISpin(_Arrows, QSpinBox):
        """Whole-number box with small up / down arrows at its right end."""
        def __init__(self, parent=None):
            super().__init__(parent)
            self._arrows_init()

    return Spin, ISpin


Spin, ISpin = _spin_classes()


class StepButton(QPushButton):
    """A small ‹ or › button beside a slider: click steps it, hold repeats."""

    def __init__(self, direction: str, tip: str = "", parent=None):
        super().__init__(parent)
        self.direction = direction
        self.setObjectName("Step")
        self.setToolTip(tip)
        self.setAutoRepeat(True)
        self.setAutoRepeatDelay(350)
        self.setAutoRepeatInterval(50)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.at_limit = False

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        ok = self.isEnabled() and not self.at_limit
        col = OFF if not ok else theme.ACCENT if self.underMouse() else theme.MUTE
        chevron(p, self.rect(), self.direction, col)
        p.end()


def slider_row(s, step: int, what: str = "") -> QWidget:
    """[‹] slider [›] on one line. The arrows move the slider by step (hold to repeat) and grey out at the ends.
    Enabling or disabling the slider does the same to its arrows."""
    from PySide6.QtCore import QEvent, QObject
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.px(4))
    dn = StepButton("left", f"{what} down".strip())
    up = StepButton("right", f"{what} up".strip())
    dn.clicked.connect(lambda: s.setValue(s.value() - step))
    up.clicked.connect(lambda: s.setValue(s.value() + step))
    h.addWidget(dn)
    h.addWidget(s, 1)
    h.addWidget(up)

    def limits(*_):
        dn.at_limit = s.value() <= s.minimum()
        up.at_limit = s.value() >= s.maximum()
        for b in (dn, up):
            b.setEnabled(s.isEnabled())
            b.update()

    class _Watch(QObject):
        def eventFilter(self, o, ev):
            if ev.type() == QEvent.Type.EnabledChange:
                limits()
            return False

    w = _Watch(box)
    s.installEventFilter(w)
    s.valueChanged.connect(limits)
    s.rangeChanged.connect(limits)
    limits()
    box.dn, box.up, box._watch = dn, up, w
    return box
