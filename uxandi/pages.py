"""The page strip under the canvas: one thumbnail per page,
click to go to it, drag left / right to reorder, + adds a page."""
from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, QTimer, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QFontMetricsF
from PySide6.QtWidgets import QWidget, QScrollArea, QFrame, QHBoxLayout, QMenu, QInputDialog

from . import theme
from .canvas import render_thumb


class PageStrip(QFrame):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setObjectName("PageStrip")
        self.doc = doc
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view = _Tiles(self)
        self.scroll.setWidget(self.view)
        lay.addWidget(self.scroll)
        self._thumbs: dict[str, object] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh_current)
        doc.changed.connect(self._timer.start)
        doc.structure.connect(self.rebuild)
        doc.page_changed.connect(self.view.update)
        self.apply_scale()

    def apply_scale(self):
        h = theme.px(68) + theme.px(14) + theme.px(16) + theme.px(10)
        self.setFixedHeight(h + 2)
        self._thumbs.clear()
        self.rebuild()

    def thumb_h(self):
        return theme.px(68)

    def thumb(self, page):
        pm = self._thumbs.get(page.id)
        if pm is None:
            pm = render_thumb(page, self.thumb_h(), theme.px(160))
            self._thumbs[page.id] = pm
        return pm

    def _refresh_current(self):
        pg = self.doc.page
        self._thumbs.pop(pg.id, None)
        self.view.relayout()

    def rebuild(self):
        live = {p.id for p in self.doc.project.pages}
        for k in list(self._thumbs):
            if k not in live:
                del self._thumbs[k]
        self._thumbs.pop(self.doc.page.id, None)
        self.view.relayout()


class _Tiles(QWidget):
    def __init__(self, strip: PageStrip):
        super().__init__()
        self.strip = strip
        self.doc = strip.doc
        self.rects: list[QRectF] = []
        self.add_rect = QRectF()
        self.drag = None
        self.setMouseTracking(True)
        self.hover = -2

    def relayout(self):
        pad = theme.px(8)
        gap = theme.px(8)
        x = pad
        self.rects = []
        lab = theme.px(14)
        for p in self.doc.project.pages:
            pm = self.strip.thumb(p)
            w = pm.width() / pm.devicePixelRatio()
            tw = max(w, theme.px(44))
            self.rects.append(QRectF(x, pad, tw + theme.px(8), self.strip.thumb_h() + lab + theme.px(10)))
            x += tw + theme.px(8) + gap
        self.add_rect = QRectF(x, pad, theme.px(44), self.strip.thumb_h() + lab + theme.px(10))
        self.setMinimumWidth(int(x + theme.px(44) + pad))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font()); f.setPixelSize(theme.px(11)); f.setFamily(theme.MONO.split(",")[0])
        cur = self.doc.page_index
        for i, (pg, r) in enumerate(zip(self.doc.project.pages, self.rects)):
            pm = self.strip.thumb(pg)
            w = pm.width() / pm.devicePixelRatio()
            h = pm.height() / pm.devicePixelRatio()
            tx = r.x() + (r.width() - w) / 2
            ty = r.y() + theme.px(4) + (self.strip.thumb_h() - h)
            if self.drag and self.drag.get("active") and self.drag["i"] == i:
                p.setOpacity(0.35)
            # border
            if i == cur:
                p.setPen(QPen(QColor(theme.ACCENT), 2))
            elif i == self.hover:
                p.setPen(QPen(QColor(0, 0, 0, 66), 2))
            else:
                p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
            for k, a in ((3, 14), (1, 36)):
                p.fillRect(QRectF(tx - k / 2, ty - k / 2 + 1, w + k, h + k), QColor(0, 0, 0, a))
            p.drawPixmap(int(tx), int(ty), pm)
            p.setFont(f)
            f.setBold(i == cur)
            p.setPen(QColor(theme.ACCENT if i == cur else theme.DIM))
            fm = QFontMetricsF(f)
            text = fm.elidedText(f"{i + 1} {pg.name}", Qt.TextElideMode.ElideRight, r.width() - 4)
            p.drawText(QRectF(r.x(), ty + h + theme.px(2), r.width(), theme.px(14)), Qt.AlignmentFlag.AlignCenter, text)
            p.setOpacity(1.0)
        # drop marker
        if self.drag and self.drag.get("active"):
            j = self.drag["to"]
            x = (self.rects[j].left() - theme.px(5)) if j < len(self.rects) else (self.rects[-1].right() + theme.px(3))
            p.fillRect(QRectF(x, self.rects[0].top(), theme.px(4), self.rects[0].height()), QColor(theme.SEL))
        # add tile
        r = self.add_rect
        pen = QPen(QColor(theme.ACCENT) if self.hover == -1 else QColor(0, 0, 0, 66), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 4, 4)
        f2 = QFont(self.font()); f2.setPixelSize(theme.px(20))
        p.setFont(f2)
        p.setPen(QColor(theme.ACCENT) if self.hover == -1 else QColor(theme.MUTE))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, "+")
        p.end()

    def _at(self, pos):
        for i, r in enumerate(self.rects):
            if r.contains(pos):
                return i
        if self.add_rect.contains(pos):
            return -1
        return -2

    def _slot(self, x):
        for j, r in enumerate(self.rects):
            if x < r.center().x():
                return j
        return len(self.rects)

    def mousePressEvent(self, e):
        pos = e.position()
        i = self._at(pos)
        if e.button() == Qt.MouseButton.LeftButton:
            if i == -1:
                self.doc.add_page(len(self.doc.project.pages) - 1)
                QTimer.singleShot(0, lambda: self.strip.scroll.horizontalScrollBar().setValue(
                    self.strip.scroll.horizontalScrollBar().maximum()))
            elif i >= 0:
                self.doc.go_page(i)
                self.drag = {"i": i, "x": pos.x(), "active": False, "to": i}
        elif e.button() == Qt.MouseButton.RightButton and i >= 0:
            self.doc.go_page(i)
            self._menu(i, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.drag:
            if not self.drag["active"] and abs(pos.x() - self.drag["x"]) > 6:
                self.drag["active"] = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            if self.drag["active"]:
                self.drag["to"] = self._slot(pos.x())
                self.update()
            return
        h = self._at(pos)
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h != -2 else Qt.CursorShape.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, e):
        d = self.drag
        self.drag = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if d and d["active"]:
            i, j = d["i"], d["to"]
            if j > i:
                j -= 1
            if j != i:
                self.doc.move_page(i, j)
        self.update()

    def mouseDoubleClickEvent(self, e):
        i = self._at(e.position())
        if i >= 0:
            self._rename(i)

    def leaveEvent(self, _):
        self.hover = -2
        self.update()

    def _rename(self, i):
        pg = self.doc.project.pages[i]
        t, ok = QInputDialog.getText(self.window(), "Rename page", "Page name:", text=pg.name)
        if ok and t.strip():
            pg.name = t.strip()
            self.doc.structure.emit()
            self.doc.commit("Page renamed")

    def _menu(self, i, gpos):
        m = QMenu(self)
        m.addAction("Rename…", lambda: self._rename(i))
        m.addAction("Copy page", lambda: self.doc.add_page(i, copy_of=self.doc.project.pages[i]))
        m.addAction("New page after", lambda: self.doc.add_page(i))
        m.addSeparator()
        a = m.addAction("Move left", lambda: self.doc.move_page(i, i - 1)); a.setEnabled(i > 0)
        b = m.addAction("Move right", lambda: self.doc.move_page(i, i + 1)); b.setEnabled(i < len(self.doc.project.pages) - 1)
        m.addSeparator()
        c = m.addAction("Remove page", lambda: self.doc.delete_page(i)); c.setEnabled(len(self.doc.project.pages) > 1)
        m.exec(gpos)
