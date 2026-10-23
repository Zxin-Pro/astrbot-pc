"""外观：自定义背景图与玻璃厚度。

背景图存成文件（不塞进 config.json——base64 塞进去会让配置文件大几 MB），
配置里只留文件名和开关。
"""

from __future__ import annotations

import base64
import binascii
import re
import time
from pathlib import Path
from typing import Any

from . import config, paths

MAX_BYTES = 8 * 1024 * 1024
MIME = re.compile(r"^data:image/(png|jpeg|jpg|webp|gif);base64,", re.I)
EXT = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "webp": "webp", "gif": "gif"}
LEVELS = ("off", "soft", "strong")


def _bg_file() -> Path | None:
    name = str((config.get("app.background") or {}).get("file") or "")
    if not name:
        return None
    paths.ensure_dirs()
    p = paths.STATE_DIR / Path(name).name
    return p if p.is_file() else None


def background_path() -> Path | None:
    """给 /files?kind=background 用的实际文件路径。"""
    return _bg_file()


def info() -> dict[str, Any]:
    bg = config.get("app.background") or {}
    f = _bg_file()
    level = str(config.get("app.glassLevel") or ("soft" if config.get("app.glass", True) else "off"))
    return {
        "ok": True,
        "enabled": bool(bg.get("enabled")) and f is not None,
        "file": f.name if f else "",
        "url": f"/files?kind=background&name={f.name}&v={int(f.stat().st_mtime)}" if f else "",
        "size": f.stat().st_size if f else 0,
        "level": level,
        "levels": list(LEVELS),
        "compact": bool(config.get("app.compact")),
    }


def set_level(level: str) -> dict[str, Any]:
    level = (level or "").strip().lower()
    if level not in LEVELS:
        return {"ok": False, "err": "厚度只能是 off / soft / strong"}
    config.save({"app": {"glassLevel": level, "glass": level != "off"}})
    return info()


def set_bg(data_url: str) -> dict[str, Any]:
    raw = (data_url or "").strip()
    m = MIME.match(raw)
    if not m:
        return {"ok": False, "err": "只支持 PNG / JPEG / WebP / GIF 图片"}
    kind = EXT.get(m.group(1).lower(), "png")
    try:
        blob = base64.b64decode(raw[m.end():], validate=True)
    except (binascii.Error, ValueError):
        return {"ok": False, "err": "图片数据不完整，换一张试试"}
    if not blob:
        return {"ok": False, "err": "图片是空的"}
    if len(blob) > MAX_BYTES:
        return {"ok": False, "err": f"图片太大（{len(blob) // 1024} KB），请压到 8 MB 以内"}
    paths.ensure_dirs()
    old = _bg_file()
    name = f"background-{int(time.time())}.{kind}"
    (paths.STATE_DIR / name).write_bytes(blob)
    if old is not None and old.name != name:
        try:
            old.unlink()
        except OSError:
            pass
    config.save({"app": {"background": {"enabled": True, "file": name}}})
    return info()


def clear_bg() -> dict[str, Any]:
    old = _bg_file()
    if old is not None:
        try:
            old.unlink()
        except OSError:
            pass
    config.save({"app": {"background": {"enabled": False, "file": ""}}})
    return info()
