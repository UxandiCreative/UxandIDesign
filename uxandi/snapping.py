"""Snapping: edges, centres, canvas, equal spacing, the middle of a gap, dots.

All maths is in canvas pixels. A box is (left, top, right, bottom).
Results also carry what to draw: guide lines and gap markers.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass

from .model import Page

LO = (0, 1)      # box index of the low edge, per axis (0 = x, 1 = y)
HI = (2, 3)
CLO = (1, 0)     # the cross axis
CHI = (3, 2)


@dataclass
class SnapSettings:
    objects: bool = True       # edges and centres of other shapes
    spacing: bool = True       # equal gaps, and the middle of the space between two shapes
    canvas: bool = True        # canvas edges and centre
    grid: bool = False         # the dots
    sizes: bool = True         # while resizing: the width / height of other shapes
    threshold: int = 7         # screen pixels
    pixel: bool = True         # round positions and sizes to whole pixels

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d):
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


@dataclass
class Gap:
    axis: int        # 0: a horizontal gap (measured along x), 1: vertical
    a: float         # start along the axis
    b: float         # end along the axis
    cross: float     # where it sits on the other axis


class SnapResult:
    def __init__(self):
        self.guides: list[tuple[float, float, float, float]] = []
        self.gaps: list[Gap] = []


def _mid(b, ax):
    return (b[LO[ax]] + b[HI[ax]]) / 2


def _overlap(a, b, ax):
    """Do the boxes overlap on the cross axis of ax?"""
    return a[CLO[ax]] < b[CHI[ax]] - 1e-6 and a[CHI[ax]] > b[CLO[ax]] + 1e-6


class Snapper:
    def __init__(self, page: Page, exclude: set[str], settings: SnapSettings, zoom: float, enabled: bool = True):
        self.s = settings
        self.enabled = enabled
        self.th = settings.threshold / max(zoom, 1e-6)
        self.W, self.H = page.width, page.height
        others = [sh for sh in page.shapes if sh.id not in exclude]
        self.boxes = [sh.aabb() for sh in others]
        self.points = [p for sh in others for p in sh.snap_points()]
        self.canvas_box = (0.0, 0.0, float(self.W), float(self.H))
        self.margin_box = page.safe_rect() if ((page.show_margins or page.keep_inside) and any(page.margins)) else None
        self._gap_cache: dict[int, list] = {}
        self._target_cache: dict[int, list] = {}
        self._target_index: dict[int, tuple] = {}
        self.grid_size = max(1, int(page.dot_spacing))

    # ------------------------------------------------------------------ targets
    def targets(self, ax):
        """(value, source box) to align to on axis ax. Made once per snapper (a drag reuses its snapper)."""
        out = self._target_cache.get(ax)
        if out is None:
            out = self._target_cache[ax] = self._make_targets(ax)
        return out

    def _near_targets(self, ax, values, dist):
        """Indices (in list order) of targets on axis ax closer than `dist` to any of `values`."""
        idx = self._target_index.get(ax)
        if idx is None:
            tg = self.targets(ax)
            order = sorted(range(len(tg)), key=lambda i: tg[i][0])
            idx = self._target_index[ax] = (order, [tg[i][0] for i in order])
        order, vals = idx
        hit = set()
        for ref in values:
            k = bisect_left(vals, ref - dist - 1e-6)
            while k < len(vals) and vals[k] <= ref + dist + 1e-6:
                hit.add(order[k])
                k += 1
        return sorted(hit)

    def _make_targets(self, ax):
        out = []
        if self.s.objects:
            for b in self.boxes:
                out += [(b[LO[ax]], b), (_mid(b, ax), b), (b[HI[ax]], b)]
        if self.s.canvas:
            size = self.W if ax == 0 else self.H
            out += [(0.0, self.canvas_box), (size / 2, self.canvas_box), (float(size), self.canvas_box)]
            if self.margin_box:
                mb = self.margin_box
                out += [(mb[LO[ax]], mb), (mb[HI[ax]], mb)]
        return out

    def _gaps(self, ax):
        """Gaps between neighbouring shapes along ax: (size, box a, box b). For each box a, the nearest box
        b after it (overlapping on the cross axis); of equal gaps the one listed first."""
        if ax in self._gap_cache:
            return self._gap_cache[ax]
        lo, hi = LO[ax], HI[ax]
        order = sorted(range(len(self.boxes)), key=lambda i: (self.boxes[i][lo], i))
        los = [self.boxes[i][lo] for i in order]
        res = []
        for a in self.boxes:
            for k in range(bisect_left(los, a[hi] + 0.5 - 1e-6), len(order)):
                b = self.boxes[order[k]]
                if b is a or not _overlap(a, b, ax):
                    continue
                g = b[lo] - a[hi]
                if g > 0.5:            # sorted by start: the first one that counts is the nearest
                    res.append((g, a, b))
                    break
        self._gap_cache[ax] = res
        return res

    # ------------------------------------------------------------------ move a box
    def q(self, v):
        g = self.grid_size
        return round(v / g) * g

    def snap_box(self, box) -> tuple[float, float, SnapResult]:
        r = SnapResult()
        if not self.enabled:
            return 0.0, 0.0, r
        if self.s.grid:      # dots win: the box's top-left goes onto a dot
            return self.q(box[0]) - box[0], self.q(box[1]) - box[1], r
        dx, gx = self._snap_axis(box, 0)
        dy, gy = self._snap_axis(box, 1)
        moved = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        r.guides = self._guides_for_box(moved)
        r.gaps = gx + gy
        return dx, dy, r

    def _snap_axis(self, box, ax):
        th = self.th
        best = None  # (dist, delta, gaps, priority)
        refs = (box[LO[ax]], _mid(box, ax), box[HI[ax]])
        tg = self.targets(ax)
        for ti in self._near_targets(ax, refs, th):       # the others are too far to count
            v = tg[ti][0]
            for ref in refs:
                d = v - ref
                if abs(d) < th and (best is None or abs(d) < best[0] - 1e-9):
                    best = (abs(d), d, [])
        if self.s.spacing:
            for d, gaps in self._spacing(box, ax):
                # edges lining up win unless an equal gap is clearly closer
                if abs(d) < th and (best is None or abs(d) < best[0] - th * 0.5):
                    best = (abs(d), d, gaps)
        if best is not None and callable(best[2]):
            best = (best[0], best[1], best[2]())     # gap markers of the winner only
        if best is None:
            if self.s.grid:
                g = max(1, self.grid_size)
                lo = box[LO[ax]]
                return round(lo / g) * g - lo, []
            return 0.0, []
        # rebuild gap markers for the final position (gaps were measured before snapping)
        return best[1], best[2]

    def _spacing(self, box, ax):
        """Candidate moves that make a gap equal to an existing gap, or centre the box in a space:
        (move, markers). Only moves under the snap distance are listed (no other can win), in the same
        order as before; markers is a function, called only for the move that wins."""
        out = []
        lo, hi = LO[ax], HI[ax]
        th = self.th
        size = box[hi] - box[lo]
        row = [b for b in self.boxes if _overlap(b, box, ax)]
        if not row:
            return out
        gaps = self._gaps(ax)
        bm = _mid(box, ax)
        gorder = sorted(range(len(gaps)), key=lambda i: gaps[i][0])
        gsizes = [gaps[i][0] for i in gorder]

        def cross_mid(b1, b2):
            lo_c = max(b1[CLO[ax]], b2[CLO[ax]]); hi_c = min(b1[CHI[ax]], b2[CHI[ax]])
            return (lo_c + hi_c) / 2

        def marker(a, b, ca, cb):
            return Gap(ax, a, b, cross_mid(ca, cb))

        def near(want):
            """Indices (in list order) of the gaps within the snap distance of size `want`."""
            k0 = k1 = bisect_left(gsizes, want - th - 1e-6)
            while k1 < len(gsizes) and gsizes[k1] <= want + th + 1e-6:
                k1 += 1
            return sorted(gorder[k0:k1])

        for n in row:
            before = _mid(n, ax) < bm
            for gi in near(box[lo] - n[hi] if before else n[lo] - box[hi]):
                g, a, b = gaps[gi]
                if before:    # neighbour before the box: box starts one gap after it
                    d = (n[hi] + g) - box[lo]
                    if abs(d) < th:
                        out.append((d, lambda n=n, g=g, a=a, b=b, d=d: [
                            marker(n[hi], n[hi] + g, n, _moved(box, ax, d)), marker(a[hi], b[lo], a, b)]))
                else:         # neighbour after the box: box ends one gap before it
                    d = (n[lo] - g) - box[hi]
                    if abs(d) < th:
                        out.append((d, lambda n=n, g=g, a=a, b=b, d=d: [
                            marker(n[lo] - g, n[lo], n, _moved(box, ax, d)), marker(a[hi], b[lo], a, b)]))
        # the middle of the space between two neighbours
        srt = sorted(row, key=lambda b: b[lo])
        los = [b[lo] for b in srt]
        for a in srt:
            j = bisect_left(los, a[hi])        # the nearest one starting where a ends or later
            while j < len(srt) and srt[j] is a:
                j += 1
            if j >= len(srt):
                continue
            nxt = srt[j]
            space = nxt[lo] - a[hi]
            if space - size < 1:
                continue
            d = (a[hi] + nxt[lo]) / 2 - bm
            if abs(d) < th:
                def mk(a=a, nxt=nxt, d=d):
                    nb = _moved(box, ax, d)
                    return [marker(a[hi], nb[lo], a, nb), marker(nb[hi], nxt[lo], nb, nxt)]
                out.append((d, mk))
        return out

    def _guides_for_box(self, box):
        """Every exact alignment of the box with a target, as drawable lines."""
        lines = []
        for ax in (0, 1):
            refs = (box[LO[ax]], _mid(box, ax), box[HI[ax]])
            tg = self.targets(ax)
            for ti in self._near_targets(ax, refs, 0.5):
                v, src = tg[ti]
                if any(abs(v - ref) < 0.5 for ref in refs):
                    c0 = min(box[CLO[ax]], src[CLO[ax]]); c1 = max(box[CHI[ax]], src[CHI[ax]])
                    lines.append((v, c0, v, c1) if ax == 0 else (c0, v, c1, v))
        return lines

    # ------------------------------------------------------------------ one edge (resizing)
    def snap_edge(self, value, ax, fixed, cross_box):
        """Snap a moving edge at `value` on axis ax. `fixed` is the opposite edge.
        Returns (new value, SnapResult)."""
        r = SnapResult()
        if not self.enabled:
            return value, r
        if self.s.grid:
            return self.q(value), r
        th = self.th
        best = None
        for v, src in self.targets(ax):
            d = v - value
            if abs(d) < th and (best is None or abs(d) < best[0]):
                best = (abs(d), v, ("line", v, src))
        if self.s.sizes:
            sign = 1 if value >= fixed else -1
            for b in self.boxes:
                L = b[HI[ax]] - b[LO[ax]]
                v = fixed + sign * L
                d = v - value
                if abs(d) < th and (best is None or abs(d) < best[0] - 0.25):
                    best = (abs(d), v, ("size", b))
        if best is None:
            if self.s.grid:
                g = max(1, self.grid_size)
                return round(value / g) * g, r
            return value, r
        v = best[1]
        info = best[2]
        if info[0] == "line":
            src = info[2]
            c0 = min(cross_box[CLO[ax]], src[CLO[ax]]); c1 = max(cross_box[CHI[ax]], src[CHI[ax]])
            r.guides.append((v, c0, v, c1) if ax == 0 else (c0, v, c1, v))
        else:
            b = info[1]
            lo_new, hi_new = sorted((fixed, v))
            # show both sizes as measurement markers: the other shape's and this one's
            off = self.th * 2
            r.gaps.append(Gap(ax, b[LO[ax]], b[HI[ax]], b[CLO[ax]] - off))
            r.gaps.append(Gap(ax, lo_new, hi_new, cross_box[CLO[ax]] - off))
        return v, r

    # ------------------------------------------------------------------ a point (line ends, drawing)
    def snap_point(self, x, y):
        r = SnapResult()
        if not self.enabled:
            return x, y, r
        if self.s.grid:
            return self.q(x), self.q(y), r
        th = self.th
        best = None
        if self.s.objects:
            pts = list(self.points)
            if self.s.canvas:
                pts += [(0, 0), (self.W, 0), (self.W, self.H), (0, self.H), (self.W / 2, self.H / 2)]
                if self.margin_box:
                    ml, mt, mr, mb = self.margin_box
                    pts += [(ml, mt), (mr, mt), (mr, mb), (ml, mb)]
            for px, py in pts:
                d = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
                if d < th and (best is None or d < best[0]):
                    best = (d, px, py)
        if best:
            x, y = best[1], best[2]
            s = th * 0.9
            r.guides += [(x - s, y - s, x + s, y + s), (x - s, y + s, x + s, y - s)]
            return x, y, r
        out = [x, y]
        for ax in (0, 1):
            val = out[ax]
            b2 = None
            for v, src in self.targets(ax):
                d = v - val
                if abs(d) < th and (b2 is None or abs(d) < b2[0]):
                    b2 = (abs(d), v, src)
            if b2:
                out[ax] = b2[1]
            elif self.s.grid:
                g = max(1, self.grid_size)
                out[ax] = round(val / g) * g
        for ax in (0, 1):
            for v, src in self.targets(ax):
                if abs(v - out[ax]) < 0.5:
                    other = out[1 - ax]
                    c0 = min(other, src[CLO[ax]]); c1 = max(other, src[CHI[ax]])
                    r.guides.append((v, c0, v, c1) if ax == 0 else (c0, v, c1, v))
        return out[0], out[1], r


def _moved(box, ax, d):
    b = list(box)
    b[LO[ax]] += d
    b[HI[ax]] += d
    return tuple(b)
