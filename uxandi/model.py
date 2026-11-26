"""Data model: projects, pages (canvases) and shapes, plus the geometry they need.

Everything is stored in canvas pixels. A page's canvas has a fixed native size
(for example 1920 x 1080 or an iPhone screen); shapes keep their positions on
that canvas no matter how large the app window is or how far it is zoomed.
"""
from __future__ import annotations

import copy
import math
import time
import uuid
from dataclasses import dataclass, field, fields

FORMAT_VERSION = 1


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ----------------------------------------------------------------------------- canvas sizes
# (group, label, width, height). Portrait sizes for tablets and phones; the
# swap button turns any of them to landscape.
PRESETS: list[tuple[str, str, int, int]] = [
    ("Desktop", "HD 1280 x 720", 1280, 720),
    ("Desktop", "Laptop 1366 x 768", 1366, 768),
    ("Desktop", "1440 x 900", 1440, 900),
    ("Desktop", "1536 x 864", 1536, 864),
    ("Desktop", "Full HD 1920 x 1080", 1920, 1080),
    ("Desktop", "1920 x 1200", 1920, 1200),
    ("Desktop", "QHD 2560 x 1440", 2560, 1440),
    ("Desktop", "2560 x 1600", 2560, 1600),
    ("Desktop", "Ultrawide 3440 x 1440", 3440, 1440),
    ("Desktop", "4K UHD 3840 x 2160", 3840, 2160),
    ("iPad", "iPad mini (A17 Pro)", 1488, 2266),
    ("iPad", "iPad 10.9\" (10th gen / A16)", 1640, 2360),
    ("iPad", "iPad Air 11\"", 1640, 2360),
    ("iPad", "iPad Air 13\"", 2048, 2732),
    ("iPad", "iPad Pro 11\" (M4)", 1668, 2420),
    ("iPad", "iPad Pro 13\" (M4)", 2064, 2752),
    ("iPad", "iPad Pro 12.9\" (older)", 2048, 2732),
    ("Phone", "iPhone SE", 750, 1334),
    ("Phone", "iPhone 13 / 14", 1170, 2532),
    ("Phone", "iPhone 15 / 16", 1179, 2556),
    ("Phone", "iPhone 15 / 16 Plus", 1290, 2796),
    ("Phone", "iPhone 16 Pro", 1206, 2622),
    ("Phone", "iPhone 16 Pro Max", 1320, 2868),
    ("Phone", "Google Pixel 8", 1080, 2400),
    ("Phone", "Google Pixel 9 Pro", 1280, 2856),
    ("Phone", "Samsung Galaxy S24", 1080, 2340),
    ("Phone", "Samsung Galaxy S24 Ultra", 1440, 3120),
]


# ----------------------------------------------------------------------------- shapes
@dataclass
class Shape:
    kind: str = "rect"                 # "rect", "ellipse" (oval / circle filling its box), "line" or "path" (freehand)
    name: str = ""
    notes: str = ""                    # free text written in the Details panel
    id: str = field(default_factory=new_id)
    # rect: top-left of the UNROTATED box, its size, rotation (degrees, clockwise) about its centre
    x: float = 0.0
    y: float = 0.0
    w: float = 200.0
    h: float = 120.0
    rotation: float = 0.0
    radius: float = 0.0                # rounded corners, canvas px
    lock_ratio: bool = False           # resize keeps proportions (squares start with this on)
    fill: str = "#E9ECF0"              # "" = no fill
    # line: two end points
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    line_style: str = "solid"          # solid / dash / dot
    cap: str = "round"                 # round / flat / square
    # path (freehand): its box is x / y / w / h / rotation like a rect; points are [u, v] in 0..1 of that box
    points: list | None = None
    # both
    stroke: str = "#111418"
    stroke_width: float = 2.0          # border thickness; for rects the border sits inside the box
    flip_h: bool = False
    flip_v: bool = False
    created: str = field(default_factory=now_iso)
    modified: str = field(default_factory=now_iso)
    contents: dict | None = None       # reserved: what goes inside the shape (programmed later)

    # ---------------------------------------------------------------- dict io
    # The same dict dataclasses.asdict gives (field order, copies of the lists and dicts inside), built
    # directly: asdict walks every value recursively and was most of the cost of each undo step.
    def to_dict(self) -> dict:
        keys = _LINE_KEYS if self.kind == "line" else _PATH_KEYS if self.kind == "path" else _BOX_KEYS
        d = {k: getattr(self, k) for k in keys}
        if "points" in d and d["points"] is not None:
            d["points"] = [list(p) for p in d["points"]]
        if d["contents"] is not None:
            d["contents"] = copy.deepcopy(d["contents"])
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Shape":
        s = cls(**{k: v for k, v in d.items() if k in _FIELD_SET})
        if s.points is not None:
            s.points = [list(p) for p in s.points]     # never shares lists with an undo snapshot
        s.contents = copy.deepcopy(s.contents)
        return s

    def clone(self, fresh_id: bool = True) -> "Shape":
        s = Shape.from_dict(copy.deepcopy(self.to_dict()))
        if fresh_id:
            s.id = new_id()
            s.created = s.modified = now_iso()
        return s

    # ---------------------------------------------------------------- geometry
    @property
    def is_line(self) -> bool:
        return self.kind == "line"

    @property
    def is_ellipse(self) -> bool:
        return self.kind == "ellipse"

    @property
    def is_path(self) -> bool:
        """A freehand drawing: a stroke through points inside its box. Not a container."""
        return self.kind == "path"

    @property
    def is_stroke(self) -> bool:
        """Drawn as a stroke only (line or freehand path): no fill, no picture, line style and ends apply."""
        return self.kind in ("line", "path")

    @property
    def is_box(self) -> bool:
        """A container (rectangle or ellipse): has fill, corners or pictures, and can hold other shapes."""
        return self.kind in ("rect", "ellipse")

    def path_local(self) -> list[tuple[float, float]]:
        """A path's points relative to its box centre, unrotated, flips applied."""
        fx, fy = (-1 if self.flip_h else 1), (-1 if self.flip_v else 1)
        return [((u - 0.5) * self.w * fx, (v - 0.5) * self.h * fy) for u, v in (self.points or [])]

    def path_points(self) -> list[tuple[float, float]]:
        """A path's points on the canvas (rotation and flips applied)."""
        cx, cy = self.center()
        return [rot_pt(cx + x, cy + y, cx, cy, self.rotation) for x, y in self.path_local()]

    def set_path_points(self, pts) -> None:
        """Make this a path through these canvas points: the box becomes their bounds, upright and unflipped."""
        pts = [(float(x), float(y)) for x, y in pts]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        l, t, r, b = min(xs), min(ys), max(xs), max(ys)
        w, h = max(1.0, r - l), max(1.0, b - t)
        self.x, self.y, self.w, self.h = l, t, w, h
        self.rotation, self.flip_h, self.flip_v = 0.0, False, False
        self.points = [[round((x - l) / w, 5), round((y - t) / h, 5)] for x, y in pts]

    def center(self) -> tuple[float, float]:
        if self.is_line:
            return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2
        return self.x + self.w / 2, self.y + self.h / 2

    def set_center(self, cx: float, cy: float) -> None:
        if self.is_line:
            ox, oy = self.center()
            self.translate(cx - ox, cy - oy)
        else:
            self.x, self.y = cx - self.w / 2, cy - self.h / 2

    def translate(self, dx: float, dy: float) -> None:
        if self.is_line:
            self.x1 += dx; self.x2 += dx
            self.y1 += dy; self.y2 += dy
        else:
            self.x += dx; self.y += dy

    def corners(self) -> list[tuple[float, float]]:
        """Scene corners: rect clockwise from top-left; line its two ends."""
        if self.is_line:
            return [(self.x1, self.y1), (self.x2, self.y2)]
        cx, cy = self.center()
        hw, hh = self.w / 2, self.h / 2
        return [rot_pt(cx + px, cy + py, cx, cy, self.rotation)
                for px, py in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]

    def aabb(self) -> tuple[float, float, float, float]:
        """Axis-aligned bounds (left, top, right, bottom) including rotation."""
        if not self.is_line and abs(self.rotation) % 360 < 1e-9:
            return self.x, self.y, self.x + self.w, self.y + self.h
        pts = self.corners()
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def to_local(self, px: float, py: float) -> tuple[float, float]:
        """Scene point -> coordinates relative to the rect's centre, unrotated."""
        cx, cy = self.center()
        lx, ly = rot_pt(px, py, cx, cy, -self.rotation)
        return lx - cx, ly - cy

    def contains(self, px: float, py: float, tol: float) -> bool:
        if self.is_line:
            return seg_dist(px, py, self.x1, self.y1, self.x2, self.y2) <= max(self.stroke_width / 2, 0) + tol
        lx, ly = self.to_local(px, py)
        if self.is_path:            # on the stroke, not inside its box (so shapes it circles stay clickable)
            pts = self.path_local()
            r = max(self.stroke_width / 2, 0) + tol
            if len(pts) == 1:
                return math.hypot(lx - pts[0][0], ly - pts[0][1]) <= r
            return any(seg_dist(lx, ly, *pts[i], *pts[i + 1]) <= r for i in range(len(pts) - 1))
        if self.is_ellipse:
            a, b = self.w / 2 + tol, self.h / 2 + tol
            return a > 0 and b > 0 and (lx / a) ** 2 + (ly / b) ** 2 <= 1.0
        return abs(lx) <= self.w / 2 + tol and abs(ly) <= self.h / 2 + tol

    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)

    def angle(self) -> float:
        return math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1))

    def max_radius(self) -> float:
        return max(0.0, min(self.w, self.h) / 2)

    def snap_points(self) -> list[tuple[float, float]]:
        """Points other things snap to: corners, edge middles and the centre."""
        if self.is_line:
            return [(self.x1, self.y1), (self.x2, self.y2), self.center()]
        c = self.corners()
        mids = [((c[i][0] + c[(i + 1) % 4][0]) / 2, (c[i][1] + c[(i + 1) % 4][1]) / 2) for i in range(4)]
        return c + mids + [self.center()]


_FIELDS = tuple(f.name for f in fields(Shape))
_FIELD_SET = frozenset(_FIELDS)
_LINE_KEYS = tuple(k for k in _FIELDS if k not in ("x", "y", "w", "h", "rotation", "radius", "lock_ratio", "fill", "points"))
_PATH_KEYS = tuple(k for k in _FIELDS if k not in ("x1", "y1", "x2", "y2", "radius", "fill"))
_BOX_KEYS = tuple(k for k in _FIELDS if k not in ("x1", "y1", "x2", "y2", "line_style", "cap", "points"))


def simplify(pts: list, eps: float) -> list:
    """Ramer-Douglas-Peucker: drop points closer than eps to the line through their neighbours (keeps the shape)."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            d = seg_dist(pts[i][0], pts[i][1], pts[a][0], pts[a][1], pts[b][0], pts[b][1])
            if d > best:
                best, idx = d, i
        if idx >= 0 and best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def rot_pt(px: float, py: float, cx: float, cy: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    dx, dy = px - cx, py - cy
    return cx + dx * ca - dy * sa, cy + dx * sa + dy * ca


def seg_dist(px, py, ax, ay, bx, by) -> float:
    vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    if L <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def norm_deg(a: float) -> float:
    a = math.fmod(a, 360.0)
    if a > 180:
        a -= 360
    if a <= -180:
        a += 360
    return round(a, 4)


def fits(box, lim, eps: float = 0.01) -> bool:
    return (box[0] >= lim[0] - eps and box[1] >= lim[1] - eps
            and box[2] <= lim[2] + eps and box[3] <= lim[3] + eps)


def push_inside(box, lim) -> tuple[float, float]:
    """The move (dx, dy) that puts box inside lim. Too big to fit: its top-left goes to lim's top-left."""
    out = []
    for lo, hi in ((0, 2), (1, 3)):
        if box[hi] - box[lo] > lim[hi] - lim[lo] or box[lo] < lim[lo]:
            out.append(lim[lo] - box[lo])
        elif box[hi] > lim[hi]:
            out.append(lim[hi] - box[hi])
        else:
            out.append(0.0)
    return out[0], out[1]


def clamp_pt(x, y, lim):
    if not lim:
        return x, y
    return min(max(x, lim[0]), lim[2]), min(max(y, lim[1]), lim[3])


def grid_fit(s: "Shape", g: float) -> None:
    """Put a shape on the dot grid: every edge of an upright (or quarter-turned) rectangle
    and both ends of a line land on dots; a tilted rectangle gets its centre on a dot."""
    if g <= 0:
        return
    q = lambda v: round(v / g) * g
    if s.is_path:           # a freehand stroke keeps its drawn shape: only its top-left goes onto a dot
        l, t, _, _ = s.aabb()
        s.translate(q(l) - l, q(t) - t)
        return
    if s.is_line:
        s.x1, s.y1, s.x2, s.y2 = q(s.x1), q(s.y1), q(s.x2), q(s.y2)
        return
    r = abs(norm_deg(s.rotation)) % 180
    quarter = abs(r - 90) < 1e-6
    if r < 1e-6 or quarter:
        l, t, rr, b = s.aabb()
        L, T, R, B = q(l), q(t), q(rr), q(b)
        if R - L < g:
            R = L + g
        if B - T < g:
            B = T + g
        bw, bh = R - L, B - T
        s.w, s.h = (bh, bw) if quarter else (bw, bh)
        s.set_center((L + R) / 2, (T + B) / 2)
    else:
        cx, cy = s.center()
        s.set_center(q(cx), q(cy))


def box_contains(outer, inner, eps: float = 0.01) -> bool:
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps
            and outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


def parents_of(shapes: list) -> dict:
    """Nesting, {shape id: parent id or None}: the parent is a rectangle whose box holds the shape completely.
    When several do, it is the smallest one drawn beneath the shape, skipping any that a filled box drawn
    between them covers (a dialog on a scrim belongs to the scrim, not to the page under the scrim). A box drawn
    on top of the shape (a copy laid over the original) is its parent only when nothing beneath holds it. Of two
    equal boxes the one drawn later is inside the earlier one. The export, the agent tools and check_layout all
    use this rule."""
    boxes = {s.id: s.aabb() for s in shapes}
    area = {k: max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1]) for k, b in boxes.items()}
    z = {s.id: i for i, s in enumerate(shapes)}
    rects = [o for o in shapes if o.is_box]
    out = {}
    for s in shapes:
        cands = [o for o in rects if o.id != s.id and box_contains(boxes[o.id], boxes[s.id])
                 and not (area[o.id] < area[s.id] or (area[o.id] == area[s.id] and z[o.id] > z[s.id]))]
        below = [o for o in cands if z[o.id] < z[s.id]]
        if below:
            def covered(c):
                return any(z[c.id] < z[o.id] and o.fill and not box_contains(boxes[c.id], boxes[o.id]) for o in below)
            cands = [c for c in below if not covered(c)] or below
        best = min(cands, key=lambda o: (area[o.id], -z[o.id]), default=None)
        out[s.id] = best.id if best else None
    return out


def union_box(boxes) -> tuple[float, float, float, float] | None:
    boxes = list(boxes)
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


# ----------------------------------------------------------------------------- pages / project
@dataclass
class Page:
    name: str = "Page 1"
    id: str = field(default_factory=new_id)
    width: int = 1920
    height: int = 1080
    preset: str = "Full HD 1920 x 1080"
    background: str = "#FFFFFF"
    dots: bool = True
    dot_spacing: int = 20
    # margins: a safe area inside the canvas edge. top, right, bottom, left in canvas px
    margins: list = field(default_factory=lambda: [40, 40, 40, 40])
    margins_linked: bool = True        # one value for all four sides
    show_margins: bool = True          # light blue see-through lines
    keep_inside: bool = True           # shapes cannot be moved / resized past the margin lines
    # groups: [{"id", "name", "members": [shape ids]}]. A shape is in one group at most.
    groups: list = field(default_factory=list)
    notes: str = ""                    # what this page / screen is, written in the Brief tab
    shapes: list[Shape] = field(default_factory=list)

    KEYS = ("name", "id", "width", "height", "preset", "background", "dots", "dot_spacing",
            "margins", "margins_linked", "show_margins", "keep_inside", "groups", "notes")

    def to_dict(self) -> dict:
        d = {k: copy.deepcopy(getattr(self, k)) for k in self.KEYS}
        d["shapes"] = [s.to_dict() for s in self.shapes]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Page":
        p = cls(**{k: copy.deepcopy(d[k]) for k in cls.KEYS if k in d})
        m = list(p.margins) if isinstance(p.margins, (list, tuple)) else [p.margins] * 4
        p.margins = [float(v) for v in (m + [0, 0, 0, 0])[:4]]
        p.shapes = [Shape.from_dict(s) for s in d.get("shapes", [])]
        ids = {s.id for s in p.shapes}
        p.groups = [dict(id=g.get("id") or new_id(), name=g.get("name", "Group"),
                         members=[m for m in g.get("members", []) if m in ids])
                    for g in (p.groups or [])]
        p.groups = [g for g in p.groups if g["members"]]
        return p

    def group_of(self, sid: str) -> dict | None:
        for g in self.groups:
            if sid in g["members"]:
                return g
        return None

    def get_group(self, gid: str) -> dict | None:
        for g in self.groups:
            if g["id"] == gid:
                return g
        return None

    def clean_groups(self) -> None:
        """Drop shapes that are gone, and groups left empty."""
        ids = {s.id for s in self.shapes}
        for g in self.groups:
            g["members"] = [m for m in g["members"] if m in ids]
        self.groups = [g for g in self.groups if g["members"]]

    def next_group_name(self) -> str:
        n = 0
        for g in self.groups:
            tail = g["name"][6:] if g["name"].startswith("Group ") else ""
            if tail.isdigit():
                n = max(n, int(tail))
        return f"Group {n + 1}"

    def safe_rect(self) -> tuple[float, float, float, float]:
        """The area inside the margins: (left, top, right, bottom)."""
        t, r, b, l = self.margins
        L, T = max(0.0, l), max(0.0, t)
        R, B = max(L + 1, self.width - max(0.0, r)), max(T + 1, self.height - max(0.0, b))
        return L, T, R, B

    def limits(self):
        """The box shapes must stay in, or None when they may go anywhere."""
        return self.safe_rect() if self.keep_inside else None

    def get(self, sid: str) -> Shape | None:
        for s in self.shapes:
            if s.id == sid:
                return s
        return None

    def next_name(self, base: str) -> str:
        n = 0
        for s in self.shapes:
            if s.name.startswith(base + " "):
                tail = s.name[len(base) + 1:]
                if tail.isdigit():
                    n = max(n, int(tail))
        return f"{base} {n + 1}"


@dataclass
class Project:
    name: str = "Untitled"
    pages: list[Page] = field(default_factory=lambda: [Page()])
    created: str = field(default_factory=now_iso)
    brief: str = ""                    # what the project is, style and rules for the agent (Brief tab)

    def to_dict(self) -> dict:
        return self.to_dict_pages([p.to_dict() for p in self.pages])

    def to_dict_pages(self, pages: list) -> dict:
        """to_dict with the page dicts already made."""
        return {"format": "uxandi", "version": FORMAT_VERSION, "name": self.name, "brief": self.brief,
                "created": self.created, "pages": pages}

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        if d.get("format") not in (None, "uxandi"):
            raise ValueError("not a Uxandi project file")
        pr = cls(name=d.get("name", "Untitled"), pages=[Page.from_dict(p) for p in d.get("pages", [])],
                 created=d.get("created", now_iso()))
        pr.brief = d.get("brief", "")
        if not pr.pages:
            pr.pages = [Page()]
        return pr
