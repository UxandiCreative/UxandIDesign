"""The agent export: one JSON file that tells an AI agent everything about the layout.

exports/
  <project>/
    <project>.ui.json                 the newest export: hand this to the agent
    history/<project>_<date_time>.json every export ever made, newest last

The export also loads back into the app (Open > Import an export...).
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from .model import PRESETS, Project, Page, Shape, norm_deg, new_id, now_iso, parents_of

EXPORT_FORMAT = "uxandi-export"
EXPORT_VERSION = 1
SCHEMA_URL = "https://raw.githubusercontent.com/UxandiCreative/UxandIDesign/main/schema/"
EXPORT_SCHEMA = SCHEMA_URL + "ui.schema.json"            # the format, as JSON Schema (uxandi/schemas.py)
COMPACT_SCHEMA = SCHEMA_URL + "ui.compact.schema.json"

HOW_TO_READ = [
    "This file describes a layout made in Uxandi: pages, and the rectangles, squares, ellipses, circles and lines placed on them.",
    "An ellipse or circle is the oval that fills its box exactly; it is a container like a rectangle (nesting still uses its box).",
    "A 'path' is a freehand stroke the user drew: 'path.points' are canvas points in drawing order (rotation and flips "
    "applied), drawn as one smooth stroke with 'style'. It never holds other elements. What it means (a circled area, "
    "an arrow, a mark, a correction) is in its notes.",
    "'project.brief' and every 'notes' field (on pages and on elements) are text written by the user, exported exactly as written.",
    "Each page is one canvas. 'canvas' gives its size in pixels and the device preset it was set to (Desktop, iPad, Phone or Custom).",
    "Coordinates are canvas pixels. The origin (0, 0) is the top-left corner of the canvas; x grows to the right, y grows downward.",
    "'bounds' is an element's own box before rotation (x, y = its top-left corner). 'visual_bounds' is the box it covers after rotation.",
    "'relative' gives the visual box as percentages of the canvas width and height.",
    "'z' is the stacking order: 1 is at the back, higher numbers are drawn on top.",
    "'parent' / 'children' and 'layout_tree' show nesting: an element whose box lies completely inside another element's box is its child. "
    "When several boxes hold it, the parent is the smallest one drawn beneath it, unless a filled box drawn over that one "
    "(a scrim, an overlay) also holds it.",
    "'groups' are sets of elements the user grouped, by name. A group's 'notes' say what the group as a whole is and does; "
    "they are separate from each member's own notes.",
    "'elements_without_notes' (per page, and for the whole project in 'summary') lists the elements whose 'notes' field is empty. "
    "'summary' also counts them, says whether 'project.brief' is empty and lists pages whose 'notes' are empty.",
    "'margins' are the distances from the canvas edges set by the user; 'margins.safe_area' is the box inside them.",
    "Colours are hex #RRGGBB. Each colour has its own opacity next to it (1 = solid, 0 = invisible), e.g. 'fill' + 'fill_opacity'. A null colour means none (no fill, no border).",
    "Border width is in pixels and sits inside the element's box. 'corner_radius' rounds the corners, in pixels.",
    "'contents' with type 'image' is a picture shown inside the element, clipped to its rounded box. 'file' is relative to this JSON file. "
    "'fit': fill = cover the box and crop the rest, fit = whole picture inside the box, stretch = scaled to the box, original = 1 image pixel per canvas pixel. "
    "'zoom' scales it further, 'offset' moves its centre from the box centre (pixels), 'opacity' fades it.",
]


def split_colour(c):
    """'#RRGGBB' or '#AARRGGBB' -> ('#RRGGBB', opacity 0..1); '' -> (None, None)."""
    if not c:
        return None, None
    c = c.strip()
    if len(c) == 9 and c.startswith("#"):
        a = int(c[1:3], 16) / 255
        return "#" + c[3:].upper(), round(a, 3)
    return c.upper(), 1


def join_colour(hex_rgb, opacity):
    if not hex_rgb:
        return ""
    if opacity is None or float(opacity) >= 0.999:
        return hex_rgb
    return "#%02X%s" % (int(round(float(opacity) * 255)), hex_rgb.lstrip("#").upper())


def _contents(s, image_map):
    from .images import image_of, size_of
    img = image_of(s)
    if not img:
        return s.contents
    path = img.get("path", "")
    sz = size_of(path)
    return {"type": "image", "file": (image_map or {}).get(path, path), "original_name": img.get("original_name", ""),
            "pixel_size": {"width": sz[0], "height": sz[1]} if sz else None,
            "fit": img.get("fit", "fill"), "zoom": _r(img.get("zoom", 1)),
            "offset": {"x": _r(img.get("dx", 0)), "y": _r(img.get("dy", 0))},
            "opacity": _r(img.get("opacity", 1))}


def _r(v: float, n: int = 2):
    v = round(float(v), n)
    return int(v) if v == int(v) else v


def _device(page: Page) -> str:
    if page.preset in ("My screen", "This screen"):
        return "Desktop"
    for g, name, w, h in PRESETS:
        if name == page.preset:
            return g
    return "Custom"


def _box(b):
    return {"x": _r(b[0]), "y": _r(b[1]), "width": _r(b[2] - b[0]), "height": _r(b[3] - b[1])}


def _contains(outer, inner, eps=0.01):
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps
            and outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


def _element_type(s: Shape) -> str:
    if s.is_line:
        return "line"
    if s.is_path:
        return "path"
    if s.is_ellipse:
        return "circle" if abs(s.w - s.h) < 0.5 else "ellipse"
    return "square" if abs(s.w - s.h) < 0.5 else "rectangle"


def page_export(page: Page, index: int, image_map: dict | None = None) -> dict:
    W, H = page.width, page.height
    shapes = page.shapes
    boxes = {s.id: s.aabb() for s in shapes}
    z = {s.id: i + 1 for i, s in enumerate(shapes)}

    # nesting: the smallest rectangle drawn beneath the element that completely holds it
    parent = parents_of(shapes)
    children = {s.id: [] for s in shapes}
    for sid, pid in parent.items():
        if pid:
            children[pid].append(sid)

    group_name = {}
    for g in page.groups:
        for m in g["members"]:
            group_name[m] = g["name"]
    t, r, b_, l = page.margins
    safe = page.safe_rect()

    elements = []
    for s in shapes:
        bb = boxes[s.id]
        e = {
            "id": s.id,
            "name": s.name,
            "type": _element_type(s),
            "notes": s.notes,
            "group": group_name.get(s.id),
            "z": z[s.id],
            "parent": parent[s.id],
            "children": sorted(children[s.id], key=lambda i: z[i]),
        }
        if s.is_line:
            e["line"] = {"start": {"x": _r(s.x1), "y": _r(s.y1)}, "end": {"x": _r(s.x2), "y": _r(s.y2)},
                         "length": _r(s.length()), "angle_degrees": _r(norm_deg(s.angle()))}
            e["visual_bounds"] = _box(bb)
            lc, lo = split_colour(s.stroke)
            e["style"] = {"color": lc, "opacity": lo, "thickness": _r(s.stroke_width), "dash": s.line_style, "ends": s.cap}
        elif s.is_path:
            e["path"] = {"points": [[_r(x), _r(y)] for x, y in s.path_points()]}
            e["bounds"] = {"x": _r(s.x), "y": _r(s.y), "width": _r(s.w), "height": _r(s.h)}
            e["rotation_degrees"] = _r(s.rotation)
            e["visual_bounds"] = _box(bb)
            lc, lo = split_colour(s.stroke)
            e["style"] = {"color": lc, "opacity": lo, "thickness": _r(s.stroke_width), "dash": s.line_style, "ends": s.cap}
        else:
            e["bounds"] = {"x": _r(s.x), "y": _r(s.y), "width": _r(s.w), "height": _r(s.h)}
            e["rotation_degrees"] = _r(s.rotation)
            e["visual_bounds"] = _box(bb)
            e["center"] = {"x": _r(s.x + s.w / 2), "y": _r(s.y + s.h / 2)}
            fc, fo = split_colour(s.fill)
            bc, bo = split_colour(s.stroke) if s.stroke_width > 0 else (None, None)
            e["style"] = {"fill": fc, "fill_opacity": fo, "border_color": bc, "border_opacity": bo,
                          "border_width": _r(s.stroke_width),
                          "corner_radius": 0 if s.is_ellipse else _r(min(s.radius, s.max_radius()))}
            e["keeps_proportions"] = bool(s.lock_ratio)
        e["relative"] = {"x_pct": _r(100 * bb[0] / W), "y_pct": _r(100 * bb[1] / H),
                         "width_pct": _r(100 * (bb[2] - bb[0]) / W), "height_pct": _r(100 * (bb[3] - bb[1]) / H)}
        e["inside_safe_area"] = _contains(safe, bb)
        e["flipped"] = {"horizontal": s.flip_h, "vertical": s.flip_v}
        e["contents"] = _contents(s, image_map)
        e["created"], e["modified"] = s.created, s.modified
        elements.append(e)

    def tree(pid):
        kids = [s.id for s in shapes if parent[s.id] == pid]
        kids.sort(key=lambda i: z[i])
        by = {s.id: s for s in shapes}
        return [{"id": k, "name": by[k].name, "children": tree(k)} for k in kids]

    groups = []
    for g in page.groups:
        mb = [boxes[m] for m in g["members"] if m in boxes]
        u = (min(x[0] for x in mb), min(x[1] for x in mb), max(x[2] for x in mb), max(x[3] for x in mb)) if mb else (0, 0, 0, 0)
        groups.append({"id": g["id"], "name": g["name"], "notes": g.get("notes") or "", "members": list(g["members"]),
                       "member_names": [next((s.name for s in shapes if s.id == m), m) for m in g["members"]],
                       "bounds": _box(u)})

    return {
        "index": index,
        "id": page.id,
        "name": page.name,
        "notes": page.notes,
        "canvas": {"width": W, "height": H, "device": _device(page), "preset": page.preset,
                   "orientation": "landscape" if W > H else ("portrait" if H > W else "square"),
                   "background": page.background},
        "margins": {"top": _r(t), "right": _r(r), "bottom": _r(b_), "left": _r(l),
                    "safe_area": _box(safe), "content_kept_inside": page.keep_inside},
        "grid": {"dot_spacing": page.dot_spacing, "dots_visible": page.dots},
        "element_count": len(elements),
        "elements_without_notes": [{"id": e["id"], "name": e["name"], "type": e["type"]}
                                   for e in elements if not (e["notes"] or "").strip()],
        "groups": groups,
        "layout_tree": tree(None),
        "elements": elements,
    }


def build_export(project: Project, snap_to_dots: bool = False, image_map: dict | None = None) -> dict:
    pages = [page_export(p, i + 1, image_map) for i, p in enumerate(project.pages)]
    missing = [{"page": pg["index"], "page_name": pg["name"], **e} for pg in pages for e in pg["elements_without_notes"]]
    total = sum(pg["element_count"] for pg in pages)
    return {
        "$schema": EXPORT_SCHEMA,
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "tool": "Uxandi",
        "exported": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "how_to_read": HOW_TO_READ,
        "project": {"name": project.name, "brief": project.brief, "page_count": len(project.pages),
                    "created": project.created, "layout_snapped_to_dots": bool(snap_to_dots)},
        "summary": {"element_count": total, "elements_with_notes": total - len(missing),
                    "elements_without_notes_count": len(missing), "elements_without_notes": missing,
                    "brief_empty": not (project.brief or "").strip(),
                    "pages_without_notes": [{"page": pg["index"], "page_name": pg["name"]}
                                            for pg in pages if not (pg["notes"] or "").strip()]},
        "pages": pages,
    }


# ---------------------------------------------------------------------------- compact export
# The same facts as the full export, without repeated, derivable or default values, so an agent
# reading it spends far fewer tokens. Every left-out field has a fixed default, listed below.

COMPACT_HOW_TO_READ = [
    "This file describes a layout made in Uxandi: pages, and the rectangles, squares and lines placed on them. "
    "It is the compact form of the Uxandi export: the same facts, with empty, default and derivable values left out.",
    "'project.brief' and every 'notes' field (on pages and on elements) are text written by the user, exported exactly as written.",
    "Each page is one canvas. 'canvas' gives its size in pixels and the device preset it was set to (Desktop, iPad, Phone or Custom).",
    "Coordinates are canvas pixels. The origin (0, 0) is the top-left corner of the canvas; x grows to the right, y grows downward.",
    "An element with 'type' ellipse or circle is the oval that fills its 'box' exactly (a container like a rectangle; nesting still uses its box).",
    "'box' is [x, y, width, height]: an element's own box before rotation, x and y = its top-left corner. "
    "A rotated element also has 'rotation_degrees' and 'visual_box', the box it covers after rotation.",
    "A line has 'line': {'start': [x, y], 'end': [x, y]} and a 'style' with its colour and thickness.",
    "A 'path' is a freehand stroke the user drew: 'points' are canvas points [x, y] in drawing order, drawn as one "
    "smooth stroke with 'style'. It never holds other elements. What it means (a circled area, an arrow, a mark) is in its notes.",
    "'elements' are listed in stacking order: the first is at the back, each later one is drawn on top of the earlier ones.",
    "'parent' is the id of the element whose box completely holds this one (nesting; when several do, the smallest one "
    "drawn beneath it that no filled box in between covers). No 'parent' means it sits directly on the canvas.",
    "'group' is the name of the user's group the element belongs to; 'groups' lists each group's members by id, "
    "with the group's own 'notes' (what the group as a whole is and does) when it has any.",
    "Colours are hex #RRGGBB. An opacity is given only when it is below 1 (e.g. 'fill_opacity').",
    "Border width is in pixels and sits inside the element's box. 'corner_radius' rounds the corners, in pixels.",
    "'contents' with type 'image' is a picture shown inside the element, clipped to its rounded box. 'file' is relative to this JSON file. "
    "'fit': fill = cover the box and crop the rest, fit = whole picture inside the box, stretch = scaled to the box, original = 1 image pixel per canvas pixel. "
    "'zoom' scales it further, 'offset' moves its centre from the box centre (pixels), 'opacity' fades it.",
    "'margins' are the distances from the canvas edges set by the user. 'grid.dot_spacing' is the spacing of the page's dot grid in pixels.",
    "'elements_without_notes' (per page) lists the names of elements whose 'notes' are empty; 'summary' counts them for the whole project.",
    "A field that is left out has its default: type = rectangle, notes = empty, parent = none, group = none, fill = none, "
    "border = none, opacities = 1, corner_radius = 0, rotation = 0, not flipped, keeps_proportions = false, no contents, "
    "inside the margins (an element that is not has 'outside_safe_area': true), page notes = empty, margins = 0.",
]


def _xy(p):
    return [p["x"], p["y"]]


def _compact_element(e: dict) -> dict:
    c = {"id": e["id"], "name": e["name"]}
    if e["type"] != "rectangle":
        c["type"] = e["type"]
    if (e.get("notes") or "").strip():
        c["notes"] = e["notes"]
    if e.get("parent"):
        c["parent"] = e["parent"]
    if e.get("group"):
        c["group"] = e["group"]
    st = e["style"]
    if e["type"] == "path":
        c["points"] = e["path"]["points"]
    if e["type"] in ("line", "path"):
        if e["type"] == "line":
            c["line"] = {"start": _xy(e["line"]["start"]), "end": _xy(e["line"]["end"])}
        s = {"color": st["color"], "thickness": st["thickness"]}
        if st.get("opacity") not in (None, 1):
            s["opacity"] = st["opacity"]
        if st.get("dash") not in (None, "solid"):
            s["dash"] = st["dash"]
        if st.get("ends") not in (None, "round"):
            s["ends"] = st["ends"]
        c["style"] = s
    else:
        b = e["bounds"]
        c["box"] = [b["x"], b["y"], b["width"], b["height"]]
        if e.get("rotation_degrees"):
            v = e["visual_bounds"]
            c["rotation_degrees"] = e["rotation_degrees"]
            c["visual_box"] = [v["x"], v["y"], v["width"], v["height"]]
        s = {}
        if st.get("fill"):
            s["fill"] = st["fill"]
            if st.get("fill_opacity") not in (None, 1):
                s["fill_opacity"] = st["fill_opacity"]
        if st.get("border_color") and st.get("border_width"):
            s["border_color"] = st["border_color"]
            s["border_width"] = st["border_width"]
            if st.get("border_opacity") not in (None, 1):
                s["border_opacity"] = st["border_opacity"]
        if st.get("corner_radius"):
            s["corner_radius"] = st["corner_radius"]
        if s:
            c["style"] = s
        if e.get("keeps_proportions"):
            c["keeps_proportions"] = True
    if not e.get("inside_safe_area", True):
        c["outside_safe_area"] = True
    fl = {k: True for k, v in (e.get("flipped") or {}).items() if v}
    if fl:
        c["flipped"] = fl
    if e.get("contents"):
        c["contents"] = e["contents"]
    return c


def compact_export(full: dict) -> dict:
    """The compact form of an export made by build_export (same facts, much smaller)."""
    pages = []
    for pg in full["pages"]:
        m = pg["margins"]
        p = {"index": pg["index"], "id": pg["id"], "name": pg["name"]}
        if (pg.get("notes") or "").strip():
            p["notes"] = pg["notes"]
        p["canvas"] = pg["canvas"]
        if any(m[k] for k in ("top", "right", "bottom", "left")):
            p["margins"] = {k: m[k] for k in ("top", "right", "bottom", "left")}
        p["grid"] = {"dot_spacing": pg["grid"]["dot_spacing"]}
        p["element_count"] = pg["element_count"]
        if pg["elements_without_notes"]:
            p["elements_without_notes"] = [e["name"] for e in pg["elements_without_notes"]]
        if pg["groups"]:
            p["groups"] = [{"name": g["name"], **({"notes": g["notes"]} if (g.get("notes") or "").strip() else {}),
                            "members": g["members"]} for g in pg["groups"]]
        p["elements"] = [_compact_element(e) for e in pg["elements"]]
        pages.append(p)
    pj, sm = full["project"], full["summary"]
    project = {"name": pj["name"], "brief": pj["brief"], "page_count": pj["page_count"]}
    if pj.get("layout_snapped_to_dots"):
        project["layout_snapped_to_dots"] = True
    return {
        "$schema": COMPACT_SCHEMA,
        "format": full["format"], "version": full["version"], "compact": True, "tool": full["tool"],
        "exported": full["exported"], "how_to_read": COMPACT_HOW_TO_READ, "project": project,
        "summary": {"element_count": sm["element_count"], "elements_without_notes_count": sm["elements_without_notes_count"],
                    "brief_empty": sm["brief_empty"],
                    "pages_without_notes": [p["page"] for p in sm["pages_without_notes"]]},
        "pages": pages,
    }


def dumps_compact(data: dict) -> str:
    """Readable but small: the outline is indented, each element sits on one line."""
    rows = {}
    for pi, pg in enumerate(data["pages"]):
        for ei, e in enumerate(pg["elements"]):
            rows[f"@@E{pi}_{ei}@@"] = json.dumps(e, ensure_ascii=False, separators=(",", ":"))
    shell = {**data, "pages": [{**pg, "elements": [f"@@E{pi}_{ei}@@" for ei in range(len(pg["elements"]))]}
                               for pi, pg in enumerate(data["pages"])]}
    text = json.dumps(shell, indent=1, ensure_ascii=False)
    for k, v in rows.items():
        text = text.replace(f'"{k}"', v, 1)
    return text


def _expand_compact(data: dict) -> dict:
    """Turn a compact export back into the full form's fields that import_export reads."""
    out = {**data, "pages": []}
    for pg in data.get("pages", []):
        p = {**pg, "notes": pg.get("notes", ""),
             "margins": {**{k: 0 for k in ("top", "right", "bottom", "left")}, **pg.get("margins", {})},
             "grid": {"dot_spacing": pg.get("grid", {}).get("dot_spacing", 20), "dots_visible": True},
             "groups": [{"name": g["name"], "notes": g.get("notes", ""), "members": g["members"]}
                        for g in pg.get("groups", [])],
             "elements": []}
        for z, e in enumerate(pg.get("elements", []), start=1):
            st = e.get("style", {})
            f = {"id": e["id"], "name": e.get("name", ""), "type": e.get("type", "rectangle"),
                 "notes": e.get("notes", ""), "z": z,
                 "flipped": {"horizontal": False, "vertical": False, **e.get("flipped", {})},
                 "contents": e.get("contents"), "keeps_proportions": e.get("keeps_proportions", False)}
            if f["type"] == "path":
                f["path"] = {"points": e["points"]}
                f["style"] = {"color": st.get("color"), "opacity": st.get("opacity", 1), "thickness": st.get("thickness", 2),
                              "dash": st.get("dash", "solid"), "ends": st.get("ends", "round")}
            elif f["type"] == "line":
                ln = e["line"]
                f["line"] = {"start": {"x": ln["start"][0], "y": ln["start"][1]}, "end": {"x": ln["end"][0], "y": ln["end"][1]}}
                f["style"] = {"color": st.get("color"), "opacity": st.get("opacity", 1), "thickness": st.get("thickness", 2),
                              "dash": st.get("dash", "solid"), "ends": st.get("ends", "round")}
            else:
                x, y, w, h = e["box"]
                f["bounds"] = {"x": x, "y": y, "width": w, "height": h}
                f["rotation_degrees"] = e.get("rotation_degrees", 0)
                f["style"] = {"fill": st.get("fill"), "fill_opacity": st.get("fill_opacity", 1),
                              "border_color": st.get("border_color"), "border_opacity": st.get("border_opacity", 1),
                              "border_width": st.get("border_width", 0), "corner_radius": st.get("corner_radius", 0)}
            p["elements"].append(f)
        out["pages"].append(p)
    return out


def safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return keep or "Untitled"


def export_text(project: Project, snap_to_dots: bool = False, compact: bool = False, image_map: dict | None = None) -> str:
    """The export as JSON text, full or compact."""
    data = build_export(project, snap_to_dots, image_map)
    if compact:
        return dumps_compact(compact_export(data))
    return json.dumps(data, indent=2, ensure_ascii=False)


def write_export(project: Project, exports_dir: Path, snap_to_dots: bool = False,
                 compact: bool = False) -> tuple[Path, str]:
    """Write <exports>/<project>/<project>.ui.json (compact: <project>.compact.ui.json) and a dated
    copy in history/. Returns (path of the newest file, the JSON text)."""
    from .images import image_of, resolve
    folder = exports_dir / safe_name(project.name)
    (folder / "history").mkdir(parents=True, exist_ok=True)
    # pictures go next to the JSON, in images/
    image_map = {}
    for pg in project.pages:
        for s in pg.shapes:
            img = image_of(s)
            if img and img.get("path") and img["path"] not in image_map:
                src = resolve(img["path"])
                if src.exists():
                    (folder / "images").mkdir(exist_ok=True)
                    dst = folder / "images" / src.name
                    if not dst.exists():
                        shutil.copyfile(src, dst)
                    image_map[img["path"]] = f"images/{src.name}"
    text = export_text(project, snap_to_dots, compact, image_map)
    kind = ".compact" if compact else ""
    latest = folder / f"{safe_name(project.name)}{kind}.ui.json"
    dated = folder / "history" / f"{safe_name(project.name)}{kind.replace('.', '_')}_{time.strftime('%Y-%m-%d_%H%M%S')}.json"
    for p in (latest, dated):
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)
    return latest, text


def import_export(data: dict, base_dir: Path | None = None) -> Project:
    """Rebuild a project from an export file."""
    if data.get("format") != EXPORT_FORMAT:
        raise ValueError("not a Uxandi export")
    if data.get("compact"):
        data = _expand_compact(data)
    pj = data.get("project", {})
    pr = Project(name=pj.get("name", "Imported"), pages=[], created=pj.get("created", now_iso()))
    pr.brief = pj.get("brief", "")
    for pd in data.get("pages", []):
        c, m = pd.get("canvas", {}), pd.get("margins", {})
        pg = Page(name=pd.get("name", "Page"), id=pd.get("id") or new_id(),
                  width=int(c.get("width", 1920)), height=int(c.get("height", 1080)),
                  preset=c.get("preset", "Custom"), background=c.get("background", "#FFFFFF"),
                  dots=pd.get("grid", {}).get("dots_visible", True),
                  dot_spacing=int(pd.get("grid", {}).get("dot_spacing", 20)),
                  margins=[float(m.get(k, 0)) for k in ("top", "right", "bottom", "left")],
                  keep_inside=bool(m.get("content_kept_inside", True)))
        pg.margins_linked = len(set(pg.margins)) == 1
        pg.notes = pd.get("notes", "")
        for e in sorted(pd.get("elements", []), key=lambda e: e.get("z", 0)):
            st = e.get("style", {})
            common = dict(id=e.get("id") or new_id(), name=e.get("name", ""), notes=e.get("notes", ""),
                          flip_h=e.get("flipped", {}).get("horizontal", False),
                          flip_v=e.get("flipped", {}).get("vertical", False),
                          contents=e.get("contents"), created=e.get("created", now_iso()),
                          modified=e.get("modified", now_iso()))
            if e.get("type") == "path":
                s = Shape(kind="path", stroke=join_colour(st.get("color") or "#111418", st.get("opacity")),
                          stroke_width=st.get("thickness", 2), line_style=st.get("dash", "solid"),
                          cap=st.get("ends", "round"), fill="", **common)
                s.set_path_points(e.get("path", {}).get("points") or [[0, 0], [1, 1]])
            elif e.get("type") == "line":
                ln = e.get("line", {})
                s = Shape(kind="line", x1=ln["start"]["x"], y1=ln["start"]["y"], x2=ln["end"]["x"], y2=ln["end"]["y"],
                          stroke=join_colour(st.get("color") or "#111418", st.get("opacity")), stroke_width=st.get("thickness", 2),
                          line_style=st.get("dash", "solid"), cap=st.get("ends", "round"), **common)
            else:
                bd = e.get("bounds", {})
                s = Shape(kind="ellipse" if e.get("type") in ("ellipse", "circle") else "rect",
                          x=bd.get("x", 0), y=bd.get("y", 0), w=bd.get("width", 100), h=bd.get("height", 100),
                          rotation=e.get("rotation_degrees", 0), radius=st.get("corner_radius", 0),
                          fill=join_colour(st.get("fill"), st.get("fill_opacity")),
                          stroke=join_colour(st.get("border_color") or "#111418", st.get("border_opacity")),
                          stroke_width=st.get("border_width", 0) if st.get("border_color") else 0,
                          lock_ratio=e.get("keeps_proportions", False), **common)
            ct = e.get("contents")
            if isinstance(ct, dict) and ct.get("type") == "image":
                from .images import import_image, new_contents, resolve
                src = (Path(base_dir) / ct["file"]) if base_dir and ct.get("file") else resolve(ct.get("file", ""))
                try:
                    rel = import_image(src) if src.exists() else ct.get("file", "")
                except Exception:
                    rel = ct.get("file", "")
                c2 = new_contents(rel, ct.get("original_name", ""))
                c2.update(fit=ct.get("fit", "fill"), zoom=float(ct.get("zoom", 1)), opacity=float(ct.get("opacity", 1)),
                          dx=float((ct.get("offset") or {}).get("x", 0)), dy=float((ct.get("offset") or {}).get("y", 0)))
                s.contents = c2
            pg.shapes.append(s)
        pg.groups = [{"id": g.get("id") or new_id(), "name": g.get("name", "Group"), "members": list(g.get("members", [])),
                      "notes": g.get("notes") or ""} for g in pd.get("groups", [])]
        pg.clean_groups()
        pr.pages.append(pg)
    if not pr.pages:
        pr.pages = [Page()]
    return pr
