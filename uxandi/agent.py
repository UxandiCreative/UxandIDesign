"""Agent tools: the commands an AI agent uses to read and build layouts in Uxandi.

One set of commands, two places to run them:
  live  the app is open: uxandi/bridge.py runs each command inside the app. The user sees
        every change at once, and each command is one undo step (Ctrl+Z).
  file  the app is closed: uxandi_agent.py runs the commands on the project files and
        saves after every change. The app shows the result next time it opens.

uxandi_agent.py serves these commands over MCP (for agents such as Claude Code, Cursor,
Claude Desktop, VS Code, Codex) and as a plain command line (`python uxandi_agent.py call ...`).

This module imports no Qt at the top, so listing the tools needs no PySide6.
"""
from __future__ import annotations

import base64
import copy
import math
import re
import time
from pathlib import Path

from .model import PRESETS, Page, Shape, union_box, norm_deg, push_inside, grid_fit, fits, now_iso, parents_of

API_VERSION = 1

GUIDE = """Uxandi is a layout tool. You place containers (rectangles, ellipses and lines, plus freehand drawings) on fixed-size canvases (pages) and write
in each one's notes what it is. Another agent later builds the real UI from the export JSON, so names and notes carry
all the meaning. There is no text element: a heading is a rectangle named "Heading" whose notes say what it says,
its size and its role. Use colours, borders and corners only where they mean something.

Good workflow
1. get_status: see the project, its pages, the page on screen, and whether the app is open (live) or not (file mode).
2. Pages: add_page / update_page with a device preset (list_presets) so the canvas has the real screen size.
   set_project brief: what the product is, style and rules. update_page notes: what this screen is for.
3. Build outside in: the big regions first (header, sidebar, content), then their children placed "in" them.
   create_shapes accepts many shapes in one call; x / y / w / h may be pixels, "N%" of the frame, or
   "center" / "end" (also "end-16", "center+8") so you rarely need arithmetic.
4. Lay out rows, columns and cards with arrange (flex-like: gap, padding, sizes like [240, "1fr", "2fr"]) and grid.
   Line things up with align and distribute. Moving a container carries the shapes inside it.
   Repeated things (cards, list rows, table rows, tabs): build one with its children, then duplicate_shapes
   (count, or to: another page for shared chrome) and place the copies with grid / arrange.
5. Same element, same look: list_templates shows the user's saved styles; give a shape "template": "<name>".
   save_template makes a small style kit (Primary button, Card, Divider) the user can pick in the Design tab too.
6. Name every shape (unique on its page) and write its notes. check_layout lists overlaps, shapes past the margins,
   near-misses of 1-2 px, generic names and missing notes. screenshot shows you the page with names on it.
7. export_json writes the brief for the building agent (exports/<project>/<project>.compact.ui.json, compact form;
   compact: false for the full form <project>.ui.json). Formats: JSON Schemas schema/ui.compact.schema.json and
   schema/ui.schema.json (also MCP resources uxandi://schema/...). import_export loads one back.

Facts
- Coordinates are canvas pixels: origin top-left, x right, y down. A rectangle's box is [x, y, w, h] before rotation.
- Canvases are device pixels: phone presets are about 3x their point size, iPads 2x, desktops 1x (4K 2x). A 44 pt touch
  target is about 132 px on a phone canvas. Size a text box for the text its notes say it holds.
- Nesting is geometric: a shape that lies completely inside a rectangle is its child. Stacking order: later = on top.
- Refer to shapes by id or exact name; to pages by number (1 = first), name or id. Leave page out for the page on screen.
- The page may keep shapes inside its margins (keep_inside) and the user may snap to the dot grid; shapes are then
  moved or shrunk to fit, and the result says so under "adjusted".
- batch runs many commands as one step (one undo, all or nothing). Use it for multi-step builds.
- Live mode: the user is watching and may be editing too. Read (get_page) before changing shapes they may have moved.
"""

DEVICE_ORDER = ("Desktop", "iPad", "Phone")


class ToolError(Exception):
    """A clear problem with the request. The message is shown to the agent as is."""


# ============================================================================= targets
class Target:
    """What the commands act on: a Doc, plus hooks for where it lives."""
    live = False

    def __init__(self, doc):
        self.doc = doc

    def before(self) -> None:
        """Called before every command (file mode: reload if someone else changed the files)."""

    def flush(self) -> None:
        """Store text the user is still typing (live mode)."""

    def loaded(self) -> None:
        """A different project is now open."""

    def persist(self) -> None:
        """File mode: write the change to disk."""

    def page_resized(self, index: int) -> None:
        """A page changed size."""

    def show(self, index: int, ids: list) -> None:
        self.doc.go_page(index)
        self.doc.set_selection(ids)

    def window_png(self, max_size: int):
        raise ToolError("A window screenshot needs the app open. Start it with: python main.py")

    def templates_changed(self) -> None:
        """A design template was saved (live mode: refresh the Design tab's list)."""


# ============================================================================= small helpers
def _r(v, n: int = 2):
    v = round(float(v), n)
    return int(v) if v == int(v) else v


def _box_list(b):
    return [_r(b[0]), _r(b[1]), _r(b[2] - b[0]), _r(b[3] - b[1])]


_HEX = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _colour(v, what: str) -> str:
    if v is None or v is False or (isinstance(v, str) and v.strip().lower() in ("", "none", "transparent")):
        return ""
    if not isinstance(v, str) or not _HEX.match(v.strip()):
        raise ToolError(f"{what}: use a hex colour like \"#1F6FEB\" (or \"#801F6FEB\" with alpha first), or null for none. Got {v!r}.")
    return v.strip().upper()


def _with_opacity(hex_col: str, opacity) -> str:
    if not hex_col or opacity is None:
        return hex_col
    o = max(0.0, min(1.0, float(opacity)))
    rgb = hex_col[-6:]
    return "#" + rgb if o >= 0.999 else "#%02X%s" % (round(o * 255), rgb)


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        try:
            return float(str(v).strip().replace("px", ""))
        except Exception:
            raise ToolError(f"{what}: expected a number, got {v!r}.")
    if math.isnan(v) or math.isinf(v):
        raise ToolError(f"{what}: expected a finite number.")
    return float(v)


_POS = re.compile(r"^\s*(start|center|centre|middle|end)\s*(?:([+-])\s*(\d+(?:\.\d+)?)\s*(?:px)?)?\s*$", re.I)
_PCT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*%\s*$")


def _length(v, span: float, what: str) -> float:
    """A size: pixels, or "N%" of the frame."""
    if isinstance(v, str):
        m = _PCT.match(v)
        if m:
            return span * float(m.group(1)) / 100
    return _num(v, what)


def _position(v, start: float, span: float, extent: float, what: str) -> float:
    """A position inside a frame [start, start + span]: pixels from its start, "N%", or
    "start" / "center" / "end" with an optional "+N" / "-N"."""
    if isinstance(v, str):
        m = _POS.match(v)
        if m:
            word = m.group(1).lower()
            base = start if word == "start" else (start + span - extent if word == "end" else start + (span - extent) / 2)
            off = float(m.group(3) or 0) * (-1 if m.group(2) == "-" else 1)
            return base + off
        m = _PCT.match(v)
        if m:
            return start + span * float(m.group(1)) / 100
    return start + _num(v, what)


def _pad4(v) -> list:
    if v is None:
        return [0.0] * 4
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [float(v)] * 4
    if isinstance(v, (list, tuple)):
        v = [_num(x, "padding") for x in v]
        if len(v) == 1:
            return v * 4
        if len(v) == 2:
            return [v[0], v[1], v[0], v[1]]
        if len(v) == 4:
            return v
    raise ToolError("padding: a number, [vertical, horizontal] or [top, right, bottom, left].")


def _contains(outer, inner, eps=0.01):
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps
            and outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


def _device(page: Page) -> str:
    for g, name, w, h in PRESETS:
        if name == page.preset:
            return g
    return "Desktop" if page.preset in ("My screen", "This screen") else "Custom"


GENERIC = re.compile(r"^(Rectangle|Square|Line)( \d+)?( copy)?$")


# ============================================================================= lookups
def _page(t: Target, ref):
    pages = t.doc.project.pages
    if ref is None or ref == "" or ref == "current":
        return t.doc.page_index, t.doc.page
    if isinstance(ref, bool):
        raise ToolError("page: a number (1 = first), a name or an id.")
    if isinstance(ref, (int, float)) or (isinstance(ref, str) and ref.strip().isdigit()):
        i = int(ref)
        if 1 <= i <= len(pages):
            return i - 1, pages[i - 1]
        raise ToolError(f"There is no page {i}. Pages are numbered 1 to {len(pages)}.")
    ref = str(ref)
    for i, p in enumerate(pages):
        if p.id == ref:
            return i, p
    hits = [(i, p) for i, p in enumerate(pages) if p.name == ref] or \
           [(i, p) for i, p in enumerate(pages) if p.name.lower() == ref.lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ToolError(f"{len(hits)} pages are named {ref!r}: use its number ({', '.join(str(i + 1) for i, _ in hits)}).")
    raise ToolError(f"No page {ref!r}. Pages: " + "; ".join(f"{i + 1} {p.name}" for i, p in enumerate(pages)))


def _shape(pg: Page, ref) -> Shape:
    if isinstance(ref, dict):
        ref = ref.get("id") or ref.get("name")
    if ref is None or ref == "":
        raise ToolError("A shape reference is empty: give its id or name.")
    ref = str(ref)
    s = pg.get(ref)
    if s:
        return s
    hits = [s for s in pg.shapes if s.name == ref] or [s for s in pg.shapes if s.name.lower() == ref.lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ToolError(f"{len(hits)} shapes on page {pg.name!r} are named {ref!r}; use an id: "
                        + ", ".join(s.id for s in hits) + ". Give shapes unique names to avoid this.")
    names = [s.name or s.id for s in pg.shapes]
    more = f" (and {len(names) - 40} more)" if len(names) > 40 else ""
    raise ToolError(f"No shape {ref!r} on page {pg.name!r}. Shapes: " + (", ".join(names[:40]) + more if names else "none yet"))


def _shapes(pg: Page, refs) -> list:
    if refs is None:
        raise ToolError("shapes: give a list of shape ids or names.")
    if not isinstance(refs, (list, tuple)):
        refs = [refs]
    out, seen = [], set()
    for r in refs:
        s = _shape(pg, r)
        if s.id not in seen:
            seen.add(s.id)
            out.append(s)
    return out


def _frame(pg: Page, ref):
    """A box (left, top, right, bottom) to place things in: the canvas, the safe area or a shape."""
    if ref is None or (isinstance(ref, str) and ref.lower() == "canvas"):
        return (0.0, 0.0, float(pg.width), float(pg.height))
    if isinstance(ref, str) and ref.lower() in ("safe_area", "safe area", "margins"):
        return pg.safe_rect()
    s = _shape(pg, ref)
    if not s.is_box:
        raise ToolError(f"{s.name or s.id} is a {'line' if s.is_line else 'drawing'}; only rectangles and ellipses can hold shapes.")
    return s.aabb()


def _inner(pg: Page, ref, padding=None):
    """The frame's box minus a rectangle's own border, minus padding."""
    l, t, r, b = _frame(pg, ref)
    if ref is not None and not (isinstance(ref, str) and ref.lower() in ("canvas", "safe_area", "safe area", "margins")):
        s = _shape(pg, ref)
        if s.stroke_width > 0 and s.stroke:
            bw = min(s.stroke_width, (r - l) / 2, (b - t) / 2)
            l, t, r, b = l + bw, t + bw, r - bw, b - bw
    pt, pr, pb, pl = _pad4(padding)
    return l + pl, t + pt, max(l + pl, r - pr), max(t + pt, b - pb)


# ============================================================================= nesting
def _parents(pg: Page) -> dict:
    """The export's nesting rule (model.parents_of): the smallest rectangle beneath the shape that holds it."""
    return parents_of(pg.shapes)


def _descendants(pg: Page, s: Shape) -> list:
    if not s.is_box:
        return []
    par = _parents(pg)
    kids = {}
    for sid, pid in par.items():
        kids.setdefault(pid, []).append(sid)
    out, todo = [], list(kids.get(s.id, []))
    while todo:
        k = todo.pop()
        out.append(k)
        todo.extend(kids.get(k, []))
    return [pg.get(k) for k in out if pg.get(k)]


# ============================================================================= describing shapes / pages
_KIND = {"rect": "rect", "rectangle": "rect", "square": "rect", "box": "rect",
         "ellipse": "ellipse", "oval": "ellipse", "circle": "ellipse", "line": "line",
         "path": "path", "drawing": "path", "freehand": "path"}


def describe_shape(s: Shape, pg: Page, parents: dict | None = None, groups: dict | None = None) -> dict:
    d = {"id": s.id, "name": s.name, "kind": s.kind}
    if s.is_line:
        d["points"] = [_r(s.x1), _r(s.y1), _r(s.x2), _r(s.y2)]
        d["stroke"] = s.stroke or None
        d["stroke_width"] = _r(s.stroke_width)
        if s.line_style != "solid":
            d["line_style"] = s.line_style
        if s.cap != "round":
            d["cap"] = s.cap
    elif s.is_path:
        d["box"] = [_r(s.x), _r(s.y), _r(s.w), _r(s.h)]
        if abs(s.rotation) > 1e-9:
            d["rotation"] = _r(s.rotation)
        d["points"] = [[_r(x), _r(y)] for x, y in s.path_points()]
        d["stroke"] = s.stroke or None
        d["stroke_width"] = _r(s.stroke_width)
        if s.line_style != "solid":
            d["line_style"] = s.line_style
        if s.cap != "round":
            d["cap"] = s.cap
    else:
        d["box"] = [_r(s.x), _r(s.y), _r(s.w), _r(s.h)]
        if abs(s.rotation) > 1e-9:
            d["rotation"] = _r(s.rotation)
            d["visual_box"] = _box_list(s.aabb())
        d["fill"] = s.fill or None
        d["stroke"] = (s.stroke or None) if s.stroke_width > 0 else None
        d["stroke_width"] = _r(s.stroke_width)
        if s.radius:
            d["radius"] = _r(min(s.radius, s.max_radius()))
    if s.flip_h:
        d["flip_h"] = True
    if s.flip_v:
        d["flip_v"] = True
    if s.notes:
        d["notes"] = s.notes
    img = s.contents if isinstance(s.contents, dict) and s.contents.get("type") == "image" else None
    if img:
        d["image"] = {k: img.get(k) for k in ("path", "fit", "zoom", "dx", "dy", "opacity")}
    if parents is not None and parents.get(s.id):
        d["parent"] = parents[s.id]
    if groups and s.id in groups:
        d["group"] = groups[s.id]
    return d


def describe_page(t: Target, i: int, pg: Page, shapes: bool = True) -> dict:
    t_, r_, b_, l_ = pg.margins
    d = {"index": i + 1, "id": pg.id, "name": pg.name, "notes": pg.notes,
         "width": pg.width, "height": pg.height, "preset": pg.preset, "device": _device(pg),
         "orientation": "landscape" if pg.width > pg.height else ("portrait" if pg.height > pg.width else "square"),
         "background": pg.background, "margins": [_r(t_), _r(r_), _r(b_), _r(l_)],
         "safe_area": _box_list(pg.safe_rect()), "keep_inside": pg.keep_inside,
         "dots": pg.dots, "dot_spacing": pg.dot_spacing, "shape_count": len(pg.shapes)}
    if not shapes:
        return d
    par = _parents(pg)
    gname = {m: g["name"] for g in pg.groups for m in g["members"]}
    d["groups"] = [{"id": g["id"], "name": g["name"], "shapes": [pg.get(m).name or m for m in g["members"] if pg.get(m)]}
                   for g in pg.groups]
    d["shapes"] = [describe_shape(s, pg, par, gname) for s in pg.shapes]
    # an indented outline: the nesting at a glance
    kids = {}
    for s in pg.shapes:
        kids.setdefault(par[s.id], []).append(s)
    lines = []

    def walk(pid, depth):
        for s in kids.get(pid, []):
            b = s.aabb()
            lines.append("  " * depth + f"{s.name or '(no name)'} [{s.id}] {_r(b[0])},{_r(b[1])} {_r(b[2] - b[0])}x{_r(b[3] - b[1])}"
                         + (" line" if s.is_line else ""))
            walk(s.id, depth + 1)
    walk(None, 0)
    d["outline"] = "\n".join(lines)
    return d


# ============================================================================= applying shape fields
RECT_KEYS = {"x", "y", "w", "h", "box", "rotation", "radius", "fill", "fill_opacity", "lock_ratio"}
LINE_KEYS = {"x1", "y1", "x2", "y2", "points", "line_style", "cap"}
PATH_KEYS = {"x", "y", "w", "h", "box", "rotation", "lock_ratio", "points", "line_style", "cap"}
COMMON_KEYS = {"name", "notes", "stroke", "stroke_opacity", "stroke_width", "in", "image", "group", "order",
               "move", "center", "carry", "kind", "shape", "template", "flip_h", "flip_v"}


def _apply(t: Target, pg: Page, s: Shape, a: dict, creating: bool) -> None:
    allowed = COMMON_KEYS | (LINE_KEYS if s.is_line else PATH_KEYS if s.is_path else RECT_KEYS)
    bad = [k for k in a if k not in allowed]
    if bad:
        other = "a rectangle" if s.is_line else "a line"
        hint = [k for k in bad if k in (RECT_KEYS if s.is_line else LINE_KEYS)]
        raise ToolError(f"{s.name or 'shape'}: unknown field(s) {', '.join(bad)}"
                        + (f" ({', '.join(hint)} belong to {other})" if hint else "")
                        + ". Fields: " + ", ".join(sorted(allowed - {'kind', 'shape'})) + ".")
    if a.get("template"):
        _apply_template(s, _read_template(a["template"]))     # first, so fields given beside it win
    if "name" in a:
        s.name = str(a["name"] or "").strip()
    if "notes" in a:
        s.notes = str(a["notes"] or "")
    if "stroke" in a:
        c = _colour(a["stroke"], "stroke")
        if c:
            s.stroke = c
        elif s.is_stroke:
            raise ToolError("stroke: a line or drawing needs a colour (delete it to remove it).")
        else:
            s.stroke_width = 0.0       # no border
    if a.get("stroke_opacity") is not None:
        s.stroke = _with_opacity(s.stroke, a["stroke_opacity"])
    if "stroke_width" in a:
        s.stroke_width = max(0.0, _num(a["stroke_width"], "stroke_width"))
    if s.is_stroke:
        if "line_style" in a:
            if a["line_style"] not in ("solid", "dash", "dot"):
                raise ToolError("line_style: solid, dash or dot.")
            s.line_style = a["line_style"]
        if "cap" in a:
            if a["cap"] not in ("round", "flat", "square"):
                raise ToolError("cap: round, flat or square.")
            s.cap = a["cap"]
    if s.is_box:
        if "fill" in a:
            s.fill = _colour(a["fill"], "fill")
        if a.get("fill_opacity") is not None:
            s.fill = _with_opacity(s.fill, a["fill_opacity"])
        if "radius" in a:
            s.radius = max(0.0, _num(a["radius"], "radius"))
    if not s.is_line:
        if "rotation" in a:
            s.rotation = norm_deg(_num(a["rotation"], "rotation"))
        if "lock_ratio" in a:
            s.lock_ratio = bool(a["lock_ratio"])
    geo_creating = creating
    if s.is_path:
        if "points" in a:
            _path_points(pg, s, a)
            geo_creating = False          # placed by its points, not centred
        elif creating:
            raise ToolError("points: a drawing needs its points, [[x, y], [x, y], ...] (2 or more, in the frame \"in\").")
    _geometry(pg, s, {k: v for k, v in a.items() if k != "points"} if s.is_path else a, geo_creating)
    for key, axis in (("flip_h", 0), ("flip_v", 1)):
        if key in a and bool(a[key]) != getattr(s, key):
            _flip(s, axis)
    if "image" in a:
        _image(s, a["image"])


def _path_points(pg: Page, s: Shape, a: dict) -> None:
    """A drawing through these points, measured in the frame "in" (default: the canvas)."""
    pts = a["points"]
    if (not isinstance(pts, list) or len(pts) < 2
            or not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in pts)):
        raise ToolError("points: a drawing's points are [[x, y], [x, y], ...] (2 or more).")
    l, t, _, _ = _frame(pg, a.get("in")) if a.get("in") is not None else (0.0, 0.0, 0.0, 0.0)
    s.set_path_points([(l + _num(x, "points"), t + _num(y, "points")) for x, y in pts])


def _flip(s: Shape, axis: int) -> None:
    """Mirror a shape about its own centre, like Shift+H / Shift+V in the app."""
    if s.is_line:
        cx, cy = s.center()
        if axis == 0:
            s.x1, s.x2 = 2 * cx - s.x1, 2 * cx - s.x2
        else:
            s.y1, s.y2 = 2 * cy - s.y1, 2 * cy - s.y2
    else:
        s.rotation = norm_deg(-s.rotation)
    if axis == 0:
        s.flip_h = not s.flip_h
    else:
        s.flip_v = not s.flip_v


# ============================================================================= design templates
TEMPLATE_FORMAT = "uxandi-template"
TEMPLATE_KEYS = ("fill", "stroke", "stroke_width", "radius", "line_style", "cap")


def _templates_dir() -> Path:
    from . import doc as docmod
    return docmod.TEMPLATES_DIR


def _template_files() -> list:
    d = _templates_dir()
    return sorted(d.glob("*.json")) if d.exists() else []


def _safe_template_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in " -_" else "_" for c in str(name)).strip()


def _read_template(name) -> dict:
    import json
    if not isinstance(name, str) or not name.strip():
        raise ToolError("template: the name of a saved design template (list_templates).")
    files = _template_files()
    hit = [f for f in files if f.stem == name] or [f for f in files if f.stem.lower() == name.lower()] or           [f for f in files if f.stem == _safe_template_name(name)]
    if not hit:
        raise ToolError(f"No design template {name!r}. " + ("Templates: " + ", ".join(f.stem for f in files) + "."
                        if files else "None saved yet: make one with save_template."))
    try:
        d = json.loads(hit[0].read_text(encoding="utf-8"))
    except Exception as e:
        raise ToolError(f"Could not read the template {hit[0].name}: {e}")
    if not isinstance(d, dict):
        raise ToolError(f"{hit[0].name} is not a design template.")
    d["name"] = hit[0].stem
    return d


def _apply_template(s: Shape, d: dict) -> None:
    """The same rules as the Design tab's Apply."""
    if d.get("stroke"):
        s.stroke = str(d["stroke"])
    if "stroke_width" in d:
        s.stroke_width = max(0.0, float(d["stroke_width"]))
    if s.is_stroke:
        s.line_style = d.get("line_style", s.line_style)
        s.cap = d.get("cap", s.cap)
    else:
        if "fill" in d:
            s.fill = d["fill"] or ""
        if "radius" in d:
            s.radius = float(d["radius"])
        if d.get("image"):
            s.contents = copy.deepcopy(d["image"])


def _template_view(d: dict) -> dict:
    out = {"name": d.get("name")}
    for k in TEMPLATE_KEYS:
        if k in d:
            out[k] = (d[k] or None) if k == "fill" else d[k]
    if d.get("image"):
        out["image"] = (d["image"] or {}).get("path")
    if d.get("saved"):
        out["saved"] = d["saved"]
    return out


def _geometry(pg: Page, s: Shape, a: dict, creating: bool) -> None:
    frame_ref = a.get("in")
    l, t, r, b = _frame(pg, frame_ref) if frame_ref is not None else (0.0, 0.0, float(pg.width), float(pg.height))
    if frame_ref is not None and _shape_or_none(pg, frame_ref) is s:
        raise ToolError(f"{s.name or s.id}: a shape cannot be placed in itself.")
    fw, fh = r - l, b - t
    if s.is_line:
        pts = a.get("points")
        if pts is not None:
            if not isinstance(pts, (list, tuple)) or len(pts) != 4:
                raise ToolError("points: [x1, y1, x2, y2].")
            a = dict(a, x1=pts[0], y1=pts[1], x2=pts[2], y2=pts[3])
        for k, start, span in (("x1", l, fw), ("y1", t, fh), ("x2", l, fw), ("y2", t, fh)):
            if k in a:
                setattr(s, k, _position(a[k], start, span, 0.0, k))
        if creating and not any(k in a for k in ("x1", "y1", "x2", "y2")):
            L = round(min(fw, fh) * 0.5)
            s.x1, s.y1, s.x2, s.y2 = l + (fw - L) / 2, t + fh / 2, l + (fw + L) / 2, t + fh / 2
    else:
        box = a.get("box")
        if box is not None:
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                raise ToolError("box: [x, y, w, h].")
            a = dict(a, x=box[0], y=box[1], w=box[2], h=box[3])
        if "w" in a:
            s.w = max(1.0, _length(a["w"], fw, "w"))
        if "h" in a:
            s.h = max(1.0, _length(a["h"], fh, "h"))
        if s.lock_ratio and ("w" in a) != ("h" in a):
            pass  # one side given: the other stays; the agent sets both for exact sizes
        if "x" in a:
            s.x = _position(a["x"], l, fw, s.w, "x")
        elif creating:
            s.x = l + (fw - s.w) / 2
        if "y" in a:
            s.y = _position(a["y"], t, fh, s.h, "y")
        elif creating:
            s.y = t + (fh - s.h) / 2
    if "center" in a:
        c = a["center"]
        if not isinstance(c, (list, tuple)) or len(c) != 2:
            raise ToolError("center: [x, y].")
        s.set_center(_num(c[0], "center x"), _num(c[1], "center y"))
    if "move" in a:
        m = a["move"]
        if not isinstance(m, (list, tuple)) or len(m) != 2:
            raise ToolError("move: [dx, dy], how far to shift it.")
        s.translate(_num(m[0], "move dx"), _num(m[1], "move dy"))


def _shape_or_none(pg, ref):
    try:
        return _shape(pg, ref) if not (isinstance(ref, str) and ref.lower() in ("canvas", "safe_area", "safe area", "margins")) else None
    except ToolError:
        return None


def _image(s: Shape, v) -> None:
    from . import images
    if not s.is_box:
        raise ToolError("image: only rectangles and ellipses hold pictures.")
    if v is None or v is False:
        if isinstance(s.contents, dict) and s.contents.get("type") == "image":
            s.contents = None
        return
    if isinstance(v, str):
        v = {"file": v}
    if not isinstance(v, dict):
        raise ToolError("image: {\"file\": \"path/to/picture.png\", \"fit\": \"fill\"} or null to remove it.")
    cur = s.contents if isinstance(s.contents, dict) and s.contents.get("type") == "image" else None
    if v.get("file"):
        src = Path(str(v["file"])).expanduser()
        if not src.is_absolute():
            src = images.ROOT / src
        if not src.exists():
            raise ToolError(f"image file not found: {src}")
        if src.suffix.lower() not in images.EXTS:
            raise ToolError(f"image: use one of {', '.join(sorted(images.EXTS))}.")
        cur = images.new_contents(images.import_image(src), src.name)
    if cur is None:
        raise ToolError("image: give \"file\" (a picture path) the first time.")
    if "fit" in v:
        if v["fit"] not in ("fill", "fit", "stretch", "original"):
            raise ToolError("image fit: fill, fit, stretch or original.")
        cur["fit"] = v["fit"]
    for k in ("zoom", "dx", "dy", "opacity"):
        if k in v:
            cur[k] = _num(v[k], f"image {k}")
    s.contents = cur


def _group(pg: Page, s: Shape, name) -> None:
    for g in pg.groups:
        g["members"] = [m for m in g["members"] if m != s.id]
    if name:
        g = next((g for g in pg.groups if g["name"] == name), None)
        if g is None:
            from .model import new_id
            g = {"id": new_id(), "name": str(name), "members": []}
            pg.groups.append(g)
        g["members"].append(s.id)
    pg.clean_groups()


def _order(pg: Page, ids: set, how: str) -> None:
    sh = pg.shapes
    if how == "front":
        sh[:] = [s for s in sh if s.id not in ids] + [s for s in sh if s.id in ids]
    elif how == "back":
        sh[:] = [s for s in sh if s.id in ids] + [s for s in sh if s.id not in ids]
    elif how == "forward":
        for i in range(len(sh) - 2, -1, -1):
            if sh[i].id in ids and sh[i + 1].id not in ids:
                sh[i], sh[i + 1] = sh[i + 1], sh[i]
    elif how == "backward":
        for i in range(1, len(sh)):
            if sh[i].id in ids and sh[i - 1].id not in ids:
                sh[i], sh[i - 1] = sh[i - 1], sh[i]
    else:
        raise ToolError("order: front, back, forward or backward.")


# ============================================================================= page rules: margins and dots
def _limits(t: Target, pg: Page):
    lim = pg.limits()
    if lim and t.doc.snap.grid:
        g = float(max(1, pg.dot_spacing))
        L, T = math.ceil(lim[0] / g - 1e-9) * g, math.ceil(lim[1] / g - 1e-9) * g
        R, B = math.floor(lim[2] / g + 1e-9) * g, math.floor(lim[3] / g + 1e-9) * g
        if R - L >= g and B - T >= g:
            lim = (L, T, R, B)
    return lim


def _geo(s: Shape):
    return (s.x1, s.y1, s.x2, s.y2) if s.is_line else (s.x, s.y, s.w, s.h, s.rotation)


def _keep_in(s: Shape, lim, shrink: bool) -> None:
    if shrink and not s.is_line and abs(norm_deg(s.rotation)) < 1e-6:
        s.w = min(s.w, lim[2] - lim[0])
        s.h = min(s.h, lim[3] - lim[1])
    dx, dy = push_inside(s.aabb(), lim)
    if dx or dy:
        s.translate(dx, dy)


def _whole_pixels(s: Shape) -> None:
    """Round edges (not sizes) so shapes laid side by side stay touching."""
    if s.is_line:
        s.x1, s.y1, s.x2, s.y2 = (round(v, 2) for v in (s.x1, s.y1, s.x2, s.y2))
        return
    if abs(norm_deg(s.rotation)) > 1e-6:
        s.x, s.y, s.w, s.h = (round(v, 2) for v in (s.x, s.y, s.w, s.h))
        return
    l, t, r, b = round(s.x), round(s.y), round(s.x + s.w), round(s.y + s.h)
    s.x, s.y, s.w, s.h = l, t, max(1, r - l), max(1, b - t)


def _settle(t: Target, pg: Page, shapes: list, was_inside: dict) -> list:
    """Apply the page's rules the way the app does: whole pixels (the app's default), the
    dots (when the user has dot snapping on), and the margins (when the page keeps shapes
    inside them and the shape was inside before). Returns what was adjusted and why."""
    notes = []
    lim = _limits(t, pg)
    grid = bool(t.doc.snap.grid)
    g = float(max(1, pg.dot_spacing))
    for s in shapes:
        if t.doc.snap.pixel:
            _whole_pixels(s)
        before = _geo(s)
        keep = lim is not None and was_inside.get(s.id, True)
        if keep:
            _keep_in(s, lim, shrink=True)
        after_margin = _geo(s)
        if grid:
            grid_fit(s, g)
        after_grid = _geo(s)
        if keep:
            _keep_in(s, lim, shrink=False)
        why = []
        if after_margin != before or _geo(s) != after_grid:
            why.append("kept inside the page margins (the page has keep_inside on)")
        if after_grid != after_margin:
            why.append(f"put on the {int(g)} px dot grid (the user has dot snapping on)")
        if why:
            d = describe_shape(s, pg)
            notes.append({"id": s.id, "name": s.name, "now": d.get("box") or d.get("points"), "why": "; ".join(why)})
    return notes


def _inside_map(t: Target, pg: Page, shapes) -> dict:
    lim = _limits(t, pg)
    return {s.id: (fits(s.aabb(), lim) if lim else True) for s in shapes}


def _carry(pg: Page, moved: list, before: dict, kids_before: dict, skip: set) -> list:
    """Shapes that were inside a moved rectangle move with it (by the shift of its top-left)."""
    carried = []
    for s in moved:
        b0 = before.get(s.id)
        if b0 is None or s.is_line:
            continue
        b1 = s.aabb()
        dx, dy = b1[0] - b0[0], b1[1] - b0[1]
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            continue
        for k in kids_before.get(s.id, []):
            if k.id in skip:
                continue
            k.translate(dx, dy)
            skip.add(k.id)
            carried.append(k.id)
    return carried


# ============================================================================= tool handlers
def t_get_status(t: Target, a: dict) -> dict:
    d = t.doc
    pr = d.project
    out = {
        "mode": "live" if t.live else "file",
        "mode_note": ("The app is open: changes appear on the user's screen; each command is one undo step."
                      if t.live else "The app is closed: commands edit the project file and save it. "
                      "The user sees the result when they open the app (python main.py)."),
        "api_version": API_VERSION,
        "project": {"name": pr.name, "file": str(d.path) if d.path else None, "unsaved_changes": bool(d.dirty),
                    "brief": pr.brief, "page_count": len(pr.pages)},
        "current_page": d.page_index + 1,
        "pages": [{"index": i + 1, "name": p.name, "size": f"{p.width}x{p.height}", "device": _device(p),
                   "preset": p.preset, "shapes": len(p.shapes), "notes": (p.notes[:120] + "…") if len(p.notes) > 120 else p.notes}
                  for i, p in enumerate(pr.pages)],
        "selection": [{"id": s.id, "name": s.name} for s in d.selected()],
        "dot_snapping": bool(d.snap.grid),
        "new_shape_style": dict(d.style),
        "design_templates": [f.stem for f in _template_files()],
    }
    return out


def t_get_page(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    if a.get("full"):
        from .export import page_export
        return page_export(pg, i + 1)
    return describe_page(t, i, pg)


def t_list_presets(t: Target, a: dict) -> dict:
    out = {}
    for g, name, w, h in PRESETS:
        out.setdefault(g, []).append({"preset": name, "width": w, "height": h})
    return {"presets": out, "note": "Tablet and phone sizes are portrait; pass orientation: \"landscape\" to turn them. "
                                    "Any other size: give width and height (the preset becomes Custom)."}


def t_list_projects(t: Target, a: dict) -> dict:
    from . import doc as docmod
    folder = docmod.PROJECTS_DIR
    files = sorted(folder.glob("*" + docmod.EXT), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    return {"folder": str(folder), "open_now": str(t.doc.path) if t.doc.path else None,
            "projects": [{"name": f.stem, "file": str(f), "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))}
                         for f in files]}


def t_create_shapes(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    specs = a.get("shapes")
    if not isinstance(specs, list) or not specs:
        raise ToolError("shapes: a list of shapes to make, e.g. [{\"name\": \"Header\", \"x\": 0, \"y\": 0, \"w\": \"100%\", \"h\": 72}].")
    made, adjusted = [], []
    for n, spec in enumerate(specs):
        if not isinstance(spec, dict):
            raise ToolError(f"shapes[{n}]: each shape is an object.")
        kind = str(spec.get("kind", "rect")).lower()
        if kind in ("rect", "rectangle", "box", "container"):
            s = Shape(kind="rect")
        elif kind == "square":
            s = Shape(kind="rect", lock_ratio=True)
        elif kind in ("ellipse", "oval"):
            kind = "ellipse"
            s = Shape(kind="ellipse")
        elif kind == "circle":
            s = Shape(kind="ellipse", lock_ratio=True)
        elif kind == "line":
            s = Shape(kind="line", stroke_width=3)
        elif kind in ("path", "drawing", "freehand"):
            kind = "path"
            s = Shape(kind="path", stroke_width=3)
        else:
            raise ToolError(f"shapes[{n}].kind: rect, square, ellipse, circle, line or path (there is no text element: "
                            "use a rect and write its text in notes).")
        t.doc.styled(s)
        if kind in ("square", "circle"):
            side = spec.get("w", spec.get("h", 200))
            spec = dict(spec, w=side, h=spec.get("h", side))
        try:
            _apply(t, pg, s, {k: v for k, v in spec.items() if k not in ("group", "order")}, creating=True)
        except ToolError as e:
            raise ToolError(f"shapes[{n}] ({spec.get('name', kind)}): {e}")
        if not s.name:
            s.name = pg.next_name({"line": "Line", "square": "Square", "ellipse": "Ellipse", "circle": "Circle",
                                   "path": "Drawing"}.get(kind, "Rectangle"))
        pg.shapes.append(s)
        if spec.get("group"):
            _group(pg, s, spec["group"])
        if spec.get("order"):
            _order(pg, {s.id}, spec["order"])
        made.append(s)
        adjusted += _settle(t, pg, [s], {})
    out = {"page": i + 1, "created": [{"id": s.id, "name": s.name, **({"points": [_r(s.x1), _r(s.y1), _r(s.x2), _r(s.y2)]} if s.is_line
                                                                        else {"box": [_r(s.x), _r(s.y), _r(s.w), _r(s.h)]})} for s in made]}
    dup = _duplicate_names(pg)
    if adjusted:
        out["adjusted"] = adjusted
    if dup:
        out["warning"] = "Names used more than once on this page (refer to these by id, or rename them): " + ", ".join(dup)
    return out


def _duplicate_names(pg):
    seen, dup = set(), []
    for s in pg.shapes:
        if s.name in seen and s.name not in dup:
            dup.append(s.name)
        seen.add(s.name)
    return dup


def t_update_shapes(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    changes = a.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ToolError("changes: a list like [{\"shape\": \"Header\", \"h\": 96, \"notes\": \"...\"}].")
    targets = []
    for n, ch in enumerate(changes):
        if not isinstance(ch, dict) or ch.get("shape") in (None, ""):
            raise ToolError(f"changes[{n}]: each change names its \"shape\" (id or name) and the fields to set.")
        targets.append((_shape(pg, ch["shape"]), ch))
    ids = {s.id for s, _ in targets}
    before = {s.id: s.aabb() for s, _ in targets}
    kids = {s.id: _descendants(pg, s) for s, ch in targets if ch.get("carry", True)}
    inside = _inside_map(t, pg, [s for s, _ in targets])
    for s, ch in targets:
        if "kind" in ch:
            want = _KIND.get(str(ch["kind"]).lower())
            if want is None:
                raise ToolError(f"{s.name}: kind is rect, ellipse, line or path.")
            if want != s.kind and not {want, s.kind} <= {"rect", "ellipse"}:
                raise ToolError(f"{s.name}: only rect and ellipse switch kinds; a line or drawing cannot become a box "
                                "or the other way round (delete it and create a new one).")
            s.kind = want                     # rect <-> ellipse keeps the box, style and contents
        try:
            _apply(t, pg, s, {k: v for k, v in ch.items() if k not in ("group", "order")}, creating=False)
        except ToolError as e:
            raise ToolError(f"{s.name or s.id}: {e}")
        if "group" in ch:
            _group(pg, s, ch["group"])
        if ch.get("order"):
            _order(pg, {s.id}, ch["order"])
    adjusted = _settle(t, pg, [s for s, _ in targets], inside)
    carried = _carry(pg, [s for s, _ in targets], before, kids, set(ids))
    par = _parents(pg)
    out = {"page": i + 1, "updated": [describe_shape(s, pg, par) for s, _ in targets]}
    if carried:
        out["carried_children"] = len(carried)
    if adjusted:
        out["adjusted"] = adjusted
    dup = _duplicate_names(pg)
    if dup:
        out["warning"] = "Names used more than once on this page: " + ", ".join(dup)
    return out


def t_delete_shapes(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    gone = _shapes(pg, a.get("shapes"))
    ids = {s.id for s in gone}
    if a.get("with_children"):
        for s in list(gone):
            for k in _descendants(pg, s):
                ids.add(k.id)
    pg.shapes = [s for s in pg.shapes if s.id not in ids]
    pg.clean_groups()
    t.doc.selection = [x for x in t.doc.selection if x not in ids]
    return {"page": i + 1, "deleted": len(ids)}


def _place(s: Shape, box) -> None:
    """Put a shape into a box (l, t, r, b). A line is mapped into the box."""
    l, t, r, b = box
    if s.is_line:
        ol, ot, or_, ob = s.aabb()
        def mx(v):
            return (l + r) / 2 if or_ - ol < 1e-9 else l + (v - ol) / (or_ - ol) * (r - l)
        def my(v):
            return (t + b) / 2 if ob - ot < 1e-9 else t + (v - ot) / (ob - ot) * (b - t)
        s.x1, s.y1, s.x2, s.y2 = mx(s.x1), my(s.y1), mx(s.x2), my(s.y2)
        return
    s.rotation = 0.0
    s.x, s.y, s.w, s.h = l, t, max(1.0, r - l), max(1.0, b - t)


def _layout_common(t: Target, a: dict):
    i, pg = _page(t, a.get("page"))
    items = _shapes(pg, a.get("shapes"))
    if not items:
        raise ToolError("shapes: at least one shape.")
    into = a.get("into")
    if into is not None:
        c = _shape_or_none(pg, into)
        if c is not None and c.id in {s.id for s in items}:
            raise ToolError("into: the container cannot be one of the shapes being arranged.")
    return i, pg, items


def _finish_layout(t, pg, i, items, before, kids, inside, a):
    adjusted = _settle(t, pg, items, inside)
    carried = _carry(pg, items, before, kids, {s.id for s in items}) if a.get("carry", True) else []
    par = _parents(pg)
    out = {"page": i + 1, "placed": [describe_shape(s, pg, par) for s in items]}
    if carried:
        out["carried_children"] = len(carried)
    if adjusted:
        out["adjusted"] = adjusted
    return out


def _snapshot_layout(t, pg, items, a):
    before = {s.id: s.aabb() for s in items}
    kids = {s.id: _descendants(pg, s) for s in items} if a.get("carry", True) else {}
    inside = _inside_map(t, pg, items)
    return before, kids, inside


def t_arrange(t: Target, a: dict) -> dict:
    i, pg, items = _layout_common(t, a)
    direction = a.get("direction", "row")
    if direction not in ("row", "column"):
        raise ToolError("direction: row (left to right) or column (top to bottom).")
    l, t_, r, b = _inner(pg, a.get("into"), a.get("padding"))
    gap = _num(a.get("gap", 0), "gap")
    row = direction == "row"
    main0, main1 = (l, r) if row else (t_, b)
    cross0, cross1 = (t_, b) if row else (l, r)
    span = main1 - main0
    sizes = a.get("sizes")
    if sizes is None:
        sizes = ["1fr"] * len(items)
    if not isinstance(sizes, list) or len(sizes) != len(items):
        raise ToolError(f"sizes: one entry per shape ({len(items)}): pixels, \"N%\", \"Nfr\" (a share of the space left) or \"auto\" (keep its size).")
    fixed, frs = [], []
    for s, v in zip(items, sizes):
        cur = (s.aabb()[2] - s.aabb()[0]) if row else (s.aabb()[3] - s.aabb()[1])
        if isinstance(v, str) and v.strip().lower().endswith("fr"):
            fixed.append(None)
            frs.append(_num(v.strip()[:-2] or 1, "fr"))
        elif v is None or (isinstance(v, str) and v.strip().lower() == "auto"):
            fixed.append(cur); frs.append(0.0)
        else:
            fixed.append(_length(v, span, "sizes")); frs.append(0.0)
    free = span - gap * (len(items) - 1) - sum(x for x in fixed if x is not None)
    total_fr = sum(frs)
    unit = max(0.0, free) / total_fr if total_fr > 0 else 0.0
    lens = [x if x is not None else unit * f for x, f in zip(fixed, frs)]
    left = span - gap * (len(items) - 1) - sum(lens)
    justify = a.get("justify", "start")
    if justify not in ("start", "center", "end", "space-between", "space-around"):
        raise ToolError("justify: start, center, end, space-between or space-around.")
    pos, g = main0, gap
    if total_fr == 0 and left > 0:
        if justify == "center":
            pos += left / 2
        elif justify == "end":
            pos += left
        elif justify == "space-between" and len(items) > 1:
            g = gap + left / (len(items) - 1)
        elif justify == "space-around":
            g = gap + left / len(items)
            pos += (g - gap) / 2
    align = a.get("align", "stretch")
    if align not in ("stretch", "start", "center", "end"):
        raise ToolError("align: stretch (fill across), start, center or end.")
    cross_size = a.get("cross_size")
    before, kids, inside = _snapshot_layout(t, pg, items, a)
    for s, L in zip(items, lens):
        bb = s.aabb()
        cur_c = (bb[3] - bb[1]) if row else (bb[2] - bb[0])
        cs = (cross1 - cross0) if align == "stretch" and cross_size is None else (
            _length(cross_size, cross1 - cross0, "cross_size") if cross_size is not None else cur_c)
        if align in ("start", "stretch"):
            c0 = cross0
        elif align == "end":
            c0 = cross1 - cs
        else:
            c0 = cross0 + (cross1 - cross0 - cs) / 2
        box = (pos, c0, pos + L, c0 + cs) if row else (c0, pos, c0 + cs, pos + L)
        _place(s, box)
        pos += L + g
    out = _finish_layout(t, pg, i, items, before, kids, inside, a)
    if left < -0.5:
        out["warning"] = f"The shapes need {_r(-left)} px more than the space has along the {direction}; they overflow it."
    return out


def t_grid(t: Target, a: dict) -> dict:
    i, pg, items = _layout_common(t, a)
    cols = int(_num(a.get("columns", 0), "columns"))
    if cols < 1:
        raise ToolError("columns: how many shapes per row (1 or more).")
    l, t_, r, b = _inner(pg, a.get("into"), a.get("padding"))
    gap = a.get("gap", 0)
    gx, gy = ((_num(gap[0], "gap"), _num(gap[1], "gap")) if isinstance(gap, (list, tuple)) else (_num(gap, "gap"),) * 2)
    rows = math.ceil(len(items) / cols)
    cw = (r - l - gx * (cols - 1)) / cols
    if a.get("row_height") is not None:
        rh = _length(a["row_height"], b - t_, "row_height")
    elif a.get("aspect") is not None:
        rh = cw / max(1e-6, _num(a["aspect"], "aspect"))
    else:
        rh = (b - t_ - gy * (rows - 1)) / rows
    if cw < 1 or rh < 1:
        raise ToolError("The grid cells come out smaller than 1 px: fewer columns, a smaller gap or less padding.")
    before, kids, inside = _snapshot_layout(t, pg, items, a)
    for n, s in enumerate(items):
        rr, cc = divmod(n, cols)
        x0, y0 = l + cc * (cw + gx), t_ + rr * (rh + gy)
        _place(s, (x0, y0, x0 + cw, y0 + rh))
    out = _finish_layout(t, pg, i, items, before, kids, inside, a)
    out["cell"] = {"width": _r(cw), "height": _r(rh), "rows": rows, "columns": cols}
    if t_ + rows * rh + gy * (rows - 1) > b + 0.5:
        out["warning"] = "The rows run past the bottom of the container."
    return out


EDGES = {"left": "left", "right": "right", "top": "top", "bottom": "bottom",
         "center_x": "center_x", "hcenter": "center_x", "center": "center_x", "centre": "center_x",
         "center_y": "center_y", "vcenter": "center_y", "middle": "center_y"}


def t_align(t: Target, a: dict) -> dict:
    i, pg, items = _layout_common(t, a)
    edge = EDGES.get(str(a.get("edge", "")).lower())
    if not edge:
        raise ToolError("edge: left, right, top, bottom, center_x or center_y.")
    to = a.get("to")
    if to is None or (isinstance(to, str) and to.lower() == "together"):
        if len(items) < 2:
            raise ToolError("One shape: say what to align it to with \"to\": \"canvas\", \"safe_area\" or a shape.")
        ref = union_box(s.aabb() for s in items)
    else:
        ref = _frame(pg, to)
    before, kids, inside = _snapshot_layout(t, pg, items, a)
    for s in items:
        bb = s.aabb()
        dx = dy = 0.0
        if edge == "left":
            dx = ref[0] - bb[0]
        elif edge == "right":
            dx = ref[2] - bb[2]
        elif edge == "center_x":
            dx = (ref[0] + ref[2]) / 2 - (bb[0] + bb[2]) / 2
        elif edge == "top":
            dy = ref[1] - bb[1]
        elif edge == "bottom":
            dy = ref[3] - bb[3]
        else:
            dy = (ref[1] + ref[3]) / 2 - (bb[1] + bb[3]) / 2
        s.translate(dx, dy)
    return _finish_layout(t, pg, i, items, before, kids, inside, a)


def t_distribute(t: Target, a: dict) -> dict:
    i, pg, items = _layout_common(t, a)
    axis = str(a.get("axis", "x")).lower()
    if axis in ("horizontal", "h", "row"):
        axis = "x"
    if axis in ("vertical", "v", "column"):
        axis = "y"
    if axis not in ("x", "y"):
        raise ToolError("axis: x (left to right) or y (top to bottom).")
    k0, k1 = (0, 2) if axis == "x" else (1, 3)
    items = sorted(items, key=lambda s: s.aabb()[k0])
    before, kids, inside = _snapshot_layout(t, pg, items, a)
    if a.get("gap") is not None:
        gap = _num(a["gap"], "gap")
        pos = items[0].aabb()[k1] + gap
        for s in items[1:]:
            bb = s.aabb()
            d = pos - bb[k0]
            s.translate(d if axis == "x" else 0, d if axis == "y" else 0)
            pos = s.aabb()[k1] + gap
    else:
        if len(items) < 3:
            raise ToolError("Equal spacing needs 3 or more shapes, or give \"gap\" for an exact gap.")
        first, last = items[0].aabb(), items[-1].aabb()
        total = sum(s.aabb()[k1] - s.aabb()[k0] for s in items)
        gap = ((last[k1] - first[k0]) - total) / (len(items) - 1)
        pos = first[k1] + gap
        for s in items[1:-1]:
            bb = s.aabb()
            d = pos - bb[k0]
            s.translate(d if axis == "x" else 0, d if axis == "y" else 0)
            pos = s.aabb()[k1] + gap
    out = _finish_layout(t, pg, i, items, before, kids, inside, a)
    out["gap"] = _r(gap)
    return out


def t_set_group(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    name = str(a.get("name") or "").strip()
    if not name:
        raise ToolError("name: the group's name.")
    members = _shapes(pg, a.get("shapes", []))
    g = next((g for g in pg.groups if g["name"] == name), None)
    if not members:
        if g:
            pg.groups.remove(g)
        return {"page": i + 1, "removed_group": name}
    ids = [s.id for s in members]
    for og in pg.groups:
        og["members"] = [m for m in og["members"] if m not in ids]
    if g is None:
        from .model import new_id
        g = {"id": new_id(), "name": name, "members": []}
        pg.groups.append(g)
    order = {s.id: n for n, s in enumerate(pg.shapes)}
    g["members"] = sorted(ids, key=lambda m: order[m])
    pg.clean_groups()
    return {"page": i + 1, "group": name, "shapes": [s.name for s in members]}


def _unique_name(names: set, base: str) -> str:
    """base if it is free, else the next number: "Card 3" -> "Card 7", "Price" -> "Price 2"."""
    if not base or base not in names:
        return base
    head, _, tail = base.rpartition(" ")
    stem = head if head and tail.isdigit() else base
    n = 1
    for nm in names:
        if nm.startswith(stem + " ") and nm[len(stem) + 1:].isdigit():
            n = max(n, int(nm[len(stem) + 1:]))
    return f"{stem} {n + 1}"


def t_duplicate_shapes(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    src = _shapes(pg, a.get("shapes"))
    if not src:
        raise ToolError("shapes: at least one shape to copy.")
    count = int(_num(a.get("count", 1), "count"))
    if not 1 <= count <= 200:
        raise ToolError("count: 1 to 200 copies.")
    with_children = a.get("with_children", True)
    j, dest = (i, pg) if a.get("to") is None else _page(t, a["to"])
    if with_children:          # a listed shape inside another listed one is copied with it already
        inner = {k.id for s in src for k in _descendants(pg, s)}
        src = [s for s in src if s.id not in inner]
    g = float(max(1, pg.dot_spacing)) if t.doc.snap.grid else 20.0
    off = a.get("offset", [0, 0] if dest is not pg else [g, g])
    if not isinstance(off, (list, tuple)) or len(off) != 2:
        raise ToolError("offset: [dx, dy], how far each copy sits from the one before.")
    dx, dy = _num(off[0], "offset dx"), _num(off[1], "offset dy")
    names = a.get("names")
    if names is not None and (not isinstance(names, list) or len(names) != count * len(src)):
        raise ToolError(f"names: one name per copy, {count * len(src)} in all "
                        "(copy 1 of each shape in order, then copy 2, ...).")
    z = {s.id: n for n, s in enumerate(pg.shapes)}
    trees = {s.id: [s] + (sorted(_descendants(pg, s), key=lambda x: z[x.id]) if with_children else []) for s in src}
    taken = {s.name for s in dest.shapes}
    copies, adjusted, nn = [], [], 0
    for k in range(1, count + 1):
        for s in src:
            tree = trees[s.id]
            made = []
            for o in tree:
                c = o.clone()
                c.translate(dx * k, dy * k)
                made.append(c)
            top = made[0]
            want = str(names[nn]).strip() if names else ""
            nn += 1
            top.name = want if want else _unique_name(taken, s.name)
            taken.add(top.name)
            for c, o in zip(made[1:], tree[1:]):
                # children named after their container follow it: "Card 1 title" -> "Card 2 title"
                follow = s.name and top.name != s.name and s.name in o.name
                c.name = _unique_name(taken, o.name.replace(s.name, top.name) if follow else o.name)
                taken.add(c.name)
            b0 = top.aabb()
            dest.shapes.extend(made)
            adjusted += _settle(t, dest, [top], {})
            b1 = top.aabb()
            if (b1[0], b1[1]) != (b0[0], b0[1]):
                for c in made[1:]:
                    c.translate(b1[0] - b0[0], b1[1] - b0[1])
            copies.append({"of": s.name or s.id, "copy": k, "id": top.id, "name": top.name,
                           "box": _box_list(top.aabb()),
                           **({"children": [{"id": c.id, "name": c.name} for c in made[1:]]} if len(made) > 1 else {})})
    out = {"page": j + 1, "copies": copies,
           "note": "Put the copies in place with arrange or grid (pass their names), then rewrite their notes."}
    if adjusted:
        out["adjusted"] = adjusted
    dup = _duplicate_names(dest)
    if dup:
        out["warning"] = "Names used more than once on this page: " + ", ".join(dup)
    return out


def t_list_templates(t: Target, a: dict) -> dict:
    out = []
    for f in _template_files():
        try:
            out.append(_template_view(_read_template(f.stem)))
        except ToolError as e:
            out.append({"name": f.stem, "error": str(e)})
    return {"folder": str(_templates_dir()), "templates": out,
            "use": "Give a shape \"template\": \"<name>\" in create_shapes / update_shapes to style it the same way."}


def t_save_template(t: Target, a: dict) -> dict:
    import json
    name = _safe_template_name(a.get("name") or "")
    if not name:
        raise ToolError("name: what to call the template, e.g. \"Primary button\".")
    d = {"format": TEMPLATE_FORMAT, "fill": "", "stroke": "#111418", "stroke_width": 2.0, "radius": 0.0,
         "line_style": "solid", "cap": "round", "image": None}
    if a.get("from") is not None:
        _, pg = _page(t, a.get("page"))
        s = _shape(pg, a["from"])
        d.update(stroke=s.stroke or "#111418", stroke_width=s.stroke_width)
        if s.is_line:
            d.update(line_style=s.line_style, cap=s.cap)
        else:
            d.update(fill=s.fill or "", radius=s.radius)
            if isinstance(s.contents, dict) and s.contents.get("type") == "image":
                d["image"] = copy.deepcopy(s.contents)
    if "fill" in a:
        d["fill"] = _colour(a["fill"], "fill")
    if "stroke" in a:
        c = _colour(a["stroke"], "stroke")
        if c:
            d["stroke"] = c
        else:
            d["stroke_width"] = 0.0
    if "stroke_width" in a:
        d["stroke_width"] = max(0.0, _num(a["stroke_width"], "stroke_width"))
    if "radius" in a:
        d["radius"] = max(0.0, _num(a["radius"], "radius"))
    if "line_style" in a:
        if a["line_style"] not in ("solid", "dash", "dot"):
            raise ToolError("line_style: solid, dash or dot.")
        d["line_style"] = a["line_style"]
    if "cap" in a:
        if a["cap"] not in ("round", "flat", "square"):
            raise ToolError("cap: round, flat or square.")
        d["cap"] = a["cap"]
    folder = _templates_dir()
    path = folder / f"{name}.json"
    if path.exists() and not a.get("overwrite"):
        raise ToolError(f"A template named {name!r} exists already. Pass overwrite: true to replace it.")
    d["saved"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d["name"] = name
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, indent=2), encoding="utf-8")
    t.templates_changed()
    return {"saved": str(path), "template": _template_view(d)}


def _export_path(ref: str) -> Path:
    from . import doc as docmod
    from .export import safe_name
    p = Path(str(ref)).expanduser()
    tries = [p] if p.is_absolute() else [Path.cwd() / p, docmod.HOME / p, docmod.EXPORTS_DIR / p]
    for c in tries:
        if c.is_file():
            return c
    n = safe_name(str(ref))
    named = [f for f in (docmod.EXPORTS_DIR / n / f"{n}.compact.ui.json", docmod.EXPORTS_DIR / n / f"{n}.ui.json")
             if f.is_file()]
    if named:
        return max(named, key=lambda f: f.stat().st_mtime)  # the newest export of that project
    raise ToolError(f"No export file {ref!r}. Give a .ui.json path, or the name of a folder in {docmod.EXPORTS_DIR}.")


def t_import_export(t: Target, a: dict) -> dict:
    import json
    from . import export as exporter
    ref = a.get("file")
    if not ref:
        raise ToolError("file: a .ui.json export (full or compact), or a project name with a folder in exports/.")
    f = _export_path(ref)
    _guard_unsaved(t, a)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        pr = exporter.import_export(data, f.parent)
    except Exception as e:
        raise ToolError(f"Could not import {f}: {e}")
    if a.get("name"):
        pr.name = str(a["name"]).strip() or pr.name
    target = _project_path(pr.name)
    if target.exists() and not a.get("overwrite"):
        raise ToolError(f"A project {target.name} exists already. Pass name to save the import under another name, "
                        "or overwrite: true to replace it.")
    t.doc.import_project(pr)
    try:
        t.doc.save(target)
    except Exception as e:
        raise ToolError(f"Imported, but could not save {target}: {e}")
    t.loaded()
    out = t_get_status(t, {})
    out["imported_from"] = str(f)
    return out


def _size_from(a: dict, pg: Page | None):
    """width / height / preset / orientation -> (preset, w, h) or None when not given."""
    preset = a.get("preset")
    w, h, name = None, None, None
    if preset:
        hit = [p for p in PRESETS if p[1] == preset] or [p for p in PRESETS if p[1].lower() == str(preset).lower()] or \
              [p for p in PRESETS if str(preset).lower() in p[1].lower()]
        if not hit:
            raise ToolError(f"No preset {preset!r}. list_presets shows them all.")
        if len(hit) > 1 and not any(p[1].lower() == str(preset).lower() for p in hit):
            raise ToolError(f"{preset!r} matches {len(hit)} presets: " + "; ".join(p[1] for p in hit) + ".")
        _, name, w, h = hit[0]
    if a.get("width") is not None or a.get("height") is not None:
        w = int(_num(a.get("width", w if w else (pg.width if pg else 1920)), "width"))
        h = int(_num(a.get("height", h if h else (pg.height if pg else 1080)), "height"))
        if not preset:
            name = "Custom"
    o = a.get("orientation")
    if o is not None:
        if o not in ("portrait", "landscape"):
            raise ToolError("orientation: portrait or landscape.")
        if w is None and pg is not None:
            w, h, name = pg.width, pg.height, pg.preset
        if w is not None and ((o == "landscape") != (w > h)) and w != h:
            w, h = h, w
    if w is None:
        return None
    if not (16 <= w <= 20000 and 16 <= h <= 20000):
        raise ToolError("width and height: 16 to 20000 px.")
    return name, w, h


def _page_fields(t: Target, pg: Page, a: dict) -> None:
    if "name" in a and a["name"] is not None:
        pg.name = str(a["name"]).strip() or pg.name
    if "notes" in a:
        pg.notes = str(a["notes"] or "")
    if "background" in a:
        pg.background = _colour(a["background"], "background") or "#FFFFFF"
    if "margins" in a:
        m = _pad4(a["margins"])
        pg.margins = [max(0.0, v) for v in m]
        pg.margins_linked = len(set(pg.margins)) == 1
    for k in ("keep_inside", "show_margins", "dots"):
        if k in a:
            setattr(pg, k, bool(a[k]))
    if "dot_spacing" in a:
        pg.dot_spacing = min(400, max(1, int(_num(a["dot_spacing"], "dot_spacing"))))


def t_add_page(t: Target, a: dict) -> dict:
    d = t.doc
    pr = d.project
    pages = pr.pages
    after = len(pages) - 1
    if a.get("after") is not None:
        after = _page(t, a["after"])[0]
    if a.get("copy_of") is not None:
        _, src = _page(t, a["copy_of"])
        from .model import new_id
        p = Page.from_dict(copy.deepcopy(src.to_dict()))
        p.id = new_id()
        remap = {}
        for s in p.shapes:
            remap[s.id] = s.id = new_id()
        for g in p.groups:
            g["id"] = new_id()
            g["members"] = [remap[m] for m in g["members"] if m in remap]
        p.name = src.name + " copy"
    else:
        base = d.page
        p = Page(name=f"Page {len(pages) + 1}", width=base.width, height=base.height, preset=base.preset,
                 dots=base.dots, dot_spacing=base.dot_spacing, margins=list(base.margins),
                 margins_linked=base.margins_linked, keep_inside=base.keep_inside)
    size = _size_from(a, None)
    if size:
        p.preset, p.width, p.height = size
    _page_fields(t, p, a)
    pages.insert(after + 1, p)
    if after + 1 <= d.page_index and a.get("show") is False:
        d.page_index += 1
    if a.get("show", True):
        d.page_index = after + 1
        d.selection = []
        d.page_changed.emit()
    return {"page": describe_page(t, after + 1, p, shapes=False)}


def t_update_page(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    size = _size_from(a, pg)
    resized = False
    if size:
        resized = (size[1], size[2]) != (pg.width, pg.height)
        pg.preset, pg.width, pg.height = size
    _page_fields(t, pg, a)
    if a.get("position") is not None:
        pages = t.doc.project.pages
        j = int(_num(a["position"], "position")) - 1
        j = max(0, min(j, len(pages) - 1))
        cur = pages[t.doc.page_index]
        pages.insert(j, pages.pop(i))
        t.doc.page_index = pages.index(cur)
        i = j
    if resized:
        t.page_resized(i)
    out = {"page": describe_page(t, i, pg, shapes=False)}
    if resized and pg.shapes:
        out["note"] = "Shapes keep their pixel positions when the canvas changes size; check_layout shows any now past the edges."
    return out


def t_delete_page(t: Target, a: dict) -> dict:
    d = t.doc
    i, pg = _page(t, a.get("page"))
    if a.get("page") in (None, ""):
        raise ToolError("page: say which page to delete.")
    if len(d.project.pages) <= 1:
        raise ToolError("A project keeps at least one page.")
    del d.project.pages[i]
    d.page_index = max(0, min(d.page_index if d.page_index < i else d.page_index - 1, len(d.project.pages) - 1))
    d.selection = []
    d.page_changed.emit()
    return {"deleted": pg.name, "pages": [f"{n + 1} {p.name}" for n, p in enumerate(d.project.pages)]}


def t_set_project(t: Target, a: dict) -> dict:
    pr = t.doc.project
    if a.get("name") is not None:
        pr.name = str(a["name"]).strip() or pr.name
    if "brief" in a:
        pr.brief = str(a["brief"] or "")
    elif a.get("append_brief"):
        pr.brief = (pr.brief.rstrip() + "\n\n" if pr.brief.strip() else "") + str(a["append_brief"])
    return {"name": pr.name, "brief": pr.brief}


def _project_path(name_or_path: str) -> Path:
    from . import doc as docmod
    p = Path(str(name_or_path)).expanduser()
    if p.suffix.lower() == docmod.EXT and (p.is_absolute() or p.exists()):
        return p if p.is_absolute() else p.resolve()
    if p.is_absolute():
        return p
    return docmod.PROJECTS_DIR / (docmod.safe_name(str(name_or_path)) + docmod.EXT)


def _guard_unsaved(t: Target, a: dict) -> None:
    if t.doc.dirty and not a.get("discard"):
        raise ToolError(f"The open project \"{t.doc.project.name}\" has unsaved changes. Call save_project first, "
                        "or pass discard: true to drop them.")


def t_open_project(t: Target, a: dict) -> dict:
    ref = a.get("project") or a.get("name") or a.get("path")
    if not ref:
        raise ToolError("project: a project name (list_projects) or a .uxandi file path.")
    p = _project_path(ref)
    if not p.exists():
        raise ToolError(f"No project file {p}. list_projects shows the saved ones.")
    _guard_unsaved(t, a)
    try:
        t.doc.load(p)
    except Exception as e:
        raise ToolError(f"Could not open {p}: {e}")
    t.loaded()
    return t_get_status(t, {})


def t_new_project(t: Target, a: dict) -> dict:
    from . import doc as docmod
    _guard_unsaved(t, a)
    name = str(a.get("name") or "").strip()
    if name and _project_path(name).exists():
        raise ToolError(f"A project named {name!r} exists already: open_project it, or choose another name.")
    t.doc.new_project()
    if name:
        t.doc.project.name = name
    size = _size_from(a, None)
    if size:
        pg = t.doc.project.pages[0]
        pg.preset, pg.width, pg.height = size
    if a.get("brief"):
        t.doc.project.brief = str(a["brief"])
    t.doc._last = t.doc._snapshot()
    if name:
        t.doc.save(docmod.PROJECTS_DIR / (docmod.safe_name(name) + docmod.EXT))
    t.loaded()
    return t_get_status(t, {})


def t_save_project(t: Target, a: dict) -> dict:
    t.flush()
    d = t.doc
    target = None
    if a.get("name"):
        target = _project_path(a["name"])
        if target.exists() and target != d.path and not a.get("overwrite"):
            raise ToolError(f"{target.name} exists already. Pass overwrite: true to replace it, or pick another name.")
        d.project.name = Path(str(a["name"])).stem if str(a["name"]).lower().endswith(".uxandi") else str(a["name"]).strip()
        d.commit("Project renamed")
    try:
        path = d.save(target)
    except Exception as e:
        raise ToolError(f"Could not save: {e}")
    t.loaded()
    return {"saved": str(path), "name": d.project.name}


def t_export_json(t: Target, a: dict) -> dict:
    from . import doc as docmod
    from . import export as exporter
    t.flush()
    try:
        path, text = exporter.write_export(t.doc.project, docmod.EXPORTS_DIR, t.doc.snap.grid,
                                           compact=bool(a.get("compact", True)))
    except Exception as e:
        raise ToolError(f"Could not export: {e}")
    pr = t.doc.project
    n = sum(len(p.shapes) for p in pr.pages)
    empty = sum(1 for p in pr.pages for s in p.shapes if not s.notes.strip())
    out = {"file": str(path), "pages": len(pr.pages), "elements": n, "elements_without_notes": empty,
           "brief_empty": not pr.brief.strip(),
           "note": "Hand this file to the agent that builds the UI. Each export is also kept in history/."}
    if a.get("include_json"):
        import json
        out["json"] = json.loads(text)
    return out


def t_select(t: Target, a: dict) -> dict:
    i, pg = _page(t, a.get("page"))
    ids = [s.id for s in _shapes(pg, a.get("shapes", []))] if a.get("shapes") else []
    t.show(i, ids)
    return {"page": i + 1, "selected": [pg.get(x).name for x in ids]}


def t_history(t: Target, a: dict) -> dict:
    act = a.get("action", "undo")
    if act not in ("undo", "redo"):
        raise ToolError("action: undo or redo.")
    n = max(1, min(50, int(_num(a.get("steps", 1), "steps"))))
    d = t.doc
    stack = d._undo if act == "undo" else d._redo
    done = 0
    for _ in range(n):
        if not stack:
            break
        (d.undo if act == "undo" else d.redo)()
        done += 1
    return {"action": act, "steps_done": done, "steps_left": len(d._undo if act == "undo" else d._redo)}


def t_check_layout(t: Target, a: dict) -> dict:
    pages = t.doc.project.pages
    which = list(enumerate(pages)) if a.get("page") == "all" else [_page(t, a.get("page"))]
    issues = []
    pr = t.doc.project
    if not pr.brief.strip():
        issues.append({"level": "warning", "type": "brief_empty", "message": "The project brief is empty: set_project brief says what the product is."})
    for i, pg in which:
        issues += _check_page(i, pg)
    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda x: order[x["level"]])
    counts = {}
    for x in issues:
        counts[x["type"]] = counts.get(x["type"], 0) + 1
    limit = int(a.get("limit", 80))
    return {"ok": not any(x["level"] != "info" for x in issues), "counts": counts, "issues": issues[:limit],
            **({"more": len(issues) - limit} if len(issues) > limit else {})}


def _check_page(i: int, pg: Page) -> list:
    out = []
    P = f"page {i + 1}"
    nm = lambda s: s.name or s.id
    if not pg.notes.strip():
        out.append({"level": "warning", "type": "page_notes_empty", "page": i + 1, "message": f"{P} ({pg.name}) has no notes: say what this screen is for."})
    canvas = (0, 0, pg.width, pg.height)
    safe = pg.safe_rect()
    par = _parents(pg)
    boxes = {s.id: s.aabb() for s in pg.shapes}
    names = {}
    for s in pg.shapes:
        b = boxes[s.id]
        names.setdefault(s.name, []).append(s)
        if b[2] <= 0 or b[3] <= 0 or b[0] >= pg.width or b[1] >= pg.height:
            out.append({"level": "error", "type": "off_canvas", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} is completely off the canvas."})
        elif not _contains(canvas, b):
            out.append({"level": "warning", "type": "past_canvas_edge", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} runs past the canvas edge (box {_box_list(b)})."})
        elif any(pg.margins) and not _contains(safe, b):
            out.append({"level": "info", "type": "outside_safe_area", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} goes past the margins (safe area {_box_list(safe)})."})
        if s.is_line and s.length() < 2:
            out.append({"level": "warning", "type": "tiny", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} is a line shorter than 2 px."})
        if s.is_box and (s.w < 2 or s.h < 2):
            out.append({"level": "warning", "type": "tiny", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} is under 2 px wide or high."})
        if not s.name.strip():
            out.append({"level": "warning", "type": "no_name", "page": i + 1, "shapes": [s.id], "message": f"Shape {s.id} has no name."})
        elif GENERIC.match(s.name):
            out.append({"level": "info", "type": "generic_name", "page": i + 1, "shapes": [s.name], "message": f"{s.name} has a generic name: name it for what it is."})
        if not s.notes.strip():
            out.append({"level": "info", "type": "no_notes", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} has no notes."})
        if s.is_box and not s.fill and (s.stroke_width <= 0 or not s.stroke) and not s.contents:
            out.append({"level": "info", "type": "invisible", "page": i + 1, "shapes": [nm(s)], "message": f"{nm(s)} has no fill, border or picture, so it cannot be seen."})
    for n, ss in names.items():
        if n and len(ss) > 1:
            out.append({"level": "warning", "type": "duplicate_name", "page": i + 1, "shapes": [s.id for s in ss],
                        "message": f"{len(ss)} shapes are named {n!r}: names should be unique on a page."})
    # siblings that partly overlap (neither holds the other): usually a mistake
    sib = {}
    for s in pg.shapes:
        if s.is_box:            # lines and drawings cross things on purpose
            sib.setdefault(par[s.id], []).append(s)
    for pid, group in sib.items():
        for x in range(len(group)):
            for y in range(x + 1, len(group)):
                a_, b_ = group[x], group[y]
                A, B = boxes[a_.id], boxes[b_.id]
                ix = min(A[2], B[2]) - max(A[0], B[0])
                iy = min(A[3], B[3]) - max(A[1], B[1])
                if ix > 0.5 and iy > 0.5 and not _contains(A, B) and not _contains(B, A):
                    out.append({"level": "warning", "type": "overlap", "page": i + 1, "shapes": [nm(a_), nm(b_)],
                                "message": f"{nm(a_)} and {nm(b_)} overlap by {_r(ix)} x {_r(iy)} px."})
                else:
                    for k, label in ((0, "left"), (2, "right"), (1, "top"), (3, "bottom")):
                        d = abs(A[k] - B[k])
                        if 0.01 < d <= 2:
                            out.append({"level": "info", "type": "near_miss", "page": i + 1, "shapes": [nm(a_), nm(b_)],
                                        "message": f"{nm(a_)} and {nm(b_)}: {label} edges are {_r(d)} px apart; line them up?"})
                            break
        if pid:
            P_ = pg.get(pid)
            pb = boxes[pid]
            for s in group:
                b = boxes[s.id]
                for k, label in ((0, "left"), (1, "top"), (2, "right"), (3, "bottom")):
                    d = abs(b[k] - pb[k])
                    if 0.01 < d <= 2:
                        out.append({"level": "info", "type": "near_miss", "page": i + 1, "shapes": [nm(s), nm(P_)],
                                    "message": f"{nm(s)} sits {_r(d)} px from the {label} edge of {nm(P_)}: flush (0) or a real padding?"})
                        break
    return out


def t_screenshot(t: Target, a: dict) -> dict:
    max_size = int(_num(a.get("max_size", 1280), "max_size"))
    max_size = max(128, min(4096, max_size))
    if a.get("of") == "window":
        png = t.window_png(max_size)
        return {"_image": png, "of": "window"}
    i, pg = _page(t, a.get("page"))
    png, w, h = render_png(pg, max_size, labels=a.get("labels", True), margins=a.get("margins", True))
    return {"_image": png, "page": i + 1, "image_size": [w, h], "canvas": [pg.width, pg.height],
            "scale": _r(w / pg.width, 4)}


def render_png(pg: Page, max_size: int, labels=True, margins=True):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt, QPointF
    from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetricsF, QPen
    from .canvas import paint_shape
    sc = min(1.0, max_size / max(pg.width, pg.height))
    W, H = max(1, round(pg.width * sc)), max(1, round(pg.height * sc))
    img = QImage(W, H, QImage.Format.Format_ARGB32)
    img.fill(QColor(pg.background))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.save()
    p.scale(sc, sc)
    p.setClipRect(QRectF(0, 0, pg.width, pg.height))
    if margins and pg.show_margins and any(pg.margins):
        from PySide6.QtGui import QPainterPath
        l, t, r, b = pg.safe_rect()
        band = QPainterPath(); band.addRect(QRectF(0, 0, pg.width, pg.height))
        inner = QPainterPath(); inner.addRect(QRectF(l, t, r - l, b - t))
        p.fillPath(band.subtracted(inner), QColor(31, 111, 235, 22))
    for s in pg.shapes:
        paint_shape(p, s)
    p.restore()
    if labels:
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        fm = QFontMetricsF(f)
        for s in pg.shapes:
            if not s.name:
                continue
            b = s.aabb()
            x, y = b[0] * sc + 2, b[1] * sc + 2
            if s.is_line:
                x, y = min(s.x1, s.x2) * sc, min(s.y1, s.y2) * sc - fm.height() - 2
            tw = fm.horizontalAdvance(s.name) + 6
            rect = QRectF(x, max(0.0, y), tw, fm.height() + 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(17, 20, 24, 190))
            p.drawRoundedRect(rect, 3, 3)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(rect.adjusted(3, 1, -3, -1), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, s.name)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba.data()), W, H


# ============================================================================= the tool list
def _o(props: dict, req=()):
    return {"type": "object", "properties": props, "required": list(req), "additionalProperties": False}


PAGE = {"description": "Page number (1 = first), name or id. Leave out for the page on screen.",
        "anyOf": [{"type": "integer"}, {"type": "string"}]}
REF = {"type": "string", "description": "Shape id or exact name."}
REFS = {"type": "array", "items": REF, "description": "Shape ids or names."}
FRAME = {"type": "string", "description": "\"canvas\" (default), \"safe_area\" (inside the margins) or a rectangle's id / name."}
CARRY = {"type": "boolean", "description": "Shapes inside a moved rectangle move with it (default true)."}
POS = {"description": "Pixels from the frame's left / top, \"N%\" of the frame, or \"start\" / \"center\" / \"end\" with optional \"+N\" / \"-N\" (e.g. \"end-24\").",
       "anyOf": [{"type": "number"}, {"type": "string"}]}
LEN = {"description": "Pixels, or \"N%\" of the frame.", "anyOf": [{"type": "number"}, {"type": "string"}]}
DOT_SPACING = {"type": "integer", "minimum": 1, "maximum": 400,
               "description": "Dot grid spacing, px: 1 (finest) to 400. Dot snapping and arrow keys move in this step."}
COLOUR = {"description": "Hex \"#RRGGBB\" (or \"#AARRGGBB\", alpha first); null for none.", "type": ["string", "null"]}

SHAPE_FIELDS = {
    "name": {"type": "string", "description": "What it is, unique on the page: \"Header\", \"Sign in button\"."},
    "notes": {"type": "string", "description": "Everything the building agent must know: purpose, text it shows, behaviour, states, data."},
    "in": FRAME | {"description": "Frame that x / y / w / h are measured in: \"canvas\" (default), \"safe_area\", or a rectangle (place a child inside its parent)."},
    "x": POS, "y": POS, "w": LEN, "h": LEN,
    "box": {"type": "array", "items": {"type": "number"}, "description": "[x, y, w, h] in one field (absolute unless \"in\" is given)."},
    "rotation": {"type": "number", "description": "Degrees clockwise about the centre."},
    "radius": {"type": "number", "description": "Corner radius in px."},
    "fill": COLOUR, "fill_opacity": {"type": "number", "description": "0..1"},
    "stroke": COLOUR | {"description": "Border / line colour, hex; null for no border."},
    "stroke_opacity": {"type": "number", "description": "0..1"},
    "stroke_width": {"type": "number", "description": "Border thickness (inside the box) or line thickness, px. 0 = no border."},
    "lock_ratio": {"type": "boolean", "description": "Resizing in the app keeps proportions."},
    "points": {"type": "array", "items": {"anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"},
                                                                         "minItems": 2, "maxItems": 2}]},
               "description": "Line: [x1, y1, x2, y2]. Path (freehand drawing): [[x, y], [x, y], ...] in the frame \"in\"."},
    "x1": POS, "y1": POS, "x2": POS, "y2": POS,
    "line_style": {"enum": ["solid", "dash", "dot"]}, "cap": {"enum": ["round", "flat", "square"]},
    "image": {"description": "Picture inside a rectangle: {\"file\": path, \"fit\": fill|fit|stretch|original, \"zoom\", \"dx\", \"dy\", \"opacity\"}; null removes it.",
              "type": ["object", "null"]},
    "group": {"type": ["string", "null"], "description": "Put it in this named group (made if new); null takes it out."},
    "order": {"enum": ["front", "back", "forward", "backward"], "description": "Stacking order change."},
    "template": {"type": "string", "description": "Style it with a saved design template (list_templates): fill, border, "
                 "corners (lines: colour, thickness, dash, ends). Style fields given beside it win."},
    "flip_h": {"type": "boolean", "description": "Mirrored left-right (e.g. a back arrow made from a forward one)."},
    "flip_v": {"type": "boolean", "description": "Mirrored top-bottom."},
}

TOOLS = [
    # ---------------------------------------------------------------- read
    ("get_status", t_get_status, False, True,
     "Start here. The project (name, brief, file, unsaved changes), every page (size, device, shape count), the page on "
     "screen, the user's selection, dot snapping, and whether the app is open (live) or closed (file mode).",
     _o({})),
    ("get_page", t_get_page, False, True,
     "One page in full: canvas size, margins and safe area, notes, groups, every shape in stacking order (back first) with "
     "box [x, y, w, h], style, notes and parent, plus an indented outline of the nesting. The fields use the same names "
     "create_shapes / update_shapes take. full: true returns the export's exhaustive form instead.",
     _o({"page": PAGE, "full": {"type": "boolean"}})),
    ("screenshot", t_screenshot, False, True,
     "A PNG of a page (shape names drawn on it by default) so you can see the layout. of: \"window\" shows the whole app "
     "window as the user sees it (live mode only).",
     _o({"page": PAGE, "max_size": {"type": "integer", "description": "Longest side in px (default 1280)."},
         "labels": {"type": "boolean"}, "margins": {"type": "boolean"}, "of": {"enum": ["page", "window"]}})),
    ("check_layout", t_check_layout, False, True,
     "Find problems: shapes off or past the canvas, past the margins, partly overlapping siblings, edges 1-2 px off from "
     "a neighbour or the parent, tiny or invisible shapes, duplicate / generic names, missing notes, empty brief or page notes. "
     "Run it before export_json. page: \"all\" checks every page.",
     _o({"page": PAGE, "limit": {"type": "integer"}})),
    ("list_presets", t_list_presets, False, True,
     "Device canvas sizes (Desktop, iPad, Phone) for add_page / update_page preset.", _o({})),
    ("list_projects", t_list_projects, False, True, "Saved projects (projects/*.uxandi), newest first.", _o({})),
    # ---------------------------------------------------------------- build
    ("create_shapes", t_create_shapes, True, False,
     "Make one or many shapes on a page (one undo step). kind: rect (default), square, ellipse, circle (an ellipse that keeps w = h), line or path (a freehand stroke through points: [[x, y], ...], for marks and annotations; never a container). Ellipses are containers like rects. There is no text element: "
     "a label, heading or button is a rect whose name and notes say what it is and shows. Place children with "
     "\"in\": parent so x / y / w / h are measured inside it, e.g. {\"name\": \"Logo\", \"in\": \"Header\", \"x\": 24, "
     "\"y\": \"center\", \"w\": 120, \"h\": 40}. Missing x / y centre the shape in its frame. New shapes use the app's "
     "current new-shape style unless you set fill / stroke. Shapes are made in list order, so a later one can be \"in\" an earlier one.",
     _o({"page": PAGE, "shapes": {"type": "array", "items": {"type": "object", "properties": {
         "kind": {"enum": ["rect", "square", "ellipse", "circle", "line", "path"]}, **SHAPE_FIELDS}}}}, ["shapes"])),
    ("update_shapes", t_update_shapes, True, False,
     "Change shapes: any field create_shapes takes (geometry, style, name, notes, image, group, order), plus "
     "move: [dx, dy] and center: [x, y]. Rectangles carry the shapes inside them when they move (carry: false to stop that). "
     "Only the fields you give change.",
     _o({"page": PAGE, "changes": {"type": "array", "items": {"type": "object", "properties": {
         "shape": REF, **SHAPE_FIELDS, "move": {"type": "array", "items": {"type": "number"}},
         "center": {"type": "array", "items": {"type": "number"}}, "carry": CARRY}, "required": ["shape"]}}}, ["changes"])),
    ("delete_shapes", t_delete_shapes, True, False,
     "Delete shapes. with_children: true also deletes every shape inside them.",
     _o({"page": PAGE, "shapes": REFS, "with_children": {"type": "boolean"}}, ["shapes"])),
    ("duplicate_shapes", t_duplicate_shapes, True, False,
     "Copy shapes, each with everything inside it (with_children: false copies the shape alone). Build one card, row "
     "or nav bar, then make the rest from it: count copies, each offset [dx, dy] from the one before (default: one dot "
     "step down-right; [0, 0] on another page). to: another page, e.g. the same tab bar on every screen. Copies get the "
     "next free name (\"Card 1\" -> \"Card 2\"); children named after their container follow it (\"Card 1 price\" -> "
     "\"Card 2 price\"), or give names, one per copy. Then place them with grid / arrange and rewrite their notes.",
     _o({"page": PAGE, "shapes": REFS, "count": {"type": "integer", "minimum": 1, "maximum": 200},
         "offset": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
         "to": PAGE | {"description": "Page to put the copies on (default: the same page)."},
         "names": {"type": "array", "items": {"type": "string"},
                   "description": "Names for the copies: copy 1 of each shape in order, then copy 2, ..."},
         "with_children": {"type": "boolean"}}, ["shapes"])),
    ("arrange", t_arrange, True, False,
     "Flex-style layout: put shapes in a row or column inside a container (or the canvas / safe area), with gap and "
     "padding. sizes, one per shape along the direction: px, \"N%\", \"Nfr\" (share of the space left; default all \"1fr\") "
     "or \"auto\" (keep size). align across: stretch (default), start, center, end (cross_size sets their size). "
     "justify (when nothing is fr): start, center, end, space-between, space-around. Example: header row "
     "{\"shapes\": [\"Logo\", \"Nav\", \"Account\"], \"into\": \"Header\", \"padding\": [12, 24], \"gap\": 16, "
     "\"sizes\": [120, \"1fr\", 160]}. Contents of arranged rectangles move with them.",
     _o({"page": PAGE, "shapes": REFS, "into": FRAME, "direction": {"enum": ["row", "column"]},
         "gap": {"type": "number"}, "padding": {"description": "px, [vertical, horizontal] or [top, right, bottom, left]",
                                                "anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]},
         "sizes": {"type": "array", "items": {"anyOf": [{"type": "number"}, {"type": "string"}]}},
         "align": {"enum": ["stretch", "start", "center", "end"]}, "cross_size": LEN,
         "justify": {"enum": ["start", "center", "end", "space-between", "space-around"]}, "carry": CARRY}, ["shapes"])),
    ("grid", t_grid, True, False,
     "Put shapes in a grid inside a container, row by row: columns, gap (px or [x, y]), padding, and row height "
     "(row_height px / \"N%\", or aspect = width / height of each cell; default: rows share the height). Good for card grids, galleries, tiles.",
     _o({"page": PAGE, "shapes": REFS, "into": FRAME, "columns": {"type": "integer"},
         "gap": {"anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]},
         "padding": {"anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]},
         "row_height": LEN, "aspect": {"type": "number"}, "carry": CARRY}, ["shapes", "columns"])),
    ("align", t_align, True, False,
     "Line shapes up by an edge or centre: left, right, top, bottom, center_x, center_y. to: \"together\" (default: "
     "their combined box), \"canvas\", \"safe_area\" or a shape. E.g. centre a dialog: {\"shapes\": [\"Dialog\"], "
     "\"edge\": \"center_x\", \"to\": \"canvas\"}.",
     _o({"page": PAGE, "shapes": REFS, "edge": {"enum": ["left", "right", "top", "bottom", "center_x", "center_y"]},
         "to": FRAME, "carry": CARRY}, ["shapes", "edge"])),
    ("distribute", t_distribute, True, False,
     "Space shapes evenly along x or y (keeping the first and last where they are), or with an exact gap from the first.",
     _o({"page": PAGE, "shapes": REFS, "axis": {"enum": ["x", "y"]}, "gap": {"type": "number"}, "carry": CARRY}, ["shapes"])),
    ("set_group", t_set_group, True, False,
     "Make or change a named group of shapes (a shape is in one group at most). An empty shapes list removes the group "
     "(the shapes stay).",
     _o({"page": PAGE, "name": {"type": "string"}, "shapes": REFS}, ["name", "shapes"])),
    # ---------------------------------------------------------------- pages and project
    ("add_page", t_add_page, True, False,
     "Add a page (a screen). Size from preset (list_presets: e.g. \"iPhone 16 Pro\", \"Full HD 1920 x 1080\") or "
     "width + height; orientation portrait / landscape. copy_of copies a page with its shapes. It opens on screen "
     "unless show: false. Also takes the update_page settings.",
     _o({"name": {"type": "string"}, "notes": {"type": "string"}, "preset": {"type": "string"},
         "width": {"type": "integer"}, "height": {"type": "integer"}, "orientation": {"enum": ["portrait", "landscape"]},
         "copy_of": PAGE, "after": PAGE, "show": {"type": "boolean"}, "background": COLOUR,
         "margins": {"anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]},
         "keep_inside": {"type": "boolean"}, "show_margins": {"type": "boolean"}, "dots": {"type": "boolean"},
         "dot_spacing": DOT_SPACING})),
    ("update_page", t_update_page, True, False,
     "Change a page: name, notes (what this screen is), size (preset / width / height / orientation), background, "
     "margins (px or [top, right, bottom, left]), keep_inside (shapes kept inside the margins), show_margins, dots, "
     "dot_spacing, position (move it to that page number). Shapes keep their pixel positions when the size changes.",
     _o({"page": PAGE, "name": {"type": "string"}, "notes": {"type": "string"}, "preset": {"type": "string"},
         "width": {"type": "integer"}, "height": {"type": "integer"}, "orientation": {"enum": ["portrait", "landscape"]},
         "background": COLOUR, "margins": {"anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]},
         "keep_inside": {"type": "boolean"}, "show_margins": {"type": "boolean"}, "dots": {"type": "boolean"},
         "dot_spacing": DOT_SPACING, "position": {"type": "integer"}})),
    ("delete_page", t_delete_page, True, False, "Delete a page and its shapes.", _o({"page": PAGE}, ["page"])),
    ("set_project", t_set_project, True, False,
     "Set the project name and the brief: what the product is, who it is for, style and rules for the building agent. "
     "append_brief adds a paragraph instead of replacing.",
     _o({"name": {"type": "string"}, "brief": {"type": "string"}, "append_brief": {"type": "string"}})),
    # ---------------------------------------------------------------- files
    ("open_project", t_open_project, False, False,
     "Open a saved project by name (list_projects) or .uxandi path. Refuses when the open one has unsaved changes "
     "unless discard: true (or save_project first).",
     _o({"project": {"type": "string"}, "discard": {"type": "boolean"}}, ["project"])),
    ("new_project", t_new_project, False, False,
     "Start a new project with one page. With a name it is saved at once as projects/<name>.uxandi. Optional "
     "preset / width / height / orientation for the first page, and brief.",
     _o({"name": {"type": "string"}, "brief": {"type": "string"}, "preset": {"type": "string"},
         "width": {"type": "integer"}, "height": {"type": "integer"}, "orientation": {"enum": ["portrait", "landscape"]},
         "discard": {"type": "boolean"}})),
    ("save_project", t_save_project, False, False,
     "Save the project (projects/<name>.uxandi). name saves it under a new name (overwrite: true replaces an existing file). "
     "In file mode every change is saved already.",
     _o({"name": {"type": "string"}, "overwrite": {"type": "boolean"}})),
    ("export_json", t_export_json, False, False,
     "Write the agent brief: exports/<project>/<project>.compact.ui.json (plus a dated copy in history/). Returns the "
     "path and how many elements still lack notes. The default compact form leaves out empty, default and derivable "
     "values (about 5x smaller, made for an LLM builder; how_to_read lists every default). compact: false writes the "
     "full form <project>.ui.json instead, every field written out (for code that parses it). include_json: true also "
     "returns the JSON. Formats: schema/ui.compact.schema.json, full: schema/ui.schema.json.",
     _o({"compact": {"type": "boolean", "default": True,
                     "description": "true (default): compact form. false: full form, every field written out."},
         "include_json": {"type": "boolean"}})),
    ("import_export", t_import_export, False, False,
     "Load a .ui.json export (full or compact) as a project and save it as projects/<name>.uxandi: round-trip a "
     "brief, or start from one another tool or agent wrote. file: a path, or a project name with a folder in exports/. "
     "name saves it under another name; overwrite: true replaces a project of that name. Refuses when the open "
     "project has unsaved changes unless discard: true.",
     _o({"file": {"type": "string"}, "name": {"type": "string"}, "overwrite": {"type": "boolean"},
         "discard": {"type": "boolean"}}, ["file"])),
    # ---------------------------------------------------------------- design templates
    ("list_templates", t_list_templates, False, True,
     "The saved design templates (the Design tab's styles: fill, border, corners, line dash). Use one on a shape with "
     "\"template\": \"<name>\" in create_shapes / update_shapes, so the same kind of element looks the same everywhere.",
     _o({})),
    ("save_template", t_save_template, False, False,
     "Save a design template the user can also pick in the Design tab: from: a shape to copy its style, and / or the "
     "fields fill, stroke, stroke_width, radius, line_style, cap. Good for a small style kit: \"Primary button\", "
     "\"Card\", \"Divider\". overwrite: true replaces one of that name.",
     _o({"name": {"type": "string"}, "from": REF, "page": PAGE, "fill": COLOUR, "stroke": COLOUR,
         "stroke_width": {"type": "number"}, "radius": {"type": "number"},
         "line_style": {"enum": ["solid", "dash", "dot"]}, "cap": {"enum": ["round", "flat", "square"]},
         "overwrite": {"type": "boolean"}}, ["name"])),
    # ---------------------------------------------------------------- session
    ("select", t_select, False, False,
     "Show a page on the user's screen and select shapes there (to point something out). No shapes: just show the page.",
     _o({"page": PAGE, "shapes": REFS})),
    ("history", t_history, False, False,
     "Undo or redo (action), steps times. Every command an agent sends is one step, like an edit by hand.",
     _o({"action": {"enum": ["undo", "redo"]}, "steps": {"type": "integer"}})),
    ("batch", None, True, False,
     "Run many commands in order as ONE step: one undo, and all or nothing (if one fails, none of them is kept). "
     "calls: [{\"tool\": \"create_shapes\", \"args\": {...}}, {\"tool\": \"arrange\", \"args\": {...}}, ...]. "
     "Any build, page or project command can go in a batch; files, templates, history, select and screenshot cannot.",
     _o({"calls": {"type": "array", "items": {"type": "object", "properties": {
         "tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["tool"]}}}, ["calls"])),
]

BY_NAME = {name: (fn, mut, ro, desc, schema) for name, fn, mut, ro, desc, schema in TOOLS}
NO_BATCH = {"open_project", "new_project", "save_project", "export_json", "import_export", "save_template",
            "select", "history", "batch", "screenshot"}
BY_NAME["batch"][4]["properties"]["calls"]["items"]["properties"]["tool"]["enum"] = [
    n for n, *_ in TOOLS if n not in NO_BATCH]
DESTRUCTIVE = {"delete_shapes", "delete_page", "new_project", "open_project", "import_export"}


def tool_list() -> list:
    """For MCP tools/list."""
    out = []
    for name, fn, mut, ro, desc, schema in TOOLS:
        out.append({"name": name, "description": desc, "inputSchema": schema,
                    "annotations": {"readOnlyHint": ro, "destructiveHint": name in DESTRUCTIVE,
                                    "idempotentHint": ro, "openWorldHint": False}})
    return out


def _label(name: str, res: dict) -> str:
    if name == "create_shapes":
        n = len(res.get("created", []))
        return f"Agent: added {n} shape{'s' if n != 1 else ''}"
    if name == "update_shapes":
        n = len(res.get("updated", []))
        return f"Agent: changed {n} shape{'s' if n != 1 else ''}"
    if name == "delete_shapes":
        return f"Agent: deleted {res.get('deleted', 0)}"
    return "Agent: " + name.replace("_", " ")


def call(t: Target, name: str, args: dict | None) -> dict:
    """Run one command. Returns a result dict; a screenshot's PNG bytes are under "_image".
    Raises ToolError for a bad request (nothing is changed then)."""
    if name not in BY_NAME:
        raise ToolError(f"Unknown tool {name!r}. Tools: " + ", ".join(BY_NAME))
    args = args or {}
    if not isinstance(args, dict):
        raise ToolError("Arguments must be an object.")
    t.before()
    fn, mut, ro, _, _ = BY_NAME[name]
    if not mut:
        if name not in ("get_status", "list_presets", "list_projects"):
            t.flush()
        res = fn(t, args)
        if name in ("history", "select") and not t.live:
            t.persist()
        return res
    t.flush()
    d = t.doc
    start = d._last
    try:
        if name == "batch":
            res = _batch(t, args)
        else:
            res = fn(t, args)
    except Exception:
        d._restore(start)          # all or nothing
        raise
    d.structure.emit()
    d.changed.emit()
    d.selection_changed.emit()
    d.commit(_label(name, res) if name != "batch" else f"Agent: {len(args.get('calls', []))} steps")
    t.persist()
    return res


def _batch(t: Target, a: dict) -> dict:
    calls = a.get("calls")
    if not isinstance(calls, list) or not calls:
        raise ToolError("calls: a list of {\"tool\": name, \"args\": {...}}.")
    results = []
    for n, c in enumerate(calls):
        if not isinstance(c, dict) or "tool" not in c:
            raise ToolError(f"calls[{n}]: {{\"tool\": name, \"args\": {{...}}}}.")
        nm = c["tool"]
        if nm in NO_BATCH:
            raise ToolError(f"calls[{n}]: {nm} cannot run inside a batch; call it on its own.")
        if nm not in BY_NAME:
            raise ToolError(f"calls[{n}]: unknown tool {nm!r}.")
        try:
            results.append({"tool": nm, "result": BY_NAME[nm][0](t, c.get("args") or {})})
        except ToolError as e:
            raise ToolError(f"Batch step {n + 1} ({nm}) failed, so nothing was changed: {e}")
    return {"steps": len(results), "results": results}


def png_b64(png: bytes) -> str:
    return base64.b64encode(png).decode("ascii")
