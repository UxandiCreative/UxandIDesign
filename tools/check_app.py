"""Headless check: drives the real app with simulated mouse and keys, asserts the
results and saves screenshots to tools/_check/. Never touches your session.

    .venv\\Scripts\\python.exe tools\\check_app.py
"""
import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "tools" / "_check"
OUT.mkdir(parents=True, exist_ok=True)

import uxandi.doc as docmod  # noqa: E402
from uxandi.model import Shape  # noqa: E402
tmp = Path(tempfile.mkdtemp())
docmod.SESSION_FILE = tmp / "session.json"
docmod.DATA_DIR = tmp
docmod.PROJECTS_DIR = tmp / "projects"

from PySide6.QtCore import Qt, QPoint, QPointF  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

import uxandi.window as winmod  # noqa: E402
from PySide6.QtWidgets import QMessageBox as _QMB  # noqa: E402
_QMB.question = staticmethod(lambda *a, **k: _QMB.StandardButton.Discard)
_QMB.warning = staticmethod(lambda *a, **k: print("WARNING DIALOG:", a[1:3]) or _QMB.StandardButton.Ok)
winmod.PROJECTS_DIR = docmod.PROJECTS_DIR
winmod.EXPORTS_DIR = tmp / "exports"
os.environ["UXANDI_NO_REVEAL"] = "1"
import uxandi.images as imgmod  # noqa: E402
import uxandi.design as desmod  # noqa: E402
imgmod.IMAGES_DIR = tmp / "assets" / "images"
desmod.TEMPLATES_DIR = tmp / "templates" / "design"

errors = []
def _hook(*a):
    msg = "".join(traceback.format_exception(*a))
    errors.append(msg)
    print(msg)


sys.excepthook = _hook

app = QApplication(sys.argv)
w = winmod.MainWindow()
w.resize(1920, 1080)
w.show()
app.processEvents()
b = w.board
doc = w.doc


def shot(name):
    for _ in range(4):
        app.processEvents()
    w.grab().save(str(OUT / f"{name}.png"))


def scr(x, y):
    p = b.to_screen(x, y)
    return QPoint(round(p.x()), round(p.y()))


def mouse(kind, pt, btn=Qt.MouseButton.LeftButton, mods=Qt.KeyboardModifier.NoModifier):
    t = {"press": QMouseEvent.Type.MouseButtonPress, "move": QMouseEvent.Type.MouseMove,
         "release": QMouseEvent.Type.MouseButtonRelease}[kind]
    buttons = Qt.MouseButton.NoButton if kind == "release" else btn
    ev = QMouseEvent(t, QPointF(pt), QPointF(b.mapToGlobal(pt)), btn if kind != "move" else Qt.MouseButton.NoButton,
                     buttons, mods)
    QApplication.sendEvent(b, ev)
    app.processEvents()


def drag(p0, p1, steps=8, mods=Qt.KeyboardModifier.NoModifier, release=True, btn=Qt.MouseButton.LeftButton):
    mouse("press", p0, btn, mods)
    for i in range(1, steps + 1):
        mouse("move", QPoint(p0.x() + (p1.x() - p0.x()) * i // steps, p0.y() + (p1.y() - p0.y()) * i // steps), btn, mods)
    if release:
        mouse("release", p1, btn, mods)


def image_ok(s_):
    return bool(s_ and isinstance(s_.contents, dict) and s_.contents.get("type") == "image")


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        errors.append(msg)


b.fit()
pg = doc.page
check((pg.width, pg.height) == (1920, 1080), "default canvas is 1920 x 1080")

# draw a rectangle with the tool
b.set_tool("rect")
drag(scr(200, 200), scr(600, 440))
s1 = doc.selected()[0]
check(s1.kind == "rect" and abs(s1.w - 400) <= 2 and abs(s1.h - 240) <= 2, f"drew rectangle {s1.w}x{s1.h}")
check(b.tool == "select", "tool returns to select after drawing")

# a second rectangle via the Create panel
w.add_shape("rect", (1200, 320))
s2 = doc.selected()[0]
check(s2.name == "Rectangle 2", f"second shape is named {s2.name}")

# move s2 so its top lines up with s1's top: drop it near y=200 and expect a snap
doc.set_selection([s2.id])
c = s2.center()
target_top = 200 + 4  # 4 px off: should snap to 200
drag(scr(*c), scr(c[0], c[1] - (s2.y - target_top)), release=False)
shot("01_snapping_while_moving")
mouse("release", scr(c[0], c[1] - (s2.y - target_top)))
check(abs(s2.y - 200) < 0.01, f"top edge snapped to 200 (y={s2.y})")

# canvas centre: drag s1 near the middle, expect exact centre
doc.set_selection([s1.id])
c = s1.center()
drag(scr(*c), scr(960 + 3, 540 - 2), release=False)
shot("02_canvas_centre_lines")
mouse("release", scr(960 + 3, 540 - 2))
check(s1.center() == (960, 540), f"centred on the canvas {s1.center()}")

# resize s1 by its right handle
doc.set_selection([s1.id])
app.processEvents()
h = [hh for hh in b.handles() if hh[0] == "resize" and hh[1] == (1, 0)][0]
p0 = QPoint(round(h[2].x()), round(h[2].y()))
drag(p0, p0 + QPoint(120, 0))
check(s1.w > 400, f"resized wider: {s1.w}")

# rotate with the round handle, Shift = 15 degree steps
h = [hh for hh in b.handles() if hh[0] == "rot"][0]
p0 = QPoint(round(h[2].x()), round(h[2].y()))
cx, cy = s1.center()
end = scr(cx + 300, cy - 300)
drag(p0, end, mods=Qt.KeyboardModifier.ShiftModifier)
check(abs(s1.rotation - 45) < 0.01, f"rotated to {s1.rotation}")

# corner radius from the panel field
w.panels["design"].refresh(); w.panels["design"].rad.setValue(30)
check(s1.radius == 30, "corner radius 30")

# nudge with arrows: 3 x Right = 3 px, one undo step
x0 = s1.x
b.setFocus()
for _ in range(3):
    QTest.keyClick(b, Qt.Key.Key_Right)
check(abs(s1.x - x0 - 3) < 0.01, "arrow keys nudge 1 px")
QTest.keyClick(b, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
check(abs(s1.x - x0 - 13) < 0.01, "Shift+arrow nudges 10 px")
doc.undo()
s1 = doc.page.get(s1.id)
check(abs(s1.x - x0) < 0.01, "one undo takes back all the quick nudges")

# a line
b.set_tool("line")
drag(scr(300, 800), scr(900, 812), mods=Qt.KeyboardModifier.ShiftModifier)
ln = doc.selected()[0]
check(ln.is_line and abs(ln.y2 - ln.y1) < 0.01, "Shift draws a straight line")

# equal spacing: three squares in a row
doc.set_selection([])
for x in (200, 500):
    w.add_shape("square", (x, 900))
sq = doc.selected()[0]
w.add_shape("square", (900, 900))
s3 = doc.selected()[0]
a_, b_ = [s for s in doc.page.shapes if s.name in ("Square 1", "Square 2")]
gap = b_.x - (a_.x + a_.w)
want = b_.x + b_.w + gap
c = s3.center()
drag(scr(*c), scr(c[0] - (s3.x - want) + 5, c[1]), release=False)
shot("03_equal_spacing")
mouse("release", scr(c[0] - (s3.x - want) + 5, c[1]))
check(abs(s3.x - want) < 0.01, f"snapped to equal gap {gap} (x={s3.x}, want {want})")

# flip / rotate buttons, rename
doc.set_selection([s3.id])
w.rotate_by(90); w.flip(0)
check(s3.flip_h, "flip sets the flag")
b.start_rename(s3.id)
b._rename.setText("Hero box")
b._finish_rename()
check(doc.page.get(s3.id).name == "Hero box", "renamed on the board")

# pages: new page with phone size
doc.add_page()
w.panels["canvas"].refresh()
pp = w.panels["canvas"].preset
i = next(i for i in range(pp.count()) if pp.itemData(i) and pp.itemData(i)[0] == "iPhone 15 / 16")
pp.setCurrentIndex(i); w.panels["canvas"]._preset(i)
check((doc.page.width, doc.page.height) == (1179, 2556), "iPhone canvas on page 2")
w.add_shape("rect")
doc.go_page(0)
shot("04_board_page1")

# save + load round trip
path = doc.save(docmod.PROJECTS_DIR / "check.uxandi")
n = len(doc.project.pages)
doc.load(path)
check(len(doc.project.pages) == n and doc.page.get(s3.id).name == "Hero box", "save and load keep everything")

# right-drag pans
ox = b.ox
drag(QPoint(500, 500), QPoint(600, 520), btn=Qt.MouseButton.RightButton)
check(abs(b.ox - ox - 100) < 1, "right-drag pans")
z = b.zoom
from PySide6.QtGui import QWheelEvent  # noqa: E402
ev = QWheelEvent(QPointF(400, 400), QPointF(b.mapToGlobal(QPoint(400, 400))), QPoint(0, 0), QPoint(0, 120),
                 Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
QApplication.sendEvent(b, ev)
check(b.zoom > z, "wheel zooms in")

# margins: default 40 px all round, shapes stop at the line
doc.go_page(0)
b.fit()
app.processEvents()
pg = doc.page
check(pg.margins == [40, 40, 40, 40] and pg.keep_inside and pg.show_margins, "margins on by default, 40 px")
w.add_shape("rect", (600, 300))
m1 = doc.selected()[0]
c = m1.center()
drag(scr(*c), scr(c[0] - 2000, c[1] - 2000))
check(abs(m1.x - 40) < 0.01 and abs(m1.y - 40) < 0.01, f"dragging past the margin stops at it ({m1.x}, {m1.y})")
doc.set_selection([m1.id]); app.processEvents()
h = [hh for hh in b.handles() if hh[0] == "resize" and hh[1] == (1, 1)][0]
p0 = QPoint(round(h[2].x()), round(h[2].y()))
drag(p0, p0 + QPoint(3000, 3000))
bx = m1.aabb()
check(abs(bx[2] - (pg.width - 40)) < 0.6 and abs(bx[3] - (pg.height - 40)) < 0.6, f"resizing stops at the margins {bx}")
b.setFocus()
QTest.keyClick(b, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
check(abs(m1.x - 40) < 0.01, "nudging cannot cross the margin")
cp = w.panels["canvas"]
cp.refresh()
cp.m[0].setValue(100)
check(pg.margins == [100, 100, 100, 100], "linked margins: one value sets all four")
cp.mlink.setChecked(False)
cp.m[1].setValue(10)
check(pg.margins == [100, 10, 100, 100], "unlinked margins: each side on its own")
cp._pull()
check(m1.aabb()[1] >= 100 - 0.01 and m1.aabb()[3] <= pg.height - 100 + 0.01, "Move everything inside fits shapes to new margins")
doc.set_selection([])
shot("07_margins")
cp.mkeep.setChecked(False)
c = m1.center()
doc.set_selection([m1.id])
drag(scr(*c), scr(c[0] - 400, c[1]))
check(m1.x < 0, "with 'keep inside' off shapes can cross the margins")
cp.mkeep.setChecked(True)
cp.mlink.setChecked(True)
cp.m[0].setValue(40)

# dot snapping: every edge on a dot, always
doc.go_page(0); b.fit(); app.processEvents()
w.panels["snap"].boxes["grid"].setChecked(True)
g = doc.page.dot_spacing
on_dots = lambda s: all(abs(v / g - round(v / g)) < 1e-6 for v in (s.aabb() if not s.is_line else (s.x1, s.y1, s.x2, s.y2)))
b.set_tool("rect")
drag(scr(333, 217), scr(611, 449))
d1 = doc.selected()[0]
check(on_dots(d1), f"drawn rectangle sits on dots {d1.aabb()}")
w.add_shape("rect", (777, 333))
d2 = doc.selected()[0]
check(on_dots(d2), f"placed rectangle sits on dots {d2.aabb()}")
d2.x += 7; d2.w += 3   # knock it off the dots, then move it
c = d2.center()
drag(scr(*c), scr(c[0] + 137, c[1] + 61))
check(on_dots(d2), f"moved shape lands fully on dots {d2.aabb()}")
doc.set_selection([d2.id]); app.processEvents()
h = [hh for hh in b.handles() if hh[0] == "resize" and hh[1] == (1, 1)][0]
p0 = QPoint(round(h[2].x()), round(h[2].y()))
drag(p0, p0 + QPoint(53, 29))
check(on_dots(d2), f"resized shape stays on dots {d2.aabb()}")
x0 = d2.x
b.setFocus(); QTest.keyClick(b, Qt.Key.Key_Right)
check(abs(d2.x - x0 - g) < 1e-6, "arrow key moves one dot")
b.set_tool("line")
drag(scr(900, 700), scr(1213, 791))
check(on_dots(doc.selected()[0]), "drawn line ends on dots")
w.panels["shape"].refresh(); doc.set_selection([d1.id]); w.panels["shape"].refresh()
w.panels["shape"].x.setValue(447)
check(on_dots(d1), f"typed x snaps to dots ({d1.x})")
# alignment lines while dragging (dots off): drag d2 so its top meets d1's top
w.panels["snap"].boxes["grid"].setChecked(False)
doc.set_selection([d2.id])
c = d2.center()
mouse("press", scr(*c)); mouse("move", scr(c[0] + 5, c[1] + 5)); mouse("move", scr(c[0] + 40, c[1] - (d2.y - d1.y)))
xs, ys = b._alignments(doc.selected())
bb = d2.aabb()
check(ys and all(any(abs(y - v) < 0.5 for v in (bb[1], (bb[1] + bb[3]) / 2, bb[3])) for y in ys), f"see-through alignment lines on the dragged edges {ys}")
shot("08_alignment_lines")
mouse("release", scr(c[0] + 40, c[1] - (d2.y - d1.y)))

# notes box: first thing in Details, saved with the shape
w.right.open = ["shape", "details", "shapes"]; w.right._sync()
doc.set_selection([d1.id]); app.processEvents(); w.refresh_panels(); app.processEvents()
dp = w.panels["details"]
check(dp.notes_f.isVisible() and dp.b.indexOf(dp.notes_f) == 0, "notes box is the first thing in Details")
dp.notes.setPlainText("Hero banner. Goes on every page.")
dp._notes_timer.timeout.emit() if False else dp._notes_save()
check(doc.page.get(d1.id).notes == "Hero banner. Goes on every page.", "typed notes are stored on the shape")
check(doc.page.get(d1.id).to_dict()["notes"].startswith("Hero"), "notes are part of the shape's data")
doc.set_selection([d2.id]); app.processEvents(); w.refresh_panels()
check(dp.notes.toPlainText() == "", "another shape shows its own (empty) notes")
doc.set_selection([d1.id]); app.processEvents(); w.refresh_panels()
check(dp.notes.toPlainText().startswith("Hero"), "notes come back when the shape is selected again")
path2 = doc.save(docmod.PROJECTS_DIR / "notes.uxandi"); doc.load(path2)
check(doc.page.get(d1.id).notes.startswith("Hero"), "notes survive save and load")
doc.set_selection([d1.id]); app.processEvents(); w.refresh_panels()
dp.notes.setFocus(); app.processEvents()
fh = doc.page.get(d1.id).flip_h
QTest.keyClicks(dp.notes, " Hi")
QTest.keyClick(dp.notes, Qt.Key.Key_H, Qt.KeyboardModifier.ShiftModifier)
check(doc.page.get(d1.id).flip_h == fh, "typing Shift+H in notes never flips the shape")
b.setFocus()
shot("09_notes")

# groups: + Group pill, group pills select, ungroup
doc.go_page(0); b.fit(); app.processEvents(); b.update(); app.processEvents()
pg = doc.page
three = [s_.id for s_ in pg.shapes if not s_.is_line][:3]
doc.set_selection(three); app.processEvents()
pills = b.pill_layout()
check(pills and pills[0][0] == "add", "+ Group pill sits first, bottom-left")
r = pills[0][2]
check(r.left() < 40 and r.bottom() > b.height() - 50, f"pill is in the bottom-left corner {r}")
mouse("press", r.center().toPoint()); mouse("release", r.center().toPoint())
check(len(pg.groups) == 1 and set(pg.groups[0]["members"]) == set(three), "+ Group made a group of the selection")
gid = pg.groups[0]["id"]
doc.set_selection([]); app.processEvents()
gr = [pp for pp in b.pill_layout() if pp[1] == gid][0][2]
mouse("press", gr.center().toPoint()); mouse("release", gr.center().toPoint())
check(set(doc.selection) == set(three), "clicking the group pill selects the whole group")
doc.set_selection([three[0]])
doc.ungroup_selected()
check(three[0] not in pg.groups[0]["members"] and len(pg.groups[0]["members"]) == 2, "ungroup takes one shape out of its group")
doc.select_group(gid)
doc.delete_selected()
check(pg.get_group(gid) is None, "deleting every member removes the group")
doc.undo()
pg = doc.page
check(pg.get_group(gid) is not None, "undo brings the group back")
doc.set_selection(three[:2]); doc.group_selection()
check(len(pg.groups) == 2 and pg.group_of(three[1])["id"] != gid and pg.get_group(gid)["members"] == [three[2]], "regrouping moves shapes out of their old group")
pth = doc.save(docmod.PROJECTS_DIR / "groups.uxandi"); doc.load(pth)
check(len(doc.page.groups) == 2, "groups survive save and load")
pg = doc.page
doc.page.groups[-1]["name"] = "Buttons"; doc.structure.emit()
gid0 = doc.page.groups[0]["id"]
doc.set_selection([]); b.hover_pill = gid0
shot("10_groups")
b.hover_pill = None

# export for agents
import json as _json
doc.project.name = "Recipe App"
w.panels["brief"].proj.setPlainText("Recipe app for busy parents. Calm, rounded, green.")
w.panels["brief"].page_t.setPlainText("Home screen: today's recipes.")
outer = Shape(kind="rect", x=100, y=100, w=800, h=500, name="Card")
inner = Shape(kind="rect", x=150, y=150, w=200, h=80, name="Buy button", notes="Primary call to action")
doc.page.shapes += [outer, inner]; doc.commit("test shapes")
path = w.export_json(compact=False)
check(path is not None and path.exists() and path.name == "Recipe App.ui.json" and path.parent.name == "Recipe App",
      f"export written to exports/<project>/<project>.ui.json ({path})")
check(len(list((path.parent / "history").glob("*.json"))) == 1, "a dated copy goes into history/")
data = _json.loads(path.read_text(encoding="utf-8"))
check(QApplication.clipboard().text() == path.read_text(encoding="utf-8"), "the export is copied to the clipboard")
check(data["format"] == "uxandi-export" and data["how_to_read"], "export has a format tag and reading guide")
miss = {e["id"] for e in data["summary"]["elements_without_notes"]}
allids = {e["id"]: e for pp in data["pages"] for e in pp["elements"]}
check(inner.id not in miss and outer.id in miss
      and miss == {i for i, e in allids.items() if not e["notes"].strip()}
      and data["summary"]["elements_without_notes_count"] == len(miss)
      and data["summary"]["elements_with_notes"] + len(miss) == data["summary"]["element_count"],
      "summary lists exactly the elements with empty notes")
check(all("page" in e and "name" in e for e in data["summary"]["elements_without_notes"])
      and {e["id"] for e in data["pages"][0]["elements_without_notes"]} <= miss,
      "each page lists its own elements without notes")
check(data["summary"]["brief_empty"] is False, "summary says whether the brief is empty")
check(data["project"]["brief"].startswith("Recipe app") and data["pages"][0]["notes"].startswith("Home"), "brief and page notes exported")
els = {e["name"]: e for e in data["pages"][0]["elements"]}
check(els["Buy button"]["parent"] == outer.id and inner.id in els["Card"]["children"], "nesting: the button is inside the card")
check(els["Buy button"]["notes"] == "Primary call to action", "element notes exported")
check(set(els["Card"]["relative"]) == {"x_pct", "y_pct", "width_pct", "height_pct"} and els["Card"]["bounds"]["width"] == 800,
      "pixel and percentage boxes exported")
check(data["pages"][0]["canvas"]["device"] in ("Desktop", "Custom", "iPad", "Phone"), "device type exported")
check(any(g["name"] == "Buttons" for g in data["pages"][0]["groups"]), "groups exported")
n_before = [len(pp.shapes) for pp in doc.project.pages]
doc._saved = _json.dumps(doc._last["project"], sort_keys=True); doc.dirty = False
w.import_path(path)
check([len(pp.shapes) for pp in doc.project.pages] == n_before and doc.page.get(inner.id).notes == "Primary call to action"
      and doc.project.brief.startswith("Recipe"), "importing the export rebuilds the project")
# compact export: same facts, far smaller, loads back the same
full_text = path.read_text(encoding="utf-8")
cpath = w.export_json()
check(cpath is not None and cpath.name == "Recipe App.compact.ui.json" and cpath.parent == path.parent,
      f"compact export written next to the full one ({cpath})")
check(any(h.name.startswith("Recipe App_compact_") for h in (path.parent / "history").glob("*.json")),
      "a dated compact copy goes into history/")
ctext = cpath.read_text(encoding="utf-8")
cdata = _json.loads(ctext)
check(QApplication.clipboard().text() == ctext, "the compact export is copied to the clipboard")
check(cdata["compact"] is True and cdata["format"] == "uxandi-export" and cdata["how_to_read"]
      and any("left out has its default" in s for s in cdata["how_to_read"]), "compact export says what left-out fields mean")
check(len(ctext) * 2 < len(full_text), f"compact export is much smaller ({len(ctext)} vs {len(full_text)} characters)")
fdata = _json.loads(full_text)
fe = {e["id"]: e for pp in fdata["pages"] for e in pp["elements"]}
ce = {e["id"]: e for pp in cdata["pages"] for e in pp["elements"]}
check(set(ce) == set(fe), "compact export has every element")
check(all(ce[i].get("notes", "") == fe[i]["notes"] and ce[i].get("parent") == fe[i]["parent"] for i in fe),
      "compact export keeps every note and parent")
check(all(ce[i]["box"] == [fe[i]["bounds"][k] for k in ("x", "y", "width", "height")] for i in fe if fe[i]["type"] != "line"),
      "compact boxes match the full export")
check([e["id"] for pp in cdata["pages"] for e in pp["elements"]] == [e["id"] for pp in fdata["pages"] for e in pp["elements"]],
      "compact elements keep the stacking order")
cel = {e["name"]: e for e in cdata["pages"][0]["elements"]}
check("notes" not in cel["Card"] and "center" not in cel["Card"] and "relative" not in cel["Card"] and "created" not in cel["Card"],
      "compact leaves out empty notes and derivable fields")
snap_before = [[(s.id, s.name, s.notes, round(s.x, 2), round(s.y, 2), round(s.w, 2), round(s.h, 2), s.fill.upper(), s.stroke_width)
                for s in pp.shapes] for pp in doc.project.pages]
doc._saved = _json.dumps(doc._last["project"], sort_keys=True); doc.dirty = False
w.import_path(cpath)
snap_after = [[(s.id, s.name, s.notes, round(s.x, 2), round(s.y, 2), round(s.w, 2), round(s.h, 2), s.fill.upper(), s.stroke_width)
               for s in pp.shapes] for pp in doc.project.pages]
check(snap_after == snap_before and doc.project.brief.startswith("Recipe"),
      "importing the compact export rebuilds the same project")
w.copy_json()
check(_json.loads(QApplication.clipboard().text()).get("compact") is True, "copy the JSON only: compact by default")
w.copy_json(compact=False)
check(_json.loads(QApplication.clipboard().text()).get("compact") is None, "copy the full JSON only")
w.b_export.click()
check(_json.loads(QApplication.clipboard().text()).get("compact") is True, "the Export JSON button writes the compact form")
shot("11_export_header")

# design tab: fill / border wheels, recents, pictures, templates, export of colours and pictures
from PySide6.QtGui import QImage, QColor as _QC  # noqa: E402
from uxandi.colors import RECENTS, ScreenPicker  # noqa: E402
dz = w.panels["design"]
w.right.open = ["design", "details"]; w.right._sync(); app.processEvents()
doc.set_selection([]); app.processEvents(); w.refresh_panels()
dz.fill.set_color("#FF8800", emit=True)
check(doc.style["fill"].upper() == "#FF8800", "nothing selected: the fill wheel sets the colour for new shapes")
w.add_shape("rect", (500, 500))
nr = doc.selected()[0]
check(nr.fill.upper() == "#FF8800", "a new shape gets that colour")
check(RECENTS.get("fill")[0] == "#FF8800", "the colour is in the recent squares")
g1 = [g for g in doc.page.groups if g["name"] == "Buttons"][0]
doc.select_group(g1["id"]); app.processEvents(); w.refresh_panels()
check("Buttons" in dz.scope.text(), f"the panel says it applies to the group ({dz.scope.text()})")
dz.fill.set_color("#3366CCCC".replace("#3366CCCC", "#CC3366CC"), emit=True)
mem = [doc.page.get(m) for m in g1["members"]]
check(all(m_.fill.upper() == "#CC3366CC" for m_ in mem if not m_.is_line), "fill goes to every shape in the selected group (with opacity)")
dz.border.set_color("#00AA00", emit=True); dz.bw.setValue(6)
check(all(m_.stroke.upper() == "#00AA00" and m_.stroke_width == 6 for m_ in mem), "border colour and thickness go to the whole group")
dz._border_all()
check(all(x.stroke.upper() == "#00AA00" for x in doc.page.shapes), "apply border to all shapes")
for _ in range(14):
    RECENTS.add("fill", "#%06X" % (_ * 1111))
check(len(RECENTS.get("fill")) == 12, "recent colours keep the last 12")
# picture
pic = tmp / "red.png"; im = QImage(40, 20, QImage.Format.Format_RGB32); im.fill(_QC("#E01010")); im.save(str(pic))
doc.set_selection([nr.id]); app.processEvents(); w.refresh_panels()
dz.put_image(str(pic))
check(nr.contents and nr.contents["type"] == "image" and nr.contents["fit"] == "fill", "picture goes into the shape")
nr.stroke_width = 0; doc.changed.emit(); app.processEvents()
cxy = b.to_screen(*nr.center()); grab = b.grab().toImage()
px_ = grab.pixelColor(int(cxy.x()), int(cxy.y()))
check(px_.red() > 180 and px_.green() < 80, f"the picture is drawn inside the shape ({px_.name()})")
dz.set_val(dz.fit, "fit"); dz._img_set("fit", "fit", "fit")
check(nr.contents["fit"] == "fit", "fit mode changes")
dz.drag.setChecked(True)
c0 = nr.center(); x0 = nr.x
drag(scr(*c0), scr(c0[0] + 30, c0[1] + 10))
check(abs(nr.contents["dx"] - 30) < 1.5 and abs(nr.x - x0) < 1e-6, "drag image moves the picture, not the shape")
dz.drag.setChecked(False)
rows = dict((k_, v_) for k_, v_ in [(r_[0].text(), r_[1].text()) for r_ in w.panels["details"].rows if r_[0].isVisible()])
w.right.open = ["design", "details"]; w.right._sync(); w.refresh_panels(); app.processEvents()
rows = {r_[0].text(): r_[1].text() for r_ in w.panels["details"].rows if not r_[0].isHidden()}
check(rows.get("picture") == "red.png" and "fit" in rows.get("picture fit", ""), f"Details lists the picture")
check(rows.get("fill", "").startswith("#FF8800"), f"Details lists the fill ({rows.get('fill')})")
# template
tp = dz.save_template("Orange card")
check(tp.exists() and _json.loads(tp.read_text())["fill"].upper() == "#FF8800", "design saved as a template")
doc.set_selection([d1.id]); app.processEvents(); w.refresh_panels()
dz.apply_template(tp)
check(doc.page.get(d1.id).fill.upper() == "#FF8800" and image_ok(doc.page.get(d1.id)), "template applies colours and picture to the selection")
# canvas colour square opens the wheel popup
cpn = w.panels["canvas"]; cpn.bg._pick(); app.processEvents()
check(cpn.bg._pop.isVisible(), "the canvas colour square opens the colour wheel"); cpn.bg._pop.close()
# eyedropper sampling
sp = ScreenPicker(lambda c: None)
fake = QImage(10, 10, QImage.Format.Format_RGB32); fake.fill(_QC("#123456"))
from PySide6.QtCore import QRect as _QR  # noqa: E402
sp.shots = [(_QR(0, 0, 10, 10), None, fake)]
check(sp.color_at(QPoint(5, 5)).name().upper() == "#123456", "eyedropper reads the colour under the cursor"); sp.close()
shot("12_design")
# export: colours as hex + opacity, picture copied next to the JSON
path = w.export_json(compact=False)
data = _json.loads(path.read_text(encoding="utf-8"))
els = {e["id"]: e for pp in data["pages"] for e in pp["elements"]}
em = els[mem[0].id] if not mem[0].is_line else els[mem[1].id]
check(em["style"]["fill"] == "#3366CC" and abs(em["style"]["fill_opacity"] - 0.8) < 0.01, f"export splits colour and opacity {em['style']}")
ei = els[nr.id]["contents"]
check(ei["type"] == "image" and (path.parent / ei["file"]).exists() and ei["fit"] == "fit", f"picture copied next to the export {ei}")
w.import_path(path)
rm_ = [doc.page.get(m_.id) for m_ in mem if not m_.is_line][0]
check(image_ok(doc.page.get(nr.id)) and rm_.fill.upper() == "#CC3366CC", "import brings colours (with opacity) and pictures back")
cpath = w.export_json()
cdata = _json.loads(cpath.read_text(encoding="utf-8"))
ce = {e["id"]: e for pp in cdata["pages"] for e in pp["elements"]}
cm = ce[rm_.id]
check(cm["style"]["fill"] == "#3366CC" and abs(cm["style"]["fill_opacity"] - 0.8) < 0.01, f"compact export keeps colour and opacity {cm['style']}")
check(ce[nr.id]["contents"]["type"] == "image" and (cpath.parent / ce[nr.id]["contents"]["file"]).exists(),
      "compact export keeps the picture")
w.import_path(cpath)
rm2 = [doc.page.get(m_.id) for m_ in mem if not m_.is_line][0]
check(image_ok(doc.page.get(nr.id)) and rm2.fill.upper() == "#CC3366CC", "compact import brings colours and pictures back")

# design controls live only in the Design tab
sp_ = w.panels["shape"]
check(not any(hasattr(sp_, k) for k in ("rad", "bw", "bc", "fc", "ls", "cap", "nofill")), "Shape tab has no colour / border / corner / line-style controls")
dz = w.panels["design"]
check(all(hasattr(dz, k) for k in ("rad", "rad_s", "ls", "cap", "bw", "fill", "border")), "Design tab has fill, border, corners and line style")
ln_ = next(x for x in doc.page.shapes if x.is_line)
doc.set_selection([ln_.id]); app.processEvents(); w.refresh_panels()
check(dz.linebox.isVisibleTo(dz) and not dz.corners.isVisibleTo(dz), "a selected line shows the Line section, not Corners")
dz.set_val(dz.ls, "dash"); dz._line("line_style", "dash", "Line style")
check(doc.page.get(ln_.id).line_style == "dash", "line style set from the Design tab")
doc.set_selection([]); app.processEvents(); w.refresh_panels()
dz.rad.setValue(12)
w.add_shape("rect")
check(doc.selected()[0].radius == 12, "new shapes get the corner radius set in Design")
dz.rad.setValue(0)

# panels never crop: every tab open, several window sizes
from PySide6.QtWidgets import QWidget as _QW  # noqa: E402
w.left.open = [k_ for k_, _ in winmod.LEFT_TABS]; w.right.open = [k_ for k_, _ in winmod.RIGHT_TABS]
w.left._sync(); w.right._sync()
doc.set_selection([doc.page.shapes[0].id])
for size in ((1920, 1080), (1366, 768), (1100, 700), (900, 600)):
    w.resize(*size)
    for _ in range(8):
        app.processEvents()
    probs = []
    for col in (w.left, w.right):
        if col.scroll.widget().width() > col.scroll.viewport().width():
            wide_ = max(((max(c_.minimumWidth(), c_.minimumSizeHint().width()), type(c_).__name__, c_.objectName())
                         for c_ in col.scroll.widget().findChildren(_QW) if c_.isVisibleTo(col.scroll.widget())
                         and not c_.inherits("QFrame") or c_.objectName() != "Panel"), default=None)
            probs.append(f"column content wider than the column (widest: {wide_})")
        for k_, p_ in col.panels.items():
            if p_.isHidden():
                continue
            if p_.height() + 1 < p_.heightForWidth(p_.width()):
                probs.append(f"{k_} shorter than its contents")
            for c_ in p_.findChildren(_QW):
                if c_.isVisibleTo(p_) and c_.mapTo(p_, c_.rect().topRight()).x() > p_.width() + 1:
                    probs.append(f"{k_}: {type(c_).__name__} sticks out")
            if not p_.shut:                     # every row in the body gets the height it needs at its width
                bl_ = p_.body.layout()
                for i_ in range(bl_.count()):
                    it_ = bl_.itemAt(i_); c_ = it_.widget()
                    if c_ is None or not c_.isVisibleTo(p_):
                        continue
                    need_ = it_.heightForWidth(c_.width()) if it_.hasHeightForWidth() else it_.minimumSize().height()
                    if c_.height() + 1 < need_:
                        probs.append(f"{k_}: {type(c_).__name__} squashed ({c_.height()} < {need_})")
    check(not probs, f"all tabs open at {size[0]}x{size[1]}: nothing cropped {probs[:3]}")
w.resize(1920, 1080); app.processEvents()

# small window: layout still fits
w.resize(1100, 700)
app.processEvents()
shot("05_small_window")
w.resize(1920, 1080)
app.processEvents()
doc.set_selection([s1.id])
for p in w.panels.values():
    p.refresh()
w.right.open = ["shape", "transform", "details"]; w.right._sync()
shot("06_panels")

# step arrows: every number box has up / down arrows, sliders without a box have ‹ › on the same line
from PySide6.QtWidgets import QAbstractSpinBox as _QASB, QSlider as _QSl, QStyle as _QSt, QStyleOptionSpinBox as _QOpt  # noqa: E402
from PySide6.QtTest import QTest as _QT  # noqa: E402
from uxandi.widgets import Spin as _Spin, ISpin as _ISpin, StepButton as _SB  # noqa: E402
boxes = w.findChildren(_QASB)
check(boxes and all(isinstance(b_, (_Spin, _ISpin)) and b_.buttonSymbols() != _QASB.ButtonSymbols.NoButtons for b_ in boxes),
      f"all {len(boxes)} number boxes have step arrows")
cv = w.panels["canvas"]
w.left.open = ["canvas"]; w.left._sync(); app.processEvents()
sp0 = cv.sp.value()
o_ = _QOpt(); cv.sp.initStyleOption(o_)
r_ = cv.sp.style().subControlRect(_QSt.ComplexControl.CC_SpinBox, o_, _QSt.SubControl.SC_SpinBoxUp, cv.sp)
check(r_.width() >= 10 and r_.right() >= cv.sp.width() - 3, f"up arrow sits at the right end of the box {r_}")
_QT.mouseClick(cv.sp, Qt.MouseButton.LeftButton, pos=r_.center()); app.processEvents()
check(cv.sp.value() == sp0 + 1 and doc.page.dot_spacing == sp0 + 1, "clicking the up arrow steps the dot spacing by 1 px")
cv.sp.setValue(sp0); app.processEvents()
dz = w.panels["design"]
sliders = [s_ for s_ in w.findChildren(_QSl)]
lone = [s_ for s_ in sliders if s_ is not dz.rad_s]
check(all(len(s_.parentWidget().findChildren(_SB)) == 2 for s_ in lone),
      f"every slider without a number box has ‹ › arrows beside it ({len(lone)})")
check(not dz.rad_s.parentWidget().findChildren(_SB), "corner slider: its number box on the same line has the arrows")
row = dz.op.parentWidget()
check(row.up.isEnabled() == dz.op.isEnabled(), "slider arrows follow the slider's enabled state")
dz.op.setEnabled(True); v0 = dz.op.value(); row.dn.click(); app.processEvents()
check(dz.op.value() == max(0, v0 - 1), "slider ‹ steps the value down")
dz.op.setValue(dz.op.maximum()); app.processEvents()
check(row.up.at_limit and not row.dn.at_limit, "› greys out at the maximum")
for p in w.panels.values():
    p.refresh()

# clicking a shape opens the Shape and Details tabs (others stay as they are)
w.right.open = ["design"]; w.right._sync(); w.right.panels["details"].set_shut(True); app.processEvents()
tgt_ = next(s_ for s_ in doc.page.shapes if not s_.is_line)
doc.set_selection([]); w.board.fit(); app.processEvents()
tcx_, tcy_ = tgt_.center()
_QT.mouseClick(w.board, Qt.MouseButton.LeftButton, pos=w.board.to_screen(tcx_, tcy_).toPoint()); app.processEvents()
check(doc.selection and {"shape", "details", "design"} <= set(w.right.open) and not w.right.panels["details"].shut
      and w.right.panels["shape"].isVisible() and w.right.panels["details"].isVisible(),
      f"clicking a shape opens Shape and Details, keeps Design open {w.right.open}")
w.right.open = ["design"]; w.right._sync(); app.processEvents()
doc.set_selection([tgt_.id]); app.processEvents()
check(w.right.open == ["design"], "selecting by other means (undo, agent, list) leaves the tabs alone")

# every drop-down shows its arrow
from PySide6.QtWidgets import QComboBox as _QCB  # noqa: E402
w.left.open = [k_ for k_, _ in winmod.LEFT_TABS]; w.left._sync(); w.right.open = [k_ for k_, _ in winmod.RIGHT_TABS]; w.right._sync()
app.processEvents()
combos_ = [c_ for c_ in w.findChildren(_QCB) if c_.isVisible()]
def _arrow_drawn(c_):
    im_ = c_.grab().toImage()
    y0_, y1_ = im_.height() // 4, im_.height() * 3 // 4
    return any(im_.pixelColor(x_, y_).lightness() < 235 for x_ in range(im_.width() - 22, im_.width() - 4)
               for y_ in range(y0_, y1_))
check(combos_ and all(_arrow_drawn(c_) for c_ in combos_), f"all {len(combos_)} visible drop-downs show an arrow")

# "My screen": the size of the monitor the window is on, in native pixels
scr_ = w.screen()
nat_ = (round(scr_.geometry().width() * scr_.devicePixelRatio()), round(scr_.geometry().height() * scr_.devicePixelRatio()))
d0_ = cv.preset.itemData(0)
check(d0_[0] == "My screen" and (d0_[1], d0_[2]) == nat_ and cv.preset.itemText(0).startswith("My screen"),
      f"first canvas size is My screen {nat_}")
pw_, ph_, pp_ = doc.page.width, doc.page.height, doc.page.preset
cv._preset(0); app.processEvents()
check((doc.page.width, doc.page.height) == nat_ and doc.page.preset == "My screen", "picking My screen sizes the canvas to the monitor")
cv.refresh()
check(cv.preset.currentIndex() == 0, "the list shows My screen for such a page")
doc.page.preset = "This screen"; cv.refresh()
check(cv.preset.currentIndex() == 0, "pages saved as 'This screen' (old name) still show My screen")
doc.page.width, doc.page.height, doc.page.preset = pw_, ph_, pp_; doc.commit("restore size"); cv.refresh()

# free draw: a brush stroke becomes a shape (a mark around an element, an arrow, anything)
import math as _m  # noqa: E402
from uxandi.model import Shape as _Sh  # noqa: E402
doc.set_selection([]); w.board.fit(); app.processEvents()
w.board.setFocus(); _QT.keyClick(w.board, Qt.Key.Key_D); app.processEvents()
check(w.board.tool == "draw" and w.tool_btns["draw"].isChecked(), "D picks the draw tool (header button on)")
n0 = len(doc.page.shapes)
ring = [(700 + 260 * _m.cos(a / 40 * 2 * _m.pi), 420 + 160 * _m.sin(a / 40 * 2 * _m.pi)) for a in range(41)]
mouse("press", scr(*ring[0]))
for x_, y_ in ring[1:]:
    mouse("move", scr(x_, y_))
mouse("release", scr(*ring[-1]))
dr = doc.page.shapes[-1]
check(len(doc.page.shapes) == n0 + 1 and dr.kind == "path" and dr.name.startswith("Drawing") and len(dr.points) >= 8
      and doc.selection == [dr.id], f"a stroke becomes a selected Drawing ({dr.kind}, {len(dr.points or [])} points)")
check(w.board.tool == "draw", "the draw tool stays on, like a brush")
bx_ = dr.aabb()
check(abs(bx_[0] - 440) < 6 and abs(bx_[2] - 960) < 6 and abs(bx_[1] - 260) < 6 and abs(bx_[3] - 580) < 6,
      f"the drawing covers where it was drawn {tuple(round(v) for v in bx_)}")
check(dr.contains(960, 420, 1) and not dr.contains(700, 420, 1), "a drawing is hit on its stroke, not inside its outline")
check({"shape", "details"} <= set(w.right.open), "drawing opens Shape and Details so its notes can be written")
mouse("press", scr(300, 300)); mouse("release", scr(300, 300))
check(len(doc.page.shapes) == n0 + 1, "a click with the draw tool adds nothing")
_QT.keyClick(w.board, Qt.Key.Key_Escape); app.processEvents()
check(w.board.tool == "select", "Esc leaves the draw tool")
doc.set_selection([dr.id]); dz.refresh(); app.processEvents()
check(not dz.corners.isVisible() and dz.linebox.isVisible() and not dz.fill.isEnabled(),
      "Design tab for a drawing: border and line style, no fill or corners")
x0_ = dr.x; w.board.fit(); app.processEvents()
gp_ = min(dr.path_points(), key=lambda q: abs(q[0] - 884) + abs(q[1] - 307))      # 45° on the ring, away from handles
drag(scr(*gp_), scr(gp_[0] + 100, gp_[1]))
check(abs(doc.page.get(dr.id).x - (x0_ + 100)) < 12, f"dragging the stroke moves the drawing ({x0_} -> {doc.page.get(dr.id).x})")
dr.notes = "Circled: make this card stand out more."
in_ = _Sh(kind="rect", x=620, y=380, w=120, h=60, name="Circled card"); doc.page.shapes.insert(0, in_); doc.commit("card")
cpath = w.export_json()
cdata = _json.loads(cpath.read_text(encoding="utf-8"))
ce_ = {e_["id"]: e_ for pp in cdata["pages"] for e_ in pp["elements"]}
check(ce_[dr.id]["type"] == "path" and len(ce_[dr.id]["points"]) == len(dr.points) and ce_[dr.id]["notes"].startswith("Circled"),
      "export: type path with its points and notes")
check(ce_[in_.id].get("parent") != dr.id, "a drawing never becomes the parent of what it circles")
from uxandi import schemas as _schemas  # noqa: E402
check(not _schemas.validate(cdata, _schemas.compact_schema()), "export with a drawing is valid against the schema")
doc._saved = _json.dumps(doc._last["project"], sort_keys=True); doc.dirty = False
pts_before = [tuple(round(v, 1) for v in p_) for p_ in dr.path_points()]
w.import_path(cpath)
dr2 = doc.page.get(dr.id)
check(dr2 is not None and dr2.kind == "path" and [tuple(round(v, 1) for v in p_) for p_ in dr2.path_points()] == pts_before,
      "import brings the drawing back point for point")
doc.set_selection([dr.id]); app.processEvents()
shot("14_drawing")

# circle: a base shape like the rectangle
from uxandi.model import Shape as _Sh  # noqa: E402
w.board.setFocus(); _QT.keyClick(w.board, Qt.Key.Key_C); app.processEvents()
check(w.board.tool == "ellipse" and w.tool_btns["ellipse"].isChecked(), "C picks the circle tool (header button on)")
n0 = len(doc.page.shapes)
_QT.mouseClick(w.board, Qt.MouseButton.LeftButton, pos=w.board.rect().center()); app.processEvents()
cs = doc.page.shapes[-1]
check(len(doc.page.shapes) == n0 + 1 and cs.kind == "ellipse" and cs.w == cs.h and cs.name.startswith("Circle")
      and w.board.tool == "select", f"a click with the circle tool adds a circle ({cs.kind} {cs.w}x{cs.h} {cs.name})")
w.add_shape("circle"); c2 = doc.page.shapes[-1]
check(c2.kind == "ellipse" and c2.lock_ratio and c2.w == c2.h, "+ Circle adds a circle that keeps its proportions")
cx_, cy_ = c2.center()
check(c2.contains(cx_, cy_, 0) and not c2.contains(c2.x + 1, c2.y + 1, 0), "a circle is hit inside its round edge, not in its box corners")
doc.set_selection([c2.id]); dz.refresh()
check(not dz.corners.isVisible(), "Design tab hides round corners for a circle")
check(not any(k_ == "radius" for k_, *_ in w.board.handles()), "no corner-radius handle on a circle")
ov = _Sh(kind="ellipse", x=100, y=100, w=300, h=120, fill="#FF8800", stroke="#111418", stroke_width=4, name="Pill")
doc.page.shapes.append(ov); doc.commit("oval")
cpath = w.export_json()
cdata = _json.loads(cpath.read_text(encoding="utf-8"))
ty = {e_["id"]: e_.get("type", "rectangle") for pp in cdata["pages"] for e_ in pp["elements"]}
check(ty[c2.id] == "circle" and ty[ov.id] == "ellipse", "export: type circle / ellipse")
doc._saved = _json.dumps(doc._last["project"], sort_keys=True); doc.dirty = False
w.import_path(cpath)
check(doc.page.get(ov.id).kind == "ellipse" and doc.page.get(c2.id).kind == "ellipse", "import brings circles and ovals back")
doc.set_selection([ov.id]); w.board.fit(); app.processEvents()
shot("13_circle")

print("\n" + ("ALL GOOD" if not errors else f"{len(errors)} PROBLEM(S):\n" + "\n".join(errors)))
sys.exit(1 if errors else 0)
