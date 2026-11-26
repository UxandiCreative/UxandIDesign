"""Live agent bridge: while the app is open, agents send commands to it here.

A small server on 127.0.0.1 only (never the network). Each request is one line of JSON,
    {"token": "...", "tool": "create_shapes", "args": {...}}
and the answer is one line,
    {"ok": true, "result": {...}}   or   {"ok": false, "error": "..."}
A screenshot's PNG comes back base64 in result["_image"].

The port and a fresh random token are written to data/bridge.json when the app starts
(data/ is git-ignored) and removed when it closes. uxandi_agent.py reads that file, so
an agent finds the open app by itself. Turn the bridge off with UXANDI_BRIDGE=0.
"""
from __future__ import annotations

import json
import os
import secrets
import traceback

from PySide6.QtCore import QObject, QByteArray, QBuffer, QIODevice
from PySide6.QtNetwork import QTcpServer, QHostAddress

from . import agent
from . import doc as docmod

PORTS = range(47321, 47331)
MAX_LINE = 64 * 1024 * 1024


def bridge_file():
    return docmod.DATA_DIR / "bridge.json"


class LiveTarget(agent.Target):
    live = True

    def __init__(self, window):
        super().__init__(window.doc)
        self.w = window

    def flush(self):
        try:
            self.w._flush_text()
        except Exception:
            pass

    def loaded(self):
        w = self.w
        w.pname.setText(w.doc.project.name)
        w.board._views.clear()
        w.board.fit()
        w._dirty(w.doc.dirty)

    def page_resized(self, index):
        if index == self.doc.page_index:
            self.w.board._views.pop(self.doc.page.id, None)
            self.doc.page_changed.emit()

    def templates_changed(self):
        p = self.w.panels.get("design")
        if p is not None:
            p._tpl_fill()

    def show(self, index, ids):
        self.doc.go_page(index)
        self.doc.set_selection(ids)
        self.w.raise_()
        self.w.activateWindow()

    def window_png(self, max_size):
        pm = self.w.grab()
        if max(pm.width(), pm.height()) > max_size:
            from PySide6.QtCore import Qt
            pm = pm.scaled(max_size, max_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        pm.save(buf, "PNG")
        buf.close()
        return bytes(ba.data())


class Bridge(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.target = LiveTarget(window)
        self.token = secrets.token_hex(16)
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._accept)
        self.port = None
        for p in list(PORTS) + [0]:
            if self.server.listen(QHostAddress.SpecialAddress.LocalHost, p):
                self.port = self.server.serverPort()
                break
        if self.port is None:
            return
        try:
            f = bridge_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"port": self.port, "token": self.token, "pid": os.getpid(),
                                     "api_version": agent.API_VERSION}), encoding="utf-8")
        except Exception:
            pass

    def _accept(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            sock.setProperty("buf", b"")
            sock.readyRead.connect(lambda s=sock: self._read(s))
            sock.disconnected.connect(sock.deleteLater)

    def _read(self, sock):
        buf = bytes(sock.property("buf") or b"") + bytes(sock.readAll().data())
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                sock.write(json.dumps(self._handle(line), ensure_ascii=False).encode("utf-8") + b"\n")
                sock.flush()
        if len(buf) > MAX_LINE:
            buf = b""
            sock.disconnectFromHost()
        sock.setProperty("buf", buf)

    def _handle(self, line: bytes) -> dict:
        try:
            req = json.loads(line.decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "Not JSON."}
        if not isinstance(req, dict) or not secrets.compare_digest(str(req.get("token", "")), self.token):
            return {"ok": False, "error": "Wrong or missing token (read it from data/bridge.json)."}
        if req.get("tool") == "_ping":
            return {"ok": True, "result": {"app": "Uxandi", "api_version": agent.API_VERSION}}
        try:
            res = agent.call(self.target, str(req.get("tool", "")), req.get("args") or {})
            if "_image" in res:
                res = dict(res, _image=agent.png_b64(res["_image"]))
            return {"ok": True, "result": res}
        except agent.ToolError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": f"Internal error in the app: {type(e).__name__}: {e}"}

    def close(self):
        self.server.close()
        try:
            f = bridge_file()
            if f.exists() and json.loads(f.read_text(encoding="utf-8")).get("token") == self.token:
                f.unlink()
        except Exception:
            pass


def start(window):
    if os.environ.get("UXANDI_BRIDGE", "1") == "0":
        return None
    b = Bridge(window)
    return b if b.port else None
