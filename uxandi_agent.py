"""Uxandi for AI agents: an MCP server and a command line, standard library only.

    python uxandi_agent.py mcp                      MCP server on stdio (what agent apps run)
    python uxandi_agent.py tools                    list the tools and their arguments
    python uxandi_agent.py call get_status          run one tool, print JSON
    python uxandi_agent.py call create_shapes '{"shapes": [{"name": "Header", "w": "100%", "h": 72, "x": 0, "y": 0}]}'
    python uxandi_agent.py call screenshot --out page.png
    python uxandi_agent.py guide                    how to use the tools well
    python uxandi_agent.py schema [--check]         write (or check) the JSON Schemas in schema/
    python uxandi_agent.py validate file.ui.json    check an export, project or template against its schema

If the app is open (python main.py), every command runs inside it: the user sees each
change at once and can undo it. If it is closed, commands edit the project files directly
and save them (file mode). Setup for each agent app: see AGENTS.md.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from uxandi import agent  # noqa: E402  (no Qt imported yet)

SERVER_NAME = "uxandi"
SERVER_VERSION = "1.1.0"
PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]


# ============================================================================= live: the open app
def _bridge_info():
    f = Path(os.environ.get("UXANDI_HOME") or ROOT) / "data" / "bridge.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return None


def live_call(tool: str, args: dict, timeout: float = 120.0):
    """Send one command to the open app. Returns (True, result) / (False, error), or None
    when the app is not open."""
    info = _bridge_info()
    if not info:
        return None
    try:
        s = socket.create_connection(("127.0.0.1", int(info["port"])), timeout=1.5)
    except OSError:
        return None
    try:
        s.settimeout(timeout)
        s.sendall(json.dumps({"token": info.get("token"), "tool": tool, "args": args}).encode("utf-8") + b"\n")
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            buf += chunk
    except OSError as e:
        return False, f"The app did not answer ({e}). Is a dialog open in it?"
    finally:
        s.close()
    try:
        r = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except Exception:
        return False, "The app sent an answer that is not JSON."
    if r.get("ok"):
        res = r.get("result") or {}
        if isinstance(res.get("_image"), str):
            res["_image"] = base64.b64decode(res["_image"])
        return True, res
    return False, r.get("error", "unknown error")


# ============================================================================= file mode: the app is closed
class FileTarget(agent.Target):
    """Works on the project the app had open last (data/session.json), or the one opened
    with open_project. Every change is saved at once, so the app shows it next time."""
    live = False

    def __init__(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        if sys.platform.startswith("win"):
            os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
        try:
            from PySide6.QtGui import QGuiApplication
        except ImportError:
            raise agent.ToolError(
                "The Uxandi app is not open, and this Python has no PySide6 to work on the files without it. "
                f"Either ask the user to start the app (python main.py), or run this server with the Python that has "
                f"the requirements installed (python -m pip install -r requirements.txt). This Python: {sys.executable}")
        self.app = QGuiApplication.instance() or QGuiApplication(["uxandi-agent"])
        from uxandi import doc as docmod
        self.docmod = docmod
        super().__init__(docmod.Doc())
        self.doc.load_session()
        self._stamp = self._mtimes()

    def _mtimes(self):
        out = []
        for p in (self.docmod.SESSION_FILE, self.doc.path):
            try:
                out.append(p.stat().st_mtime_ns if p else None)
            except OSError:
                out.append(None)
        return out

    def before(self):
        """Someone else (the app, the user, another agent) changed the files: load them again."""
        now = self._mtimes()
        if now == self._stamp:
            return
        if now[0] != self._stamp[0]:
            d = self.docmod.Doc()
            d.load_session()
            self.doc = d
        elif self.doc.path and self.doc.path.exists():
            self.doc.load(self.doc.path)
        self._stamp = self._mtimes()

    def persist(self):
        if self.doc.path:
            self.doc.save()
        else:
            self.doc.save_session()
        self._stamp = self._mtimes()

    def loaded(self):
        self.doc.save_session()
        self._stamp = self._mtimes()


_file_target = None


def run(tool: str, args: dict):
    """Run a tool in the open app, or on the files when it is closed.
    Returns (True, result) or (False, error message)."""
    r = live_call(tool, args)
    if r is not None:
        return r
    global _file_target
    try:
        if _file_target is None:
            _file_target = FileTarget()
        return True, agent.call(_file_target, tool, args)
    except agent.ToolError as e:
        return False, str(e)
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return False, f"Internal error: {type(e).__name__}: {e}"


# ============================================================================= MCP over stdio
def _content(res: dict) -> list:
    out = []
    img = res.pop("_image", None) if isinstance(res, dict) else None
    out.append({"type": "text", "text": json.dumps(res, indent=1, ensure_ascii=False)})
    if img:
        out.append({"type": "image", "data": base64.b64encode(img).decode("ascii"), "mimeType": "image/png"})
    return out


def _handle(msg: dict):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        want = params.get("protocolVersion")
        return {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False},
                                 "prompts": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "title": "Uxandi", "version": SERVER_VERSION},
                "instructions": agent.GUIDE}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": agent.tool_list()}
    if method == "tools/call":
        name = params.get("name", "")
        ok, res = run(name, params.get("arguments") or {})
        if ok:
            return {"content": _content(res), "isError": False}
        return {"content": [{"type": "text", "text": str(res)}], "isError": True}
    if method == "resources/list":
        return {"resources": [{k: v for k, v in r.items() if k != "read"} for r in _resources()]}
    if method == "resources/templates/list":
        return {"resourceTemplates": []}
    if method == "resources/read":
        uri = params.get("uri")
        r = next((r for r in _resources() if r["uri"] == uri), None)
        if r is None:
            raise ValueError(f"Unknown resource {uri!r}. resources/list shows them.")
        return {"contents": [{"uri": uri, "mimeType": r["mimeType"], "text": r["read"]()}]}
    if method == "prompts/list":
        return {"prompts": [{k: v for k, v in pr.items() if k != "text"} for pr in PROMPTS]}
    if method == "prompts/get":
        pr = next((pr for pr in PROMPTS if pr["name"] == params.get("name")), None)
        if pr is None:
            raise ValueError(f"Unknown prompt {params.get('name')!r}. prompts/list shows them.")
        a = params.get("arguments") or {}
        missing = [x["name"] for x in pr.get("arguments", []) if x.get("required") and not a.get(x["name"])]
        if missing:
            raise ValueError("Missing prompt argument(s): " + ", ".join(missing))
        return {"description": pr["description"],
                "messages": [{"role": "user", "content": {"type": "text", "text": pr["text"](a)}}]}
    if mid is None:          # a notification (initialized, cancelled ...): nothing to answer
        return None
    raise LookupError(method)


# ============================================================================= MCP resources and prompts
def _resources() -> list:
    from uxandi import schemas
    files = schemas.all_files()
    out = [{"uri": "uxandi://guide", "name": "guide", "title": "How to build layouts well", "mimeType": "text/plain",
            "description": "The workflow and facts every agent should know first (the same text as the server instructions).",
            "read": lambda: agent.GUIDE}]
    tools_md = ROOT / "TOOLS.md"
    if tools_md.exists():
        out.append({"uri": "uxandi://reference/tools", "name": "tools-reference", "title": "Tool reference and recipes",
                    "mimeType": "text/markdown",
                    "description": "Every tool with its arguments, plus recipes for common screens (lists, forms, dashboards, flows).",
                    "read": lambda: tools_md.read_text(encoding="utf-8")})
    about = {"ui.schema.json": ("schema-export", "Export format (.ui.json)", "JSON Schema of the export the building agent reads."),
             "ui.compact.schema.json": ("schema-export-compact", "Compact export format", "JSON Schema of <project>.compact.ui.json."),
             "project.schema.json": ("schema-project", "Project file format (.uxandi)", "JSON Schema of a saved project."),
             "design-template.schema.json": ("schema-template", "Design template format", "JSON Schema of a Design tab style template."),
             "tools.json": ("tools", "Tool list", "Every tool's description, input schema and hints, as one JSON file.")}
    for fname, (name, title, desc) in about.items():
        out.append({"uri": f"uxandi://schema/{fname}", "name": name, "title": title, "description": desc,
                    "mimeType": "application/schema+json" if fname.endswith("schema.json") else "application/json",
                    "read": (lambda data=files[fname]: schemas.dump(data))})
    return out


_COMMON = """Rules that make the export useful to the agent that builds the real UI:
- Containers only. There is no text element: a heading, label, input or button is a rectangle. Its name says what it
  is; its notes give the exact text it shows, what it does, its states (hover, disabled, error, empty, loading) and data.
- Real sizes. Canvases are device pixels: phone presets are about 3x their point size, iPads 2x, desktops 1x (4K 2x). A 44 pt
  touch target is about 132 px on a phone canvas. Size each text box for the text its notes say it holds.
- Set the page dot_spacing first and keep every size, gap and padding a multiple of it.
- Build outside in, in batches: big regions, then children placed "in" them. Use arrange / grid / align / distribute
  instead of arithmetic. Build one repeated item (card, row, list item) with its children, then duplicate_shapes.
- Same element, same look: use design templates (list_templates; save_template for a small kit) via "template".
- Colours, borders and corners only where they mean something. The brief says the visual style in words."""


def _p_design_screen(a):
    dev = a.get("device") or "the right device preset (list_presets)"
    return f"""Design this screen in Uxandi: {a.get('screen')}
Device: {dev}.

1. get_status. If the project brief is empty, write it with set_project: the product, who it is for, the style.
2. add_page (or update_page) with the device preset. Page notes: what this screen is for, its main task, how the
   user gets here and where each action goes.
3. Build it (see the rules below), then check_layout and fix every warning, and screenshot to look at it.
4. Tell me what you built and anything you were unsure of.

{_COMMON}"""


def _p_design_flow(a):
    dev = a.get("device") or "the right device preset (list_presets)"
    return f"""Design this flow in Uxandi, one page per screen: {a.get('flow')}
Device: {dev}.

1. get_status, then write or extend the project brief (set_project).
2. List the screens first, including the states that need their own screen (empty, loading, error, success).
3. Build the first screen fully. Make the next ones with add_page copy_of (keeps the shared header / tab bar) and
   change what differs; or duplicate_shapes with "to" to put shared chrome on pages that already exist.
4. Navigation lives in notes: every button or link says which page it opens (by page name) and what it sends.
5. check_layout with page "all", screenshot each page, fix, then export_json.

{_COMMON}"""


def _p_review(a):
    which = f"page {a['page']}" if a.get("page") else "every page"
    return f"""Review the Uxandi layout ({which}) as the agent that must build it from the export, and fix what you can.

1. check_layout (page "all" for every page) and get_page; screenshot each page and look.
2. Fix: overlaps, near-misses of 1-2 px, shapes past the margins, generic or duplicate names, missing notes.
3. Then the things a tool cannot see: notes too thin to build from (no exact text, no behaviour, no states), repeated
   items that differ in size or spacing, gaps that are not multiples of the dot spacing, touch targets under about
   132 px on phone canvases, text boxes too small for the text their notes promise, unclear navigation between pages.
4. Report what you changed and what needs the user's decision. In live mode, select the shapes you mean.

{_COMMON}"""


def _p_handoff(a):
    return """Prepare this Uxandi project for the agent that will build the real UI.

1. get_status: the brief must say what the product is, who it is for, the visual style and any rules.
2. check_layout with page "all": no missing notes, no generic names, every page has notes.
3. Fix what is missing (ask me where only I can know the answer), then export_json (compact form; compact: false
   only if the builder is code that wants every field written out).
4. Give me the export path. The format is described by schema/ui.schema.json and schema/ui.compact.schema.json."""


PROMPTS = [
    {"name": "design_screen", "title": "Design a screen",
     "description": "Build one screen as a container layout with names and notes, ready to export.",
     "arguments": [{"name": "screen", "description": "What the screen is and what it must contain.", "required": True},
                   {"name": "device", "description": "Device preset, e.g. \"iPhone 16 Pro\" or \"Full HD 1920 x 1080\".", "required": False}],
     "text": _p_design_screen},
    {"name": "design_flow", "title": "Design a multi-screen flow",
     "description": "Onboarding, checkout, settings...: one page per screen, shared chrome, navigation in notes.",
     "arguments": [{"name": "flow", "description": "The flow and its screens.", "required": True},
                   {"name": "device", "description": "Device preset.", "required": False}],
     "text": _p_design_flow},
    {"name": "review_layout", "title": "Review and fix a layout",
     "description": "Check a layout the way the building agent will read it, and fix it.",
     "arguments": [{"name": "page", "description": "Page number or name (default: every page).", "required": False}],
     "text": _p_review},
    {"name": "prepare_handoff", "title": "Prepare the hand-off",
     "description": "Make sure brief and notes are complete, then export the JSON for the building agent.",
     "arguments": [], "text": _p_handoff},
]


def serve_mcp():
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    sys.stdout = sys.stderr          # stray prints must never corrupt the protocol stream

    def send(obj):
        out.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
        out.flush()

    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            msg = json.loads(raw.decode("utf-8"))
        except Exception:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        batch = msg if isinstance(msg, list) else [msg]
        replies = []
        for m in batch:
            if not isinstance(m, dict) or "method" not in m:
                continue          # a response to us: we send no requests, so ignore
            try:
                res = _handle(m)
                if m.get("id") is not None:
                    replies.append({"jsonrpc": "2.0", "id": m["id"], "result": res if res is not None else {}})
            except LookupError:
                if m.get("id") is not None:
                    replies.append({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": f"Method not found: {m.get('method')}"}})
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                if m.get("id") is not None:
                    replies.append({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32603, "message": str(e)}})
        if isinstance(msg, list):
            if replies:
                send(replies)
        else:
            for r in replies:
                send(r)


# ============================================================================= command line
def _cli(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd == "mcp":
        serve_mcp()
        return 0
    if cmd == "guide":
        print(agent.GUIDE.strip())
        return 0
    if cmd == "tools":
        for t in agent.tool_list():
            props = t["inputSchema"].get("properties", {})
            req = set(t["inputSchema"].get("required", []))
            args = ", ".join(k + ("*" if k in req else "") for k in props)
            print(f"{t['name']}({args})\n    {t['description']}\n")
        return 0
    if cmd == "call":
        if len(argv) < 2:
            print("usage: python uxandi_agent.py call <tool> ['{json args}' | @file.json | -] [--out file.png]", file=sys.stderr)
            return 2
        tool, rest = argv[1], argv[2:]
        out_png = None
        if "--out" in rest:
            k = rest.index("--out")
            out_png = rest[k + 1] if k + 1 < len(rest) else None
            rest = rest[:k] + rest[k + 2:]
        raw = rest[0] if rest else "{}"
        if raw == "-":
            raw = sys.stdin.read()
        elif raw.startswith("@"):
            raw = Path(raw[1:]).read_text(encoding="utf-8")
        try:
            args = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError as e:
            print(f"Arguments are not valid JSON: {e}", file=sys.stderr)
            return 2
        ok, res = run(tool, args)
        if not ok:
            print(json.dumps({"error": res}, indent=1, ensure_ascii=False))
            return 1
        img = res.pop("_image", None)
        if img:
            path = Path(out_png or f"uxandi_{tool}.png")
            path.write_bytes(img)
            res["image_file"] = str(path.resolve())
        sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    if cmd == "schema":
        from uxandi import schemas
        if "--check" in argv[1:]:
            bad = schemas.stale()
            if bad:
                print("Out of date in schema/: " + ", ".join(bad) + ". Run: python uxandi_agent.py schema", file=sys.stderr)
                return 1
            print("schema/ is up to date.")
            return 0
        for p in schemas.write_all():
            print(p)
        return 0
    if cmd == "validate":
        from uxandi import schemas
        if len(argv) < 2:
            print("usage: python uxandi_agent.py validate <file.ui.json | file.uxandi | template.json> ...", file=sys.stderr)
            return 2
        bad = 0
        for f in argv[1:]:
            try:
                data = json.loads(Path(f).read_text(encoding="utf-8"))
                name, sch = schemas.schema_for(data)
            except Exception as e:
                print(f"{f}: {e}")
                bad += 1
                continue
            errs = schemas.validate(data, sch)
            print(f"{f}: valid ({name})" if not errs else f"{f}: {len(errs)} problem(s) against {name}\n  " + "\n  ".join(errs))
            bad += bool(errs)
        return 1 if bad else 0
    print(f"Unknown command {cmd!r}. Try: mcp, tools, call, guide, schema, validate.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
