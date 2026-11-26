"""Headless check of the agent tools: file mode, the live bridge inside the app, and the MCP
server over stdio. Uses a temporary folder (UXANDI_HOME), never your projects or session.

    .venv\\Scripts\\python.exe tools\\check_agent.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="uxandi_agent_"))
os.environ["UXANDI_HOME"] = str(TMP)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
os.environ["UXANDI_NO_REVEAL"] = "1"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "_check"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))

import uxandi_agent as ua  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)   # the live part needs widgets; file mode reuses this app
fails = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


def ok(tool, args=None):
    good, res = ua.run(tool, args or {})
    if not good:
        raise AssertionError(f"{tool} failed: {res}")
    return res


def err(tool, args):
    good, res = ua.run(tool, args)
    return None if good else res


# ============================================================================= file mode
print("file mode")
st = ok("get_status")
check(st["mode"] == "file", "no app open: file mode")
ok("new_project", {"name": "Test Shop", "preset": "iPhone 16 Pro", "brief": "A small shop app."})
st = ok("get_status")
check(st["project"]["name"] == "Test Shop" and st["pages"][0]["size"] == "1206x2622", "new project with a phone canvas")
check((TMP / "projects" / "Test Shop.uxandi").exists(), "named project saved at once")
ok("update_page", {"notes": "Home screen: header, then a grid of products.", "margins": 24, "name": "Home"})
r = ok("create_shapes", {"shapes": [
    {"name": "Header", "x": 0, "y": 0, "w": "100%", "h": 120, "fill": "#FFFFFF", "stroke": "#E5E7EB", "stroke_width": 1,
     "notes": "Top bar."},
    {"name": "Logo", "in": "Header", "x": 16, "y": "center", "w": 80, "h": 48},
    {"name": "Title", "in": "Header", "w": 300, "h": 48},
    {"name": "Cart", "in": "Header", "x": "end-16", "y": "center", "w": 48, "h": 48, "radius": 24},
]})
check(any(a["name"] == "Header" for a in r.get("adjusted", [])), "header pushed inside the 24 px margins and reported")
hdr = next(c for c in r["created"] if c["name"] == "Header")
check(hdr["box"] == [24, 24, 1158, 120], f"header box after margins {hdr['box']}")
logo = next(c for c in r["created"] if c["name"] == "Logo")
check(logo["box"][0] == 40, "logo placed 16 px inside the header")
cart = next(c for c in r["created"] if c["name"] == "Cart")
check(cart["box"][0] + cart["box"][2] == 24 + 1158 - 16, "end-16 puts the cart 16 px from the right")
r = ok("arrange", {"shapes": ["Logo", "Title", "Cart"], "into": "Header", "padding": [0, 16], "gap": 12,
                   "sizes": [80, "1fr", 48], "align": "center", "cross_size": 48})
boxes = {p["name"]: p["box"] for p in r["placed"]}
check(boxes["Title"][0] == boxes["Logo"][0] + 80 + 12 and boxes["Cart"][0] == boxes["Title"][0] + boxes["Title"][2] + 12,
      f"arrange row with gaps {boxes}")
check(boxes["Title"][1] == 24 + 36, "centred across the header")
ok("create_shapes", {"shapes": [{"name": "Content", "in": "safe_area", "x": 0, "y": 140, "w": "100%", "h": 2000, "fill": None,
                                 "stroke": "#E5E7EB", "stroke_width": 1}]
                     + [{"name": f"Card {i + 1}", "fill": "#F3F4F6", "radius": 12, "notes": f"Product {i + 1}"} for i in range(6)]})
r = ok("grid", {"shapes": [f"Card {i + 1}" for i in range(6)], "into": "Content", "columns": 2, "gap": 16, "padding": 16, "aspect": 1.2})
check("warning" not in r, "grid fits its container")
check(r["cell"]["columns"] == 2 and r["cell"]["rows"] == 3, "grid 2 x 3")
pg = ok("get_page")
par = {s["name"]: s.get("parent") for s in pg["shapes"]}
cid = next(s["id"] for s in pg["shapes"] if s["name"] == "Content")
check(all(par[f"Card {i + 1}"] == cid for i in range(6)), "cards nest inside Content")
check("  Card 1" in pg["outline"], "outline shows nesting")
before = next(s["box"] for s in pg["shapes"] if s["name"] == "Card 1")
r = ok("update_shapes", {"changes": [{"shape": "Content", "move": [0, 20]}]})
check(r.get("carried_children") == 6, "moving Content carries its 6 cards")
pg = ok("get_page")
after = next(s["box"] for s in pg["shapes"] if s["name"] == "Card 1")
check(after[1] == before[1] + 20, "card moved with its container")
n0 = ok("get_status")["pages"][0]["shapes"]
e = err("batch", {"calls": [{"tool": "create_shapes", "args": {"shapes": [{"name": "Temp"}]}},
                            {"tool": "update_shapes", "args": {"changes": [{"shape": "Nope", "h": 4}]}}]})
check(e and "nothing was changed" in e and "Nope" in e, "batch fails with a clear message")
check(ok("get_status")["pages"][0]["shapes"] == n0, "failed batch kept nothing")
r = ok("batch", {"calls": [{"tool": "create_shapes", "args": {"shapes": [{"name": "Footer", "in": "safe_area", "x": 0, "y": "end", "w": "100%", "h": 80}]}},
                           {"tool": "update_page", "args": {"background": "#FAFAFA"}}]})
check(r["steps"] == 2, "batch of 2 runs")
check(ok("get_status")["pages"][0]["shapes"] == n0 + 1, "batch added the footer")
ok("history", {"action": "undo"})
check(ok("get_status")["pages"][0]["shapes"] == n0, "one undo removes the whole batch")
ok("history", {"action": "redo"})
e = err("create_shapes", {"shapes": [{"name": "X", "kind": "text"}]})
check(e and "no text element" in e, "text kind refused with the reason")
e = err("update_shapes", {"changes": [{"shape": "Header", "points": [0, 0, 1, 1]}]})
check(e and "belong to a line" in e, "line field on a rect explained")
e = err("create_shapes", {"shapes": [{"name": "Bad", "fill": "red"}]})
check(e and "hex" in e, "bad colour explained")
ok("create_shapes", {"shapes": [{"name": "Dup", "x": 100, "y": 300, "w": 50, "h": 50}, {"name": "Dup", "x": 200, "y": 300, "w": 50, "h": 50},
                               {"name": "Overlapper", "x": 800, "y": 100, "w": 300, "h": 100}]})
e = err("update_shapes", {"changes": [{"shape": "Dup", "h": 10}]})
check(e and "use an id" in e, "ambiguous name asks for an id")
ok("align", {"shapes": ["Logo"], "edge": "center_x", "to": "canvas"})
ck = ok("check_layout")
types = ck["counts"]
check("duplicate_name" in types and "overlap" in types, f"check_layout finds problems {sorted(types)}")
r = ok("screenshot", {"max_size": 800})
png = r.get("_image")
check(isinstance(png, bytes) and png[:4] == b"\x89PNG" and max(r["image_size"]) == 800, "screenshot PNG at 800 px")
(OUT / "agent_file_mode.png").write_bytes(png)
ok("add_page", {"name": "Product", "copy_of": 1, "notes": "Product details."})
ok("update_page", {"page": "Product", "orientation": "landscape"})
st = ok("get_status")
check(st["pages"][1]["size"] == "2622x1206" and st["current_page"] == 2, "copied page turned landscape")
ex = ok("export_json", {"compact": False})
check(Path(ex["file"]).exists() and ex["elements"] > 10, "export written")
data = json.loads(Path(ex["file"]).read_text(encoding="utf-8"))
check(data["format"] == "uxandi-export" and len(data["pages"]) == 2, "export is the normal agent JSON")
exc = ok("export_json")
cdata = json.loads(Path(exc["file"]).read_text(encoding="utf-8"))
check(exc["file"].endswith(".compact.ui.json") and cdata.get("compact") is True
      and sum(len(p["elements"]) for p in cdata["pages"]) == ex["elements"]
      and Path(exc["file"]).stat().st_size * 2 < Path(ex["file"]).stat().st_size,
      "export_json default is compact: same elements, much smaller file")
check(len(ok("list_projects")["projects"]) == 1, "list_projects")
ok("new_project", {"name": "Second"})
ok("open_project", {"project": "Test Shop"})
check(ok("get_status")["project"]["name"] == "Test Shop", "reopened the first project")
check(len(ok("list_presets")["presets"]["Phone"]) > 5, "presets")
ok("update_page", {"page": 2, "dot_spacing": 1})
check(ok("get_page", {"page": 2})["dot_spacing"] == 1, "dot spacing goes down to 1 px")
ok("update_page", {"page": 2, "dot_spacing": 0})
check(ok("get_page", {"page": 2})["dot_spacing"] == 1, "dot spacing below 1 is held at 1")

# ----------------------------------------------------------------------------- copies, templates, flip, import
print("copies, templates, flip, import")
ok("create_shapes", {"page": 1, "shapes": [
    {"name": "Tile 1", "x": 100, "y": 1400, "w": 300, "h": 200},
    {"name": "Tile 1 label", "in": "Tile 1", "x": 20, "y": 20, "w": 200, "h": 40},
    {"name": "Badge", "in": "Tile 1", "x": "end-20", "y": 20, "w": 40, "h": 40}]})
r = ok("duplicate_shapes", {"page": 1, "shapes": ["Tile 1"], "count": 2})
cp = r["copies"]
check([c["name"] for c in cp] == ["Tile 2", "Tile 3"], f"copies take the next free names {[c['name'] for c in cp]}")
check([k["name"] for k in cp[0]["children"]] == ["Tile 2 label", "Badge 2"], "children follow their container's name, or get a number")
pg = ok("get_page", {"page": 1})
by = {s["name"]: s for s in pg["shapes"]}
check(by["Tile 2 label"]["parent"] == by["Tile 2"]["id"] and by["Tile 1 label"]["parent"] == by["Tile 1"]["id"],
      "overlapping copies: each child keeps its own container")
r = ok("grid", {"page": 1, "shapes": ["Tile 1", "Tile 2", "Tile 3"], "into": "Content", "columns": 3, "gap": 16, "padding": 16, "row_height": 200})
pg = ok("get_page", {"page": 1})
by = {s["name"]: s for s in pg["shapes"]}
check(all(by[f"Tile {n} label"]["parent"] == by[f"Tile {n}"]["id"] for n in (1, 2, 3)), "grid carries each copy's children")
r = ok("duplicate_shapes", {"page": 1, "shapes": ["Header"], "to": 2})
check(r["page"] == 2 and r["copies"][0]["name"] == "Header 2" and len(r["copies"][0]["children"]) == 3,
      f"copy with children to another page {r['copies'][0]['name']}")
e = err("duplicate_shapes", {"page": 1, "shapes": ["Tile 1"], "count": 2, "names": ["Only one"]})
check(e and "one name per copy" in e, "names count checked")
r = ok("save_template", {"name": "Primary button", "fill": "#1F6FEB", "stroke": None, "radius": 12})
check(Path(r["saved"]).exists() and str(TMP) in r["saved"], "save_template writes under UXANDI_HOME")
e = err("save_template", {"name": "Primary button", "fill": "#000000"})
check(e and "overwrite" in e, "save_template will not overwrite by accident")
check(ok("list_templates")["templates"][0]["fill"] == "#1F6FEB", "list_templates")
check("Primary button" in ok("get_status")["design_templates"], "get_status lists templates")
r = ok("create_shapes", {"page": 1, "shapes": [{"name": "Buy button", "in": "Tile 1", "x": 20, "y": "end-20", "w": 120, "h": 40,
                                                "template": "Primary button", "radius": 4}]})
pg = ok("get_page", {"page": 1})
bb = next(s for s in pg["shapes"] if s["name"] == "Buy button")
check(bb["fill"] == "#1F6FEB" and bb["stroke"] is None and bb["radius"] == 4, "template styles a shape; fields beside it win")
e = err("update_shapes", {"page": 1, "changes": [{"shape": "Buy button", "template": "Nope"}]})
check(e and "Primary button" in e, "unknown template lists the saved ones")
ok("update_shapes", {"page": 1, "changes": [{"shape": "Buy button", "rotation": 10, "flip_h": True}]})
bb = next(s for s in ok("get_page", {"page": 1})["shapes"] if s["name"] == "Buy button")
check(bb.get("flip_h") is True and bb["rotation"] == -10, "flip_h mirrors the shape (rotation too)")
# circles and ovals: containers like rectangles
cr = ok("create_shapes", {"page": 1, "shapes": [
    {"name": "Avatar", "kind": "circle", "x": 40, "y": 40, "w": 120, "notes": "User photo, round."},
    {"name": "Avatar dot", "kind": "circle", "in": "Avatar", "x": "end-8", "y": "end-8", "w": 24, "notes": "Online status."},
    {"name": "Status pill", "kind": "ellipse", "x": 400, "y": 40, "w": 160, "h": 80, "notes": "Pill-shaped badge."}]})
shp = {s["name"]: s for s in ok("get_page", {"page": 1})["shapes"]}
check(shp["Avatar"]["kind"] == "ellipse" and shp["Avatar"]["box"][2] == shp["Avatar"]["box"][3] == 120
      and shp["Status pill"]["kind"] == "ellipse" and shp["Status pill"]["box"][3] == 80, "create_shapes makes circles (w = h) and ovals")
check(shp["Avatar dot"].get("parent") == shp["Avatar"]["id"], "a circle holds children like a rectangle")
ok("update_shapes", {"page": 1, "changes": [{"shape": "Status pill", "kind": "rect"}]})
check(next(s for s in ok("get_page", {"page": 1})["shapes"] if s["name"] == "Status pill")["kind"] == "rect",
      "kind switches between rect and ellipse, keeping the box")
e = err("update_shapes", {"page": 1, "changes": [{"shape": "Status pill", "kind": "line"}]})
check(e and "cannot become" in e, "a box cannot turn into a line")
ok("update_shapes", {"page": 1, "changes": [{"shape": "Status pill", "kind": "ellipse"}]})
# freehand drawings: a mark the agent can read (and draw)
ok("create_shapes", {"page": 1, "shapes": [{"name": "Fix avatar", "kind": "path", "notes": "Circled: make the avatar bigger.",
                                             "points": [[30, 30], [180, 26], [190, 170], [24, 166], [32, 36]]}]})
mk = next(s for s in ok("get_page", {"page": 1})["shapes"] if s["name"] == "Fix avatar")
check(mk["kind"] == "path" and mk["points"][0] == [30, 30] and len(mk["points"]) == 5 and mk["box"] == [24, 26, 166, 144],
      f"create_shapes draws a path through its points {mk.get('box')}")
check(not any(s.get("parent") == mk["id"] for s in ok("get_page", {"page": 1})["shapes"]), "a drawing never holds shapes")
lay = ok("check_layout", {"page": 1})
check(not any("Fix avatar" in f.get("shapes", []) and f["type"] in ("overlap", "near_miss", "invisible", "tiny")
              for f in lay["issues"]), "check_layout does not flag a drawing for crossing things")
ok("update_shapes", {"page": 1, "changes": [{"shape": "Fix avatar", "move": [10, 0]}]})
mk2 = next(s for s in ok("get_page", {"page": 1})["shapes"] if s["name"] == "Fix avatar")
check(mk2["points"][0] == [40, 30], "moving a drawing moves every point")
e = err("create_shapes", {"page": 1, "shapes": [{"name": "Empty mark", "kind": "path"}]})
check(e and "points" in e, "a drawing needs points")
e = err("update_shapes", {"page": 1, "changes": [{"shape": "Fix avatar", "kind": "rect"}]})
check(e and "only rect and ellipse" in e, "a drawing cannot turn into a box")
e = err("create_shapes", {"page": 1, "shapes": [{"name": "Inside mark", "in": "Fix avatar", "x": 0, "y": 0, "w": 10, "h": 10}]})
check(e and "drawing" in e, "nothing can be placed in a drawing")
cex = json.loads(Path(ok("export_json")["file"]).read_text(encoding="utf-8"))
pe = next(e_ for p_ in cex["pages"] for e_ in p_["elements"] if e_["name"] == "Fix avatar")
check(pe["type"] == "path" and pe["points"][0] == [40, 30] and pe["notes"].startswith("Circled"), "export: the drawing's points and notes")
ctypes = {e_["name"]: e_.get("type", "rectangle") for p_ in cex["pages"] for e_ in p_["elements"]}
check(ctypes["Avatar"] == "circle" and ctypes["Status pill"] == "ellipse", f"export types circle / ellipse {ctypes.get('Avatar')}")
n_before = ok("get_status")["pages"][0]["shapes"]
ok("export_json", {})
r = ok("import_export", {"file": "Test Shop", "name": "Test Shop copy"})
check(r["project"]["name"] == "Test Shop copy" and (TMP / "projects" / "Test Shop copy.uxandi").exists(), "import_export round trip")
check(r["pages"][0]["shapes"] == n_before, "every shape came back")
e = err("import_export", {"file": "Test Shop", "name": "Test Shop copy"})
check(e and "exists already" in e, "import will not overwrite a project by accident")
e = err("batch", {"calls": [{"tool": "save_template", "args": {"name": "X"}}]})
check(e and "cannot run inside a batch" in e, "file / template commands stay out of batches")

# ----------------------------------------------------------------------------- schemas
print("schemas")
from uxandi import schemas  # noqa: E402

check(not schemas.stale(), f"schema/ and TOOLS.md match the code {schemas.stale()} (run: python uxandi_agent.py schema)")
exp = ok("export_json", {"compact": False})
cexp = ok("export_json")
for f in (exp["file"], cexp["file"], str(TMP / "projects" / "Test Shop copy.uxandi"),
          str(TMP / "templates" / "design" / "Primary button.json")):
    data = json.loads(Path(f).read_text(encoding="utf-8"))
    name, sch = schemas.schema_for(data)
    errs = schemas.validate(data, sch)
    check(not errs, f"{Path(f).name} is valid against {name} {errs[:3]}")
bad = json.loads(Path(exp["file"]).read_text(encoding="utf-8"))
bad["pages"][0]["elements"][0]["style"]["fill"] = "red"
check(schemas.validate(bad, schemas.export_schema()), "the validator catches a bad colour")
tools_json = json.loads((ROOT / "schema" / "tools.json").read_text(encoding="utf-8"))
check({t["name"] for t in tools_json["tools"]} == set(ua.agent.BY_NAME), "schema/tools.json lists every tool")

# ----------------------------------------------------------------------------- every recipe in TOOLS.md
print("TOOLS.md recipes")
import re  # noqa: E402

ok("new_project", {"name": "Recipes", "brief": "Every recipe in TOOLS.md, run in order."})
md = (ROOT / "TOOLS.md").read_text(encoding="utf-8")
recipes = re.findall(r"```json\n(.*?)```", md[md.index("## Recipes"):md.index("## The export")], re.S)
for n, blk in enumerate(recipes, 1):
    c = json.loads(blk)
    good, res = ua.run(c["tool"], c["args"])
    check(good, f"recipe {n} ({c['tool']}) {'' if good else res}")
ck = ok("check_layout", {"page": "all"})
real = [x for x in ck["issues"] if x["level"] != "info" and x.get("page") != 1]
check(not real, f"the recipes build a clean layout {[x['message'] for x in real][:5]}")
ok("open_project", {"project": "Test Shop"})

# ============================================================================= live: the app with its bridge
print("live mode (the app, offscreen)")
import uxandi.window as winmod  # noqa: E402

w = winmod.MainWindow()
w.resize(1600, 950)
w.show()
app.processEvents()
check(w.bridge is not None and (TMP / "data" / "bridge.json").exists(), "bridge started and wrote data/bridge.json")
results = {}


def client():
    try:
        results["status"] = ua.live_call("get_status", {})
        results["make"] = ua.live_call("create_shapes", {"shapes": [{"name": "Live box", "x": 200, "y": 200, "w": 300, "h": 200}]})
        results["shot"] = ua.live_call("screenshot", {"of": "window", "max_size": 900})
        results["bad"] = ua.live_call("update_shapes", {"changes": [{"shape": "Nope"}]})
        results["tpl"] = ua.live_call("save_template", {"name": "Live style", "fill": "#00AA00"})
        info = json.loads((TMP / "data" / "bridge.json").read_text())
        import socket
        s = socket.create_connection(("127.0.0.1", info["port"]))
        s.sendall(json.dumps({"token": "wrong", "tool": "get_status"}).encode() + b"\n")
        results["token"] = json.loads(s.recv(65536).decode())
        s.close()
    except Exception as e:  # pragma: no cover
        results["exc"] = repr(e)


th = threading.Thread(target=client)
th.start()
t0 = time.time()
while th.is_alive() and time.time() - t0 < 60:
    app.processEvents()
    time.sleep(0.005)
check("exc" not in results, f"client ran {results.get('exc', '')}")
check(results["status"][0] and results["status"][1]["mode"] == "live", "live get_status")
check(results["make"][0] and any(s.name == "Live box" for s in w.doc.page.shapes), "shape appears in the open window")
check(w.doc._undo and "Agent" in w.status.toolTip(), "agent edit is an undo step and shows in the status bar")
check(results["shot"][0] and results["shot"][1]["_image"][:4] == b"\x89PNG", "window screenshot")
(OUT / "agent_live_window.png").write_bytes(results["shot"][1]["_image"])
check(results["bad"] == (False, results["bad"][1]) and "No shape" in results["bad"][1], "live error comes back as text")
check(not results["token"]["ok"], "wrong token refused")
cv = w.panels["canvas"]
w.doc.page.dots = False
cv.refresh()
check(cv.sp.minimum() == 1 and cv.sp.isEnabled(), "Canvas tab: dot spacing from 1 px, editable while the dots are hidden")
dp = w.panels["design"]
check(results["tpl"][0] and dp.tpl.findText("Live style") >= 0, "save_template shows up in the Design tab at once")
w.doc.undo()
check(not any(s.name == "Live box" for s in w.doc.page.shapes), "Ctrl+Z undoes the agent's shape")
w.close()
check(not (TMP / "data" / "bridge.json").exists(), "bridge.json removed on close")

# ============================================================================= MCP over stdio
print("MCP server")
env = dict(os.environ)
p = subprocess.Popen([sys.executable, str(ROOT / "uxandi_agent.py"), "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, env=env)


def rpc(obj):
    p.stdin.write((json.dumps(obj) + "\n").encode())
    p.stdin.flush()
    if "id" not in obj:
        return None
    return json.loads(p.stdout.readline().decode())


init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "check", "version": "0"}}})
check(init["result"]["protocolVersion"] == "2025-06-18" and "instructions" in init["result"], "initialize")
rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
tl = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
names = [t["name"] for t in tl["result"]["tools"]]
check(len(names) >= 20 and "create_shapes" in names and "batch" in names, f"tools/list: {len(names)} tools")
c = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_status", "arguments": {}}})
check(not c["result"]["isError"] and json.loads(c["result"]["content"][0]["text"])["project"]["name"] == "Test Shop", "tools/call get_status")
c = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "screenshot", "arguments": {"max_size": 400}}})
check(any(x["type"] == "image" for x in c["result"]["content"]), "screenshot returns an image block")
c = rpc({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "update_shapes", "arguments": {"changes": [{"shape": "Nope"}]}}})
check(c["result"]["isError"], "tool error is isError, not a protocol error")
c = rpc({"jsonrpc": "2.0", "id": 6, "method": "bogus/method"})
check(c.get("error", {}).get("code") == -32601, "unknown method")
caps = init["result"]["capabilities"]
check("resources" in caps and "prompts" in caps, "initialize offers resources and prompts")
rl = rpc({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})["result"]["resources"]
uris = [x["uri"] for x in rl]
check("uxandi://schema/ui.schema.json" in uris and "uxandi://reference/tools" in uris and "uxandi://guide" in uris,
      f"resources/list: {len(uris)} resources")
rr = rpc({"jsonrpc": "2.0", "id": 8, "method": "resources/read", "params": {"uri": "uxandi://schema/ui.schema.json"}})
check(json.loads(rr["result"]["contents"][0]["text"])["title"] == "Uxandi export", "resources/read returns the export schema")
pl = rpc({"jsonrpc": "2.0", "id": 9, "method": "prompts/list"})["result"]["prompts"]
check({"design_screen", "design_flow", "review_layout", "prepare_handoff"} <= {x["name"] for x in pl}, "prompts/list")
pgp = rpc({"jsonrpc": "2.0", "id": 10, "method": "prompts/get",
           "params": {"name": "design_screen", "arguments": {"screen": "A login screen", "device": "iPhone 16 Pro"}}})
check("A login screen" in pgp["result"]["messages"][0]["content"]["text"], "prompts/get fills the arguments")
pgp = rpc({"jsonrpc": "2.0", "id": 11, "method": "prompts/get", "params": {"name": "design_screen", "arguments": {}}})
check("error" in pgp and "screen" in pgp["error"]["message"], "prompts/get asks for a missing argument")
p.stdin.close()
p.wait(10)
check(p.returncode == 0, "server exits cleanly when stdin closes")

print()
print("ALL OK" if not fails else f"{len(fails)} FAILED:\n  " + "\n  ".join(fails))
print("temp folder:", TMP)
sys.exit(1 if fails else 0)
