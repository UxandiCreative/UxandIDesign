"""Side columns: a row of tabs on top of each column; a tab
drops its panel down (click again to put it away, any number open at once);
every panel folds by clicking its title."""
from __future__ import annotations

import json
import math

from PySide6.QtCore import Qt, QRect, QSize, QPoint, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (QWidget, QLayout, QSizePolicy, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox,
                               QComboBox, QSlider, QColorDialog, QGridLayout, QListWidget, QListWidgetItem,
                               QAbstractItemView, QApplication, QPlainTextEdit)
from PySide6.QtCore import QTimer

from . import theme
from .widgets import WrapCheck, Spin, ISpin, slider_row
from .model import PRESETS, Shape, union_box, norm_deg


# ----------------------------------------------------------------------------- flow layout (wraps like CSS flex-wrap)
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=4):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def set_gap(self, g):
        self._sp = g
        self.invalidate()

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, r, test):
        # split into lines, then centre every item vertically on its line
        lines, cur, x = [], [], r.x()
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            hint = it.sizeHint()
            if cur and x + hint.width() > r.right() + 1:
                lines.append(cur)
                cur, x = [], r.x()
            cur.append((it, hint))
            x += hint.width() + self._sp
        if cur:
            lines.append(cur)
        y = r.y()
        for ln in lines:
            hmax = max(h.height() for _, h in ln)
            x = r.x()
            if not test:
                for it, h in ln:
                    it.setGeometry(QRect(QPoint(x, y + (hmax - h.height()) // 2), h))
                    x += h.width() + self._sp
            y += hmax + self._sp
        return max(0, y - self._sp - r.y()) if lines else 0


# ----------------------------------------------------------------------------- small builders
def label(text, obj="FieldLabel"):
    l = QLabel(text)
    l.setObjectName(obj)
    l.setWordWrap(True)      # long text wraps; it never pushes the panel wider than its column
    return l


def hint(text):
    l = QLabel(text)
    l.setObjectName("Hint")
    l.setWordWrap(True)
    return l


def button(text, tip="", obj=None, checkable=False):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if tip:
        b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def spin(lo, hi, dec=0, step=1.0, suffix=""):
    """Number box: type a value, or click / hold its arrows (or wheel, arrow keys) to step it."""
    s = Spin()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setKeyboardTracking(False)
    s.setAccelerated(True)
    if suffix:
        s.setSuffix(suffix)
    s.setMinimumWidth(10)
    s.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return s


def field(text, w):
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    v.addWidget(label(text))
    v.addWidget(w)
    return box


def hrow(*ws, stretch_last=False):
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.px(8))
    for w in ws:
        if w == "stretch":
            h.addStretch(1)
        else:
            h.addWidget(w, 1 if not isinstance(w, QPushButton) or w.objectName() not in ("Ic", "Swatch") else 0)
    return box


def brow(*ws):
    """A row of buttons that wraps onto the next line when the column is narrow."""
    box = QWidget()
    fl = FlowLayout(box, theme.px(6))
    for w in ws:
        fl.addWidget(w)
    sp = box.sizePolicy()
    sp.setHeightForWidth(True)
    box.setSizePolicy(sp)
    return box


class Swatch(QPushButton):
    """A colour button. Click to choose a colour."""
    picked = Signal(str)

    def __init__(self, tip="", alpha=True):
        super().__init__()
        self.setObjectName("Swatch")
        self.setToolTip(tip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._c = "#000000"
        self._alpha = alpha
        self.clicked.connect(self._pick)

    def set_color(self, c: str):
        self._c = c or "#000000"
        col = QColor(self._c)
        self.setStyleSheet(f"QPushButton#Swatch{{background:{col.name(QColor.NameFormat.HexArgb if col.alpha() < 255 else QColor.NameFormat.HexRgb)};"
                           f"border:1px solid rgba(0,0,0,66);}}")

    def color(self):
        return self._c

    def _pick(self):
        """Open the colour wheel (with recent colours and the eyedropper) under this square."""
        from .colors import ColorPopup

        def done(name):
            self.set_color(name)
            self.picked.emit(name)

        pop = ColorPopup(self._c, done)
        pos = self.mapToGlobal(self.rect().bottomLeft())
        scr = self.screen().availableGeometry() if self.screen() else None
        pop.adjustSize()
        if scr is not None:
            if pos.x() + pop.width() > scr.right():
                pos.setX(scr.right() - pop.width())
            if pos.y() + pop.height() > scr.bottom():
                pos.setY(self.mapToGlobal(self.rect().topLeft()).y() - pop.height())
        pop.move(pos)
        pop.show()
        self._pop = pop


# ----------------------------------------------------------------------------- panel + column
class Panel(QFrame):
    def __init__(self, key, title, extra=None):
        super().__init__()
        self.key = key
        self.setObjectName("Panel")
        self.shut = False
        self._title_text = title
        self.v = QVBoxLayout(self)
        sp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        self.title.setObjectName("PanelTitle")
        self.title.setWordWrap(True)
        self.title.setCursor(Qt.CursorShape.PointingHandCursor)
        self.title.mousePressEvent = lambda e: self.set_shut(not self.shut, user=True)
        top.addWidget(self.title, 1)
        if extra:
            for w in extra:
                top.addWidget(w)
        self.v.addLayout(top)
        self.body = QWidget()
        self.b = QVBoxLayout(self.body)
        self.b.setContentsMargins(0, 0, 0, 0)
        self.v.addWidget(self.body)
        self.v.addStretch(1)            # spare height goes below the body (top alignment would size the body by its
                                        # plain size hint and squash wrapped text and number boxes)
        self.on_fold = None
        self.apply_scale()
        self._title()

    def _title(self):
        self.title.setText(("▸  " if self.shut else "▾  ") + self._title_text.upper())

    def set_shut(self, s, user=False):
        self.shut = s
        self.body.setVisible(not s)
        self._title()
        if user and self.on_fold:
            self.on_fold()

    def apply_scale(self):
        m = theme.px(12)
        self.v.setContentsMargins(m, m, m, m)
        self.v.setSpacing(theme.px(8))
        self.b.setSpacing(theme.px(8))
        f = QFont(self.title.font())
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 106)
        self.title.setFont(f)
        for lay in self.body.findChildren(QHBoxLayout):
            lay.setSpacing(theme.px(8))


class Column(QWidget):
    """Tabs on top, panels below in a scroll area."""
    state_changed = Signal()

    def __init__(self, tabs: list[tuple[str, str]]):
        super().__init__()
        self.tabdef = tabs
        self.open = [tabs[0][0]]
        self.panels: dict[str, Panel] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.v = v
        self.tabbar = QWidget()
        self.flow = FlowLayout(self.tabbar, theme.px(4))
        self.tabbtn = {}
        for k, t in tabs:
            b = button(t, "Click: show this panel. Click again: put it away. Any number can be open.", "Tab", True)
            b.clicked.connect(lambda _=False, k=k: self.toggle(k))
            self.flow.addWidget(b)
            self.tabbtn[k] = b
        v.addWidget(self.tabbar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        self.inner = QVBoxLayout(inner)
        self.inner.setContentsMargins(0, 0, 0, 0)
        self.inner.addStretch(1)
        self.scroll.setWidget(inner)
        v.addWidget(self.scroll, 1)
        self.apply_scale()

    def add(self, panel: Panel):
        self.panels[panel.key] = panel
        order = [k for k, _ in self.tabdef]
        # keep the tab order
        idx = sum(1 for k in order[:order.index(panel.key)] if k in self.panels)
        self.inner.insertWidget(idx, panel)
        panel.on_fold = self.state_changed.emit
        self._sync()

    def toggle(self, k):
        if k in self.open:
            self.open.remove(k)
        else:
            self.open.append(k)
            p = self.panels.get(k)
            if p and p.shut:
                p.set_shut(False)
        self._sync()
        if k in self.open and k in self.panels:
            self.scroll.ensureWidgetVisible(self.panels[k], 0, theme.px(8))
        self.state_changed.emit()

    def show_tabs(self, keys):
        """Open these tabs (and unfold their panels) without closing any others."""
        new = [k for k in keys if k in self.panels and (k not in self.open or self.panels[k].shut)]
        if not new:
            return
        for k in new:
            if k not in self.open:
                self.open.append(k)
            if self.panels[k].shut:
                self.panels[k].set_shut(False)
        self._sync()
        self.state_changed.emit()

    def _sync(self):
        for k, b in self.tabbtn.items():
            b.setChecked(k in self.open)
        for k, p in self.panels.items():
            p.setVisible(k in self.open)

    def state(self):
        return {"open": list(self.open), "shut": [k for k, p in self.panels.items() if p.shut]}

    def set_state(self, st):
        if not st:
            return
        valid = {k for k, _ in self.tabdef}
        self.open = [k for k in st.get("open", self.open) if k in valid]
        for k, p in self.panels.items():
            p.set_shut(k in st.get("shut", []))
        self._sync()

    def apply_scale(self):
        self.v.setSpacing(theme.px(6))
        self.inner.setSpacing(theme.px(12))
        self.flow.set_gap(theme.px(4))
        for p in self.panels.values():
            p.apply_scale()


MY_SCREEN = "My screen"        # preset name of the "size of the monitor the window is on" entry


class _PresetBox(QComboBox):
    """The canvas size list. Calls before_popup each time it opens (the window may have moved to another monitor)."""

    def __init__(self, before_popup):
        super().__init__()
        self._before = before_popup

    def showPopup(self):
        self._before()
        super().showPopup()


# ----------------------------------------------------------------------------- base for panels that follow the document
class DocPanel(Panel):
    def __init__(self, key, title, win, extra=None):
        super().__init__(key, title, extra)
        self.win = win
        self.doc = win.doc
        self._busy = False

    def refresh(self):
        pass

    def set_val(self, w, v):
        w.blockSignals(True)
        if isinstance(w, (QDoubleSpinBox, QSpinBox, QSlider)):
            w.setValue(v)
        elif isinstance(w, QCheckBox):
            w.setChecked(bool(v))
        elif isinstance(w, QLineEdit):
            if not w.hasFocus():
                w.setText(v)
        elif isinstance(w, QComboBox):
            i = w.findData(v)
            w.setCurrentIndex(max(0, i))
        w.blockSignals(False)


# ----------------------------------------------------------------------------- LEFT: brief
class BriefPanel(DocPanel):
    """Free text for the agent: the whole project, and this page."""

    def __init__(self, win):
        super().__init__("brief", "Brief", win)
        b = self.b
        b.addWidget(hint("Goes into the export. Tell the agent what you are building: the product, who it is for, "
                         "the look and feel, fonts, colours, rules."))
        self.proj = QPlainTextEdit()
        self.proj.setPlaceholderText("Project brief: e.g. 'A recipe app for busy parents. Calm, rounded, lots of white space. "
                                     "Primary colour green. Every screen has a bottom tab bar…'")
        self.proj.setFixedHeight(theme.px(130))
        self.page_t = QPlainTextEdit()
        self.page_t.setPlaceholderText("This page: what screen it is and what happens on it.")
        self.page_t.setFixedHeight(theme.px(90))
        self.page_f = field("this page", self.page_t)
        b.addWidget(field("project brief", self.proj))
        b.addWidget(self.page_f)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(500)
        self._timer.timeout.connect(self._save)
        self.proj.textChanged.connect(self._typed)
        self.page_t.textChanged.connect(self._typed)
        self._page_id = None

    def refresh(self):
        pg = self.doc.page
        if pg.id != self._page_id:
            self._save()
        self.page_f.findChild(QLabel).setText(f"this page · {pg.name}")
        for w, v in ((self.proj, self.doc.project.brief), (self.page_t, pg.notes)):
            if (pg.id != self._page_id or not w.hasFocus()) and w.toPlainText() != v:
                w.blockSignals(True); w.setPlainText(v); w.blockSignals(False)
        self._page_id = pg.id

    def _typed(self):
        self.doc.project.brief = self.proj.toPlainText()
        if self._page_id in (None, self.doc.page.id):
            self._page_id = self.doc.page.id
            self.doc.page.notes = self.page_t.toPlainText()
        self._timer.start()

    def _save(self):
        if self._timer.isActive():
            self._timer.stop()
            self.doc.commit("Brief", merge="brief")


# ----------------------------------------------------------------------------- LEFT: canvas
class CanvasPanel(DocPanel):
    def __init__(self, win):
        super().__init__("canvas", "Canvas", win)
        b = self.b
        self.name = QLineEdit()
        self.name.setPlaceholderText("page name")
        self.name.editingFinished.connect(self._name)
        b.addWidget(field("page name", self.name))
        self.preset = _PresetBox(self._my_screen_item)
        self.preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.preset.setMinimumContentsLength(8)
        self._fill_presets()
        self.preset.activated.connect(self._preset)
        b.addWidget(field("native screen size", self.preset))
        self.w = spin(16, 20000, 0, 1, " px")
        self.h = spin(16, 20000, 0, 1, " px")
        self.swap = button("⇄", "Swap width and height (portrait / landscape)", "Ic")
        self.swap.clicked.connect(self._swap)
        self.w.valueChanged.connect(self._size)
        self.h.valueChanged.connect(self._size)
        b.addWidget(hrow(field("width", self.w), field("height", self.h), self.swap))
        self.dots = WrapCheck("dots")
        self.dots.toggled.connect(self._dots)
        self.sp = spin(1, 400, 0, 1, " px")   # 1 px: one canvas pixel, the finest grid
        self.sp.valueChanged.connect(self._dots)
        self.bg = Swatch("Canvas colour", alpha=False)
        self.bg.picked.connect(self._bg)
        b.addWidget(hrow(self.dots, field("dot spacing", self.sp), field("colour", self.bg)))
        # margins: the safe area inside the canvas edge
        line = QFrame(); line.setFixedHeight(1); line.setStyleSheet(f"background:{theme.LINE};")
        b.addWidget(line)
        sub = QLabel("MARGINS"); sub.setObjectName("PanelTitle")
        b.addWidget(sub)
        self.m = []
        boxes = []
        for i, t in enumerate(("top", "right", "bottom", "left")):
            sp_ = spin(0, 10000, 0, 1)
            sp_.setToolTip(f"Distance from the {t} edge of the canvas, in canvas pixels")
            sp_.valueChanged.connect(lambda v, i=i: self._margin(i, v))
            self.m.append(sp_)
            boxes.append(field(t, sp_))
        b.addWidget(hrow(*boxes))
        self.mlink = WrapCheck("same on all sides")
        self.mlink.toggled.connect(self._mlink)
        self.mshow = WrapCheck("show margin lines")
        self.mshow.setToolTip("Light blue see-through lines around the canvas")
        self.mshow.toggled.connect(self._mflags)
        self.mkeep = WrapCheck("keep shapes inside the margins")
        self.mkeep.setToolTip("Shapes stop at the margin lines when you move, resize, turn, draw or nudge them")
        self.mkeep.toggled.connect(self._mflags)
        b.addWidget(self.mlink)
        b.addWidget(self.mshow)
        b.addWidget(self.mkeep)
        pull = button("Move everything inside", "Shapes that are past the margins now are moved (or shrunk) to fit", "Small")
        pull.clicked.connect(self._pull)
        b.addWidget(brow(pull))
        b.addWidget(hint("Shapes keep their place on the canvas in canvas pixels. Changing the size or the margins never moves them."))

    def my_screen_size(self) -> tuple[int, int]:
        """Native pixels of the monitor this window is on (Windows scaling undone: 125% of 1536 x 864 = 1920 x 1080)."""
        win = self.window()
        scr = (win.screen() if win is not None else None) or QGuiApplication.primaryScreen()
        r = scr.geometry()
        dpr = scr.devicePixelRatio()
        return round(r.width() * dpr), round(r.height() * dpr)

    def _my_screen_item(self):
        """Keep the first entry in step with the monitor the window is on now (checked each time the list opens)."""
        sw, sh = self.my_screen_size()
        self.preset.setItemText(0, f"My screen  {sw} x {sh}")
        self.preset.setItemData(0, (MY_SCREEN, sw, sh))

    def _fill_presets(self):
        p = self.preset
        p.clear()
        sw, sh = self.my_screen_size()
        p.addItem(f"My screen  {sw} x {sh}", (MY_SCREEN, sw, sh))
        group = None
        for g, name, w, h in PRESETS:
            if g != group:
                p.insertSeparator(p.count())
                p.addItem(f"— {g} —", None)
                idx = p.count() - 1
                p.model().item(idx).setEnabled(False)
                group = g
            p.addItem(f"{name}   {w} x {h}" if "x" not in name else name, (name, w, h))
        p.insertSeparator(p.count())
        p.addItem("Custom", ("Custom", 0, 0))

    def refresh(self):
        pg = self.doc.page
        self.set_val(self.name, pg.name)
        self.set_val(self.w, pg.width)
        self.set_val(self.h, pg.height)
        self.set_val(self.dots, pg.dots)
        self.set_val(self.sp, pg.dot_spacing)
        self.bg.set_color(pg.background)
        for sp_, v in zip(self.m, pg.margins):
            self.set_val(sp_, v)
        self.set_val(self.mlink, pg.margins_linked)
        self.set_val(self.mshow, pg.show_margins)
        self.set_val(self.mkeep, pg.keep_inside)
        self.preset.blockSignals(True)
        found = -1
        for i in range(self.preset.count()):
            d = self.preset.itemData(i)
            if d and d[0] == MY_SCREEN and pg.preset in (MY_SCREEN, "This screen"):
                found = i
                break
            if d and d[0] == pg.preset and {d[1], d[2]} == {pg.width, pg.height}:
                found = i
        if found < 0:
            found = self.preset.count() - 1
        self.preset.setCurrentIndex(found)
        self.preset.blockSignals(False)

    def _name(self):
        t = self.name.text().strip()
        if t and t != self.doc.page.name:
            self.doc.page.name = t
            self.doc.structure.emit()
            self.doc.commit("Page renamed")

    def _preset(self, i):
        d = self.preset.itemData(i)
        if not d or d[0] == "Custom":
            return
        pg = self.doc.page
        name, w, h = d
        if name == MY_SCREEN:
            self._my_screen_item()
            name, w, h = self.preset.itemData(0)
        pg.preset, pg.width, pg.height = name, int(w), int(h)
        self._resized(f"Canvas {pg.width} x {pg.height}")

    def _size(self):
        pg = self.doc.page
        w, h = int(self.w.value()), int(self.h.value())
        if (w, h) == (pg.width, pg.height):
            return
        pg.width, pg.height = w, h
        pg.preset = "Custom"
        self._resized(f"Canvas {w} x {h}")

    def _swap(self):
        pg = self.doc.page
        pg.width, pg.height = pg.height, pg.width
        self._resized("Canvas turned")

    def _resized(self, msg):
        self.doc.structure.emit()
        self.doc.commit(msg)
        self.win.board.fit()
        self.refresh()

    def _dots(self, *_):
        pg = self.doc.page
        pg.dots = self.dots.isChecked()
        pg.dot_spacing = int(self.sp.value())   # snapping uses it even while the dots are hidden
        self.doc.changed.emit()
        self.doc.commit("Dots", merge="dots")

    def _margin(self, i, v):
        pg = self.doc.page
        if pg.margins_linked:
            pg.margins = [float(v)] * 4
            for sp_ in self.m:
                self.set_val(sp_, v)
        else:
            pg.margins[i] = float(v)
        self.doc.changed.emit()
        self.doc.commit("Margins", merge="margins")

    def _mlink(self, v):
        pg = self.doc.page
        pg.margins_linked = v
        if v:
            pg.margins = [pg.margins[0]] * 4
            self.refresh()
        self.doc.changed.emit()
        self.doc.commit("Margins linked" if v else "Margins per side")

    def _mflags(self, *_):
        pg = self.doc.page
        pg.show_margins = self.mshow.isChecked()
        pg.keep_inside = self.mkeep.isChecked()
        self.doc.changed.emit()
        self.doc.commit("Margins")

    def _pull(self):
        pg = self.doc.page
        lim = pg.safe_rect()
        keep = pg.keep_inside
        pg.keep_inside = True
        for s in pg.shapes:
            self.win.board.keep_in([s])
        pg.keep_inside = keep
        self.doc.changed.emit()
        self.doc.structure.emit()
        self.doc.commit("Moved everything inside the margins")

    def _bg(self, c):
        self.doc.page.background = c
        self.doc.structure.emit()
        self.doc.commit("Canvas colour")


# ----------------------------------------------------------------------------- LEFT: create
class CreatePanel(DocPanel):
    def __init__(self, win):
        super().__init__("create", "Create", win)
        b = self.b
        b.addWidget(label("add in the middle of the view"))
        r1 = button("+ Rectangle", "A new rectangle in the middle of the view")
        r2 = button("+ Square", "A new square (keeps its proportions when resized)")
        r4 = button("+ Circle", "A new circle (keeps its proportions when resized)")
        r3 = button("+ Line", "A new line")
        r1.clicked.connect(lambda: win.add_shape("rect"))
        r2.clicked.connect(lambda: win.add_shape("square"))
        r4.clicked.connect(lambda: win.add_shape("circle"))
        r3.clicked.connect(lambda: win.add_shape("line"))
        b.addWidget(brow(r1, r2, r4, r3))
        b.addWidget(label("or draw on the canvas"))
        self.dr = button("✎ Rectangle  R", "Then drag on the canvas. Shift = square, Alt = from the centre.", checkable=True)
        self.de = button("✎ Circle  C", "Then drag on the canvas. Shift = circle (else an oval), Alt = from the centre.",
                         checkable=True)
        self.dl = button("✎ Line  L", "Then drag on the canvas. Shift = 45° steps.", checkable=True)
        self.dd = button("✎ Draw  D", "Freehand, like a brush: each stroke is a shape. Stays on until Esc or V.",
                         checkable=True)
        self.dd.clicked.connect(lambda: win.board.set_tool("select" if win.board.tool == "draw" else "draw"))
        self.dr.clicked.connect(lambda: win.board.set_tool("select" if win.board.tool == "rect" else "rect"))
        self.de.clicked.connect(lambda: win.board.set_tool("select" if win.board.tool == "ellipse" else "ellipse"))
        self.dl.clicked.connect(lambda: win.board.set_tool("select" if win.board.tool == "line" else "line"))
        b.addWidget(brow(self.dr, self.de, self.dl, self.dd))
        b.addWidget(hint("Click without dragging for a default size. Esc goes back to selecting."))
        win.board.tool_changed.connect(self._tool)

    def _tool(self, t):
        self.dr.setChecked(t == "rect")
        self.de.setChecked(t == "ellipse")
        self.dl.setChecked(t == "line")
        self.dd.setChecked(t == "draw")


# ----------------------------------------------------------------------------- LEFT: snapping
class SnapPanel(DocPanel):
    def __init__(self, win):
        super().__init__("snap", "Snapping", win)
        b = self.b
        s = self.doc.snap
        self.boxes = {}
        for k, text, tip in (
                ("objects", "edges and centres of shapes", "Line up with the edges and middles of other shapes"),
                ("spacing", "equal spacing and gaps", "Keep the same gap as other shapes, or sit in the exact middle of the space between two"),
                ("canvas", "canvas edges and centre", "Line up with the canvas edges and its centre lines"),
                ("sizes", "same width / height while resizing", "Resize to the width or height of another shape"),
                ("grid", "the dots (every edge on a dot)", "On: shapes are drawn, placed, moved and resized only onto the dots, and arrow keys move one dot. This wins over the other snaps."),
                ("pixel", "whole pixels", "Round positions and sizes to whole canvas pixels")):
            c = WrapCheck(text)
            c.setToolTip(tip)
            c.setChecked(getattr(s, k))
            c.toggled.connect(lambda v, k=k: self._set(k, v))
            b.addWidget(c)
            self.boxes[k] = c
        self.th = ISpin()
        self.th.setRange(1, 40)
        self.th.setSuffix(" screen px")
        self.th.setValue(s.threshold)
        self.th.valueChanged.connect(lambda v: self._set("threshold", v))
        b.addWidget(field("snap distance", self.th))
        self.helpers = WrapCheck("see-through blue centre and alignment lines while dragging")
        self.helpers.setChecked(win.board.show_helpers)
        self.helpers.toggled.connect(self._helpers)
        b.addWidget(self.helpers)
        self.all_dots = button("Put everything on the dots", "Snap every shape on this page to the dot grid now", "Small")
        self.all_dots.clicked.connect(self._all_dots)
        b.addWidget(brow(self.all_dots))
        b.addWidget(hint("Hold Ctrl while dragging to move freely. Pink = lined up with a shape or spacing, blue = the canvas centre or margins."))

    def refresh(self):
        s = self.doc.snap
        for k, c in self.boxes.items():
            self.set_val(c, getattr(s, k))
        for kk in ("objects", "spacing", "sizes"):
            self.boxes[kk].setEnabled(not s.grid)
        self.set_val(self.th, s.threshold)
        self.set_val(self.helpers, self.win.board.show_helpers)

    def _set(self, k, v):
        setattr(self.doc.snap, k, v)
        if k == "grid":
            for kk in ("objects", "spacing", "sizes"):
                self.boxes[kk].setEnabled(not v)
            self.doc.status.emit("Dot snapping on: every edge lands on a dot" if v else "Dot snapping off")
        self.win.save_ui_soon()

    def _all_dots(self):
        pg = self.doc.page
        g = float(max(1, pg.dot_spacing))
        from .model import grid_fit
        for s in pg.shapes:
            grid_fit(s, g)
            self.win.board.keep_in([s], shrink=False)
        self.doc.changed.emit()
        self.doc.structure.emit()
        self.doc.commit("Everything on the dots")

    def _helpers(self, v):
        self.win.board.show_helpers = v
        self.win.save_ui_soon()


# ----------------------------------------------------------------------------- LEFT: view
class ViewPanel(DocPanel):
    def __init__(self, win):
        super().__init__("view", "View", win)
        b = self.b
        self.names = WrapCheck("name tag on selected shapes")
        self.names.setChecked(win.board.show_names)
        self.names.toggled.connect(self._names)
        b.addWidget(self.names)
        bf = button("Fit", "Whole canvas in view (Ctrl+0)")
        b1 = button("100%", "Canvas pixels = screen pixels (Ctrl+1)")
        b5 = button("50%")
        b2 = button("200%")
        bf.clicked.connect(win.board.fit)
        b1.clicked.connect(lambda: win.board.set_zoom(1.0))
        b5.clicked.connect(lambda: win.board.set_zoom(0.5))
        b2.clicked.connect(lambda: win.board.set_zoom(2.0))
        b.addWidget(brow(bf, b1, b5, b2))
        fs = button("Full screen  F11")
        fs.clicked.connect(win.toggle_fullscreen)
        b.addWidget(fs)
        keys = ("V select · R rectangle · C circle · L line\n"
                "Arrows nudge 1 px · Shift+arrows 10 px\n"
                "Right-drag or Space-drag pans · wheel zooms\n"
                "Shift keeps proportions / straight lines / 15° turns\n"
                "Alt-drag copies · Alt-resize from the centre\n"
                "Double-click or F2 names a shape\n"
                "Ctrl+D duplicate · Ctrl+C / V copy, paste · Del delete\n"
                "Ctrl+] / Ctrl+[ forward / backward\n"
                "Shift+H / Shift+V flip · Ctrl+Z / Ctrl+Y undo, redo")
        b.addWidget(label("keys"))
        b.addWidget(hint(keys))

    def refresh(self):
        self.set_val(self.names, self.win.board.show_names)

    def _names(self, v):
        self.win.board.show_names = v
        self.win.board.update()
        self.win.save_ui_soon()


# ----------------------------------------------------------------------------- RIGHT: shape properties
class ShapePanel(DocPanel):
    def __init__(self, win):
        super().__init__("shape", "Shape", win)
        b = self.b
        self.info = label("", "Hint")
        b.addWidget(self.info)
        self.name = QLineEdit()
        self.name.setPlaceholderText("name")
        self.name.editingFinished.connect(self._name)
        self.name_f = field("name", self.name)
        b.addWidget(self.name_f)
        # geometry
        self.x = spin(-100000, 100000, 1); self.y = spin(-100000, 100000, 1)
        self.w = spin(1, 100000, 1); self.h = spin(1, 100000, 1)
        self.fx = field("x", self.x); self.fy = field("y", self.y)
        self.fw = field("width", self.w); self.fh = field("height", self.h)
        b.addWidget(hrow(self.fx, self.fy))
        self.size_row = hrow(self.fw, self.fh)
        b.addWidget(self.size_row)
        for sp_, k in ((self.x, "x"), (self.y, "y"), (self.w, "w"), (self.h, "h")):
            sp_.valueChanged.connect(lambda v, k=k: self._geo(k, v))
        # line end
        self.x2 = spin(-100000, 100000, 1); self.y2 = spin(-100000, 100000, 1)
        self.x2.valueChanged.connect(lambda v: self._geo("x2", v))
        self.y2.valueChanged.connect(lambda v: self._geo("y2", v))
        self.end_row = hrow(field("end x", self.x2), field("end y", self.y2))
        b.addWidget(self.end_row)
        self.lock = WrapCheck("keep proportions")
        self.lock.setToolTip("Resizing keeps the width : height ratio (Shift does the opposite while dragging)")
        self.lock.toggled.connect(self._lock)
        b.addWidget(self.lock)
        self.empty = hint("Nothing selected. Click a shape, drag a box around several, or press R / L to draw.")
        b.addWidget(hint("Colours, border, corners, line style and pictures are in the Design tab."))
        b.addWidget(self.empty)

    def refresh(self):
        sel = self.doc.selected()
        has = bool(sel)
        rects = [s for s in sel if not s.is_line]
        lines = [s for s in sel if s.is_line]
        one = sel[0] if len(sel) == 1 else None
        self.empty.setVisible(not has)
        for w in (self.name_f, self.fx, self.fy, self.size_row, self.lock, self.end_row):
            w.setVisible(has)
        if not has:
            self.info.setText("")
            return
        kind = {"rect": "rectangle", "path": "drawing"}.get(one.kind, one.kind) if one else f"{len(sel)} shapes"
        self.info.setText(f"{kind}{' · ' + one.id if one else ''}")
        self.name.setEnabled(one is not None)
        self.set_val(self.name, one.name if one else f"{len(sel)} shapes")
        self.lock.setVisible(bool(one and not one.is_line))
        self.end_row.setVisible(bool(one and one.is_line))
        self.size_row.setVisible(bool(one and not one.is_line) or len(sel) > 1)
        self.w.setEnabled(one is not None); self.h.setEnabled(one is not None)
        if one and one.is_line:
            self.fx.findChild(QLabel).setText("start x"); self.fy.findChild(QLabel).setText("start y")
            self.set_val(self.x, one.x1); self.set_val(self.y, one.y1)
            self.set_val(self.x2, one.x2); self.set_val(self.y2, one.y2)
        elif one:
            self.fx.findChild(QLabel).setText("x"); self.fy.findChild(QLabel).setText("y")
            self.set_val(self.x, one.x); self.set_val(self.y, one.y)
            self.set_val(self.w, one.w); self.set_val(self.h, one.h)
            self.set_val(self.lock, one.lock_ratio)
        else:
            bx = union_box(s.aabb() for s in sel)
            self.fx.findChild(QLabel).setText("x (all)"); self.fy.findChild(QLabel).setText("y (all)")
            self.set_val(self.x, bx[0]); self.set_val(self.y, bx[1])
            self.set_val(self.w, bx[2] - bx[0]); self.set_val(self.h, bx[3] - bx[1])

    # -- edits
    def _name(self):
        sel = self.doc.selected()
        if len(sel) == 1:
            t = self.name.text().strip()
            if t and t != sel[0].name:
                sel[0].name = t
                self.doc.structure.emit()
                self.doc.commit(f"Renamed to {t}")

    def _geo(self, k, v):
        sel = self.doc.selected()
        if not sel:
            return
        if len(sel) == 1:
            s = sel[0]
            if s.is_line:
                if k == "x": s.x1 = v
                elif k == "y": s.y1 = v
                elif k == "x2": s.x2 = v
                elif k == "y2": s.y2 = v
            else:
                if k in ("w", "h") and s.lock_ratio and s.w > 0 and s.h > 0:
                    r = s.w / s.h
                    if k == "w":
                        s.w, s.h = v, v / r
                    else:
                        s.w, s.h = v * r, v
                else:
                    setattr(s, k, v)
        else:
            bx = union_box(s.aabb() for s in sel)
            dx = v - bx[0] if k == "x" else 0
            dy = v - bx[1] if k == "y" else 0
            for s in sel:
                s.translate(dx, dy)
        self.win.board.keep_in(sel)
        self.win.board.fit_grid(sel)
        self.win.board.keep_in(sel, shrink=False)
        self.doc.changed.emit()
        self.doc.commit("Moved" if k in ("x", "y", "x2", "y2") else "Resized")

    def _lock(self, v):
        for s in self.doc.selected():
            s.lock_ratio = v
        self.doc.commit("Keep proportions " + ("on" if v else "off"))


# ----------------------------------------------------------------------------- RIGHT: transform
class TransformPanel(DocPanel):
    def __init__(self, win):
        super().__init__("transform", "Transform", win)
        b = self.b
        self.rot = spin(-180, 180, 1, 1, " °")
        self.rot.setWrapping(True)
        self.rot.valueChanged.connect(self._rot)
        r0 = button("0°", "Straight again", "Small")
        r0.clicked.connect(lambda: self._set_rot(0))
        self.rot_f = field("rotation", self.rot)
        b.addWidget(hrow(self.rot_f, r0))
        l90 = button("⟲ 90°", "Turn left 90°"); r90 = button("⟳ 90°", "Turn right 90°"); r180 = button("180°")
        l90.clicked.connect(lambda: win.rotate_by(-90)); r90.clicked.connect(lambda: win.rotate_by(90))
        r180.clicked.connect(lambda: win.rotate_by(180))
        b.addWidget(brow(l90, r90, r180))
        fh = button("⇋ Flip horizontal", "Mirror left-right (Shift+H)")
        fv = button("⇵ Flip vertical", "Mirror top-bottom (Shift+V)")
        fh.clicked.connect(lambda: win.flip(0)); fv.clicked.connect(lambda: win.flip(1))
        b.addWidget(brow(fh, fv))
        b.addWidget(label("order"))
        o = []
        for t, k, tip in (("Front", "front", "Bring to front (Ctrl+Shift+])"), ("Forward", "forward", "Ctrl+]"),
                          ("Backward", "backward", "Ctrl+["), ("Back", "back", "Send to back (Ctrl+Shift+[)")):
            bb = button(t, tip, "Small")
            bb.clicked.connect(lambda _=False, k=k: self.doc.reorder(k))
            o.append(bb)
        b.addWidget(brow(*o))
        d = button("Duplicate", "Ctrl+D"); x = button("Delete", "Del")
        d.clicked.connect(win.duplicate); x.clicked.connect(self.doc.delete_selected)
        b.addWidget(brow(d, x))
        self.note = hint("")
        b.addWidget(self.note)

    def refresh(self):
        sel = self.doc.selected()
        self.setEnabled(bool(sel))
        one = sel[0] if len(sel) == 1 else None
        self.rot.setEnabled(bool(one))
        if one:
            self.set_val(self.rot, norm_deg(one.angle()) if one.is_line else one.rotation)
            self.rot_f.findChild(QLabel).setText("angle" if one.is_line else "rotation")
            fl = [n for n, v in (("horizontal", one.flip_h), ("vertical", one.flip_v)) if v]
            self.note.setText("Flipped " + " and ".join(fl) if fl else "")
        else:
            self.note.setText("Turns and flips act on the whole selection around its middle." if sel else "Select a shape first.")

    def _rot(self, v):
        self._set_rot(v)

    def _set_rot(self, v):
        sel = self.doc.selected()
        if len(sel) != 1:
            return
        s = sel[0]
        if s.is_line:
            cx, cy = s.center()
            L = s.length() / 2
            a = math.radians(v)
            s.x1, s.y1 = cx - math.cos(a) * L, cy - math.sin(a) * L
            s.x2, s.y2 = cx + math.cos(a) * L, cy + math.sin(a) * L
        else:
            s.rotation = norm_deg(v)
        self.doc.changed.emit()
        self.doc.commit("Rotated")


# ----------------------------------------------------------------------------- RIGHT: details
def colour_text(c: str) -> str:
    col = QColor(c)
    if not col.isValid():
        return str(c)
    a = col.alphaF()
    return col.name(QColor.NameFormat.HexRgb).upper() + (f" at {a * 100:.0f}% opacity" if a < 0.999 else "")


def picture_rows(s):
    from .images import image_of, size_of
    img = image_of(s)
    if not img:
        return [("picture", "none")]
    sz = size_of(img.get("path", ""))
    return [("picture", img.get("original_name") or img.get("path", "")),
            ("picture file", img.get("path", "") + ("" if sz else "  (missing)")),
            ("picture size", f"{sz[0]} × {sz[1]} px" if sz else "—"),
            ("picture fit", f"{img.get('fit', 'fill')}, zoom {float(img.get('zoom', 1)) * 100:.0f}%"),
            ("picture offset", f"{float(img.get('dx', 0)):g}, {float(img.get('dy', 0)):g}"),
            ("picture opacity", f"{float(img.get('opacity', 1)) * 100:.0f}%")]



class DetailsPanel(DocPanel):
    def __init__(self, win):
        cp = button("Copy", "Copy the selected shape's details as JSON", "Small")
        super().__init__("details", "Details", win, extra=[cp])
        cp.clicked.connect(self._copy)
        # the first thing: a box to write anything about the selected shape (saved with it)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Write anything about this shape…")
        self.notes.setTabChangesFocus(True)
        self.notes.setFixedHeight(theme.px(84))
        self.notes.textChanged.connect(self._notes_typed)
        self.notes_f = field("notes", self.notes)
        self.b.addWidget(self.notes_f)
        self._notes_id = None
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(500)
        self._notes_timer.timeout.connect(self._notes_save)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(theme.px(10))
        self.grid.setVerticalSpacing(theme.px(3))
        self.grid.setColumnStretch(1, 1)
        holder = QWidget(); holder.setLayout(self.grid)
        self.b.addWidget(holder)
        self.rows = []

    def _rows(self, items):
        while len(self.rows) < len(items):
            k = label("", "KVKey"); v = QLabel(); v.setObjectName("KV")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            v.setWordWrap(True)
            r = len(self.rows)
            self.grid.addWidget(k, r, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(v, r, 1)
            self.rows.append((k, v))
        for i, (k, v) in enumerate(self.rows):
            if i < len(items):
                k.setText(items[i][0]); v.setText(items[i][1]); k.show(); v.show()
            else:
                k.hide(); v.hide()

    def refresh(self):
        if self.isHidden() or self.shut:
            return
        sel = self.doc.selected()
        pg = self.doc.page
        one = sel[0] if len(sel) == 1 else None
        if (one.id if one else None) != self._notes_id:
            self._notes_save()                       # keep what was typed for the last shape
        self.notes_f.setVisible(one is not None)
        if one is not None:
            self.notes.setFixedHeight(theme.px(84))
            if one.id != self._notes_id or (not self.notes.hasFocus() and self.notes.toPlainText() != one.notes):
                self.notes.blockSignals(True)
                self.notes.setPlainText(one.notes)
                self.notes.blockSignals(False)
        self._notes_id = one.id if one else None
        W, H = pg.width, pg.height
        f = lambda v: f"{v:.1f}".rstrip("0").rstrip(".")
        pct = lambda v, t: f"{100 * v / t:.2f}%"
        if not sel:
            items = [("page", f"{self.doc.page_index + 1} · {pg.name}"), ("canvas", f"{W} × {H} px"),
                     ("preset", pg.preset), ("shapes", str(len(pg.shapes))),
                     ("selection", "none")]
        elif len(sel) > 1:
            b = union_box(s.aabb() for s in sel)
            items = [("selected", f"{len(sel)} shapes"), ("bounds x, y", f"{f(b[0])}, {f(b[1])}"),
                     ("bounds size", f"{f(b[2] - b[0])} × {f(b[3] - b[1])}"),
                     ("centre", f"{f((b[0] + b[2]) / 2)}, {f((b[1] + b[3]) / 2)}"),
                     ("names", ", ".join(s.name or s.id for s in sel))]
        else:
            s = sel[0]
            z = pg.shapes.index(s) + 1
            b = s.aabb()
            grp = pg.group_of(s.id)
            common = [("name", s.name or "—"), ("group", grp["name"] if grp else "none"), ("id", s.id),
                      ("type", {"line": "line", "ellipse": "ellipse", "path": "drawing"}.get(s.kind, "rectangle")),
                      ("page", f"{self.doc.page_index + 1} · {pg.name}"), ("layer", f"{z} of {len(pg.shapes)} (1 = back)")]
            if s.is_line:
                geo = [("start", f"{f(s.x1)}, {f(s.y1)}"), ("end", f"{f(s.x2)}, {f(s.y2)}"),
                       ("length", f"{f(s.length())} px"), ("angle", f"{f(norm_deg(s.angle()))}°"),
                       ("centre", "{}, {}".format(*map(f, s.center()))),
                       ("on canvas", f"{pct(min(s.x1, s.x2), W)}, {pct(min(s.y1, s.y2), H)}"),
                       ("thickness", f"{f(s.stroke_width)} px"), ("colour", s.stroke),
                       ("style", f"{s.line_style}, {s.cap} ends")]
            else:
                inside = b[0] >= 0 and b[1] >= 0 and b[2] <= W and b[3] <= H
                geo = [("x, y", f"{f(s.x)}, {f(s.y)}"), ("size", f"{f(s.w)} × {f(s.h)}"),
                       ("right, bottom", f"{f(s.x + s.w)}, {f(s.y + s.h)}"),
                       ("centre", "{}, {}".format(*map(f, s.center()))),
                       ("on canvas", f"x {pct(s.x, W)} · y {pct(s.y, H)}"),
                       ("of canvas", f"w {pct(s.w, W)} · h {pct(s.h, H)}"),
                       ("rotation", f"{f(s.rotation)}°"),
                       ("bounds", f"{f(b[0])}, {f(b[1])} → {f(b[2])}, {f(b[3])}"),
                       ("fits canvas", "yes" if inside else "no, partly outside"),
                       ("aspect", f"{s.w / s.h:.3f}" if s.h else "—"), ("area", f"{f(s.w * s.h)} px²"),
                       ("corners", f"{f(min(s.radius, s.max_radius()))} px"),
                       ("border", f"{f(s.stroke_width)} px {colour_text(s.stroke)}" if s.stroke_width > 0 else "none"),
                       ("fill", colour_text(s.fill) if s.fill else "none"),
                       *picture_rows(s),
                       ("proportions", "kept" if s.lock_ratio else "free")]
            flips = [n for n, v in (("horizontal", s.flip_h), ("vertical", s.flip_v)) if v]
            items = common + geo + [("flipped", ", ".join(flips) or "no"), ("created", s.created),
                                    ("modified", s.modified), ("contents", "none yet")]
        self._rows(items)

    def _notes_typed(self):
        s = self.doc.get(self._notes_id) if self._notes_id else None
        if s is None:
            return
        s.notes = self.notes.toPlainText()
        self._notes_timer.start()

    def _notes_save(self):
        if not self._notes_timer.isActive():
            return
        self._notes_timer.stop()
        self.doc.commit("Notes", merge="notes")

    def _copy(self):
        self._notes_save()
        sel = self.doc.selected()
        data = [s.to_dict() for s in sel] if sel else self.doc.page.to_dict()
        if isinstance(data, list) and len(data) == 1:
            data = data[0]
        QApplication.clipboard().setText(json.dumps(data, indent=2))
        self.doc.status.emit("Details copied")


# ----------------------------------------------------------------------------- RIGHT: shapes list
class ShapesPanel(DocPanel):
    def __init__(self, win):
        super().__init__("shapes", "Shapes", win)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.list.itemSelectionChanged.connect(self._sel)
        self.list.itemChanged.connect(self._renamed)
        self.list.model().rowsMoved.connect(self._moved)
        self.list.setMinimumHeight(theme.px(120))
        self.b.addWidget(self.list)
        self.b.addWidget(hint("Top = in front. Drag to change the order. Double-click to rename."))

    def refresh(self):
        pass

    def rebuild(self):
        self._busy = True
        self.list.blockSignals(True)
        self.list.clear()
        for s in reversed(self.doc.page.shapes):
            it = QListWidgetItem({"line": "╱  ", "path": "✎  ", "ellipse": "◯  "}.get(s.kind, "▭  ") + (s.name or s.id))
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self._busy = False
        self.sync_sel()
        rows = max(4, min(14, self.list.count()))
        self.list.setFixedHeight(int(rows * (theme.px(13) + theme.px(12)) + theme.px(8)))

    def sync_sel(self):
        self._busy = True
        self.list.blockSignals(True)
        ids = set(self.doc.selection)
        last = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            on = it.data(Qt.ItemDataRole.UserRole) in ids
            it.setSelected(on)
            if on:
                last = it
        if last:
            self.list.scrollToItem(last)
        self.list.blockSignals(False)
        self._busy = False

    def _sel(self):
        if self._busy:
            return
        ids = [it.data(Qt.ItemDataRole.UserRole) for it in self.list.selectedItems()]
        self.doc.set_selection(ids)

    def _renamed(self, it):
        if self._busy:
            return
        sid = it.data(Qt.ItemDataRole.UserRole)
        s = self.doc.get(sid)
        if not s:
            return
        t = it.text()
        for pre in ("╱  ", "▭  "):
            if t.startswith(pre):
                t = t[len(pre):]
        t = t.strip()
        if t and t != s.name:
            s.name = t
            self.doc.commit(f"Renamed to {t}")
            self.doc.changed.emit()
        self.rebuild()

    def _moved(self, *_):
        if self._busy:
            return
        order = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        pg = self.doc.page
        by = {s.id: s for s in pg.shapes}
        pg.shapes = [by[i] for i in reversed(order) if i in by]
        self.doc.commit("Order changed")
        self.doc.changed.emit()
