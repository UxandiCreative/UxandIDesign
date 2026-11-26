"""The Design tab: fill colour, border colour and thickness, a picture inside the shape,
and design templates (saved in templates/design/)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QLabel, QComboBox, QSlider, QFileDialog, QInputDialog, QMessageBox, QFrame,
                               QWidget, QVBoxLayout, QHBoxLayout)

from . import theme, images
from .colors import ColorPicker
from .doc import TEMPLATES_DIR
from .images import image_of, FITS
from .panels import DocPanel, button, brow, hrow, field, hint, label, spin, slider_row

TEMPLATE_FORMAT = "uxandi-template"


def _sub(text):
    w = QLabel(text.upper())
    w.setObjectName("PanelTitle")
    return w


def _rule():
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{theme.LINE};")
    return f


class DesignPanel(DocPanel):
    def __init__(self, win):
        super().__init__("design", "Design", win)
        b = self.b
        self.scope = hint("")
        b.addWidget(self.scope)

        # ---------------------------------------------------------------- fill
        b.addWidget(_sub("Fill colour"))
        self.fill = ColorPicker("fill", none_text="no fill")
        self.fill.changed.connect(self._fill)
        self.fill.none_toggled.connect(self._nofill)
        b.addWidget(self.fill)
        fa = button("Apply fill to all shapes", "Every rectangle and square on this page gets this fill", "Small")
        fa.clicked.connect(self._fill_all)
        b.addWidget(brow(fa))
        b.addWidget(_rule())

        # ---------------------------------------------------------------- border
        b.addWidget(_sub("Border"))
        self.border = ColorPicker("border")
        self.border.changed.connect(self._border)
        b.addWidget(self.border)
        self.bw = spin(0, 2000, 1, 0.5, " px")
        self.bw.valueChanged.connect(self._bw)
        b.addWidget(field("thickness (0 = no border)", self.bw))
        ba = button("Apply border to all shapes", "Every shape on this page gets this border colour and thickness", "Small")
        ba.clicked.connect(self._border_all)
        b.addWidget(brow(ba))
        b.addWidget(_rule())

        # ---------------------------------------------------------------- corners
        self.corners = QWidget()
        cl = QVBoxLayout(self.corners); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(theme.px(6))
        cl.addWidget(_sub("Round corners"))
        self.rad_s = QSlider(Qt.Orientation.Horizontal)
        self.rad_s.setRange(0, 1000)
        self.rad_s.setToolTip("0 = square corners, all the way = as round as the shape allows")
        self.rad = spin(0, 50000, 0, 1, " px")
        self.rad_s.valueChanged.connect(self._rad_slider)
        self.rad_s.sliderReleased.connect(lambda: self.doc.commit("Corner radius", merge="radius"))
        self.rad.valueChanged.connect(self._rad_spin)
        rr = QHBoxLayout(); rr.setContentsMargins(0, 0, 0, 0); rr.setSpacing(theme.px(8))
        rr.addWidget(self.rad_s, 3); rr.addWidget(self.rad, 1)
        cl.addLayout(rr)
        cl.addWidget(_rule())
        b.addWidget(self.corners)

        # ---------------------------------------------------------------- lines
        self.linebox = QWidget()
        ll = QVBoxLayout(self.linebox); ll.setContentsMargins(0, 0, 0, 0); ll.setSpacing(theme.px(6))
        ll.addWidget(_sub("Line"))
        self.ls = QComboBox()
        for k, t in (("solid", "solid"), ("dash", "dashed"), ("dot", "dotted")):
            self.ls.addItem(t, k)
        self.cap = QComboBox()
        for k, t in (("round", "round ends"), ("flat", "flat ends"), ("square", "square ends")):
            self.cap.addItem(t, k)
        self.ls.activated.connect(lambda _: self._line("line_style", self.ls.currentData(), "Line style"))
        self.cap.activated.connect(lambda _: self._line("cap", self.cap.currentData(), "Line ends"))
        ll.addWidget(hrow(field("style", self.ls), field("ends", self.cap)))
        ll.addWidget(hint("The colour and thickness of a line or drawing are the Border above."))
        ll.addWidget(_rule())
        b.addWidget(self.linebox)

        # ---------------------------------------------------------------- picture
        b.addWidget(_sub("Image"))
        self.up = button("Upload image…", "Put a picture inside the selected rectangle(s). It is copied into assets/images/.")
        self.rm = button("Remove", "Take the picture out", "Small")
        self.up.clicked.connect(self._upload)
        self.rm.clicked.connect(self._remove)
        b.addWidget(brow(self.up, self.rm))
        self.img_info = hint("")
        b.addWidget(self.img_info)
        self.fit = QComboBox()
        for k, t in FITS:
            self.fit.addItem(t, k)
        self.fit.activated.connect(lambda _: self._img_set("fit", self.fit.currentData(), "Picture fit"))
        b.addWidget(field("how it sits in the shape", self.fit))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(10, 400)
        self.zoom.valueChanged.connect(lambda v: self._img_set("zoom", v / 100, None))
        self.zoom.sliderReleased.connect(lambda: self.doc.commit("Picture zoom", merge="imgzoom"))
        self.zoom_l = label("zoom 100%")
        b.addWidget(self.zoom_l)
        b.addWidget(slider_row(self.zoom, 1, "zoom 1%"))
        self.op = QSlider(Qt.Orientation.Horizontal)
        self.op.setRange(0, 100)
        self.op.valueChanged.connect(lambda v: self._img_set("opacity", v / 100, None))
        self.op.sliderReleased.connect(lambda: self.doc.commit("Picture opacity", merge="imgop"))
        self.op_l = label("opacity 100%")
        b.addWidget(self.op_l)
        b.addWidget(slider_row(self.op, 1, "opacity 1%"))
        self.drag = button("✥ Drag image", "On: dragging a shape moves its picture inside it instead of moving the shape", checkable=True)
        self.drag.toggled.connect(self._drag)
        rs = button("Reset", "Centre the picture again at 100%", "Small")
        rs.clicked.connect(self._img_reset)
        b.addWidget(brow(self.drag, rs))
        self.img_widgets = [self.rm, self.fit, self.zoom, self.op, rs, self.drag]
        b.addWidget(_rule())

        # ---------------------------------------------------------------- templates
        b.addWidget(_sub("Templates"))
        self.tpl = QComboBox()
        self.tpl.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.tpl.setMinimumContentsLength(8)
        b.addWidget(self.tpl)
        ta = button("Apply", "Apply this template to the selection (nothing selected: to new shapes)", "Small")
        ts = button("Save as template…", "Save the fill, border and picture settings shown here under a name", "Small")
        td = button("Delete", "Delete this template", "Small")
        ta.clicked.connect(self._tpl_apply)
        ts.clicked.connect(self._tpl_save)
        td.clicked.connect(self._tpl_delete)
        b.addWidget(brow(ta, ts, td))
        b.addWidget(hint("Templates are kept in templates/design/ and work in every project."))
        self._tpl_fill()

    # ------------------------------------------------------------------ what the edits go to
    def targets(self):
        return self.doc.selected()

    def rects(self):
        return [s for s in self.doc.selected() if s.is_box]

    def refresh(self):
        sel = self.targets()
        rects = self.rects()
        st = self.doc.style
        pg = self.doc.page
        if not sel:
            self.scope.setText("Nothing selected: these are the colours for NEW shapes.")
        else:
            grp = None
            ids = set(self.doc.selection)
            for g in pg.groups:
                if set(g["members"]) == ids:
                    grp = g
            what = f"{grp['name']} ({len(sel)} shapes)" if grp else (sel[0].name if len(sel) == 1 else f"{len(sel)} selected shapes")
            self.scope.setText(f"Changes apply to: {what}")
        ref = rects[0] if rects else None
        fill = ref.fill if ref else (st.get("fill", "") if not sel else "")
        self.fill.set_none(not fill)
        if fill:
            self.fill.set_color(fill)
        bref = sel[0] if sel else None
        self.border.set_color(bref.stroke if bref else st.get("stroke", "#111418"))
        self.set_val(self.bw, bref.stroke_width if bref else st.get("stroke_width", 2.0))
        self.fill.setEnabled(bool(rects) or not sel)
        lines = [s for s in sel if s.is_stroke]
        self.corners.setVisible(any(not s.is_ellipse for s in rects) or not sel)
        self.linebox.setVisible(bool(lines) or not sel)
        if rects:
            mr = max(s.max_radius() for s in rects)
            r0 = rects[0].radius
            self.rad_s.blockSignals(True)
            self.rad_s.setValue(int(round(1000 * min(1.0, r0 / mr))) if mr > 0 else 0)
            self.rad_s.blockSignals(False)
            self.set_val(self.rad, r0)
        elif not sel:
            self.set_val(self.rad, st.get("radius", 0))
        lref = lines[0] if lines else None
        self.set_val(self.ls, lref.line_style if lref else st.get("line_style", "solid"))
        self.set_val(self.cap, lref.cap if lref else st.get("cap", "round"))
        # picture
        img = next((image_of(s) for s in rects if image_of(s)), None)
        self.up.setEnabled(bool(rects))
        for w in self.img_widgets:
            w.setEnabled(img is not None)
        if img:
            sz = images.size_of(img.get("path", ""))
            self.img_info.setText(f"{img.get('original_name', '')}  {sz[0]} × {sz[1]} px" if sz else "picture file missing")
            self.set_val(self.fit, img.get("fit", "fill"))
            self.set_val(self.zoom, int(round(float(img.get("zoom", 1)) * 100)))
            self.set_val(self.op, int(round(float(img.get("opacity", 1)) * 100)))
        else:
            self.img_info.setText("Select a rectangle, then Upload image." if not rects else "No picture in the selection.")
            if self.drag.isChecked():
                self.drag.setChecked(False)
        self.zoom_l.setText(f"zoom {self.zoom.value()}%")
        self.op_l.setText(f"opacity {self.op.value()}%")

    # ------------------------------------------------------------------ fill / border
    def _fill(self, c, final):
        rects = self.rects()
        if not self.targets():
            self.doc.style["fill"] = c
            self.fill.set_none(False)
            self.win.save_ui_soon()
            return
        for s in rects:
            s.fill = c
        self.fill.set_none(False)
        self.doc.changed.emit()
        if final:
            self.doc.commit("Fill colour", merge="fill")

    def _nofill(self, on):
        if not self.targets():
            self.doc.style["fill"] = "" if on else self.fill.color()
            self.win.save_ui_soon()
            return
        for s in self.rects():
            s.fill = "" if on else self.fill.color()
        self.doc.changed.emit()
        self.doc.commit("No fill" if on else "Fill")

    def _border(self, c, final):
        if not self.targets():
            self.doc.style["stroke"] = c
            self.win.save_ui_soon()
            return
        for s in self.targets():
            s.stroke = c
        self.doc.changed.emit()
        if final:
            self.doc.commit("Border colour", merge="stroke")

    def _bw(self, v):
        if not self.targets():
            self.doc.style["stroke_width"] = v
            self.win.save_ui_soon()
            return
        for s in self.targets():
            s.stroke_width = v
        self.doc.changed.emit()
        self.doc.commit("Border thickness", merge="bw")

    def _fill_all(self):
        c = "" if (self.fill.none and self.fill.none.isChecked()) else self.fill.color()
        n = 0
        for s in self.doc.page.shapes:
            if s.is_box:
                s.fill = c
                n += 1
        self.doc.changed.emit()
        self.doc.commit(f"Fill on all {n} shapes")

    def _border_all(self):
        c, w = self.border.color(), self.bw.value()
        for s in self.doc.page.shapes:
            s.stroke, s.stroke_width = c, w
        self.doc.changed.emit()
        self.doc.commit(f"Border on all {len(self.doc.page.shapes)} shapes")

    # ------------------------------------------------------------------ corners / line
    def _rad_slider(self, v):
        rects = self.rects()
        if not self.targets():
            return
        for s in rects:
            s.radius = round(s.max_radius() * v / 1000)
        if rects:
            self.set_val(self.rad, rects[0].radius)
        self.doc.changed.emit()
        if not self.rad_s.isSliderDown():
            self.doc.commit("Corner radius", merge="radius")

    def _rad_spin(self, v):
        if not self.targets():
            self.doc.style["radius"] = v
            self.win.save_ui_soon()
            return
        for s in self.rects():
            s.radius = min(v, s.max_radius())
        self.doc.changed.emit()
        self.doc.commit("Corner radius", merge="radius")

    def _line(self, key, value, msg):
        if not self.targets():
            self.doc.style[key] = value
            self.win.save_ui_soon()
            return
        for s in self.targets():
            if s.is_stroke:
                setattr(s, key, value)
        self.doc.changed.emit()
        self.doc.commit(msg)

    # ------------------------------------------------------------------ picture
    def _upload(self):
        rects = self.rects()
        if not rects:
            self.doc.status.emit("Select a rectangle first")
            return
        f, _ = QFileDialog.getOpenFileName(self.win, "Choose a picture", str(Path.home()),
                                           "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;All files (*)")
        if f:
            self.put_image(f)

    def put_image(self, path):
        rects = self.rects()
        try:
            rel = images.import_image(path)
        except Exception as e:
            QMessageBox.warning(self.win, "Could not load the picture", str(e))
            return
        if images.pixmap(rel) is None:
            QMessageBox.warning(self.win, "Could not load the picture", f"{path} is not a picture this app can read.")
            return
        for s in rects:
            s.contents = images.new_contents(rel, Path(path).name)
        self.doc.changed.emit()
        self.doc.commit(f"Picture in {len(rects)} shape{'s' if len(rects) != 1 else ''}")
        self.refresh()

    def _remove(self):
        n = 0
        for s in self.rects():
            if image_of(s):
                s.contents = None
                n += 1
        self.doc.changed.emit()
        self.doc.commit(f"Picture removed from {n}")
        self.refresh()

    def _img_set(self, key, value, msg):
        if self._busy:
            return
        for s in self.rects():
            img = image_of(s)
            if img:
                img[key] = value
        self.zoom_l.setText(f"zoom {self.zoom.value()}%")
        self.op_l.setText(f"opacity {self.op.value()}%")
        self.doc.changed.emit()
        if msg:
            self.doc.commit(msg)
        elif key == "zoom" and not self.zoom.isSliderDown():
            self.doc.commit("Picture zoom", merge="imgzoom")
        elif key == "opacity" and not self.op.isSliderDown():
            self.doc.commit("Picture opacity", merge="imgop")

    def _img_reset(self):
        for s in self.rects():
            img = image_of(s)
            if img:
                img.update(dx=0.0, dy=0.0, zoom=1.0)
        self.doc.changed.emit()
        self.doc.commit("Picture reset")
        self.refresh()

    def _drag(self, on):
        self.win.board.img_drag = on
        self.doc.status.emit("Drag a picture to move it inside its shape. Click ✥ again to stop." if on
                             else "Dragging moves shapes again")

    # ------------------------------------------------------------------ templates
    def current_template(self) -> dict:
        img = next((image_of(s) for s in self.rects() if image_of(s)), None)
        nofill = bool(self.fill.none and self.fill.none.isChecked())
        return {"format": TEMPLATE_FORMAT, "fill": "" if nofill else self.fill.color(),
                "stroke": self.border.color(), "stroke_width": self.bw.value(),
                "radius": self.rad.value(), "line_style": self.ls.currentData(), "cap": self.cap.currentData(),
                "image": dict(img) if img else None, "saved": time.strftime("%Y-%m-%d %H:%M:%S")}

    def _tpl_fill(self, select: str | None = None):
        self.tpl.clear()
        files = sorted(TEMPLATES_DIR.glob("*.json")) if TEMPLATES_DIR.exists() else []
        for f in files:
            self.tpl.addItem(f.stem, str(f))
        if not files:
            self.tpl.addItem("(no templates yet)", None)
        if select:
            i = self.tpl.findText(select)
            if i >= 0:
                self.tpl.setCurrentIndex(i)

    def _tpl_save(self):
        name, ok = QInputDialog.getText(self.win, "Save design template", "Template name:")
        if not ok or not name.strip():
            return
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip() or "Template"
        self.save_template(safe)

    def save_template(self, name: str) -> Path:
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        d = self.current_template()
        d["name"] = name
        path = TEMPLATES_DIR / f"{name}.json"
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")
        self._tpl_fill(select=name)
        self.doc.status.emit(f"Template saved: {name}")
        return path

    def _tpl_apply(self):
        f = self.tpl.currentData()
        if f:
            self.apply_template(Path(f))

    def apply_template(self, path: Path):
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.warning(self.win, "Could not read the template", str(e))
            return
        sel = self.targets()
        if not sel:       # no selection: the template becomes the style for new shapes
            self.doc.style.update(fill=d.get("fill", ""), stroke=d.get("stroke", "#111418"),
                                  stroke_width=float(d.get("stroke_width", 2)), radius=float(d.get("radius", 0)),
                                  line_style=d.get("line_style", "solid"), cap=d.get("cap", "round"))
            self.win.save_ui_soon()
            self.refresh()
            self.doc.status.emit(f"Template {path.stem}: new shapes will use it")
            return
        for s in sel:
            s.stroke = d.get("stroke", s.stroke)
            s.stroke_width = float(d.get("stroke_width", s.stroke_width))
            if s.is_box:
                s.fill = d.get("fill", s.fill)
                if "radius" in d:
                    s.radius = min(float(d["radius"]), s.max_radius())
                if d.get("image"):
                    s.contents = dict(d["image"])
            else:
                s.line_style = d.get("line_style", s.line_style)
                s.cap = d.get("cap", s.cap)
        self.doc.changed.emit()
        self.doc.commit(f"Template {path.stem} on {len(sel)} shape{'s' if len(sel) != 1 else ''}")
        self.refresh()

    def _tpl_delete(self):
        f = self.tpl.currentData()
        if not f:
            return
        if QMessageBox.question(self.win, "Delete template", f"Delete the template \"{Path(f).stem}\"?") \
                == QMessageBox.StandardButton.Yes:
            Path(f).unlink(missing_ok=True)
            self._tpl_fill()

    def apply_scale(self):
        super().apply_scale()
        for p in (getattr(self, "fill", None), getattr(self, "border", None)):
            if p:
                p.apply_scale()
