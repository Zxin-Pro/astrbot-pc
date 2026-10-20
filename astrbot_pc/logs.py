"""日志：列文件、取尾巴、按新增行推送。

日志一律按 UTF-8 读，读不出来的字节用 replace 兜住 —— 宁可显示乱码也不要抛异常。
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any

from . import paths
from .events import bus

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
HEX_NOISE = re.compile(r"^[0-9a-fA-F\s]{80,}$")
LEVEL = re.compile(r"\[(error|warn|warning|info|debug|critical)\]|\[(E|W|I|D)\]", re.I)


def _clean(line: str, compact: bool = True) -> str:
    line = ANSI.sub("", line.rstrip("\r\n"))
    if compact and HEX_NOISE.match(line):
        return ""
    return line


def level_of(line: str) -> str:
    m = LEVEL.search(line)
    if not m:
        if "Traceback" in line or "Error:" in line:
            return "error"
        return "info"
    tag = (m.group(1) or m.group(2) or "info").lower()
    if tag.startswith("warn"):
        return "warn"
    if tag in ("e", "error", "critical"):
        return "error"
    if tag in ("d", "debug"):
        return "debug"
    return "info"


def discover() -> list[dict[str, Any]]:
    """所有能看的日志文件。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(p: Path, group: str, label: str | None = None) -> None:
        key = str(p.resolve()).lower()
        if key in seen or not p.is_file():
            return
        seen.add(key)
        try:
            st = p.stat()
        except OSError:
            return
        out.append({
            "path": str(p),
            "name": label or p.name,
            "group": group,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
        })

    for p in sorted(paths.LOG_DIR.glob("*.log")):
        add(p, "应用", {"napcat.log": "NapCat 输出", "astrbot.log": "AstrBot 输出"}.get(p.name, p.name))

    for root in (paths.STACK_DIR / "astrbot" / "data", paths.STACK_DIR / "astrbot" / "data" / "logs"):
        if root.is_dir():
            for p in sorted(root.glob("*.log")):
                add(p, "AstrBot")
            for p in sorted(root.glob("*.log.*"))[:20]:
                add(p, "AstrBot")

    napcat_root = paths.STACK_DIR / "napcat"
    if napcat_root.is_dir():
        for p in sorted(napcat_root.glob("*.log")):
            add(p, "NapCat")
        logs_dir = napcat_root / "logs"
        if logs_dir.is_dir():
            for p in sorted(logs_dir.glob("*.log")):
                add(p, "NapCat")

    out.sort(key=lambda x: (x["group"], x["name"]))
    return out


def tail(path: str, lines: int = 400, compact: bool = True) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "err": "日志文件不存在", "lines": [], "path": path}
    try:
        data = _read_tail(p, max(64 * 1024, lines * 512))
    except Exception as e:
        return {"ok": False, "err": f"读取失败：{e}", "lines": [], "path": path}
    raw = data.splitlines()[-lines:]
    cleaned = [_clean(x, compact) for x in raw]
    cleaned = [x for x in cleaned if x]
    return {
        "ok": True,
        "path": str(p),
        "name": p.name,
        "size": p.stat().st_size,
        "lines": cleaned,
        "levels": [level_of(x) for x in cleaned],
        "compact": compact,
    }


def _read_tail(p: Path, nbytes: int) -> str:
    size = p.stat().st_size
    with p.open("rb") as f:
        if size > nbytes:
            f.seek(-nbytes, 2)
            data = f.read()
            first_nl = data.find(b"\n")
            if first_nl > 0:
                data = data[first_nl + 1:]
        else:
            data = f.read()
    return data.decode("utf-8", "replace")


class LogFollower:
    """盯住当前日志文件，有新增行就往事件总线推。"""

    def __init__(self, interval: float = 1.0, max_lines: int = 200) -> None:
        self.interval = interval
        self.max_lines = max_lines
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._path: str = ""
        self._pos = 0
        self._lock = threading.Lock()

    def follow(self, path: str) -> dict[str, Any]:
        p = Path(path)
        if not p.is_file():
            return {"ok": False, "err": "日志文件不存在"}
        with self._lock:
            self._path = str(p)
            self._pos = p.stat().st_size
        if not self._thread or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="log-follow", daemon=True)
            self._thread.start()
        return {"ok": True, "path": self._path}

    def unfollow(self) -> dict[str, Any]:
        with self._lock:
            self._path = ""
        return {"ok": True}

    def current(self) -> str:
        with self._lock:
            return self._path

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            with self._lock:
                path = self._path
                pos = self._pos
            if not path:
                continue
            p = Path(path)
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size < pos:
                pos = 0
            if size == pos:
                continue
            try:
                with p.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read(min(size - pos, 256 * 1024))
                data = chunk.decode("utf-8", "replace")
                new_pos = pos + len(chunk)
                if not data.endswith("\n"):
                    cut = data.rfind("\n")
                    if cut < 0:
                        continue
                    data = data[: cut + 1]
                    new_pos = pos + len(data.encode("utf-8"))
            except Exception:
                continue
            with self._lock:
                self._pos = new_pos
            lines = [x for x in (_clean(l, True) for l in data.splitlines()) if x]
            if not lines:
                continue
            lines = lines[-self.max_lines:]
            bus.emit("log", {
                "path": path,
                "lines": lines,
                "levels": [level_of(x) for x in lines],
                "ts": int(time.time()),
            })


follower = LogFollower()
