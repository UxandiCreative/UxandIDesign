"""The board: a fixed-size canvas you zoom and pan, with shapes on it.

Mouse
  left            select, move, resize (handles), rotate (round handle above),
                  round corners (small inner handle), draw with the Rectangle / Line tool
  left on empty   selection box (Ctrl / Shift adds)
  right drag      pan (a right click without dragging opens the menu)
  middle drag     pan;  Space + left drag: pan
  wheel           zoom toward the cursor
Modifiers while dragging
  Shift  keep proportions / lock to one axis / 15 degree steps / 45 degree lines
  Alt    resize from the centre; Alt + drag a shape = drag a copy
  Ctrl   no snapping for this drag
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import (QPainter, QColor, QPen, QBrush, QPolygonF, QFont, QFontMetricsF,
                           QPixmap, QPainterPath, QCursor)
from PySide6.QtWidgets import QWidget, QLineEdit, QApplication

from . import theme
from .model import Shape, Page, rot_pt, union_box, norm_deg, fits, push_inside, clamp_pt, grid_fit, simplify
from .snapping import Snapper, SnapResult, Gap
from . import images
from .images import image_of

DRAG_MODES = ("move", "resize", "gresize", "rotate", "draw_rect", "draw_line", "line_end")
HANDLES = [(-1, -1), (1, -1), (1, 1), (-1, 1), (0, -1), (1, 0), (0, 1), (-1, 0)]
DASH = {"solid": Qt.PenStyle.SolidLine, "dash": Qt.PenStyle.DashLine, "dot": Qt.PenStyle.DotLine}
CAP = {"round": Qt.PenCapStyle.RoundCap, "flat": Qt.PenCapStyle.FlatCap, "square": Qt.PenCapStyle.SquareCap}


# ----------------------------------------------------------------------------- painting shapes
def paint_shape(p: QPainter, s: Shape) -> None:
    """Draw one shape in canvas coordinates."""
    if s.is_line:
        if s.stroke_width <= 0:
            return
        pen = QPen(QColor(s.stroke), s.stroke_width)
        pen.setStyle(DASH.get(s.line_style, Qt.PenStyle.SolidLine))
        pen.setCapStyle(CAP.get(s.cap, Qt.PenCapStyle.RoundCap))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(s.x1, s.y1), QPointF(s.x2, s.y2))
        return
    if s.is_path:
        _paint_path(p, s)
        return
    p.save()
    cx, cy = s.center()
    p.translate(cx, cy)
    p.rotate(s.rotation)
    sw = max(0.0, min(s.stroke_width, min(s.w, s.h) / 2))
    R = max(0.0, min(s.radius, s.max_radius()))
    outer = QRectF(-s.w / 2, -s.h / 2, s.w, s.h)
    oval = s.is_ellipse
    # 1 fill, 2 picture (inside the border), 3 border on top
    if s.fill:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(s.fill))
        if oval:
            p.drawEllipse(outer)
        else:
            p.drawRoundedRect(outer, R, R) if R > 0 else p.drawRect(outer)
    img = image_of(s)
    if img:
        _paint_image(p, s, img, outer.adjusted(sw, sw, -sw, -sw), max(0.0, R - sw), oval)
    if sw > 0:
        pen = QPen(QColor(s.stroke), sw)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = outer.adjusted(sw / 2, sw / 2, -sw / 2, -sw / 2)
        rad = max(0.0, R - sw / 2)
        if oval:
            p.drawEllipse(r)
        else:
            p.drawRoundedRect(r, rad, rad) if rad > 0 else p.drawRect(r)
    p.restore()


def stroke_path(pts) -> QPainterPath:
    """A smooth curve through freehand points (midpoint quadratic smoothing)."""
    path = QPainterPath()
    if not pts:
        return path
    path.moveTo(QPointF(*pts[0]))
    if len(pts) < 3:
        for x, y in pts[1:]:
            path.lineTo(QPointF(x, y))
        return path
    for i in range(1, len(pts) - 1):
        mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
        path.quadTo(QPointF(*pts[i]), QPointF(mx, my))
    path.lineTo(QPointF(*pts[-1]))
    return path


def _paint_path(p: QPainter, s: Shape) -> None:
    if s.stroke_width <= 0 or not s.points:
        return
    pen = QPen(QColor(s.stroke), s.stroke_width)
    pen.setStyle(DASH.get(s.line_style, Qt.PenStyle.SolidLine))
    pen.setCapStyle(CAP.get(s.cap, Qt.PenCapStyle.RoundCap))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.save()
    cx, cy = s.center()
    p.translate(cx, cy)
    p.rotate(s.rotation)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pts = s.path_local()
    if len(pts) == 1:
        p.drawPoint(QPointF(*pts[0]))
    else:
        p.drawPath(stroke_path(pts))
    p.restore()


def image_rect(s: Shape, img: dict, inner: QRectF, iw: float, ih: float) -> QRectF:
    """Where the picture lands, in the shape's own (centred, unrotated) coordinates."""
    bw, bh = max(1e-6, inner.width()), max(1e-6, inner.height())
    fit = img.get("fit", "fill")
    z = float(img.get("zoom", 1.0) or 1.0)
    if fit == "stretch":
        tw, th = bw * z, bh * z
    elif fit == "original":
        tw, th = iw * z, ih * z
    else:
        k = (max if fit == "fill" else min)(bw / iw, bh / ih) * z
        tw, th = iw * k, ih * k
    c = inner.center()
    dx, dy = float(img.get("dx", 0.0)), float(img.get("dy", 0.0))
    return QRectF(c.x() + dx - tw / 2, c.y() + dy - th / 2, tw, th)


def _paint_image(p: QPainter, s: Shape, img: dict, inner: QRectF, rad: float, oval: bool = False):
    if inner.width() <= 0 or inner.height() <= 0:
        return
    path = QPainterPath()
    if oval:
        path.addEllipse(inner)
    else:
        path.addRoundedRect(inner, rad, rad)
    p.save()
    p.setClipPath(path, Qt.ClipOperation.IntersectClip)
    pm = images.pixmap(img.get("path", ""))
    if pm is None:      # the file is missing: grey box with a cross
        p.fillRect(inner, QColor(0, 0, 0, 20))
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.drawLine(inner.topLeft(), inner.bottomRight())
        p.drawLine(inner.topRight(), inner.bottomLeft())
        p.restore()
        return
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    if s.flip_h or s.flip_v:
        p.scale(-1 if s.flip_h else 1, -1 if s.flip_v else 1)
    p.setOpacity(p.opacity() * max(0.0, min(1.0, float(img.get("opacity", 1.0)))))
    p.drawPixmap(image_rect(s, img, inner, pm.width(), pm.height()), pm, QRectF(0, 0, pm.width(), pm.height()))
    p.restore()


def render_thumb(page: Page, height: int, max_width: int) -> QPixmap:
    sc = min(height / page.height, max_width / page.width)
    w, h = max(1, round(page.width * sc)), max(1, round(page.height * sc))
    dpr = 2.0
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(QColor(page.background))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(sc, sc)
    p.setClipRect(QRectF(0, 0, page.width, page.height))
    for s in page.shapes:
        paint_shape(p, s)
    p.end()
    return pm


def _dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


# ----------------------------------------------------------------------------- the board widget
class Board(QWidget):
    tool_changed = Signal(str)
    shape_clicked = Signal()          # a shape was clicked on the canvas (the window opens its tabs)
    zoom_changed = Signal(float)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(200, 150)
        self.zoom = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self._views: dict[str, tuple[float, float, float]] = {}
        self._need_fit = True
        self.tool = "select"
        self.mode = None
        self.hover = None
        self.guides: list = []
        self.gaps: list[Gap] = []
        self.marquee = None
        self.drag_label = None
        self.preview: Shape | None = None
        self.show_names = True
        self.show_helpers = True       # faint blue canvas centre lines while dragging
        self.space = False
        self.menu_provider = None      # callable(global_pos, shape | None, canvas_point)
        self._label_rects: list[tuple[str, QRectF]] = []
        self._rename: QLineEdit | None = None
        self._rename_id = None
        self._press = None
        self.hover_pill = None
        self._pills = []
        self.img_drag = False          # Design > Image > Drag image: dragging moves the picture inside its shape
        self.group_menu = None         # callable(global_pos, group id)
        self.group_rename = None       # callable(group id)
        doc.changed.connect(self.update)
        doc.structure.connect(self.update)
        doc.selection_changed.connect(self.update)
        doc.page_changed.connect(self._page_changed)

    # ------------------------------------------------------------------ view
    @property
    def page(self) -> Page:
        return self.doc.page

    def to_screen(self, x: float, y: float) -> QPointF:
        return QPointF(self.ox + x * self.zoom, self.oy + y * self.zoom)

    def to_canvas(self, pt: QPointF) -> tuple[float, float]:
        return (pt.x() - self.ox) / self.zoom, (pt.y() - self.oy) / self.zoom

    def fit(self) -> None:
        m = theme.px(36)
        pw, ph = self.page.width, self.page.height
        W, H = max(1, self.width() - 2 * m), max(1, self.height() - 2 * m)
        self.zoom = max(0.02, min(W / pw, H / ph))
        self.ox = (self.width() - pw * self.zoom) / 2
        self.oy = (self.height() - ph * self.zoom) / 2
        self._remember()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def set_zoom(self, z: float, anchor: QPointF | None = None) -> None:
        z = max(0.02, min(16.0, z))
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        cx, cy = self.to_canvas(anchor)
        self.zoom = z
        self.ox = anchor.x() - cx * z
        self.oy = anchor.y() - cy * z
        self._remember()
        self.zoom_changed.emit(self.zoom)
        self.update()

    def _remember(self):
        self._views[self.page.id] = (self.zoom, self.ox, self.oy)

    def _page_changed(self):
        self.cancel_rename()
        v = self._views.get(self.page.id)
        if v:
            self.zoom, self.ox, self.oy = v
            self.zoom_changed.emit(self.zoom)
            self.update()
        else:
            self.fit()

    def view_center_canvas(self) -> tuple[float, float]:
        return self.to_canvas(QPointF(self.width() / 2, self.height() / 2))

    def resizeEvent(self, e):
        old = e.oldSize()
        if self._need_fit or old.width() <= 0:
            self._need_fit = False
            self.fit()
            return
        # keep the point that was in the middle in the middle
        cx, cy = (old.width() / 2 - self.ox) / self.zoom, (old.height() / 2 - self.oy) / self.zoom
        self.ox = self.width() / 2 - cx * self.zoom
        self.oy = self.height() / 2 - cy * self.zoom
        self._remember()

    def set_tool(self, t: str) -> None:
        if t != self.tool:
            self.tool = t
            self.tool_changed.emit(t)
        self.setCursor(Qt.CursorShape.CrossCursor if t in ("rect", "ellipse", "line", "draw") else Qt.CursorShape.ArrowCursor)

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rad = theme.px(8)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(theme.STAGE))
        page = self.page
        z = self.zoom
        crect = QRectF(self.ox, self.oy, page.width * z, page.height * z)
        # shadow + paper
        for i, a in ((6, 10), (3, 18), (1, 30)):
            p.fillRect(crect.adjusted(-i, -i + 2, i, i + 2), QColor(0, 0, 0, a))
        p.fillRect(crect, QColor(page.background))
        if page.dots:
            self._paint_dots(p, crect)
        if page.show_margins and any(page.margins):
            l, t, r, b = page.safe_rect()
            band = QPainterPath(); band.addRect(crect)
            inner = QPainterPath(); inner.addRect(QRectF(self.to_screen(l, t), self.to_screen(r, b)))
            p.fillPath(band.subtracted(inner), QColor(31, 111, 235, 14))
        # shapes: faint outside the canvas, full strength inside
        p.save()
        p.translate(self.ox, self.oy)
        p.scale(z, z)
        p.setOpacity(0.28)
        for s in page.shapes:
            paint_shape(p, s)
        p.setOpacity(1.0)
        p.setClipRect(QRectF(0, 0, page.width, page.height), Qt.ClipOperation.IntersectClip)
        for s in page.shapes:
            paint_shape(p, s)
        if self.preview:
            paint_shape(p, self.preview)
        p.restore()
        p.setClipPath(clip)
        self._paint_overlay(p)
        # frame
        p.setClipping(False)
        p.setPen(QPen(QColor(0, 0, 0, 36), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), rad, rad)
        p.end()

    def _paint_dots(self, p: QPainter, crect: QRectF):
        sp = max(1, self.page.dot_spacing)
        step = sp
        while step * self.zoom < 9:
            step *= 2
        vis = crect.intersected(QRectF(self.rect()))
        if vis.isEmpty():
            return
        x0, y0 = self.to_canvas(vis.topLeft())
        x1, y1 = self.to_canvas(vis.bottomRight())
        i0, i1 = math.ceil(x0 / step), math.floor(x1 / step)
        j0, j1 = math.ceil(y0 / step), math.floor(y1 / step)
        if (i1 - i0 + 1) * (j1 - j0 + 1) > 120000:
            return
        pen = QPen(QColor(theme.DOT), max(1.6, min(3.0, 0.12 * step * self.zoom)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        pts = []
        for j in range(j0, j1 + 1):
            y = self.oy + j * step * self.zoom
            for i in range(i0, i1 + 1):
                pts.append(QPointF(self.ox + i * step * self.zoom, y))
        p.drawPoints(pts)

    def _outline(self, p: QPainter, s: Shape) -> None:
        """Draw a shape's outline on screen: a line, the stroke of a freehand path, or the box."""
        if s.is_line:
            p.drawLine(self.to_screen(s.x1, s.y1), self.to_screen(s.x2, s.y2))
        elif s.is_path:
            p.drawPath(stroke_path([(q.x(), q.y()) for q in (self.to_screen(x, y) for x, y in s.path_points())]))
        else:
            p.drawPolygon(self._poly(s))

    def _poly(self, s: Shape) -> QPolygonF:
        return QPolygonF([self.to_screen(x, y) for x, y in s.corners()])

    def _paint_overlay(self, p: QPainter):
        page = self.page
        sel = self.doc.selected()
        sel_ids = {s.id for s in sel}
        blue = QColor(theme.SEL)
        S = theme.S
        # margins: light blue see-through line
        if page.show_margins and any(page.margins):
            l, t, r, b = page.safe_rect()
            p.setPen(QPen(QColor(77, 163, 255, 170), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(self.to_screen(l, t), self.to_screen(r, b)))
        # faint blue helper lines while dragging: canvas centre lines (and edges)
        if self.show_helpers and self.mode in DRAG_MODES:
            self._paint_helpers(p, sel)
        # hover
        if self.hover and self.hover not in sel_ids and self.mode is None:
            hs = page.get(self.hover)
            if hs:
                p.setPen(QPen(blue, 1.5)); p.setBrush(Qt.BrushStyle.NoBrush)
                self._outline(p, hs)
        # names
        self._label_rects = []
        if self.show_names:
            self._paint_names(p, sel_ids)
        # selection outlines + handles
        if sel and self.mode not in ("draw_rect", "draw_line", "draw_path"):
            p.setBrush(Qt.BrushStyle.NoBrush)
            for s in sel:
                p.setPen(QPen(blue, 1.5))
                self._outline(p, s)
            if len(sel) > 1:
                b = union_box(s.aabb() for s in sel)
                pen = QPen(blue, 1.2); pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.drawRect(QRectF(self.to_screen(b[0], b[1]), self.to_screen(b[2], b[3])))
            if self.mode in (None, "pending", "resize", "gresize", "radius", "line_end"):
                self._paint_handles(p)
        # alignment: see-through blue lines across the canvas wherever the dragged
        # shape's edges or middle line up with another shape's edges or middle
        W, H = page.width, page.height
        see = QColor(theme.SEL); see.setAlpha(120)
        if self.show_helpers and self.mode in DRAG_MODES:
            xs, ys = self._alignments(sel)
            p.setPen(QPen(see, 1))
            for x in xs:
                p.drawLine(self.to_screen(x, 0), self.to_screen(x, H))
            for y in ys:
                p.drawLine(self.to_screen(0, y), self.to_screen(W, y))
        # snap guides (same see-through blue) and gap markers (pink, with the distance)
        p.setPen(QPen(see, 1))
        for (x1, y1, x2, y2) in self.guides:
            p.drawLine(self.to_screen(x1, y1), self.to_screen(x2, y2))
        for g in self.gaps:
            self._paint_gap(p, g)
        # selection box
        if self.marquee:
            r = QRectF(self.to_screen(*self.marquee[:2]), self.to_screen(*self.marquee[2:])).normalized()
            p.setPen(QPen(blue, 1)); p.setBrush(QColor(31, 111, 235, 28))
            p.drawRect(r)
        # live size / position
        if self.drag_label:
            text, anchor = self.drag_label
            self._pill(p, text, anchor, blue, below=True)
        # group members of the hovered pill
        if self.hover_pill and self.hover_pill != "add":
            g = page.get_group(self.hover_pill)
            if g:
                pen = QPen(QColor(theme.ACCENT), 2); pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen); p.setBrush(QColor(11, 122, 75, 22))
                for sid in g["members"]:
                    s = page.get(sid)
                    if s:
                        self._outline(p, s)
        self._paint_pills(p)

    def _alignments(self, sel):
        """x and y values where the dragged box lines up with another shape or the canvas centre."""
        if self.preview:
            boxes = [self.preview.aabb()]
            skip = set()
        elif sel:
            boxes = [s.aabb() for s in sel]
            if len(boxes) > 1:
                boxes.append(union_box(boxes))
            skip = {s.id for s in sel}
        else:
            return [], []
        mine_x = [v for b in boxes for v in (b[0], (b[0] + b[2]) / 2, b[2])]
        mine_y = [v for b in boxes for v in (b[1], (b[1] + b[3]) / 2, b[3])]
        cand_x, cand_y = [], []
        for o in self.page.shapes:
            if o.id in skip:
                continue
            ob = o.aabb()
            cand_x += [ob[0], (ob[0] + ob[2]) / 2, ob[2]]
            cand_y += [ob[1], (ob[1] + ob[3]) / 2, ob[3]]
        W, H = self.page.width, self.page.height
        cand_x.append(W / 2); cand_y.append(H / 2)
        xs = sorted({round(v, 3) for v in cand_x if any(abs(v - m) < 0.5 for m in mine_x)})
        ys = sorted({round(v, 3) for v in cand_y if any(abs(v - m) < 0.5 for m in mine_y)})
        return xs, ys

    # ------------------------------------------------------------------ group pills (bottom-left, fixed)
    def _pill_font(self):
        f = QFont(self.font()); f.setPixelSize(theme.px(12)); f.setWeight(QFont.Weight.DemiBold)
        return f

    def pill_layout(self):
        """[(kind, group id, QRectF, text)], from the bottom-left corner, wrapping upwards."""
        fm = QFontMetricsF(self._pill_font())
        h, gap, m, pad = theme.px(26), theme.px(6), theme.px(12), theme.px(12)
        items = [("add", "add", "+ Group")]
        for g in self.page.groups:
            items.append(("group", g["id"], f"{g['name']}  ·  {len(g['members'])}"))
        out = []
        x, y = m, self.height() - m - h
        for kind, gid, text in items:
            w = fm.horizontalAdvance(text) + 2 * pad
            if x + w > self.width() - m and x > m:
                x, y = m, y - h - gap
            out.append((kind, gid, QRectF(x, y, w, h), text))
            x += w + gap
        self._pills = out
        return out

    def pill_at(self, pos: QPointF):
        for kind, gid, r, _ in self._pills:
            if r.contains(pos):
                return kind, gid
        return None

    def _paint_pills(self, p: QPainter):
        p.setFont(self._pill_font())
        sel = set(self.doc.selection)
        for kind, gid, r, text in self.pill_layout():
            rad = r.height() / 2
            hov = self.hover_pill == gid
            if kind == "add":
                ok = bool(sel)
                pen = QPen(QColor(theme.ACCENT) if (ok or hov) else QColor(0, 0, 0, 66), 1.5)
                pen.setStyle(Qt.PenStyle.DashLine)
                p.setPen(pen)
                p.setBrush(QColor(theme.ACCENT_BG) if hov and ok else QColor(theme.SURFACE))
                p.drawRoundedRect(r, rad, rad)
                p.setPen(QColor(theme.ACCENT) if ok else QColor(theme.MUTE))
            else:
                g = self.page.get_group(gid)
                active = g is not None and set(g["members"]) == sel
                part = g is not None and not active and bool(sel & set(g["members"]))
                if active:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(theme.ACCENT))
                else:
                    p.setPen(QPen(QColor(theme.ACCENT) if (hov or part) else QColor(0, 0, 0, 66), 1.2))
                    p.setBrush(QColor(theme.ACCENT_BG) if hov else QColor(theme.SURFACE))
                p.drawRoundedRect(r, rad, rad)
                p.setPen(QColor("#FFFFFF") if active else QColor(theme.TEXT))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _pill_click(self, kind, gid, mods):
        if kind == "add":
            self.doc.group_selection()
        else:
            self.doc.select_group(gid, add=bool(mods & Qt.KeyboardModifier.ShiftModifier))
        self.update()

    def _paint_helpers(self, p: QPainter, sel):
        page = self.page
        W, H = page.width, page.height
        faint = QColor(theme.HINT_LINE); faint.setAlpha(70)
        pen = QPen(faint, 1); pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(self.to_screen(W / 2, 0), self.to_screen(W / 2, H))
        p.drawLine(self.to_screen(0, H / 2), self.to_screen(W, H / 2))
        # the dragged thing's own centre lines across the canvas, very faint
        box = None
        if self.preview:
            box = self.preview.aabb()
        elif sel:
            box = union_box(s.aabb() for s in sel)
        if box:
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            f2 = QColor(theme.HINT_LINE); f2.setAlpha(38)
            p.setPen(QPen(f2, 1))
            p.drawLine(self.to_screen(cx, 0), self.to_screen(cx, H))
            p.drawLine(self.to_screen(0, cy), self.to_screen(W, cy))
            # centre mark of the dragged box
            c = self.to_screen(cx, cy)
            k = theme.px(4)
            f3 = QColor(theme.HINT_LINE); f3.setAlpha(150)
            p.setPen(QPen(f3, 1))
            p.drawLine(QPointF(c.x() - k, c.y()), QPointF(c.x() + k, c.y()))
            p.drawLine(QPointF(c.x(), c.y() - k), QPointF(c.x(), c.y() + k))

    def _paint_names(self, p: QPainter, sel_ids):
        f = QFont(self.font()); f.setPixelSize(theme.px(11)); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        fm = QFontMetricsF(f)
        hgt = fm.height() + theme.px(2)
        for s in self.page.shapes:
            if not s.name or s.id not in sel_ids:      # names show only on selected shapes
                continue
            b = s.aabb()
            tl = self.to_screen(b[0], b[1])
            wmax = max(theme.px(60), (b[2] - b[0]) * self.zoom)
            text = fm.elidedText(s.name, Qt.TextElideMode.ElideRight, wmax)
            tw = fm.horizontalAdvance(text) + theme.px(10)
            r = QRectF(tl.x(), tl.y() - hgt - theme.px(3), tw, hgt)
            if s.id == self._rename_id:
                continue
            if s.id in sel_ids:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(theme.ACCENT))
                p.drawRoundedRect(r, 3, 3)
                p.setPen(QColor("#FFFFFF"))
            else:
                p.setPen(QColor(theme.MUTE))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
            self._label_rects.append((s.id, r))

    def _pill(self, p: QPainter, text: str, anchor: QPointF, color: QColor, below=False):
        f = QFont(self.font()); f.setPixelSize(theme.px(11)); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        fm = QFontMetricsF(f)
        w = fm.horizontalAdvance(text) + theme.px(12)
        h = fm.height() + theme.px(4)
        y = anchor.y() + theme.px(8) if below else anchor.y() - h / 2
        r = QRectF(anchor.x() - w / 2, y, w, h)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(color)
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_gap(self, p: QPainter, g: Gap):
        col = QColor(theme.SNAP)
        p.setPen(QPen(col, 1))
        k = theme.px(4)
        if g.axis == 0:
            a, b = self.to_screen(g.a, g.cross), self.to_screen(g.b, g.cross)
            p.drawLine(a, b)
            p.drawLine(QPointF(a.x(), a.y() - k), QPointF(a.x(), a.y() + k))
            p.drawLine(QPointF(b.x(), b.y() - k), QPointF(b.x(), b.y() + k))
        else:
            a, b = self.to_screen(g.cross, g.a), self.to_screen(g.cross, g.b)
            p.drawLine(a, b)
            p.drawLine(QPointF(a.x() - k, a.y()), QPointF(a.x() + k, a.y()))
            p.drawLine(QPointF(b.x() - k, b.y()), QPointF(b.x() + k, b.y()))
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        self._pill(p, f"{abs(g.b - g.a):g}" if abs(g.b - g.a) % 1 else f"{int(round(abs(g.b - g.a)))}", mid, col)

    def _paint_handles(self, p: QPainter):
        blue = QColor(theme.SEL)
        hs = theme.px(9)
        for kind, data, pt in self.handles():
            if kind == "rot":
                base = data
                p.setPen(QPen(blue, 1.5)); p.drawLine(base, pt)
                p.setBrush(blue); p.setPen(QPen(QColor("#FFFFFF"), 1.5))
                p.drawEllipse(pt, hs * 0.62, hs * 0.62)
            elif kind == "radius":
                p.setBrush(QColor("#FFFFFF")); p.setPen(QPen(QColor(theme.SNAP), 1.5))
                p.drawEllipse(pt, hs * 0.42, hs * 0.42)
            elif kind == "end":
                p.setBrush(QColor("#FFFFFF")); p.setPen(QPen(blue, 1.5))
                p.drawEllipse(pt, hs * 0.55, hs * 0.55)
            else:
                p.setBrush(QColor("#FFFFFF")); p.setPen(QPen(blue, 1.5))
                p.drawRect(QRectF(pt.x() - hs / 2, pt.y() - hs / 2, hs, hs))

    # ------------------------------------------------------------------ handles
    def handles(self):
        """[(kind, data, screen point)] for the current selection."""
        sel = self.doc.selected()
        out = []
        if not sel:
            return out
        S = theme.S
        if len(sel) == 1 and sel[0].is_line:
            s = sel[0]
            out.append(("end", 0, self.to_screen(s.x1, s.y1)))
            out.append(("end", 1, self.to_screen(s.x2, s.y2)))
            return out
        if len(sel) == 1:
            s = sel[0]
            cx, cy = s.center()
            sw, sh = s.w * self.zoom, s.h * self.zoom
            for hx, hy in HANDLES:
                if (hx == 0 and sw < 30 * S) or (hy == 0 and sh < 30 * S):
                    continue
                x, y = rot_pt(cx + hx * s.w / 2, cy + hy * s.h / 2, cx, cy, s.rotation)
                out.append(("resize", (hx, hy), self.to_screen(x, y)))
            tx, ty = rot_pt(cx, cy - s.h / 2, cx, cy, s.rotation)
            base = self.to_screen(tx, ty)
            a = math.radians(s.rotation)
            d = theme.px(26)
            out.append(("rot", base, QPointF(base.x() + math.sin(a) * d, base.y() - math.cos(a) * d)))
            if sw > 56 * S and sh > 56 * S and s.kind == "rect":
                inset = max(min(s.radius, s.max_radius()), theme.px(14) / self.zoom)
                inset = min(inset, s.max_radius())
                x, y = rot_pt(cx - s.w / 2 + inset, cy - s.h / 2 + inset, cx, cy, s.rotation)
                out.append(("radius", None, self.to_screen(x, y)))
            return out
        b = union_box(s.aabb() for s in sel)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        bw, bh = (b[2] - b[0]) * self.zoom, (b[3] - b[1]) * self.zoom
        for hx, hy in HANDLES:
            if (hx == 0 and bw < 30 * S) or (hy == 0 and bh < 30 * S):
                continue
            out.append(("gresize", (hx, hy), self.to_screen(cx + hx * (b[2] - b[0]) / 2, cy + hy * (b[3] - b[1]) / 2)))
        base = self.to_screen(cx, b[1])
        out.append(("rot", base, QPointF(base.x(), base.y() - theme.px(26))))
        return out

    def handle_at(self, pos: QPointF):
        r = theme.px(8)
        best = None
        for h in self.handles():
            d = _dist(h[2], pos)
            if d <= r and (best is None or d < best[0]):
                best = (d, h)
        return best[1] if best else None

    def shape_at(self, pos: QPointF) -> Shape | None:
        x, y = self.to_canvas(pos)
        tol = theme.px(4) / self.zoom
        for sid, r in reversed(self._label_rects):
            if r.contains(pos):
                return self.page.get(sid)
        for s in reversed(self.page.shapes):
            if s.contains(x, y, tol):
                return s
        return None

    def _cursor_for(self, h):
        kind = h[0]
        if kind == "rot":
            return Qt.CursorShape.PointingHandCursor
        if kind in ("radius", "end"):
            return Qt.CursorShape.CrossCursor
        hx, hy = h[1]
        rot = 0.0
        sel = self.doc.selected()
        if kind == "resize" and sel:
            rot = sel[0].rotation
        ang = (math.degrees(math.atan2(hy, hx)) + rot) % 180
        if ang < 22.5 or ang >= 157.5:
            return Qt.CursorShape.SizeHorCursor
        if ang < 67.5:
            return Qt.CursorShape.SizeFDiagCursor
        if ang < 112.5:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.SizeBDiagCursor

    # ------------------------------------------------------------------ helpers
    def _snapper(self, exclude, mods=None) -> Snapper:
        mods = QApplication.keyboardModifiers() if mods is None else mods
        enabled = not (mods & Qt.KeyboardModifier.ControlModifier)
        return Snapper(self.page, set(exclude), self.doc.snap, self.zoom, enabled)

    @property
    def grid_on(self) -> bool:
        return bool(self.doc.snap.grid) and not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)

    def gsize(self) -> float:
        return float(max(1, self.page.dot_spacing))

    def lim(self):
        """The margin box shapes must stay in (None = anywhere). With dot snapping on it
        shrinks to the last dots inside the margin lines."""
        lim = self.page.limits()
        if lim and self.doc.snap.grid:
            g = self.gsize()
            L, T = math.ceil(lim[0] / g - 1e-9) * g, math.ceil(lim[1] / g - 1e-9) * g
            R, B = math.floor(lim[2] / g + 1e-9) * g, math.floor(lim[3] / g + 1e-9) * g
            if R - L >= g and B - T >= g:
                lim = (L, T, R, B)
        return lim

    def fit_grid(self, shapes):
        """Dot snapping on: put every shape on the dots."""
        if not self.doc.snap.grid:
            return
        g = self.gsize()
        for s in shapes:
            grid_fit(s, g)

    def _limits(self, orig=None):
        """The margin box, or None. When the shapes being changed started outside it,
        they are not trapped (None) so they can still be edited."""
        lim = self.lim()
        if lim and orig:
            b0 = union_box(o.aabb() for o in orig.values())
            if b0 and not fits(b0, lim):
                return None
        return lim

    def _hold_inside(self, orig):
        """After a resize / rotate: if the shapes went past the margins, go back along
        the way from the start to the furthest point that still fits."""
        lim = self._limits(orig)
        if not lim:
            return
        shapes = {sid: self.page.get(sid) for sid in orig}
        shapes = {k: v for k, v in shapes.items() if v}
        cur = union_box(s.aabb() for s in shapes.values())
        if cur is None or fits(cur, lim):
            return
        target = {sid: s.clone(fresh_id=False) for sid, s in shapes.items()}
        keys = ("x", "y", "w", "h", "x1", "y1", "x2", "y2")

        def at(t):
            for sid, s in shapes.items():
                o, g = orig[sid], target[sid]
                for k in keys:
                    setattr(s, k, getattr(o, k) + (getattr(g, k) - getattr(o, k)) * t)
                if not s.is_line:
                    s.rotation = norm_deg(o.rotation + norm_deg(g.rotation - o.rotation) * t)

        lo, hi = 0.0, 1.0
        for _ in range(22):
            mid = (lo + hi) / 2
            at(mid)
            if fits(union_box(s.aabb() for s in shapes.values()), lim):
                lo = mid
            else:
                hi = mid
        at(lo)
        for s in shapes.values():
            if s.is_line:
                s.x1, s.y1, s.x2, s.y2 = (round(v, 3) for v in (s.x1, s.y1, s.x2, s.y2))
            else:
                s.x, s.y, s.w, s.h = (round(v, 3) for v in (s.x, s.y, s.w, s.h))
                if self.doc.snap.pixel and abs(norm_deg(s.rotation)) < 1e-6:
                    s.x, s.y = round(s.x), round(s.y)
                    s.w, s.h = max(1.0, float(round(s.w))), max(1.0, float(round(s.h)))
        b = union_box(s.aabb() for s in shapes.values())
        dx, dy = push_inside(b, lim)
        for s in shapes.values():
            s.translate(dx, dy)

    def _grid_after(self, pr):
        shapes = [s for s in (self.page.get(i) for i in pr["orig"]) if s]
        if self.grid_on:
            self.fit_grid(shapes)
        self._hold_inside(pr["orig"])
        if self.grid_on:
            self.fit_grid(shapes)

    def _rnd(self, v: float) -> float:
        return float(round(v)) if self.doc.snap.pixel else v

    def _set_snap(self, res: SnapResult | None):
        self.guides = res.guides if res else []
        self.gaps = res.gaps if res else []

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        self.setFocus()
        pos = e.position()
        btn = e.button()
        mods = e.modifiers()
        self.cancel_rename()
        hit = self.pill_at(pos)
        if hit and not self.space:
            kind, gid = hit
            if btn == Qt.MouseButton.LeftButton:
                self._pill_click(kind, gid, mods)
            elif btn == Qt.MouseButton.RightButton and kind == "group" and self.group_menu:
                self.group_menu(e.globalPosition().toPoint(), gid)
            return
        if btn in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton) or (btn == Qt.MouseButton.LeftButton and self.space):
            self.mode = "pan"
            self._press = {"pos": pos, "ox": self.ox, "oy": self.oy, "btn": btn, "moved": False}
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if btn != Qt.MouseButton.LeftButton:
            return
        cx, cy = self.to_canvas(pos)
        if self.tool == "draw":          # freehand: every point as drawn, no snapping
            x, y = clamp_pt(cx, cy, (0, 0, self.page.width, self.page.height))
            self.mode = "draw_path"
            self._press = {"pos": pos, "pts": [(x, y)]}
            self.preview = None
            return
        if self.tool in ("rect", "ellipse", "line"):
            sn = self._snapper([], mods)
            x, y, res = sn.snap_point(cx, cy)
            x, y = clamp_pt(self._rnd(x), self._rnd(y), self.lim())
            self._set_snap(res)
            self.mode = "draw_line" if self.tool == "line" else "draw_rect"
            self._press = {"pos": pos, "p0": (x, y), "kind": "ellipse" if self.tool == "ellipse" else "rect"}
            self.preview = None
            return
        if self.img_drag:
            s = self.shape_at(pos)
            if s and image_of(s):
                if s.id not in self.doc.selection:
                    self.doc.set_selection([s.id])
                img = image_of(s)
                self.mode = "imgpan"
                self._press = {"pos": pos, "c": (cx, cy), "sid": s.id,
                               "dx": float(img.get("dx", 0)), "dy": float(img.get("dy", 0))}
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        h = self.handle_at(pos)
        if h:
            self._start_handle(h, pos)
            return
        s = self.shape_at(pos)
        add = bool(mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        if s:
            if add:
                ids = list(self.doc.selection)
                if s.id in ids:
                    ids.remove(s.id)
                    self.doc.set_selection(ids)
                    self.mode = None
                    return
                ids.append(s.id)
                self.doc.set_selection(ids)
            elif s.id not in self.doc.selection:
                self.doc.set_selection([s.id])
            self.shape_clicked.emit()
            self.mode = "pending"
            self._press = {"pos": pos, "c": (cx, cy), "alt": bool(mods & Qt.KeyboardModifier.AltModifier)}
            return
        # empty: selection box
        self.mode = "marquee"
        self._press = {"pos": pos, "c": (cx, cy), "base": list(self.doc.selection) if add else []}
        if not add:
            self.doc.set_selection([])
        self.marquee = (cx, cy, cx, cy)

    def _start_handle(self, h, pos):
        kind = h[0]
        sel = self.doc.selected()
        orig = {s.id: s.clone(fresh_id=False) for s in sel}
        cx, cy = self.to_canvas(pos)
        self._press = {"pos": pos, "c": (cx, cy), "orig": orig, "h": h}
        if kind == "resize":
            self.mode = "resize"
        elif kind == "gresize":
            self.mode = "gresize"
            self._press["box"] = union_box(s.aabb() for s in orig.values())
        elif kind == "rot":
            self.mode = "rotate"
            if len(sel) == 1:
                piv = sel[0].center()
            else:
                b = union_box(s.aabb() for s in orig.values())
                piv = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
            self._press["pivot"] = piv
            self._press["a0"] = math.degrees(math.atan2(cy - piv[1], cx - piv[0]))
        elif kind == "radius":
            self.mode = "radius"
        elif kind == "end":
            self.mode = "line_end"

    def mouseMoveEvent(self, e):
        pos = e.position()
        mods = e.modifiers()
        if self.mode is None:
            self._hover(pos)
            return
        pr = self._press
        if self.mode == "pan":
            if _dist(pos, pr["pos"]) > 3:
                pr["moved"] = True
            self.ox = pr["ox"] + pos.x() - pr["pos"].x()
            self.oy = pr["oy"] + pos.y() - pr["pos"].y()
            self._remember()
            self.update()
            return
        cx, cy = self.to_canvas(pos)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        if self.mode == "pending":
            if _dist(pos, pr["pos"]) < 3:
                return
            if pr.get("alt"):
                copies = [s.clone() for s in self.doc.selected()]
                for c in copies:
                    c.name = c.name + " copy" if c.name else c.name
                self.doc.page.shapes.extend(copies)
                self.doc.selection = [c.id for c in copies]
                self.doc.structure.emit()
                self.doc.selection_changed.emit()
                pr["dup"] = True
            pr["orig"] = {s.id: s.clone(fresh_id=False) for s in self.doc.selected()}
            pr["box"] = union_box(s.aabb() for s in pr["orig"].values())
            self.mode = "move"
        if self.mode == "move":
            self._do_move(cx, cy, shift, mods)
        elif self.mode == "resize":
            self._do_resize(cx, cy, shift, alt, mods)
        elif self.mode == "gresize":
            self._do_gresize(cx, cy, shift, alt, mods)
        elif self.mode == "rotate":
            self._do_rotate(cx, cy, shift)
        elif self.mode == "radius":
            self._do_radius(cx, cy)
        elif self.mode == "line_end":
            self._do_line_end(cx, cy, shift, mods)
        elif self.mode == "imgpan":
            s = self.page.get(pr["sid"])
            img = image_of(s) if s else None
            if img:
                ddx, ddy = cx - pr["c"][0], cy - pr["c"][1]
                lx, ly = rot_pt(ddx, ddy, 0, 0, -s.rotation)
                if s.flip_h:
                    lx = -lx
                if s.flip_v:
                    ly = -ly
                img["dx"], img["dy"] = round(pr["dx"] + lx, 2), round(pr["dy"] + ly, 2)
                b = s.aabb()
                self.drag_label = (f"picture {img['dx']:g}, {img['dy']:g}", self.to_screen((b[0] + b[2]) / 2, b[3]))
        elif self.mode == "marquee":
            x0, y0 = pr["c"]
            self.marquee = (x0, y0, cx, cy)
            l, r = sorted((x0, cx)); t, b = sorted((y0, cy))
            hit = [s.id for s in self.page.shapes
                   if not (s.aabb()[2] < l or s.aabb()[0] > r or s.aabb()[3] < t or s.aabb()[1] > b)]
            self.doc.set_selection(pr["base"] + [i for i in hit if i not in pr["base"]])
            self.update()
            return
        elif self.mode == "draw_rect":
            self._do_draw_rect(cx, cy, shift, alt, mods)
        elif self.mode == "draw_line":
            self._do_draw_line(cx, cy, shift, mods)
        elif self.mode == "draw_path":
            pts = pr["pts"]
            x, y = clamp_pt(cx, cy, (0, 0, self.page.width, self.page.height))
            if math.hypot(x - pts[-1][0], y - pts[-1][1]) * self.zoom >= 1.5:
                pts.append((x, y))
                if not self.preview:
                    self.preview = self.doc.styled(Shape(kind="path"))
                self.preview.set_path_points(pts)
        self.doc.changed.emit()

    def _hover(self, pos):
        hit = self.pill_at(pos)
        hp = hit[1] if hit else None
        if hp != self.hover_pill:
            self.hover_pill = hp
            self.update()
        if hit:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Make a group of the selected shapes (Ctrl+G)" if hit[0] == "add" else
                            "Click: select this group · Shift+click: add it · double-click: rename · right-click: more")
            return
        self.setToolTip("")
        if self.space:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self.tool != "select":
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self.img_drag:
            s = self.shape_at(pos)
            self.setCursor(Qt.CursorShape.OpenHandCursor if s and image_of(s) else Qt.CursorShape.ArrowCursor)
            return
        h = self.handle_at(pos)
        if h:
            self.setCursor(self._cursor_for(h))
            new = self.hover
        else:
            s = self.shape_at(pos)
            new = s.id if s else None
            self.setCursor(Qt.CursorShape.SizeAllCursor if s else Qt.CursorShape.ArrowCursor)
        if new != self.hover:
            self.hover = new
            self.update()

    # ---------------------------------------------------------------- move
    def _do_move(self, cx, cy, shift, mods):
        pr = self._press
        dx, dy = cx - pr["c"][0], cy - pr["c"][1]
        if shift:
            if abs(dx) > abs(dy):
                dy = 0
            else:
                dx = 0
        b = pr["box"]
        box = (b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy)
        sn = self._snapper(pr["orig"].keys(), mods)
        sx, sy, res = sn.snap_box(box)
        if shift:
            if dx == 0:
                sx = 0
            if dy == 0:
                sy = 0
            res.guides = sn._guides_for_box((box[0] + sx, box[1] + sy, box[2] + sx, box[3] + sy))
        if self.doc.snap.grid and sn.enabled:
            tx, ty = dx + sx, dy + sy
        else:
            tx = dx + sx if sx else self._rnd(b[0] + dx) - b[0]
            ty = dy + sy if sy else self._rnd(b[1] + dy) - b[1]
        lim = self.lim()
        if lim:
            px_, py_ = push_inside((b[0] + tx, b[1] + ty, b[2] + tx, b[3] + ty), lim)
            tx += px_; ty += py_
        for sid, o in pr["orig"].items():
            s = self.page.get(sid)
            if not s:
                continue
            if s.is_line:
                s.x1, s.y1, s.x2, s.y2 = (round(v, 4) for v in (o.x1 + tx, o.y1 + ty, o.x2 + tx, o.y2 + ty))
            else:
                s.x, s.y = round(o.x + tx, 4), round(o.y + ty, 4)
        if self.doc.snap.grid and sn.enabled:
            moved = [s for s in (self.page.get(i) for i in pr["orig"]) if s]
            self.fit_grid(moved)
            self.keep_in(moved, shrink=False)
        self._set_snap(res)
        nb = (b[0] + tx, b[1] + ty, b[2] + tx, b[3] + ty)
        self.drag_label = (f"X {nb[0]:g}   Y {nb[1]:g}", self.to_screen((nb[0] + nb[2]) / 2, nb[3]))

    # ---------------------------------------------------------------- resize one rect
    def _do_resize(self, cx, cy, shift, alt, mods):
        pr = self._press
        (hx, hy) = pr["h"][1]
        sid, o = next(iter(pr["orig"].items()))
        s = self.page.get(sid)
        if not s:
            return
        rot = o.rotation
        C0 = o.center()
        ax, ay = (0.0, 0.0) if alt else (-hx * o.w / 2, -hy * o.h / 2)
        mx, my = rot_pt(cx, cy, C0[0], C0[1], -rot)
        mx -= C0[0]; my -= C0[1]
        if alt:   # from the centre: the box grows on both sides
            nw = 2 * mx * hx if hx else o.w
            nh = 2 * my * hy if hy else o.h
        else:     # signed sizes: dragging past the opposite edge keeps working
            nw = (mx - ax) * hx if hx else o.w
            nh = (my - ay) * hy if hy else o.h
        res = SnapResult()
        upright = abs(norm_deg(rot)) < 1e-6
        if upright and not alt:
            sn = self._snapper([sid], mods)
            cur_box = (C0[0] - o.w / 2, C0[1] - o.h / 2, C0[0] + o.w / 2, C0[1] + o.h / 2)
            if hx:
                fixed = C0[0] + ax
                v, r1 = sn.snap_edge(fixed + hx * nw, 0, fixed, cur_box)
                nw = (v - fixed) * hx
                res.guides += r1.guides; res.gaps += r1.gaps
            if hy:
                fixed = C0[1] + ay
                v, r2 = sn.snap_edge(fixed + hy * nh, 1, fixed, cur_box)
                nh = (v - fixed) * hy
                res.guides += r2.guides; res.gaps += r2.gaps
        lock = shift != bool(o.lock_ratio)
        lim = self._limits(pr["orig"])
        if lim and upright:   # each moving edge stops at its own margin line
            for axis, (hv, a_, n) in enumerate(((hx, ax, nw), (hy, ay, nh))):
                if not hv:
                    continue
                c0 = C0[axis]
                lo, hi = lim[axis], lim[axis + 2]
                if alt:
                    half = min(abs(n) / 2, c0 - lo, hi - c0)
                    n = math.copysign(2 * half, n if n else 1)
                else:
                    fixed = c0 + a_
                    edge = min(max(fixed + hv * n, lo), hi)
                    n = (edge - fixed) * hv
                if axis == 0:
                    nw = n
                else:
                    nh = n
        if lock and o.w > 0 and o.h > 0:
            ratio = o.w / o.h
            if hx and hy:
                if abs(nw) / o.w >= abs(nh) / o.h:
                    nh = math.copysign(abs(nw) / ratio, nh if nh else 1)
                else:
                    nw = math.copysign(abs(nh) * ratio, nw if nw else 1)
            elif hx:
                nh = abs(nw) / ratio
            elif hy:
                nw = abs(nh) * ratio
            res = SnapResult() if (hx and hy) else res
        min_sz = 1.0
        if abs(nw) < min_sz:
            nw = math.copysign(min_sz, nw if nw else 1)
        if abs(nh) < min_sz:
            nh = math.copysign(min_sz, nh if nh else 1)
        if self.doc.snap.pixel:
            nw = math.copysign(max(1, round(abs(nw))), nw)
            nh = math.copysign(max(1, round(abs(nh))), nh)
        if alt:
            clx, cly = 0.0, 0.0
        else:
            clx = (ax + hx * nw / 2) if hx else 0.0
            cly = (ay + hy * nh / 2) if hy else 0.0
        ncx, ncy = rot_pt(C0[0] + clx, C0[1] + cly, C0[0], C0[1], rot)
        s.w, s.h = abs(nw), abs(nh)
        s.set_center(ncx, ncy)
        if upright and self.doc.snap.pixel:
            s.x, s.y = round(s.x * 2) / 2, round(s.y * 2) / 2
        self._grid_after(pr)
        self._set_snap(res)
        b = s.aabb()
        self.drag_label = (f"{s.w:g} × {s.h:g}", self.to_screen((b[0] + b[2]) / 2, b[3]))

    # ---------------------------------------------------------------- resize a group
    def _do_gresize(self, cx, cy, shift, alt, mods):
        pr = self._press
        hx, hy = pr["h"][1]
        b = pr["box"]
        bc = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        anc_x = bc[0] if alt else (b[2] if hx < 0 else b[0])
        anc_y = bc[1] if alt else (b[3] if hy < 0 else b[1])
        res = SnapResult()
        sn = self._snapper(pr["orig"].keys(), mods)
        sx = sy = 1.0
        if hx:
            edge0 = b[0] if hx < 0 else b[2]
            ex = cx
            if not alt:
                ex, r1 = sn.snap_edge(cx, 0, anc_x, b); res.guides += r1.guides
            den = edge0 - anc_x
            sx = (ex - anc_x) / den if abs(den) > 1e-9 else 1.0
        if hy:
            edge0 = b[1] if hy < 0 else b[3]
            ey = cy
            if not alt:
                ey, r2 = sn.snap_edge(cy, 1, anc_y, b); res.guides += r2.guides
            den = edge0 - anc_y
            sy = (ey - anc_y) / den if abs(den) > 1e-9 else 1.0
        if shift or not hx or not hy:
            if shift:
                if hx and hy:
                    m = max(abs(sx), abs(sy))
                    sx, sy = math.copysign(m, sx), math.copysign(m, sy)
                elif hx:
                    sy = abs(sx)
                else:
                    sx = abs(sy)
        for sid, o in pr["orig"].items():
            s = self.page.get(sid)
            if not s:
                continue
            if s.is_line:
                s.x1 = anc_x + (o.x1 - anc_x) * sx; s.x2 = anc_x + (o.x2 - anc_x) * sx
                s.y1 = anc_y + (o.y1 - anc_y) * sy; s.y2 = anc_y + (o.y2 - anc_y) * sy
                if self.doc.snap.pixel:
                    s.x1, s.y1, s.x2, s.y2 = (round(v) for v in (s.x1, s.y1, s.x2, s.y2))
                continue
            ocx, ocy = o.center()
            ncx, ncy = anc_x + (ocx - anc_x) * sx, anc_y + (ocy - anc_y) * sy
            r = abs(norm_deg(o.rotation)) % 180
            swap = 45 < r < 135
            fx, fy = (abs(sy), abs(sx)) if swap else (abs(sx), abs(sy))
            s.w, s.h = max(1.0, o.w * fx), max(1.0, o.h * fy)
            if self.doc.snap.pixel:
                s.w, s.h = float(round(s.w)) or 1.0, float(round(s.h)) or 1.0
            s.set_center(ncx, ncy)
        self._grid_after(pr)
        self._set_snap(res)
        nb = union_box(s.aabb() for s in self.doc.selected())
        self.drag_label = (f"{nb[2] - nb[0]:.0f} × {nb[3] - nb[1]:.0f}", self.to_screen((nb[0] + nb[2]) / 2, nb[3]))

    # ---------------------------------------------------------------- rotate
    def _do_rotate(self, cx, cy, shift):
        pr = self._press
        px_, py_ = pr["pivot"]
        a = math.degrees(math.atan2(cy - py_, cx - px_))
        delta = a - pr["a0"]
        single = len(pr["orig"]) == 1
        if single:
            o = next(iter(pr["orig"].values()))
            base = 0.0 if o.is_line else o.rotation
            target = base + delta
            if shift:
                target = round(target / 15) * 15
            elif abs(norm_deg(target)) % 90 < 1.5 or abs(norm_deg(target)) % 90 > 88.5:
                target = round(target / 90) * 90       # gentle pull to straight angles
            delta = target - base
        elif shift:
            delta = round(delta / 15) * 15
        for sid, o in pr["orig"].items():
            s = self.page.get(sid)
            if not s:
                continue
            if s.is_line:
                s.x1, s.y1 = rot_pt(o.x1, o.y1, px_, py_, delta)
                s.x2, s.y2 = rot_pt(o.x2, o.y2, px_, py_, delta)
            else:
                ncx, ncy = rot_pt(*o.center(), px_, py_, delta)
                s.rotation = norm_deg(o.rotation + delta)
                s.set_center(ncx, ncy)
        self._grid_after(pr)
        self._set_snap(None)
        show = norm_deg(delta) if not single or next(iter(pr["orig"].values())).is_line else norm_deg(
            next(iter(pr["orig"].values())).rotation + delta)
        self.drag_label = (f"{show:g}°", self.to_screen(px_, py_))

    # ---------------------------------------------------------------- corner radius
    def _do_radius(self, cx, cy):
        pr = self._press
        sid, o = next(iter(pr["orig"].items()))
        s = self.page.get(sid)
        if not s:
            return
        lx, ly = o.to_local(cx, cy)
        d = ((lx + o.w / 2) + (ly + o.h / 2)) / 2
        d = max(0.0, min(o.max_radius(), d))
        if d < theme.px(14) / self.zoom * 0.6:
            d = 0.0
        s.radius = self._rnd(d)
        b = s.aabb()
        self.drag_label = (f"radius {s.radius:g}", self.to_screen((b[0] + b[2]) / 2, b[3]))

    # ---------------------------------------------------------------- line ends
    def _do_line_end(self, cx, cy, shift, mods):
        pr = self._press
        idx = pr["h"][1]
        sid, o = next(iter(pr["orig"].items()))
        s = self.page.get(sid)
        if not s:
            return
        fx, fy = (o.x2, o.y2) if idx == 0 else (o.x1, o.y1)
        res = SnapResult()
        if shift:
            ang = math.atan2(cy - fy, cx - fx)
            ang = round(ang / (math.pi / 4)) * (math.pi / 4)
            L = math.hypot(cx - fx, cy - fy)
            x, y = fx + math.cos(ang) * L, fy + math.sin(ang) * L
        else:
            x, y, res = self._snapper([sid], mods).snap_point(cx, cy)
        x, y = clamp_pt(self._rnd(x), self._rnd(y), self._limits(pr["orig"]))
        if idx == 0:
            s.x1, s.y1 = x, y
        else:
            s.x2, s.y2 = x, y
        self._set_snap(res)
        self.drag_label = (f"{s.length():.0f} px  {norm_deg(s.angle()):g}°", self.to_screen(x, y))

    # ---------------------------------------------------------------- drawing new shapes
    def _do_draw_rect(self, cx, cy, shift, alt, mods):
        pr = self._press
        x0, y0 = pr["p0"]
        x, y, res = self._snapper([], mods).snap_point(cx, cy)
        lim = self.lim()
        x, y = clamp_pt(self._rnd(x), self._rnd(y), lim)
        w, h = x - x0, y - y0
        if shift:
            m = max(abs(w), abs(h))
            if lim:   # a square must fit both ways
                if alt:
                    room_x = min(x0 - lim[0], lim[2] - x0); room_y = min(y0 - lim[1], lim[3] - y0)
                else:
                    room_x = (lim[2] - x0) if w >= 0 else (x0 - lim[0])
                    room_y = (lim[3] - y0) if h >= 0 else (y0 - lim[1])
                m = min(m, room_x, room_y)
            w, h = math.copysign(m, w if w else 1), math.copysign(m, h if h else 1)
        elif alt and lim:
            w = math.copysign(min(abs(w), x0 - lim[0], lim[2] - x0), w if w else 1)
            h = math.copysign(min(abs(h), y0 - lim[1], lim[3] - y0), h if h else 1)
        if alt:
            l, t, r, b = x0 - abs(w), y0 - abs(h), x0 + abs(w), y0 + abs(h)
        else:
            l, r = sorted((x0, x0 + w)); t, b = sorted((y0, y0 + h))
        if not self.preview:
            self.preview = Shape(kind=pr.get("kind", "rect"))
        self.preview.x, self.preview.y, self.preview.w, self.preview.h = l, t, max(1, r - l), max(1, b - t)
        self.preview.lock_ratio = shift
        self._set_snap(res)
        self.drag_label = (f"{self.preview.w:g} × {self.preview.h:g}", self.to_screen((l + r) / 2, b))

    def _do_draw_line(self, cx, cy, shift, mods):
        pr = self._press
        x0, y0 = pr["p0"]
        res = SnapResult()
        if shift:
            ang = round(math.atan2(cy - y0, cx - x0) / (math.pi / 4)) * (math.pi / 4)
            L = math.hypot(cx - x0, cy - y0)
            x, y = x0 + math.cos(ang) * L, y0 + math.sin(ang) * L
        else:
            x, y, res = self._snapper([], mods).snap_point(cx, cy)
        x, y = clamp_pt(self._rnd(x), self._rnd(y), self.lim())
        if not self.preview:
            self.preview = Shape(kind="line", stroke_width=3)
        self.preview.x1, self.preview.y1, self.preview.x2, self.preview.y2 = x0, y0, x, y
        self._set_snap(res)
        self.drag_label = (f"{self.preview.length():.0f} px", self.to_screen(x, y))

    def mouseReleaseEvent(self, e):
        mode, pr = self.mode, self._press
        self.mode = None
        self._press = None
        self._set_snap(None)
        self.drag_label = None
        self.marquee = None
        if mode == "pan":
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.space else Qt.CursorShape.ArrowCursor)
            if pr["btn"] == Qt.MouseButton.RightButton and not pr["moved"] and self.menu_provider:
                s = self.shape_at(e.position())
                if s and s.id not in self.doc.selection:
                    self.doc.set_selection([s.id])
                self.menu_provider(e.globalPosition().toPoint(), s, self.to_canvas(e.position()))
            self._hover(e.position())
            self.update()
            return
        if mode == "move":
            n = len(pr["orig"])
            self.doc.commit(("Copied " if pr.get("dup") else "Moved ") + (f"{n} shapes" if n > 1 else "shape"))
        elif mode in ("resize", "gresize"):
            self.doc.commit("Resized")
        elif mode == "rotate":
            self.doc.commit("Rotated")
        elif mode == "radius":
            self.doc.commit("Corner radius")
        elif mode == "imgpan":
            self.doc.commit("Picture moved")
        elif mode == "line_end":
            self.doc.commit("Line changed")
        elif mode == "draw_rect":
            self._finish_rect(pr)
        elif mode == "draw_path":
            self._finish_path(pr)
        elif mode == "draw_line":
            self._finish_line(pr)
        elif mode == "pending" and not pr.get("alt"):
            # a plain click on a shape that was part of a multi-selection selects just it
            mods = e.modifiers()
            if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                s = self.shape_at(e.position())
                if s and len(self.doc.selection) > 1:
                    self.doc.set_selection([s.id])
        self.doc.changed.emit()
        self._hover(e.position())
        self.update()

    def _finish_rect(self, pr):
        pv = self.preview
        self.preview = None
        x0, y0 = pr["p0"]
        kind = pr.get("kind", "rect")
        oval = kind == "ellipse"
        if pv is None or (pv.w < 3 and pv.h < 3):      # a click: default size (a circle for the circle tool)
            pv = Shape(kind=kind, x=x0, y=y0, w=160 if oval else 200, h=160 if oval else 120, lock_ratio=oval)
        square = abs(pv.w - pv.h) < 0.5
        s = self.doc.styled(Shape(kind=kind, x=pv.x, y=pv.y, w=pv.w, h=pv.h, lock_ratio=square and pv.lock_ratio))
        self.keep_in([s])
        if self.grid_on:
            self.fit_grid([s]); self.keep_in([s])
        s.name = self.page.next_name(("Circle" if square else "Ellipse") if oval else ("Square" if square else "Rectangle"))
        self.set_tool("select")
        self.doc.add_shapes([s], f"Added {s.name}")

    def _finish_path(self, pr):
        """A freehand stroke becomes a shape. The draw tool stays on (like a brush); the new stroke is selected
        so its notes can be written straight away."""
        self.preview = None
        pts = simplify(pr["pts"], max(0.35, 0.6 / self.zoom))
        if len(pts) < 2 or max(math.hypot(x - pts[0][0], y - pts[0][1]) for x, y in pts) * self.zoom < 4:
            self.update()
            return              # a click, not a stroke
        s = self.doc.styled(Shape(kind="path"))
        s.stroke_width = max(1.0, s.stroke_width)
        s.set_path_points([(round(x, 2), round(y, 2)) for x, y in pts])
        s.name = self.page.next_name("Drawing")
        self.doc.add_shapes([s], f"Added {s.name}")
        self.shape_clicked.emit()

    def _finish_line(self, pr):
        pv = self.preview
        self.preview = None
        x0, y0 = pr["p0"]
        if pv is None or pv.length() < 3:
            pv = Shape(kind="line", x1=x0, y1=y0, x2=x0 + 200, y2=y0, stroke_width=3)
        s = self.doc.styled(Shape(kind="line", x1=pv.x1, y1=pv.y1, x2=pv.x2, y2=pv.y2, stroke_width=3))
        self.keep_in([s])
        if self.grid_on:
            self.fit_grid([s]); self.keep_in([s])
        s.name = self.page.next_name("Line")
        self.set_tool("select")
        self.doc.add_shapes([s], f"Added {s.name}")

    def mouseDoubleClickEvent(self, e):
        hit = self.pill_at(e.position())
        if hit:
            if hit[0] == "group" and self.group_rename:
                self.group_rename(hit[1])
            return
        if e.button() != Qt.MouseButton.LeftButton or self.tool != "select":
            return
        s = self.shape_at(e.position())
        if s:
            self.doc.set_selection([s.id])
            self.start_rename(s.id)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d == 0:
            d = e.pixelDelta().y()
        if d == 0:
            return
        self.set_zoom(self.zoom * (1.0015 ** d), e.position())

    def leaveEvent(self, _):
        if self.hover or self.hover_pill:
            self.hover = None
            self.hover_pill = None
            self.update()

    # ------------------------------------------------------------------ keys
    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        plain = not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier))
        if k == Qt.Key.Key_Space and not e.isAutoRepeat():
            self.space = True
            if self.mode is None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            big = bool(mods & Qt.KeyboardModifier.ShiftModifier)
            step = 10 if big else 1
            if self.doc.snap.grid:
                step = self.gsize() * (5 if big else 1)
            dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(k, 0)
            dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(k, 0)
            sel = self.doc.selected()
            if sel:
                lim = self.lim()
                if lim:
                    b = union_box(s.aabb() for s in sel)
                    if fits(b, lim):
                        px_, py_ = push_inside((b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy), lim)
                        dx += px_; dy += py_
                for s in sel:
                    s.translate(dx, dy)
                if self.doc.snap.grid:
                    self.fit_grid(sel)
                    self.keep_in(sel, shrink=False)
                self.doc.changed.emit()
                self.doc.commit("Nudged", merge="nudge")
            return
        if k in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.doc.delete_selected()
            return
        if k == Qt.Key.Key_Escape:
            if self.mode:
                self._cancel_drag()
            elif self.tool != "select":
                self.set_tool("select")
            else:
                self.doc.set_selection([])
            return
        if k == Qt.Key.Key_F2:
            sel = self.doc.selected()
            if sel:
                self.start_rename(sel[0].id)
            return
        if plain and not (mods & Qt.KeyboardModifier.ShiftModifier):
            if k == Qt.Key.Key_V:
                self.set_tool("select"); return
            if k == Qt.Key.Key_R:
                self.set_tool("rect"); return
            if k == Qt.Key.Key_C:
                self.set_tool("ellipse"); return
            if k == Qt.Key.Key_D:
                self.set_tool("draw"); return
            if k == Qt.Key.Key_L:
                self.set_tool("line"); return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self.space = False
            if self.mode is None:
                self._hover(self.mapFromGlobal(QCursor.pos()).toPointF())
            return
        super().keyReleaseEvent(e)

    def _cancel_drag(self):
        pr = self._press
        if pr and "orig" in pr:
            for sid, o in pr["orig"].items():
                s = self.page.get(sid)
                if s:
                    for k, v in o.to_dict().items():
                        setattr(s, k, v)
            if pr.get("dup"):
                ids = set(pr["orig"].keys())
                self.page.shapes = [s for s in self.page.shapes if s.id not in ids]
                self.doc.selection = []
                self.doc.structure.emit(); self.doc.selection_changed.emit()
        self.mode = None
        self._press = None
        self.preview = None
        self.marquee = None
        self.drag_label = None
        self._set_snap(None)
        self.doc.changed.emit()

    def focusOutEvent(self, e):
        self.space = False
        super().focusOutEvent(e)

    def keep_in(self, shapes, shrink=True):
        """Fit shapes inside the margins (an upright rectangle that is too big shrinks)."""
        lim = self.lim()
        if not lim or not shapes:
            return
        if shrink and len(shapes) == 1 and not shapes[0].is_line and abs(norm_deg(shapes[0].rotation)) < 1e-6:
            s = shapes[0]
            s.w = min(s.w, lim[2] - lim[0])
            s.h = min(s.h, lim[3] - lim[1])
        b = union_box(s.aabb() for s in shapes)
        dx, dy = push_inside(b, lim)
        for s in shapes:
            s.translate(dx, dy)

    # ------------------------------------------------------------------ renaming on the board
    def start_rename(self, sid: str):
        s = self.page.get(sid)
        if not s:
            return
        self.cancel_rename()
        ed = QLineEdit(self)
        ed.setText(s.name)
        ed.selectAll()
        b = s.aabb()
        tl = self.to_screen(b[0], b[1])
        w = max(theme.px(160), min(theme.px(320), (b[2] - b[0]) * self.zoom))
        h = theme.px(26)
        ed.setGeometry(int(tl.x()), int(max(2, tl.y() - h - theme.px(2))), int(w), h)
        ed.show()
        ed.setFocus()
        self._rename, self._rename_id = ed, sid
        ed.returnPressed.connect(self._finish_rename)
        ed.editingFinished.connect(self._finish_rename)
        ed.installEventFilter(self)
        self.update()

    def eventFilter(self, obj, ev):
        if obj is self._rename and ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            self.cancel_rename()
            self.setFocus()
            return True
        return super().eventFilter(obj, ev)

    def _finish_rename(self):
        ed, sid = self._rename, self._rename_id
        if ed is None:
            return
        self._rename, self._rename_id = None, None
        name = ed.text().strip()
        ed.hide()
        ed.deleteLater()
        s = self.page.get(sid)
        if s and name and name != s.name:
            s.name = name
            self.doc.structure.emit()
            self.doc.commit(f"Renamed to {name}")
        self.setFocus()
        self.update()

    def cancel_rename(self):
        if self._rename is not None:
            ed = self._rename
            self._rename, self._rename_id = None, None
            ed.blockSignals(True)
            ed.hide()
            ed.deleteLater()
            self.update()
