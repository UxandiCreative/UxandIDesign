"""Pictures inside shapes. Uploaded files are copied into assets/images/ (named by their
content, so the same picture is stored once) and shapes keep the relative path."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from PySide6.QtGui import QPixmap, QImageReader

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "assets" / "images"
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
FITS = [("fill", "Fill (cover the shape, crop the rest)"), ("fit", "Fit (whole picture inside)"),
        ("stretch", "Stretch (to the shape)"), ("original", "Original size")]

_cache: dict[str, QPixmap] = {}
_sizes: dict[str, tuple[int, int]] = {}


def resolve(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else ROOT / p


def import_image(src: str | Path) -> str:
    """Copy a picture into assets/images/ and return its path relative to the project folder."""
    src = Path(src)
    data = src.read_bytes()
    ext = src.suffix.lower() if src.suffix.lower() in EXTS else ".png"
    name = hashlib.sha1(data).hexdigest()[:16] + ext
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    dst = IMAGES_DIR / name
    if not dst.exists():
        shutil.copyfile(src, dst)
    try:
        return dst.relative_to(ROOT).as_posix()
    except ValueError:
        return dst.as_posix()


def pixmap(rel: str) -> QPixmap | None:
    if not rel:
        return None
    pm = _cache.get(rel)
    if pm is None:
        p = resolve(rel)
        pm = QPixmap(str(p)) if p.exists() else QPixmap()
        _cache[rel] = pm
    return None if pm.isNull() else pm


def size_of(rel: str) -> tuple[int, int] | None:
    """Pixel size of a picture file (read from its header once: files are named by their content)."""
    if rel in _sizes:
        return _sizes[rel]
    r = QImageReader(str(resolve(rel)))
    s = r.size()
    out = (s.width(), s.height()) if s.isValid() else None
    if out:                     # a missing file is asked again next time (it may come back)
        _sizes[rel] = out
    return out


def prune(keep) -> None:
    """Forget the pictures no shape in `keep` (paths) uses, so a project that was closed frees their memory.
    They are read again from disk if they come back (undo, reopening)."""
    keep = set(keep)
    for k in [k for k in _cache if k not in keep]:
        del _cache[k]


def new_contents(rel: str, original_name: str) -> dict:
    return {"type": "image", "path": rel, "original_name": original_name, "fit": "fill",
            "zoom": 1.0, "dx": 0.0, "dy": 0.0, "opacity": 1.0}


def image_of(shape) -> dict | None:
    c = shape.contents
    return c if isinstance(c, dict) and c.get("type") == "image" else None
