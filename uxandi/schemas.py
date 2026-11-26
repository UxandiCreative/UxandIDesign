"""JSON Schemas for every file Uxandi reads or writes, plus a small validator.

    schema/ui.schema.json               the agent export (<project>.ui.json): the contract for the building agent
    schema/ui.compact.schema.json       the compact export (<project>.compact.ui.json)
    schema/project.schema.json          a saved project (projects/<name>.uxandi)
    schema/design-template.schema.json  a Design tab style template (templates/design/<name>.json)
    schema/tools.json                   every agent tool: description, input schema, hints (the MCP tools/list)

The files in schema/ are generated from this module and uxandi/agent.py:

    python uxandi_agent.py schema           write them
    python uxandi_agent.py schema --check   fail if they are out of date (tools/check_agent.py runs this)
    python uxandi_agent.py validate <file>  check a .ui.json, .compact.ui.json, .uxandi or template file

No Qt and no third-party packages: the validator covers the JSON Schema keywords these schemas use.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .export import EXPORT_FORMAT, EXPORT_VERSION, SCHEMA_URL, EXPORT_SCHEMA, COMPACT_SCHEMA
from .model import FORMAT_VERSION

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schema"
BASE_URL = SCHEMA_URL
DRAFT = "https://json-schema.org/draft/2020-12/schema"

EXPORT_SCHEMA_URL = EXPORT_SCHEMA
COMPACT_SCHEMA_URL = COMPACT_SCHEMA


# ============================================================================= building blocks
def obj(props: dict, required=(), extra: bool = False, desc: str | None = None) -> dict:
    o = {"type": "object", "properties": props, "required": list(required), "additionalProperties": extra}
    if desc:
        o = {"description": desc, **o}
    return o


def arr(items, desc: str | None = None, **kw) -> dict:
    a = {"type": "array", "items": items, **kw}
    return {"description": desc, **a} if desc else a


def ref(name: str) -> dict:
    return {"$ref": f"#/$defs/{name}"}


def d(schema: dict, desc: str) -> dict:
    return {"description": desc, **schema}


S = {"type": "string"}
N = {"type": "number"}
I = {"type": "integer"}
B = {"type": "boolean"}
NUM_OR_NULL = {"type": ["number", "null"]}
STR_OR_NULL = {"type": ["string", "null"]}
HEX = {"type": "string", "pattern": "^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$"}
HEX_OR_NULL = {"anyOf": [HEX, {"type": "null"}]}
OPACITY = {"type": ["number", "null"], "minimum": 0, "maximum": 1}
DEVICE = {"enum": ["Desktop", "iPad", "Phone", "Custom"]}
ORIENTATION = {"enum": ["portrait", "landscape", "square"]}
FIT = {"enum": ["fill", "fit", "stretch", "original"]}
DASH = {"enum": ["solid", "dash", "dot"]}
ENDS = {"enum": ["round", "flat", "square"]}
NOTES = d(S, "Text the user (or the designing agent) wrote: what the element is, the text it shows, behaviour, states, data.")
XY = arr(N, "[x, y] in canvas pixels.", minItems=2, maxItems=2)
XYWH = arr(N, "[x, y, width, height] in canvas pixels.", minItems=4, maxItems=4)

BOX = obj({"x": N, "y": N, "width": N, "height": N}, ["x", "y", "width", "height"], desc="A box in canvas pixels; x, y = top-left.")
POINT = obj({"x": N, "y": N}, ["x", "y"])
CANVAS = obj({"width": d(I, "Canvas width, px."), "height": d(I, "Canvas height, px."),
              "device": d(DEVICE, "The device family of the preset."), "preset": d(S, "Preset name, or Custom."),
              "orientation": ORIENTATION, "background": HEX},
             ["width", "height", "device", "preset", "orientation", "background"])
IMAGE_EXPORT = obj({
    "type": {"const": "image"},
    "file": d(S, "Picture file, relative to the export JSON (images/<name>)."),
    "original_name": S,
    "pixel_size": {"anyOf": [obj({"width": I, "height": I}, ["width", "height"]), {"type": "null"}]},
    "fit": d(FIT, "fill = cover the box and crop; fit = whole picture inside; stretch = scaled to the box; original = 1 image px per canvas px."),
    "zoom": N, "offset": d(POINT, "Moves the picture's centre from the box centre, px."), "opacity": N},
    ["type", "file", "fit", "zoom", "offset", "opacity"], desc="A picture shown inside the element, clipped to its rounded box.")
CONTENTS = {"description": "What is inside the element: null, or a picture. Other object types are reserved for later versions.",
            "anyOf": [{"type": "null"}, ref("image"), {"type": "object"}]}


# ============================================================================= the full export
def _element_common() -> dict:
    return {
        "id": d(S, "Stable id, unique on the page."),
        "name": d(S, "What the element is (\"Header\", \"Sign in button\"). Unique on the page in a good layout."),
        "notes": NOTES,
        "group": d(STR_OR_NULL, "Name of the user's group it belongs to, or null."),
        "z": d({"type": "integer", "minimum": 1}, "Stacking order: 1 is at the back, higher is drawn on top."),
        "parent": d(STR_OR_NULL, "Id of the smallest rectangle whose box holds this one completely, or null (on the canvas)."),
        "children": arr(S, "Ids of the elements directly inside it, back to front."),
        "relative": obj({"x_pct": N, "y_pct": N, "width_pct": N, "height_pct": N},
                        ["x_pct", "y_pct", "width_pct", "height_pct"], desc="The visual box as % of the canvas width and height."),
        "inside_safe_area": d(B, "The visual box lies inside the page margins."),
        "flipped": obj({"horizontal": B, "vertical": B}, ["horizontal", "vertical"]),
        "contents": CONTENTS,
        "created": S, "modified": S,
    }


COMMON_REQ = ["id", "name", "notes", "group", "z", "parent", "children", "relative", "inside_safe_area", "flipped",
              "contents", "created", "modified"]


def export_schema() -> dict:
    rect = obj({
        **_element_common(),
        "type": d({"enum": ["rectangle", "square", "ellipse", "circle"]},
                  "square / circle: width and height are equal (within half a pixel). ellipse / circle: the oval filling the box."),
        "bounds": d(ref("box"), "The element's own box before rotation."),
        "rotation_degrees": d(N, "Clockwise, about the centre."),
        "visual_bounds": d(ref("box"), "The box it covers after rotation."),
        "center": ref("point"),
        "style": obj({"fill": HEX_OR_NULL, "fill_opacity": OPACITY, "border_color": HEX_OR_NULL, "border_opacity": OPACITY,
                      "border_width": d(N, "px, inside the box. 0 = no border."), "corner_radius": d(N, "px.")},
                     ["fill", "fill_opacity", "border_color", "border_opacity", "border_width", "corner_radius"],
                     desc="Colours are #RRGGBB; null means none. Opacity 1 = solid."),
        "keeps_proportions": B,
    }, COMMON_REQ + ["type", "bounds", "rotation_degrees", "visual_bounds", "center", "style", "keeps_proportions"],
        desc="A rectangle, square, ellipse or circle: a container. A heading, label, button or image is a container whose name and "
             "notes say what it is.")
    line = obj({
        **_element_common(),
        "type": {"const": "line"},
        "line": obj({"start": ref("point"), "end": ref("point"), "length": N, "angle_degrees": d(N, "-180..180, 0 = pointing right.")},
                    ["start", "end", "length", "angle_degrees"]),
        "visual_bounds": ref("box"),
        "style": obj({"color": HEX_OR_NULL, "opacity": OPACITY, "thickness": N, "dash": DASH, "ends": ENDS},
                     ["color", "opacity", "thickness", "dash", "ends"]),
    }, COMMON_REQ + ["type", "line", "visual_bounds", "style"], desc="A line: a divider, connector or rule.")
    path = obj({
        **_element_common(),
        "type": {"const": "path"},
        "path": obj({"points": arr(XY, "Canvas points in drawing order, rotation and flips applied.", minItems=1)}, ["points"]),
        "bounds": d(ref("box"), "The box the drawing was made in, before rotation."),
        "rotation_degrees": N,
        "visual_bounds": d(ref("box"), "The area the stroke covers."),
        "style": obj({"color": HEX_OR_NULL, "opacity": OPACITY, "thickness": N, "dash": DASH, "ends": ENDS},
                     ["color", "opacity", "thickness", "dash", "ends"]),
    }, COMMON_REQ + ["type", "path", "bounds", "rotation_degrees", "visual_bounds", "style"],
        desc="A freehand stroke the user drew. Never holds other elements; its notes say what it means.")
    tree = obj({"id": S, "name": S, "children": arr(ref("tree_node"))}, ["id", "name", "children"])
    page = obj({
        "index": d({"type": "integer", "minimum": 1}, "Page number, 1 = first."),
        "id": S, "name": S,
        "notes": d(S, "What this screen is for."),
        "canvas": ref("canvas"),
        "margins": obj({"top": N, "right": N, "bottom": N, "left": N, "safe_area": ref("box"),
                        "content_kept_inside": d(B, "The app keeps shapes inside the margins.")},
                       ["top", "right", "bottom", "left", "safe_area", "content_kept_inside"]),
        "grid": obj({"dot_spacing": d(I, "Dot grid spacing, px: the layout's base unit."), "dots_visible": B},
                    ["dot_spacing", "dots_visible"]),
        "element_count": I,
        "elements_without_notes": arr(obj({"id": S, "name": S, "type": S}, ["id", "name", "type"])),
        "groups": arr(obj({"id": S, "name": S, "members": arr(S), "member_names": arr(S), "bounds": ref("box")},
                          ["id", "name", "members", "member_names", "bounds"])),
        "layout_tree": arr(ref("tree_node"), "The nesting as a tree, back to front."),
        "elements": arr(ref("element"), "Every element in stacking order (back first)."),
    }, ["index", "id", "name", "notes", "canvas", "margins", "grid", "element_count", "elements_without_notes",
        "groups", "layout_tree", "elements"])
    return {
        "$schema": DRAFT,
        "$id": EXPORT_SCHEMA_URL,
        "title": "Uxandi export",
        "description": "A layout made in Uxandi, for the agent that builds the real UI: pages (canvases with real screen "
                       "sizes) holding rectangles, ellipses, lines and freehand drawings. Names and notes carry the meaning; boxes and styles carry the geometry.",
        "type": "object",
        "properties": {
            "$schema": d(S, "This schema's URL."),
            "format": {"const": EXPORT_FORMAT},
            "version": {"const": EXPORT_VERSION},
            "tool": S,
            "exported": d(S, "Local time, YYYY-MM-DDTHH:MM:SS."),
            "how_to_read": arr(S, "Plain-language reading guide, also for agents that never saw this schema."),
            "project": obj({"name": S, "brief": d(S, "What the product is, who it is for, style and rules."),
                            "page_count": I, "created": S,
                            "layout_snapped_to_dots": d(B, "The user had dot snapping on: sizes and gaps are multiples of the dot spacing.")},
                           ["name", "brief", "page_count", "created", "layout_snapped_to_dots"]),
            "summary": obj({"element_count": I, "elements_with_notes": I, "elements_without_notes_count": I,
                            "elements_without_notes": arr(obj({"page": I, "page_name": S, "id": S, "name": S, "type": S},
                                                              ["page", "page_name", "id", "name", "type"])),
                            "brief_empty": B,
                            "pages_without_notes": arr(obj({"page": I, "page_name": S}, ["page", "page_name"]))},
                           ["element_count", "elements_with_notes", "elements_without_notes_count", "elements_without_notes",
                            "brief_empty", "pages_without_notes"]),
            "pages": arr(ref("page"), minItems=1),
        },
        "required": ["format", "version", "tool", "exported", "how_to_read", "project", "summary", "pages"],
        "additionalProperties": False,
        "$defs": {"box": BOX, "point": POINT, "canvas": CANVAS, "image": IMAGE_EXPORT, "tree_node": tree,
                  "page": page, "element": {"oneOf": [ref("rect_element"), ref("line_element"), ref("path_element")]},
                  "rect_element": rect, "line_element": line, "path_element": path},
    }


# ============================================================================= the compact export
def compact_schema() -> dict:
    common = {
        "id": S, "name": S, "notes": NOTES,
        "parent": d(S, "Id of the element whose box holds this one. Left out: on the canvas."),
        "group": d(S, "Name of the user's group. Left out: none."),
        "outside_safe_area": d({"const": True}, "Only given when the element is not inside the page margins."),
        "flipped": obj({"horizontal": {"const": True}, "vertical": {"const": True}}),
        "contents": CONTENTS,
    }
    rect = obj({
        **common,
        "type": d({"enum": ["rectangle", "square", "ellipse", "circle"]}, "Left out: rectangle. ellipse / circle: the oval filling the box."),
        "box": d(ref("xywh"), "The own box before rotation."),
        "rotation_degrees": N, "visual_box": d(ref("xywh"), "The box it covers after rotation (rotated elements only)."),
        "style": obj({"fill": HEX, "fill_opacity": OPACITY, "border_color": HEX, "border_width": N,
                      "border_opacity": OPACITY, "corner_radius": N},
                     desc="Only what is set: no fill = no 'fill'; no border = no 'border_color'."),
        "keeps_proportions": {"const": True},
    }, ["id", "name", "box"])
    line = obj({
        **common,
        "type": {"const": "line"},
        "line": obj({"start": ref("xy"), "end": ref("xy")}, ["start", "end"]),
        "style": obj({"color": HEX_OR_NULL, "thickness": N, "opacity": OPACITY, "dash": {"enum": ["dash", "dot"]},
                      "ends": {"enum": ["flat", "square"]}}, ["color", "thickness"]),
    }, ["id", "name", "type", "line", "style"])
    path = obj({
        **common,
        "type": {"const": "path"},
        "points": arr(XY, "Canvas points in drawing order, rotation and flips applied.", minItems=1),
        "style": obj({"color": HEX_OR_NULL, "thickness": N, "opacity": OPACITY, "dash": {"enum": ["dash", "dot"]},
                      "ends": {"enum": ["flat", "square"]}}, ["color", "thickness"]),
    }, ["id", "name", "type", "points", "style"])
    page = obj({
        "index": I, "id": S, "name": S, "notes": S,
        "canvas": ref("canvas"),
        "margins": obj({"top": N, "right": N, "bottom": N, "left": N}, ["top", "right", "bottom", "left"]),
        "grid": obj({"dot_spacing": I}, ["dot_spacing"]),
        "element_count": I,
        "elements_without_notes": arr(S, "Names of elements whose notes are empty."),
        "groups": arr(obj({"name": S, "members": arr(S)}, ["name", "members"])),
        "elements": arr(ref("element"), "Stacking order: the first is at the back."),
    }, ["index", "id", "name", "canvas", "grid", "element_count", "elements"])
    image = dict(IMAGE_EXPORT)
    return {
        "$schema": DRAFT,
        "$id": COMPACT_SCHEMA_URL,
        "title": "Uxandi compact export",
        "description": "The compact form of the Uxandi export: the same facts with empty, default and derivable values left "
                       "out (see how_to_read for every default).",
        "type": "object",
        "properties": {
            "$schema": S,
            "format": {"const": EXPORT_FORMAT}, "version": {"const": EXPORT_VERSION}, "compact": {"const": True},
            "tool": S, "exported": S, "how_to_read": arr(S),
            "project": obj({"name": S, "brief": S, "page_count": I, "layout_snapped_to_dots": {"const": True}},
                           ["name", "brief", "page_count"]),
            "summary": obj({"element_count": I, "elements_without_notes_count": I, "brief_empty": B,
                            "pages_without_notes": arr(I, "Page numbers.")},
                           ["element_count", "elements_without_notes_count", "brief_empty", "pages_without_notes"]),
            "pages": arr(ref("page"), minItems=1),
        },
        "required": ["format", "version", "compact", "tool", "exported", "how_to_read", "project", "summary", "pages"],
        "additionalProperties": False,
        "$defs": {"xy": XY, "xywh": XYWH, "point": POINT, "canvas": CANVAS, "image": image, "page": page,
                  "element": {"oneOf": [ref("rect_element"), ref("line_element"), ref("path_element")]},
                  "rect_element": rect, "line_element": line, "path_element": path},
    }


# ============================================================================= the project file
IMAGE_PROJECT = obj({"type": {"const": "image"}, "path": d(S, "Relative to the app folder (assets/images/<hash>.<ext>)."),
                     "original_name": S, "fit": FIT, "zoom": N, "dx": N, "dy": N, "opacity": N},
                    ["type", "path"], extra=True)


def project_schema() -> dict:
    common = {"kind": S, "name": S, "notes": S, "id": S, "stroke": {"anyOf": [HEX, {"const": ""}]}, "stroke_width": N, "flip_h": B, "flip_v": B,
              "created": S, "modified": S,
              "contents": {"anyOf": [{"type": "null"}, ref("image"), {"type": "object"}]}}
    rect = obj({**common, "kind": {"enum": ["rect", "ellipse"]}, "x": N, "y": N, "w": N, "h": N, "rotation": N, "radius": N,
                "lock_ratio": B, "fill": {"anyOf": [HEX, {"const": ""}]}}, ["kind", "id", "x", "y", "w", "h"],
               desc="A rectangle, or an ellipse (the oval filling the box; radius unused). fill \"\" = no fill; stroke_width 0 = no border.")
    line = obj({**common, "kind": {"const": "line"}, "x1": N, "y1": N, "x2": N, "y2": N, "line_style": DASH, "cap": ENDS},
               ["kind", "id", "x1", "y1", "x2", "y2"])
    path = obj({**common, "kind": {"const": "path"}, "x": N, "y": N, "w": N, "h": N, "rotation": N, "lock_ratio": B,
                "line_style": DASH, "cap": ENDS,
                "points": arr(arr(N, "[u, v]: 0..1 across the box.", minItems=2, maxItems=2), minItems=1)},
               ["kind", "id", "x", "y", "w", "h", "points"],
               desc="A freehand stroke: its box (x, y, w, h, rotation) and its points as fractions of that box.")
    page = obj({"name": S, "id": S, "width": I, "height": I, "preset": S, "background": HEX, "dots": B, "dot_spacing": I,
                "margins": arr(N, "[top, right, bottom, left], px.", minItems=4, maxItems=4),
                "margins_linked": B, "show_margins": B, "keep_inside": B,
                "groups": arr(obj({"id": S, "name": S, "members": arr(S)}, ["id", "name", "members"])),
                "notes": S, "shapes": arr({"oneOf": [ref("rect"), ref("line"), ref("path")]}, "Stacking order: back first.")},
               ["name", "id", "width", "height", "shapes"])
    return {
        "$schema": DRAFT, "$id": BASE_URL + "project.schema.json",
        "title": "Uxandi project (.uxandi)",
        "description": "A saved project: pages and their shapes, as the app stores them (canvas pixels, colours #RRGGBB or #AARRGGBB).",
        "type": "object",
        "properties": {"format": {"const": "uxandi"}, "version": {"const": FORMAT_VERSION}, "name": S, "brief": S,
                       "created": S, "pages": arr(ref("page"), minItems=1)},
        "required": ["format", "version", "name", "pages"],
        "additionalProperties": False,
        "$defs": {"image": IMAGE_PROJECT, "page": page, "rect": rect, "line": line, "path": path},
    }


def template_schema() -> dict:
    return {
        "$schema": DRAFT, "$id": BASE_URL + "design-template.schema.json",
        "title": "Uxandi style template",
        "description": "A Design tab style (templates/design/<name>.json). Shapes take it with \"template\": \"<name>\".",
        "type": "object",
        "properties": {"format": {"const": "uxandi-template"}, "name": S,
                       "fill": d({"anyOf": [HEX, {"const": ""}]}, "\"\" = no fill."), "stroke": HEX,
                       "stroke_width": N, "radius": N, "line_style": DASH, "cap": ENDS,
                       "image": {"anyOf": [{"type": "null"}, IMAGE_PROJECT]}, "saved": S},
        "required": ["format"],
        "additionalProperties": False,
    }


def tools_document() -> dict:
    from . import agent
    return {"server": "uxandi", "api_version": agent.API_VERSION,
            "description": "Every Uxandi agent tool, as MCP tools/list sends it. "
                           "Generated by `python uxandi_agent.py schema`; see TOOLS.md for use cases and recipes.",
            "tools": agent.tool_list()}


def all_files() -> dict:
    """{file name: content} for schema/."""
    return {"ui.schema.json": export_schema(), "ui.compact.schema.json": compact_schema(),
            "project.schema.json": project_schema(), "design-template.schema.json": template_schema(),
            "tools.json": tools_document()}


def dump(data) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# ============================================================================= TOOLS.md: the generated reference part
TOOLS_MD = ROOT / "TOOLS.md"
MD_START = "<!-- tool-reference:start (generated by `python uxandi_agent.py schema`; edit uxandi/agent.py instead) -->"
MD_END = "<!-- tool-reference:end -->"
TOOL_GROUPS = [
    ("Read", ["get_status", "get_page", "screenshot", "check_layout", "list_presets", "list_projects"]),
    ("Build", ["create_shapes", "update_shapes", "delete_shapes", "duplicate_shapes", "set_group"]),
    ("Layout", ["arrange", "grid", "align", "distribute"]),
    ("Design templates", ["list_templates", "save_template"]),
    ("Pages and project", ["add_page", "update_page", "delete_page", "set_project"]),
    ("Files", ["open_project", "new_project", "save_project", "export_json", "import_export"]),
    ("Session", ["select", "history", "batch"]),
]


def _type_of(s: dict) -> str:
    if not isinstance(s, dict):
        return ""
    if "enum" in s:
        return " \\| ".join(f"`{json.dumps(v)}`" for v in s["enum"])
    if "anyOf" in s:
        return " or ".join(t for t in (_type_of(x) for x in s["anyOf"]) if t)
    t = s.get("type")
    if isinstance(t, list):
        return " or ".join(t)
    if t == "array":
        inner = _type_of(s.get("items", {}))
        return f"array of {inner}" if inner else "array"
    return t or "any"


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def tools_markdown() -> str:
    from . import agent
    by = {t["name"]: t for t in agent.tool_list()}
    grouped = [n for _, names in TOOL_GROUPS for n in names]
    missing = [n for n in by if n not in grouped]
    groups = TOOL_GROUPS + ([("Other", missing)] if missing else [])
    out = [MD_START, "", f"## Tool reference ({len(by)} tools)", ""]
    for title, names in groups:
        out += [f"### {title}", ""]
        for n in names:
            t = by.get(n)
            if t is None:
                continue
            sch = t["inputSchema"]
            req = set(sch.get("required", []))
            hints = [h for h, on in (("read-only", t["annotations"]["readOnlyHint"]),
                                     ("destructive", t["annotations"]["destructiveHint"])) if on]
            out += [f"#### `{n}`" + (f" ({', '.join(hints)})" if hints else ""), "", t["description"], ""]
            props = sch.get("properties", {})
            if not props:
                out += ["No arguments.", ""]
                continue
            out += ["| Argument | Type | Description |", "|---|---|---|"]
            for k, v in props.items():
                desc = v.get("description", "") if isinstance(v, dict) else ""
                if k == "shapes" and isinstance(v, dict) and v.get("type") == "array" and isinstance(v.get("items"), dict) \
                        and v["items"].get("properties"):
                    desc = "Shape objects: the fields in the table below."
                if k == "changes":
                    desc = "Change objects: \"shape\" (id or name) plus any shape field below, \"move\", \"center\", \"carry\"."
                out.append(f"| `{k}`{' (required)' if k in req else ''} | {_cell(_type_of(v))} | {_cell(desc)} |")
            out.append("")
            if n == "create_shapes":
                fields = sch["properties"]["shapes"]["items"]["properties"]
                out += ["Shape fields (create_shapes and update_shapes):", "",
                        "| Field | Type | Description |", "|---|---|---|"]
                for k, v in fields.items():
                    out.append(f"| `{k}` | {_cell(_type_of(v))} | {_cell(v.get('description', ''))} |")
                out.append("")
    out.append(MD_END)
    return "\n".join(out) + "\n"


def _tools_md_text() -> str | None:
    """TOOLS.md with its generated part brought up to date (None when the file or its markers are missing)."""
    if not TOOLS_MD.exists():
        return None
    text = TOOLS_MD.read_text(encoding="utf-8")
    a, b = text.find(MD_START), text.find(MD_END)
    if a < 0 or b < 0:
        return None
    return text[:a] + tools_markdown() + text[b + len(MD_END) + 1:]


def write_all(folder: Path = SCHEMA_DIR) -> list:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, data in all_files().items():
        p = folder / name
        p.write_text(dump(data), encoding="utf-8", newline="\n")
        out.append(p)
    md = _tools_md_text()
    if md is not None:
        TOOLS_MD.write_text(md, encoding="utf-8", newline="\n")
        out.append(TOOLS_MD)
    return out


def stale(folder: Path = SCHEMA_DIR) -> list:
    """The generated files (schema/*, the reference part of TOOLS.md) that differ from what the code makes."""
    bad = []
    for name, data in all_files().items():
        p = folder / name
        if not p.exists() or p.read_text(encoding="utf-8") != dump(data):
            bad.append(name)
    md = _tools_md_text()
    if md is None or TOOLS_MD.read_text(encoding="utf-8") != md:
        bad.append("TOOLS.md")
    return bad


def schema_for(data) -> tuple[str, dict]:
    """Pick the schema that fits a loaded file."""
    if isinstance(data, dict):
        f = data.get("format")
        if f == EXPORT_FORMAT:
            return ("ui.compact.schema.json", compact_schema()) if data.get("compact") else ("ui.schema.json", export_schema())
        if f == "uxandi":
            return "project.schema.json", project_schema()
        if f == "uxandi-template":
            return "design-template.schema.json", template_schema()
    raise ValueError("Not a Uxandi file: no known \"format\" field.")


# ============================================================================= a small validator
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is_type(v, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool) or (isinstance(v, float) and v.is_integer())
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def validate(inst, schema: dict, root: dict | None = None, path: str = "$", limit: int = 50) -> list:
    """Problems as "path: message" strings (empty = valid). Covers the keywords used in this module."""
    root = root or schema
    errs: list = []

    def go(v, s, p):
        if len(errs) >= limit:
            return
        if "$ref" in s:
            node = root
            for part in s["$ref"].lstrip("#/").split("/"):
                node = node[part]
            go(v, node, p)
            return
        if "const" in s and v != s["const"]:
            errs.append(f"{p}: should be {s['const']!r}")
            return
        if "enum" in s and v not in s["enum"]:
            errs.append(f"{p}: {v!r} is not one of {s['enum']}")
            return
        if "type" in s:
            ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(_is_type(v, t) for t in ts):
                errs.append(f"{p}: expected {' or '.join(ts)}, got {type(v).__name__}")
                return
        for key in ("anyOf", "oneOf"):
            if key in s:
                hits = [sub for sub in s[key] if not validate(v, sub, root, p, 1)]
                if not hits or (key == "oneOf" and len(hits) > 1):
                    if key == "oneOf" and len(hits) > 1:
                        errs.append(f"{p}: matches more than one of oneOf")
                    else:     # report the closest branch's problems
                        best = min((validate(v, sub, root, p, limit) for sub in s[key]), key=len)
                        errs.extend(best or [f"{p}: matches none of {key}"])
                    return
        if isinstance(v, str) and "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{p}: {v!r} does not match {s['pattern']}")
        if _is_type(v, "number"):
            if "minimum" in s and v < s["minimum"]:
                errs.append(f"{p}: {v} < {s['minimum']}")
            if "maximum" in s and v > s["maximum"]:
                errs.append(f"{p}: {v} > {s['maximum']}")
        if isinstance(v, list):
            if "minItems" in s and len(v) < s["minItems"]:
                errs.append(f"{p}: fewer than {s['minItems']} items")
            if "maxItems" in s and len(v) > s["maxItems"]:
                errs.append(f"{p}: more than {s['maxItems']} items")
            if "items" in s:
                for n, x in enumerate(v):
                    go(x, s["items"], f"{p}[{n}]")
        if isinstance(v, dict):
            props = s.get("properties", {})
            for k in s.get("required", []):
                if k not in v:
                    errs.append(f"{p}: missing {k!r}")
            for k, x in v.items():
                if k in props:
                    go(x, props[k], f"{p}.{k}")
                elif s.get("additionalProperties") is False:
                    errs.append(f"{p}: unexpected field {k!r}")
                elif isinstance(s.get("additionalProperties"), dict):
                    go(x, s["additionalProperties"], f"{p}.{k}")

    go(inst, schema, path)
    return errs[:limit]
