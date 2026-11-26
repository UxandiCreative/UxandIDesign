"""Main window: header bar, left column, board + page strip, right column."""
from __future__ import annotations

import copy
import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QAction, QKeySequence, QFont
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFrame,
                               QMenu, QFileDialog, QMessageBox, QApplication, QSizePolicy)

from . import theme
from .canvas import Board
from .doc import Doc, PROJECTS_DIR, EXPORTS_DIR, EXT, safe_name
from . import export as exporter
from .model import Shape, union_box, rot_pt, norm_deg
from .pages import PageStrip
from .panels import (FlowLayout, Column, button, BriefPanel, CanvasPanel, CreatePanel, SnapPanel, ViewPanel,
                     ShapePanel, TransformPanel, DetailsPanel, ShapesPanel)

LEFT_TABS = [("brief", "Brief"), ("canvas", "Canvas"), ("create", "Create"), ("snap", "Snapping"), ("view", "View")]
RIGHT_TABS = [("shape", "Shape"), ("design", "Design"), ("transform", "Transform"), ("details", "Details"), ("shapes", "Shapes")]


class Sep(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("Sep")
        self.apply_scale()

    def apply_scale(self):
        self.setFixedSize(1, theme.px(20))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc = Doc()
        self.clip: list[dict] = []
        self._paste_n = 0
        ui = self.doc.load_session()
        self.setWindowTitle("Uxandi")
        self.resize(1600, 950)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        self.rv = QVBoxLayout(root)

        # ---------------------------------------------------------------- header
        self.header = QWidget()
        self.header.setObjectName("Header")
        hb = QHBoxLayout(self.header)
        hb.setContentsMargins(0, 0, 0, 0)
        self.hleft = QWidget()
        self.hflow = FlowLayout(self.hleft, theme.px(12))
        self.hright = QWidget()
        hr = QHBoxLayout(self.hright)
        hr.setContentsMargins(0, 0, 0, 0)
        self.hr = hr
        hb.addWidget(self.hleft, 1)
        hb.addWidget(self.hright, 0, Qt.AlignmentFlag.AlignTop)
        title = QLabel("Uxandi"); title.setObjectName("Title")
        self.pname = QLineEdit(self.doc.project.name)
        self.pname.setToolTip("Project name. Save puts it in projects/<name>.uxandi")
        self.pname.editingFinished.connect(self._pname)
        self.b_open = button("Open ▾", "Open a saved project (Ctrl+O)")
        self.open_menu = QMenu(self)
        self.open_menu.aboutToShow.connect(self._fill_open)
        self.b_open.setMenu(self.open_menu)
        b_new = button("New", "Start an empty project (Ctrl+N)")
        b_save = button("Save", "Save the project (Ctrl+S)", "Primary")
        b_saveas = button("Save as…", "Save under a new name (Ctrl+Shift+S)")
        b_new.clicked.connect(self.new_project)
        b_save.clicked.connect(self.save)
        b_saveas.clicked.connect(self.save_as)
        self.tool_btns = {}
        for k, t, tip in (("select", "↖ Select", "Select and move (V)"), ("rect", "▭ Rectangle", "Draw rectangles (R)"),
                          ("ellipse", "◯ Circle", "Draw circles and ovals (C). Shift = circle"),
                          ("line", "╱ Line", "Draw lines (L)"),
                          ("draw", "✎ Draw", "Freehand drawing, like a brush (D). Each stroke is a shape: select it and write in its notes what it means")):
            b = button(t, tip, checkable=True)
            b.clicked.connect(lambda _=False, k=k: self.board.set_tool(k))
            self.tool_btns[k] = b
        b_undo = button("↶", "Undo (Ctrl+Z)", "Ic"); b_redo = button("↷", "Redo (Ctrl+Y)", "Ic")
        b_undo.clicked.connect(self.doc.undo); b_redo.clicked.connect(self.doc.redo)
        b_zo = button("−", "Zoom out", "Ic"); b_fit = button("Fit", "Whole canvas in view (Ctrl+0)"); b_zi = button("+", "Zoom in (mouse wheel)", "Ic")
        self.zlab = QLabel("100%"); self.zlab.setObjectName("Mono")
        self.status = QLabel(""); self.status.setObjectName("Status")
        b_fs = button("⛶", "Full screen on / off (F11)", "Ic")
        b_fs.clicked.connect(self.toggle_fullscreen)
        self.seps = [Sep() for _ in range(4)]
        for w in (title, self.seps[0], self.pname, self.b_open, b_new, b_save, b_saveas, self.seps[1],
                  *self.tool_btns.values(), self.seps[2], b_undo, b_redo, self.seps[3], b_zo, b_fit, b_zi,
                  self.zlab, self.status):
            self.hflow.addWidget(w)
        # right end of the bar: Export (the point of the app) and full screen
        self.b_export = button("⇪ Export JSON", "Write the agent JSON (compact) for this project to exports/<project>/, "
                               "copy it to the clipboard and show it in its folder", "Primary")
        self.b_export.clicked.connect(lambda: self.export_json())
        self.b_exmenu = button("▾", "More export options", "Ic")
        self.ex_menu = QMenu(self)
        self.ex_menu.addAction("Export JSON and show it", lambda: self.export_json())
        self.ex_menu.addAction("Copy the JSON only (no file)", lambda: self.copy_json())
        self.ex_menu.addSeparator()
        self.ex_menu.addAction("Export full JSON (every field written out) and show it", lambda: self.export_json(compact=False))
        self.ex_menu.addAction("Copy the full JSON only (no file)", lambda: self.copy_json(compact=False))
        self.ex_menu.addSeparator()
        self.ex_menu.addAction("Open the exports folder", self.open_exports)
        self.ex_menu.addSeparator()
        self.ex_menu.addAction("Import an export…", self.import_dialog)
        self.b_exmenu.clicked.connect(lambda: self.ex_menu.exec(self.b_exmenu.mapToGlobal(self.b_exmenu.rect().bottomLeft())))
        hr.addWidget(self.b_export)
        hr.addWidget(self.b_exmenu)
        hr.addWidget(b_fs)
        self.rv.addWidget(self.header)

        # ---------------------------------------------------------------- main row
        main = QHBoxLayout()
        self.main = main
        self.board = Board(self.doc)
        self.board.menu_provider = self._context_menu
        self.board.group_menu = self._group_menu
        self.board.group_rename = self._rename_group
        self.left = Column(LEFT_TABS)
        self.right = Column(RIGHT_TABS)
        mid = QVBoxLayout()
        self.mid = mid
        mid.addWidget(self.board, 1)
        self.strip = PageStrip(self.doc)
        mid.addWidget(self.strip)
        main.addWidget(self.left)
        main.addLayout(mid, 1)
        main.addWidget(self.right)
        self.rv.addLayout(main, 1)

        b_zo.clicked.connect(lambda: self.board.set_zoom(self.board.zoom / 1.25))
        b_zi.clicked.connect(lambda: self.board.set_zoom(self.board.zoom * 1.25))
        b_fit.clicked.connect(self.board.fit)
        self.board.zoom_changed.connect(lambda z: self.zlab.setText(f"{z * 100:.0f}%"))
        self.board.tool_changed.connect(self._tool_changed)

        self.panels = {}
        for cls in (BriefPanel, CanvasPanel, CreatePanel, SnapPanel, ViewPanel):
            p = cls(self); self.left.add(p); self.panels[p.key] = p
        from .design import DesignPanel
        for cls in (ShapePanel, DesignPanel, TransformPanel, DetailsPanel, ShapesPanel):
            p = cls(self); self.right.add(p); self.panels[p.key] = p
        self.left.open = ["canvas", "create"]
        self.right.open = ["design", "details", "shapes"]
        self.left._sync(); self.right._sync()
        self.left.state_changed.connect(self._ui_changed)
        self.right.state_changed.connect(self._ui_changed)

        # restore UI state from the last session
        if ui:
            self.left.set_state(ui.get("left"))
            self.right.set_state(ui.get("right"))
            self.board.show_names = ui.get("names", True)
            self.board.show_helpers = ui.get("helpers", True)
            if not ui.get("design_seen"):       # the Design tab is new: open it once
                if "design" not in self.right.open:
                    self.right.open.insert(0, "design")
                self.right._sync()
            from .colors import RECENTS
            RECENTS.load(ui.get("recents"))
            if isinstance(ui.get("style"), dict):
                self.doc.style.update(ui["style"])

        # ---------------------------------------------------------------- signals
        d = self.doc
        self._rt = QTimer(self); self._rt.setSingleShot(True); self._rt.setInterval(0)
        self._rt.timeout.connect(self.refresh_panels)
        d.changed.connect(self._rt.start)
        d.selection_changed.connect(self._rt.start)
        self.board.shape_clicked.connect(lambda: self.right.show_tabs(["shape", "details"]))
        d.selection_changed.connect(self.panels["shapes"].sync_sel)
        d.structure.connect(self.panels["shapes"].rebuild)
        d.structure.connect(self._rt.start)
        d.page_changed.connect(self._rt.start)
        d.status.connect(self.say)
        d.dirty_changed.connect(self._dirty)
        self._autosave = QTimer(self); self._autosave.setSingleShot(True); self._autosave.setInterval(1200)
        self._autosave.timeout.connect(self._save_session)
        self._uisave = QTimer(self); self._uisave.setSingleShot(True); self._uisave.setInterval(800)
        self._uisave.timeout.connect(self._save_session)
        self._msg_t = QTimer(self); self._msg_t.setSingleShot(True); self._msg_t.timeout.connect(lambda: self.status.setText(""))

        self._actions()
        self._scale_key = None
        self.apply_scale(force=True)
        self.panels["shapes"].rebuild()
        self.refresh_panels()
        self._tool_changed(self.board.tool)
        self._dirty(self.doc.dirty)
        self.say("Ready. R draws a rectangle, L a line. Right-drag pans, wheel zooms.")
        from . import bridge          # lets AI agents work in this window (see AGENTS.md)
        self.bridge = bridge.start(self)

    # ------------------------------------------------------------------ shortcuts
    def _actions(self):
        def act(keys, fn):
            a = QAction(self)
            a.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, (list, tuple)) else [keys])])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(fn)
            self.addAction(a)
            return a
        act("Ctrl+Z", self.doc.undo)
        act(["Ctrl+Y", "Ctrl+Shift+Z"], self.doc.redo)
        act("Ctrl+S", self.save)
        act("Ctrl+Shift+S", self.save_as)
        act("Ctrl+O", self.open_dialog)
        act("Ctrl+N", self.new_project)
        act("Ctrl+D", self.duplicate)
        act("Ctrl+G", lambda: self._if_board(self.doc.group_selection))
        act("Ctrl+Shift+G", lambda: self._if_board(self.doc.ungroup_selected))
        act("Ctrl+C", self.copy)
        act("Ctrl+X", self.cut)
        act("Ctrl+V", self.paste)
        act("Ctrl+A", self.select_all)
        act("Ctrl+0", self.board.fit)
        act("Ctrl+1", lambda: self.board.set_zoom(1.0))
        act(["Ctrl+=", "Ctrl++"], lambda: self.board.set_zoom(self.board.zoom * 1.25))
        act("Ctrl+-", lambda: self.board.set_zoom(self.board.zoom / 1.25))
        act("Ctrl+]", lambda: self.doc.reorder("forward"))
        act("Ctrl+[", lambda: self.doc.reorder("backward"))
        act("Ctrl+Shift+]", lambda: self.doc.reorder("front"))
        act("Ctrl+Shift+[", lambda: self.doc.reorder("back"))
        act("Shift+H", lambda: self._if_board(lambda: self.flip(0)))
        act("Shift+V", lambda: self._if_board(lambda: self.flip(1)))
        act("F11", self.toggle_fullscreen)
        act("Ctrl+Q", self.close)
        act("Ctrl+PgDown", lambda: self.doc.go_page(self.doc.page_index + 1))
        act("Ctrl+PgUp", lambda: self.doc.go_page(self.doc.page_index - 1))

    def _if_board(self, fn):
        w = QApplication.focusWidget()
        if self._text_focus():
            return
        fn()

    # ------------------------------------------------------------------ responsive sizing
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.apply_scale()

    def apply_scale(self, force=False):
        w, h = max(1, self.width()), max(1, self.height())
        s = max(0.72, min(1.6, min(w / 1920, h / 1080)))
        s = round(s * 20) / 20
        side_l = int(max(210, min(420, w * 0.18)))
        side_r = int(max(210, min(420, w * 0.18)))
        key = (s,)
        if force or key != self._scale_key:
            self._scale_key = key
            theme.S = s
            QApplication.instance().setStyleSheet(theme.qss())
            m = theme.px(16)
            self.rv.setContentsMargins(m, theme.px(12), m, m)
            self.rv.setSpacing(theme.px(12))
            self.main.setSpacing(theme.px(12))
            self.mid.setSpacing(theme.px(8))
            self.hflow.set_gap(theme.px(10))
            for sp in self.seps:
                sp.apply_scale()
            self.pname.setFixedWidth(theme.px(170))
            self.status.setFixedWidth(theme.px(360))
            self.zlab.setFixedWidth(theme.px(46))
            self.left.apply_scale(); self.right.apply_scale()
            self.strip.apply_scale()
            self.panels["shapes"].rebuild()
        self.left.setFixedWidth(side_l)
        self.right.setFixedWidth(side_r)
        self.header.updateGeometry()
        self.hr.setSpacing(theme.px(6))
        right_w = self.hright.sizeHint().width() + theme.px(12)
        hh = max(self.hflow.heightForWidth(max(100, w - 2 * theme.px(16) - right_w)), self.hright.sizeHint().height())
        self.header.setFixedHeight(hh)

    # ------------------------------------------------------------------ state
    def refresh_panels(self):
        for p in self.panels.values():
            if not p.isHidden():      # open in its column (the window itself may not be on screen yet)
                p.refresh()

    def say(self, text):
        fm = self.status.fontMetrics()
        self.status.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, self.status.width()))
        self.status.setToolTip(text)
        self._msg_t.start(6000)

    def _dirty(self, d):
        name = self.doc.project.name
        where = f"  ({self.doc.path.name})" if self.doc.path else ""
        self.setWindowTitle(f"Uxandi  ·  {name}{where}{'  •' if d else ''}")
        if self.pname.text() != name and not self.pname.hasFocus():
            self.pname.setText(name)
        self._autosave.start()

    def _ui_changed(self):
        self.refresh_panels()
        self.save_ui_soon()

    def save_ui_soon(self):
        self._uisave.start()

    def ui_state(self):
        from .colors import RECENTS
        return {"left": self.left.state(), "right": self.right.state(),
                "names": self.board.show_names, "helpers": self.board.show_helpers,
                "design_seen": True, "recents": RECENTS.lists, "style": dict(self.doc.style)}

    def _save_session(self):
        try:
            self.doc.save_session(self.ui_state())
        except Exception as e:
            self.say(f"Could not keep the session: {e}")

    def _tool_changed(self, t):
        for k, b in self.tool_btns.items():
            b.setChecked(k == t)

    def _pname(self):
        t = self.pname.text().strip() or "Untitled"
        if t != self.doc.project.name:
            self.doc.project.name = t
            self.doc.commit("Project renamed")

    # ------------------------------------------------------------------ files
    def _fill_open(self):
        m = self.open_menu
        m.clear()
        files = sorted(PROJECTS_DIR.glob("*" + EXT), key=lambda p: p.stat().st_mtime, reverse=True) if PROJECTS_DIR.exists() else []
        for f in files[:30]:
            m.addAction(f.stem, lambda f=f: self.open_path(f))
        if files:
            m.addSeparator()
        m.addAction("Browse…", self.open_dialog)
        m.addAction("Import an export…", self.import_dialog)

    def _ok_to_drop(self) -> bool:
        if not self.doc.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", f"Save \"{self.doc.project.name}\" first?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        if r == QMessageBox.StandardButton.Save:
            return self.save()
        return True

    def open_dialog(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getOpenFileName(self, "Open project", str(PROJECTS_DIR), f"Uxandi (*{EXT});;All files (*)")
        if f:
            self.open_path(Path(f))

    def open_path(self, f: Path):
        if not self._ok_to_drop():
            return
        try:
            self.doc.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Could not open", f"{f}\n\n{e}")
            return
        self.pname.setText(self.doc.project.name)
        self.board._views.clear()
        self.board.fit()

    def new_project(self):
        if not self._ok_to_drop():
            return
        self.doc.new_project()
        self.pname.setText(self.doc.project.name)
        self.board._views.clear()
        self.board.fit()

    def save(self) -> bool:
        self._pname()
        try:
            if self.doc.path is None:
                return self.save_as()
            self.doc.save()
            return True
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return False

    def save_as(self) -> bool:
        self._pname()
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        start = PROJECTS_DIR / (safe_name(self.doc.project.name) + EXT)
        f, _ = QFileDialog.getSaveFileName(self, "Save project", str(start), f"Uxandi (*{EXT})")
        if not f:
            return False
        p = Path(f)
        if p.suffix.lower() != EXT:
            p = p.with_suffix(EXT)
        if self.doc.project.name in ("", "Untitled"):
            self.doc.project.name = p.stem
            self.pname.setText(p.stem)
        try:
            self.doc.save(p)
        except Exception as e:
            QMessageBox.warning(self, "Could not save", str(e))
            return False
        self._dirty(self.doc.dirty)
        return True

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange and self.isMinimized():
            self.board.drop_caches()     # the kept board picture is rebuilt when the window comes back

    def closeEvent(self, e):
        self._save_session()
        if getattr(self, "bridge", None):
            self.bridge.close()
        super().closeEvent(e)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    # ------------------------------------------------------------------ shape commands
    def add_shape(self, kind, at=None):
        pg = self.doc.page
        W, H = pg.width, pg.height
        cx, cy = at if at else self.board.view_center_canvas()
        cx = min(max(cx, 0), W); cy = min(max(cy, 0), H)
        if kind == "line":
            L = round(min(W, H) * 0.25)
            s = Shape(kind="line", x1=round(cx - L / 2), y1=round(cy), x2=round(cx + L / 2), y2=round(cy), stroke_width=3)
            s.name = pg.next_name("Line")
            self.doc.styled(s)
        elif kind in ("square", "circle"):
            a = round(min(W, H) * 0.2)
            s = Shape(kind="rect" if kind == "square" else "ellipse", x=round(cx - a / 2), y=round(cy - a / 2), w=a, h=a,
                      lock_ratio=True)
            s.name = pg.next_name("Square" if kind == "square" else "Circle")
            self.doc.styled(s)
        else:
            w = round(min(W, H) * 0.3); h = round(w * 0.6)
            s = Shape(kind="rect", x=round(cx - w / 2), y=round(cy - h / 2), w=w, h=h)
            s.name = pg.next_name("Rectangle")
            self.doc.styled(s)
        self.board.keep_in([s])
        self.board.fit_grid([s])
        self.board.keep_in([s], shrink=False)
        self.doc.add_shapes([s], f"Added {s.name}")
        self.board.setFocus()

    def duplicate(self):
        sel = self.doc.selected()
        if not sel:
            return
        copies = []
        off = self.board.gsize() if self.doc.snap.grid else 20
        for s in sel:
            c = s.clone()
            c.translate(off, off)
            c.name = self._copy_name(s.name)
            copies.append(c)
        self.board.keep_in(copies)
        self.board.fit_grid(copies)
        self.doc.add_shapes(copies, f"Duplicated {len(copies)}")

    def _copy_name(self, name):
        if not name:
            return name
        return self.doc.page.next_name(name.rsplit(" ", 1)[0]) if name.rsplit(" ", 1)[-1].isdigit() else name + " copy"

    def copy(self):
        if self._text_focus():
            return
        sel = self.doc.selected()
        if sel:
            self.clip = [s.to_dict() for s in sel]
            self._paste_n = 0
            self.say(f"Copied {len(sel)}")

    def cut(self):
        if self._text_focus():
            return
        self.copy()
        self.doc.delete_selected()

    def paste(self, at=None):
        if self._text_focus() or not self.clip:
            return
        self._paste_n += 1
        shapes = []
        for d in self.clip:
            s = Shape.from_dict(copy.deepcopy(d)).clone()
            shapes.append(s)
        if at:
            b = union_box(s.aabb() for s in shapes)
            dx, dy = at[0] - (b[0] + b[2]) / 2, at[1] - (b[1] + b[3]) / 2
        else:
            ids = {s.id for s in self.doc.page.shapes}
            same = any(d["id"] in ids for d in self.clip)
            dx = dy = 20 * self._paste_n if same else 0
        for s in shapes:
            s.translate(round(dx), round(dy))
            if s.name and self.doc.page.get(s.id) is None:
                if any(o.name == s.name for o in self.doc.page.shapes):
                    s.name = self._copy_name(s.name)
        self.board.keep_in(shapes)
        self.board.fit_grid(shapes)
        self.board.keep_in(shapes, shrink=False)
        self.doc.add_shapes(shapes, f"Pasted {len(shapes)}")

    def select_all(self):
        if self._text_focus():
            return
        self.doc.set_selection([s.id for s in self.doc.page.shapes])

    def _text_focus(self):
        w = QApplication.focusWidget()
        return w is not None and (isinstance(w, QLineEdit) or w.inherits("QAbstractSpinBox")
                                  or w.inherits("QPlainTextEdit"))

    def _pivot(self, sel):
        if len(sel) == 1:
            return sel[0].center()
        b = union_box(s.aabb() for s in sel)
        return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2

    def rotate_by(self, deg):
        sel = self.doc.selected()
        if not sel:
            return
        px_, py_ = self._pivot(sel)
        for s in sel:
            if s.is_line:
                s.x1, s.y1 = rot_pt(s.x1, s.y1, px_, py_, deg)
                s.x2, s.y2 = rot_pt(s.x2, s.y2, px_, py_, deg)
                s.x1, s.y1, s.x2, s.y2 = (round(v, 3) for v in (s.x1, s.y1, s.x2, s.y2))
            else:
                c = rot_pt(*s.center(), px_, py_, deg)
                s.rotation = norm_deg(s.rotation + deg)
                s.set_center(round(c[0], 3), round(c[1], 3))
        self.board.keep_in(sel)
        self.board.fit_grid(sel)
        self.doc.changed.emit()
        self.doc.commit(f"Turned {deg:+g}°")

    def flip(self, axis):
        sel = self.doc.selected()
        if not sel:
            return
        px_, py_ = self._pivot(sel)
        for s in sel:
            if s.is_line:
                if axis == 0:
                    s.x1, s.x2 = 2 * px_ - s.x1, 2 * px_ - s.x2
                else:
                    s.y1, s.y2 = 2 * py_ - s.y1, 2 * py_ - s.y2
            else:
                cx, cy = s.center()
                if axis == 0:
                    cx = 2 * px_ - cx
                else:
                    cy = 2 * py_ - cy
                s.rotation = norm_deg(-s.rotation)
                s.set_center(cx, cy)
            if axis == 0:
                s.flip_h = not s.flip_h
            else:
                s.flip_v = not s.flip_v
        self.board.keep_in(sel)
        self.board.fit_grid(sel)
        self.doc.changed.emit()
        self.doc.commit("Flipped " + ("horizontally" if axis == 0 else "vertically"))

    # ------------------------------------------------------------------ export for agents
    def _flush_text(self):
        """Store text still being typed in the notes and brief boxes."""
        self.panels["details"]._notes_save()
        self.panels["brief"]._save()
        self._pname()

    def export_json(self, compact: bool = True):
        """compact (default): the same facts without empty, default and derivable values (far smaller for agents).
        compact=False: the full form, every field written out."""
        self._flush_text()
        try:
            path, text = exporter.write_export(self.doc.project, EXPORTS_DIR, self.doc.snap.grid, compact=compact)
        except Exception as e:
            QMessageBox.warning(self, "Could not export", str(e))
            return None
        QApplication.clipboard().setText(text)
        n = sum(len(p.shapes) for p in self.doc.project.pages)
        empty = sum(1 for p in self.doc.project.pages for s in p.shapes if not s.notes.strip())
        tail = f" · {empty} without notes" if empty else " · all have notes"
        kind = "" if compact else "full "
        self.say(f"Exported {kind}{len(self.doc.project.pages)} page(s), {n} elements{tail} → "
                 f"{path.relative_to(EXPORTS_DIR.parent)} (also copied)")
        self._reveal(path)
        return path

    def copy_json(self, compact: bool = True):
        self._flush_text()
        text = exporter.export_text(self.doc.project, self.doc.snap.grid, compact=compact)
        QApplication.clipboard().setText(text)
        self.say(("Agent JSON" if compact else "Full agent JSON") + " copied to the clipboard")

    def open_exports(self):
        folder = EXPORTS_DIR / exporter.safe_name(self.doc.project.name)
        folder = folder if folder.exists() else EXPORTS_DIR
        folder.mkdir(parents=True, exist_ok=True)
        self._reveal(folder, select=False)

    def _reveal(self, path: Path, select=True):
        import os, subprocess, sys
        if os.environ.get("UXANDI_NO_REVEAL"):
            return
        try:
            if sys.platform.startswith("win"):
                if select:
                    subprocess.Popen(["explorer", "/select,", str(path)])
                else:
                    os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R" if select else "", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent if select else path)])
        except Exception as e:
            self.say(f"Saved, but could not open the folder: {e}")

    def import_dialog(self):
        EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getOpenFileName(self, "Import an export", str(EXPORTS_DIR), "Uxandi export (*.json);;All files (*)")
        if f:
            self.import_path(Path(f))

    def import_path(self, f: Path):
        import json
        if not self._ok_to_drop():
            return
        try:
            pr = exporter.import_export(json.loads(Path(f).read_text(encoding="utf-8")), Path(f).parent)
        except Exception as e:
            QMessageBox.warning(self, "Could not import", f"{f}\n\n{e}")
            return
        self.doc.import_project(pr)
        self.pname.setText(pr.name)
        self.board._views.clear()
        self.board.fit()
        self.say(f"Imported {Path(f).name}. Save it to keep it as a project.")

    # ------------------------------------------------------------------ groups
    def _group_menu(self, gpos, gid):
        g = self.doc.page.get_group(gid)
        if not g:
            return
        m = QMenu(self)
        m.addAction(f"Select {g['name']}", lambda: self.doc.select_group(gid))
        m.addAction("Add to the selection", lambda: self.doc.select_group(gid, add=True))
        m.addAction("Rename…", lambda: self._rename_group(gid))
        m.addSeparator()
        m.addAction("Ungroup (the shapes stay)", lambda: self.doc.dissolve_group(gid))
        m.exec(gpos)

    def _rename_group(self, gid):
        from PySide6.QtWidgets import QInputDialog
        g = self.doc.page.get_group(gid)
        if not g:
            return
        t, ok = QInputDialog.getText(self, "Rename group", "Group name:", text=g["name"])
        if ok:
            self.doc.rename_group(gid, t)

    # ------------------------------------------------------------------ right-click menu
    def _context_menu(self, gpos, shape, cpt):
        m = QMenu(self)
        if shape:
            sel = self.doc.selection
            pg = self.doc.page
            if len(sel) > 1:
                m.addAction(f"Group these {len(sel)}   Ctrl+G", self.doc.group_selection)
            groups = {}
            for sid in sel:
                g = pg.group_of(sid)
                if g:
                    groups[g["id"]] = g
            if groups:
                for g in groups.values():
                    m.addAction(f"Select all of {g['name']}", lambda gid=g["id"]: self.doc.select_group(gid))
                names = ", ".join(g["name"] for g in groups.values())
                m.addAction(f"Remove from {names}   Ctrl+Shift+G", self.doc.ungroup_selected)
            elif len(sel) == 1:
                m.addAction("Make a group of it   Ctrl+G", self.doc.group_selection)
            m.addSeparator()
            m.addAction("Rename   F2", lambda: self.board.start_rename(shape.id))
            m.addAction("Duplicate   Ctrl+D", self.duplicate)
            m.addAction("Copy   Ctrl+C", self.copy)
            m.addSeparator()
            m.addAction("Turn left 90°", lambda: self.rotate_by(-90))
            m.addAction("Turn right 90°", lambda: self.rotate_by(90))
            m.addAction("Flip horizontal   Shift+H", lambda: self.flip(0))
            m.addAction("Flip vertical   Shift+V", lambda: self.flip(1))
            m.addSeparator()
            m.addAction("Bring to front", lambda: self.doc.reorder("front"))
            m.addAction("Send to back", lambda: self.doc.reorder("back"))
            m.addSeparator()
            m.addAction("Delete   Del", self.doc.delete_selected)
        else:
            m.addAction("Rectangle here", lambda: self.add_shape("rect", cpt))
            m.addAction("Square here", lambda: self.add_shape("square", cpt))
            m.addAction("Circle here", lambda: self.add_shape("circle", cpt))
            m.addAction("Line here", lambda: self.add_shape("line", cpt))
            m.addSeparator()
            a = m.addAction("Paste here", lambda: self.paste(cpt)); a.setEnabled(bool(self.clip))
            m.addAction("Select all   Ctrl+A", self.select_all)
            m.addAction("Fit canvas   Ctrl+0", self.board.fit)
        m.exec(gpos)
