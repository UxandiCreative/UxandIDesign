"""Marching ants from the selection to its notes box.

One shape selected: ants run round its outline. A whole group selected: round the group's box. A second
line of ants leaves the outline's right side, runs right to the gap beside the right column, then up or
down and into the notes box (the shape's, or the group's) in the Details panel, so the eye lands on
where to write.

It is a see-through widget over the whole window that ignores the mouse. It runs only while it has
something to show and the app is the active one; each step repaints just thin strips along the lines.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QRect
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget

from . import theme

STEP_MS = 90          # one march step; about 11 repaints of the thin strips a second
DASH = 4              # dash and gap, in pen widths
PAD = 4               # px around each line segment that is repainted


class NotesLink(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._outline = None          # QPainterPath, window coordinates
        self._link = None             # QPainterPath, window coordinates
        self._board_clip = QRectF()
        self._lit = None              # the notes box whose border is lit
        self._region = QRegion()
        self._phase = 0.0
        self._t = QTimer(self)
        self._t.setInterval(STEP_MS)
        self._t.timeout.connect(self._step)
        self._soon = QTimer(self)      # after any change: look again once the panels have laid out
        self._soon.setSingleShot(True)
        self._soon.setInterval(0)
        self._soon.timeout.connect(self.relook)
        # the window calls poke() after it refreshes its panels (selection, edits, pages)
        win.board.zoom_changed.connect(self._soon.start)
        win.right.state_changed.connect(self._soon.start)
        win.right.scroll.verticalScrollBar().valueChanged.connect(self._soon.start)
        QApplication.instance().applicationStateChanged.connect(lambda _s: self._soon.start())

    def poke(self):
        self._soon.start()

    # ------------------------------------------------------------------ geometry
    def _target(self):
        """(notes box widget, outline path in board coordinates) or None."""
        win = self.win
        dp = win.panels.get("details")
        board = win.board
        if dp is None or dp.isHidden() or dp.shut or board.mode is not None:
            return None
        sel = win.doc.selected()
        if not sel:
            return None
        if len(sel) == 1 and dp.notes_f.isVisible():
            return dp.notes, self._shape_path(board, sel[0])
        if dp.gnotes_f.isVisible():
            b = (min(s.aabb()[0] for s in sel), min(s.aabb()[1] for s in sel),
                 max(s.aabb()[2] for s in sel), max(s.aabb()[3] for s in sel))
            m = theme.px(6)
            path = QPainterPath()
            path.addRect(QRectF(board.to_screen(b[0], b[1]), board.to_screen(b[2], b[3])).adjusted(-m, -m, m, m))
            return dp.gnotes, path
        return None

    @staticmethod
    def _shape_path(board, s) -> QPainterPath:
        path = QPainterPath()
        if s.is_line:
            path.moveTo(board.to_screen(s.x1, s.y1))
            path.lineTo(board.to_screen(s.x2, s.y2))
            return path
        if s.is_path:
            pts = [board.to_screen(x, y) for x, y in s.path_points()]
            if pts:
                path.moveTo(pts[0])
                for q in pts[1:]:
                    path.lineTo(q)
            return path
        cx, cy = s.center()
        local = QPainterPath()
        r = QRectF(-s.w / 2, -s.h / 2, s.w, s.h)
        if s.is_ellipse:
            local.addEllipse(r)
        else:
            local.addRect(r)
        t = QTransform()
        t.translate(board.ox, board.oy)
        t.scale(board.zoom, board.zoom)
        t.translate(cx, cy)
        t.rotate(s.rotation)
        return t.map(local)

    def relook(self):
        """Work out the lines again; start or stop marching."""
        tg = self._target()
        outline = link = None
        clip = QRectF()
        if tg is not None:
            box, path = tg
            board = self.win.board
            vis = box.visibleRegion().boundingRect()
            if not vis.isEmpty() and board.isVisible():
                off = board.mapTo(self.win, board.rect().topLeft())
                outline = path.translated(off.x(), off.y())
                clip = QRectF(board.mapTo(self.win, board.rect().topLeft()), board.size().toSizeF())
                tl = box.mapTo(self.win, vis.topLeft())
                tr = QRectF(tl.x(), tl.y(), vis.width(), vis.height())
                link = self._route(outline, clip, tr)
        self._outline, self._link, self._board_clip = outline, link, clip
        self._light(tg[0] if link is not None else None)
        self._repaint()
        live = outline is not None and QApplication.applicationState() == Qt.ApplicationState.ApplicationActive
        if live and not self._t.isActive():
            self._t.start()
        elif not live:
            self._t.stop()

    def _light(self, box):
        """Blue border on the notes box the ants run into (theme: QPlainTextEdit[linked="true"]).
        Restyled only when the box changes."""
        if box is self._lit:
            return
        for w, on in ((self._lit, False), (box, True)):
            if w is not None:
                w.setProperty("linked", on)
                w.style().unpolish(w)
                w.style().polish(w)
                w.update()
        self._lit = box

    def _route(self, outline: QPainterPath, clip: QRectF, box: QRectF):
        """Right side of the outline, level with its middle -> right to the gap -> up / down -> into the
        box's left edge."""
        polys = outline.toSubpathPolygons()
        cy = outline.boundingRect().center().y()
        best = None
        for poly in polys:                          # where the level line through the middle meets the outline
            for a, b in zip(poly, list(poly)[1:]):
                if (a.y() - cy) * (b.y() - cy) <= 0 and a.y() != b.y():
                    x = a.x() + (cy - a.y()) * (b.x() - a.x()) / (b.y() - a.y())
                    if best is None or x > best.x():
                        best = QPointF(x, cy)
        if best is None:                            # a level line: its right end
            for poly in polys:
                for q in poly:
                    if best is None or q.x() > best.x() + 0.01:
                        best = q
        if best is None:
            return None
        inner = clip.adjusted(1, 1, -1, -1)
        if not inner.contains(best):               # the shape is scrolled out of the board: start at its edge
            best = QPointF(min(max(best.x(), inner.left()), inner.right()),
                           min(max(best.y(), inner.top()), inner.bottom()))
        col = self.win.right
        col_left = col.mapTo(self.win, col.rect().topLeft()).x()
        gx = (clip.right() + col_left) / 2 if col_left > clip.right() else box.left() - theme.px(8)
        ty = min(max(best.y(), box.top() + theme.px(14)), box.bottom() - theme.px(14))
        if box.height() < theme.px(28):
            ty = box.center().y()
        path = QPainterPath(best)
        path.lineTo(gx, best.y())
        path.lineTo(gx, ty)
        path.lineTo(box.left(), ty)
        return path

    def _strips(self) -> QRegion:
        """Thin rectangles along every line: the only area repainted each step."""
        reg = QRegion()
        for path in (self._outline, self._link):
            if path is None:
                continue
            for poly in path.toSubpathPolygons():
                for a, b in zip(poly, list(poly)[1:]):
                    r = QRectF(a, b).normalized().adjusted(-PAD, -PAD, PAD, PAD)
                    reg = reg.united(QRect(int(r.x()), int(r.y()), int(r.width()) + 1, int(r.height()) + 1))
        return reg

    def _repaint(self):
        new = self._strips()
        old, self._region = self._region, new
        dirty = old.united(new)
        if not dirty.isEmpty():
            if self.geometry() != self.win.rect():
                self.setGeometry(self.win.rect())
            self.raise_()
            self.update(dirty)

    def _step(self):
        self._phase = (self._phase - 1) % (2 * DASH)
        # positions follow the board (zoom, pan, panels scrolling) while marching
        self.relook()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, e):
        if self._outline is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 1.5
        under = QPen(QColor(255, 255, 255, 230), w)
        ants = QPen(QColor(theme.SEL), w)
        ants.setDashPattern([DASH, DASH])
        ants.setDashOffset(self._phase)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.save()
        p.setClipRect(self._board_clip)
        for pen in (under, ants):
            p.setPen(pen)
            p.drawPath(self._outline)
        p.restore()
        if self._link is not None:
            for pen in (under, ants):
                p.setPen(pen)
                p.drawPath(self._link)
            end = self._link.currentPosition()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.SEL))
            p.drawEllipse(end, 3, 3)
        p.end()
