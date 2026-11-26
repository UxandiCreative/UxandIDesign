"""The open document: project, current page, selection, undo / redo, files."""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .model import Project, Page, Shape, now_iso, new_id
from .snapping import SnapSettings

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("UXANDI_HOME") or ROOT)   # where projects, exports and data live
PROJECTS_DIR = HOME / "projects"
EXPORTS_DIR = HOME / "exports"
DATA_DIR = HOME / "data"
TEMPLATES_DIR = HOME / "templates" / "design"   # Design tab style templates
SESSION_FILE = DATA_DIR / "session.json"
EXT = ".uxandi"
UNDO_LIMIT = 300


class Doc(QObject):
    changed = Signal()            # shapes moved / restyled (cheap: repaint, refresh fields)
    structure = Signal()          # shapes added / removed / reordered, pages changed
    selection_changed = Signal()
    page_changed = Signal()       # another page is now on screen
    status = Signal(str)
    dirty_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.project = Project()
        self.page_index = 0
        self.selection: list[str] = []
        self.path: Path | None = None
        self.snap = SnapSettings()
        # Design tab with nothing selected: what new shapes look like
        self.style = {"fill": "#E9ECF0", "stroke": "#111418", "stroke_width": 2.0}
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._last = self._snapshot()
        self._last_key = None
        self._last_t = 0.0
        self._saved = json.dumps(self._last["project"], sort_keys=True)
        self.dirty = False

    # ------------------------------------------------------------------ access
    @property
    def page(self) -> Page:
        return self.project.pages[self.page_index]

    def get(self, sid: str) -> Shape | None:
        return self.page.get(sid)

    def selected(self) -> list[Shape]:
        out = []
        for sid in self.selection:
            s = self.page.get(sid)
            if s:
                out.append(s)
        return out

    def set_selection(self, ids) -> None:
        ids = [i for i in dict.fromkeys(ids) if self.page.get(i)]
        if ids != self.selection:
            self.selection = ids
            self.selection_changed.emit()

    # ------------------------------------------------------------------ undo
    def _snapshot(self) -> dict:
        return {"project": self.project.to_dict(), "page": self.page_index, "sel": list(self.selection)}

    def _restore(self, snap: dict) -> None:
        self.project = Project.from_dict(copy.deepcopy(snap["project"]))
        self.page_index = min(snap["page"], len(self.project.pages) - 1)
        self.selection = [i for i in snap["sel"] if self.page.get(i)]
        self._last = snap
        self._after_change()
        self.page_changed.emit()
        self.structure.emit()
        self.selection_changed.emit()

    def commit(self, label: str = "", merge: str | None = None) -> None:
        """Call after every finished edit. Edits with the same `merge` key within a
        second become one undo step (arrow-key nudges, for instance)."""
        self._touch_modified()
        snap = self._snapshot()
        t = time.monotonic()
        if not (merge and merge == self._last_key and t - self._last_t < 1.0):
            self._undo.append(self._last)
            if len(self._undo) > UNDO_LIMIT:
                self._undo.pop(0)
        self._last_key, self._last_t = merge, t
        self._last = snap
        self._redo.clear()
        self._after_change()
        if label:
            self.status.emit(label)

    def _touch_modified(self) -> None:
        before = {}
        prev = self._last["project"]["pages"]
        for p in prev:
            for s in p["shapes"]:
                before[s["id"]] = s
        stamp = now_iso()
        for p in self.project.pages:
            for s in p.shapes:
                old = before.get(s.id)
                d = s.to_dict()
                if old is None:
                    continue
                a = dict(old); b = dict(d)
                a.pop("modified", None); b.pop("modified", None)
                if a != b:
                    s.modified = stamp

    def undo(self) -> None:
        if not self._undo:
            self.status.emit("Nothing to undo")
            return
        self._redo.append(self._snapshot())
        self._restore(self._undo.pop())
        self._last_key = None
        self.status.emit("Undo")

    def redo(self) -> None:
        if not self._redo:
            self.status.emit("Nothing to redo")
            return
        self._undo.append(self._snapshot())
        self._restore(self._redo.pop())
        self._last_key = None
        self.status.emit("Redo")

    def _after_change(self) -> None:
        cur = json.dumps(self._last["project"], sort_keys=True)
        d = cur != self._saved
        if d != self.dirty:
            self.dirty = d
            self.dirty_changed.emit(d)
        else:
            self.dirty_changed.emit(d)

    # ------------------------------------------------------------------ shapes
    def add_shapes(self, shapes: list[Shape], label: str = "Added") -> None:
        self.page.shapes.extend(shapes)
        self.selection = [s.id for s in shapes]
        self.structure.emit()
        self.selection_changed.emit()
        self.commit(label)

    def delete_selected(self) -> None:
        if not self.selection:
            return
        n = len(self.selection)
        ids = set(self.selection)
        self.page.shapes = [s for s in self.page.shapes if s.id not in ids]
        self.page.clean_groups()
        self.selection = []
        self.structure.emit()
        self.selection_changed.emit()
        self.commit(f"Deleted {n} shape{'s' if n != 1 else ''}")

    def styled(self, s: Shape) -> Shape:
        """Give a new shape the current style for new shapes."""
        st = self.style
        s.stroke = st.get("stroke", s.stroke)
        if s.is_stroke:
            s.stroke_width = max(1.0, float(st.get("stroke_width", s.stroke_width)) or s.stroke_width)
            s.line_style = st.get("line_style", s.line_style)
            s.cap = st.get("cap", s.cap)
            if s.is_path:
                s.fill = ""
        else:
            s.fill = st.get("fill", s.fill)
            s.stroke_width = float(st.get("stroke_width", s.stroke_width))
            s.radius = float(st.get("radius", s.radius))
        return s

    # ------------------------------------------------------------------ groups
    def group_selection(self) -> dict | None:
        ids = [i for i in self.selection if self.page.get(i)]
        if not ids:
            self.status.emit("Select shapes first, then + Group")
            return None
        pg = self.page
        for g in pg.groups:          # a shape is in one group at most: take it out of its old one
            g["members"] = [m for m in g["members"] if m not in ids]
        pg.groups = [g for g in pg.groups if g["members"]]
        order = {s.id: i for i, s in enumerate(pg.shapes)}
        g = {"id": new_id(), "name": pg.next_group_name(), "members": sorted(ids, key=lambda i: order[i])}
        pg.groups.append(g)
        self.structure.emit()
        self.commit(f"{g['name']}: {len(ids)} shape{'s' if len(ids) != 1 else ''}")
        return g

    def ungroup_selected(self) -> None:
        ids = set(self.selection)
        pg = self.page
        hit = [g["name"] for g in pg.groups if ids & set(g["members"])]
        if not hit:
            self.status.emit("Nothing selected is in a group")
            return
        for g in pg.groups:
            g["members"] = [m for m in g["members"] if m not in ids]
        pg.groups = [g for g in pg.groups if g["members"]]
        self.structure.emit()
        self.commit("Taken out of " + ", ".join(hit))

    def dissolve_group(self, gid: str) -> None:
        g = self.page.get_group(gid)
        if not g:
            return
        self.page.groups = [x for x in self.page.groups if x["id"] != gid]
        self.structure.emit()
        self.commit(f"{g['name']} ungrouped (the shapes stay)")

    def rename_group(self, gid: str, name: str) -> None:
        g = self.page.get_group(gid)
        name = name.strip()
        if g and name and name != g["name"]:
            g["name"] = name
            self.structure.emit()
            self.commit(f"Group renamed to {name}")

    def select_group(self, gid: str, add: bool = False) -> None:
        g = self.page.get_group(gid)
        if not g:
            return
        ids = (list(self.selection) if add else []) + [m for m in g["members"] if m not in (self.selection if add else [])]
        self.set_selection(ids)
        self.status.emit(f"{g['name']} selected ({len(g['members'])})")

    def reorder(self, how: str) -> None:
        """how: front, forward, backward, back"""
        sh = self.page.shapes
        sel = set(self.selection)
        if not sel:
            return
        if how == "front":
            sh[:] = [s for s in sh if s.id not in sel] + [s for s in sh if s.id in sel]
        elif how == "back":
            sh[:] = [s for s in sh if s.id in sel] + [s for s in sh if s.id not in sel]
        elif how == "forward":
            for i in range(len(sh) - 2, -1, -1):
                if sh[i].id in sel and sh[i + 1].id not in sel:
                    sh[i], sh[i + 1] = sh[i + 1], sh[i]
        elif how == "backward":
            for i in range(1, len(sh)):
                if sh[i].id in sel and sh[i - 1].id not in sel:
                    sh[i], sh[i - 1] = sh[i - 1], sh[i]
        self.structure.emit()
        self.commit({"front": "Brought to front", "back": "Sent to back",
                     "forward": "Brought forward", "backward": "Sent backward"}[how])

    # ------------------------------------------------------------------ pages
    def go_page(self, i: int) -> None:
        i = max(0, min(i, len(self.project.pages) - 1))
        if i == self.page_index:
            return
        self.page_index = i
        self.selection = []
        self.page_changed.emit()
        self.structure.emit()
        self.selection_changed.emit()

    def add_page(self, after: int | None = None, copy_of: Page | None = None) -> None:
        after = self.page_index if after is None else after
        if copy_of:
            p = Page.from_dict(copy.deepcopy(copy_of.to_dict()))
            from .model import new_id
            p.id = new_id()
            remap = {}
            for s in p.shapes:
                remap[s.id] = s.id = new_id()
            for g in p.groups:
                g["id"] = new_id()
                g["members"] = [remap[m] for m in g["members"] if m in remap]
            p.name = copy_of.name + " copy"
        else:
            base = self.page
            p = Page(name=f"Page {len(self.project.pages) + 1}", width=base.width, height=base.height,
                     preset=base.preset, dots=base.dots, dot_spacing=base.dot_spacing)
        self.project.pages.insert(after + 1, p)
        self.page_index = after + 1
        self.selection = []
        self.page_changed.emit()
        self.structure.emit()
        self.selection_changed.emit()
        self.commit("Page copied" if copy_of else "Page added")

    def delete_page(self, i: int) -> None:
        if len(self.project.pages) <= 1:
            self.status.emit("A project keeps at least one page")
            return
        del self.project.pages[i]
        self.page_index = min(self.page_index if self.page_index < i else self.page_index - 1,
                              len(self.project.pages) - 1)
        self.page_index = max(0, self.page_index)
        self.selection = []
        self.page_changed.emit()
        self.structure.emit()
        self.selection_changed.emit()
        self.commit("Page removed")

    def move_page(self, i: int, j: int) -> None:
        pages = self.project.pages
        if i == j or not (0 <= i < len(pages)):
            return
        cur = pages[self.page_index]
        p = pages.pop(i)
        j = max(0, min(j, len(pages)))
        pages.insert(j, p)
        self.page_index = pages.index(cur)
        self.structure.emit()
        self.page_changed.emit()
        self.commit("Pages reordered")

    # ------------------------------------------------------------------ files
    def new_project(self) -> None:
        self.project = Project()
        self.path = None
        self.page_index = 0
        self.selection = []
        self._undo.clear(); self._redo.clear()
        self._last = self._snapshot()
        self._saved = json.dumps(self._last["project"], sort_keys=True)
        self._after_change()
        self.page_changed.emit(); self.structure.emit(); self.selection_changed.emit()
        self.status.emit("New project")

    def save(self, path: Path | None = None) -> Path:
        path = Path(path or self.path or (PROJECTS_DIR / (safe_name(self.project.name) + EXT)))
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.project.to_dict()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        self.path = path
        self._saved = json.dumps(self._last["project"], sort_keys=True) if self._last else ""
        self._saved = json.dumps(data, sort_keys=True)
        self._after_change()
        self.save_session()
        self.status.emit(f"Saved {path.name}")
        return path

    def load(self, path: Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self.project = Project.from_dict(data)
        self.path = Path(path)
        self.page_index = 0
        self.selection = []
        self._undo.clear(); self._redo.clear()
        self._last = self._snapshot()
        self._saved = json.dumps(self._last["project"], sort_keys=True)
        self._after_change()
        self.page_changed.emit(); self.structure.emit(); self.selection_changed.emit()
        self.status.emit(f"Opened {self.path.name}")

    def import_project(self, project) -> None:
        """Put a project rebuilt from an export on screen (as a new, unsaved project)."""
        self.project = project
        self.path = None
        self.page_index = 0
        self.selection = []
        self._undo.clear(); self._redo.clear()
        self._last = self._snapshot()
        self._saved = ""
        self._after_change()
        self.page_changed.emit(); self.structure.emit(); self.selection_changed.emit()

    def save_session(self, ui: dict | None = None) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        old = {}
        if SESSION_FILE.exists():
            try:
                old = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            except Exception:
                old = {}
        d = {"path": str(self.path) if self.path else None, "project": self.project.to_dict(),
             "page": self.page_index, "saved": self._saved, "snap": self.snap.to_dict(),
             "ui": ui if ui is not None else old.get("ui", {})}
        tmp = SESSION_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(d), encoding="utf-8")
        os.replace(tmp, SESSION_FILE)

    def load_session(self) -> dict:
        """Reopen what was on screen last time. Returns the saved UI state."""
        if not SESSION_FILE.exists():
            return {}
        try:
            d = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            self.project = Project.from_dict(d["project"])
            self.path = Path(d["path"]) if d.get("path") else None
            self.page_index = max(0, min(int(d.get("page", 0)), len(self.project.pages) - 1))
            self.snap = SnapSettings.from_dict(d.get("snap"))
            self._last = self._snapshot()
            self._saved = d.get("saved") or json.dumps(self._last["project"], sort_keys=True)
            self._after_change()
            return d.get("ui", {}) or {}
        except Exception as e:  # a broken session never stops the app opening
            self.status.emit(f"Could not reopen the last session: {e}")
            return {}


def safe_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()
    return keep or "Untitled"
