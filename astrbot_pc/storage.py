"""存储占用统计与清理。

界面上的占用条不能只有备份大小——真正占大头的是 NapCat 与 AstrBot 本体。
扫描带时间上限，慢盘上宁可少报几个数，也不能让页面转圈。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import paths

SCAN_BUDGET = 6.0


def _walk(path: Path, deadline: float, skip: set[str] | None = None) -> tuple[int, int]:
    """返回 (bytes, files)。超过预算就停下，已统计的部分照常返回。"""
    total = 0
    files = 0
    skip = skip or set()
    stack = [path]
    while stack:
        if time.monotonic() > deadline:
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    if e.name in skip:
                        continue
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, files


def _size(path: Path, deadline: float, skip: set[str] | None = None) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    return _walk(path, deadline, skip)[0]


def _sections() -> list[tuple[str, str, Path, set[str]]]:
    stack = paths.STACK_DIR
    return [
        ("astrbot", "AstrBot 本体", stack / "astrbot", {"__pycache__", ".git"}),
        ("napcat", "NapCat", stack / "napcat", {"__pycache__"}),
        ("venv", "Python 虚拟环境", stack / ".venv", {"__pycache__"}),
        ("logs", "日志", paths.LOG_DIR, set()),
        ("backups", "备份", paths.BACKUP_DIR, set()),
        ("tmp", "临时文件", paths.TMP_DIR, set()),
        ("state", "状态与配置", paths.STATE_DIR, {"__pycache__"}),
        ("diag", "诊断包", paths.DIAG_DIR, set()),
    ]


_cache: dict[str, Any] = {"ts": 0.0, "data": None}
_CACHE_TTL = 30.0


def scan(force: bool = False) -> dict[str, Any]:
    """统计各目录占用。

    Args:
        force: 为 True 时忽略 30 秒缓存（清理后需要立即刷新）。

    Returns:
        统计数据，结构见下方 return。
    """
    if not force and _cache["data"] is not None and time.time() - _cache["ts"] < _CACHE_TTL:
        return dict(_cache["data"], cached=True)
    deadline = time.monotonic() + SCAN_BUDGET
    rows: list[dict[str, Any]] = []
    for key, label, path, skip in _sections():
        if key == "venv" and not path.exists():
            continue
        rows.append({"key": key, "label": label, "bytes": _size(path, deadline, skip), "path": str(path)})
    rows.append({
        "key": "config",
        "label": "配置文件",
        "bytes": _size(paths.CONFIG_FILE, deadline),
        "path": str(paths.CONFIG_FILE),
    })

    disk: dict[str, Any] = {}
    try:
        usage = shutil.disk_usage(str(paths.ROOT))
        disk = {"free": usage.free, "total": usage.total, "used": usage.used}
    except Exception:
        disk = {"free": 0, "total": 0, "used": 0}

    data = {
        "ok": True,
        "items": rows,
        "total": sum(r["bytes"] for r in rows),
        "disk": disk,
        "ts": int(time.time()),
        "cached": False,
    }
    _cache["ts"] = time.time()
    _cache["data"] = data
    return dict(data)


def _clear_dir(path: Path, keep: set[str] | None = None) -> int:
    keep = keep or set()
    freed = 0
    if not path.is_dir():
        return 0
    for child in path.iterdir():
        if child.name in keep:
            continue
        try:
            if child.is_dir():
                freed += _size(child, time.monotonic() + 2.0)
                shutil.rmtree(child, ignore_errors=True)
            else:
                freed += child.stat().st_size
                child.unlink()
        except OSError:
            continue
    return freed


def _purge_pycache() -> int:
    freed = 0
    for root, dirs, _files in os.walk(paths.STACK_DIR):
        for d in list(dirs):
            if d != "__pycache__":
                continue
            p = Path(root) / d
            freed += _size(p, time.monotonic() + 1.5)
            shutil.rmtree(p, ignore_errors=True)
            dirs.remove(d)
    return freed


def clean(what: str = "tmp") -> dict[str, Any]:
    """what：tmp / diag / logs / cache / quick。

    日志只删轮转出去的老文件（xxx.log.1 之类），正在写的保留。
    """
    what = (what or "tmp").strip().lower()
    freed = 0
    done: list[str] = []
    if what in ("tmp", "quick"):
        freed += _clear_dir(paths.TMP_DIR)
        done.append("临时文件")
    if what in ("diag", "quick"):
        freed += _clear_dir(paths.DIAG_DIR)
        done.append("诊断包")
    if what in ("cache", "quick"):
        freed += _purge_pycache()
        done.append("字节码缓存")
    if what == "logs":
        for f in paths.LOG_DIR.glob("*.log.*"):
            try:
                freed += f.stat().st_size
                f.unlink()
            except OSError:
                continue
        for f in list(paths.LOG_DIR.glob("*.log")):
            try:
                if time.time() - f.stat().st_mtime > 86400:
                    freed += f.stat().st_size
                    f.write_text("", encoding="utf-8")
            except OSError:
                continue
        done.append("旧日志")
    if not done:
        return {"ok": False, "err": "不认识的清理项"}
    return {"ok": True, "freed": freed, "done": done, "storage": scan(force=True)}
