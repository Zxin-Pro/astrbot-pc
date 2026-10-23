"""内置命令行：把排障常用的命令直接跑在界面上。

只允许把工作目录设在数据目录里，输出截断到 64 KB，超时连子进程树一起杀——
界面里的一个输入框不该能把整台机器卡住。
"""

from __future__ import annotations

import codecs
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from . import paths

MAX_OUTPUT = 64 * 1024
MAX_TIMEOUT = 180


def _cwd(raw: str) -> Path:
    cand = Path(raw).expanduser()
    if not str(raw or "").strip():
        return paths.ROOT
    if not cand.is_absolute():
        cand = paths.ROOT / cand
    try:
        cand = cand.resolve()
        cand.relative_to(paths.ROOT.resolve())
    except Exception:
        return paths.ROOT
    return cand if cand.is_dir() else paths.ROOT


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    return env


def run(cmd: str, cwd: str = "", timeout: int = 60) -> dict[str, Any]:
    cmd = (cmd or "").strip()
    if not cmd:
        return {"ok": False, "err": "命令是空的"}
    if len(cmd) > 2000:
        return {"ok": False, "err": "命令太长"}
    work = _cwd(cwd)
    timeout = max(3, min(MAX_TIMEOUT, int(timeout or 60)))
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            ["cmd", "/c", cmd],
            cwd=str(work),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=_env(),
        )
    except Exception as e:
        return {"ok": False, "err": f"启动失败：{e}"}
    timed_out = False
    try:
        raw, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc.pid)
        try:
            raw, _ = proc.communicate(timeout=5)
        except Exception:
            raw = b""
    out = _decode(raw or b"")
    cut = False
    if len(out) > MAX_OUTPUT:
        half = MAX_OUTPUT // 2
        out = out[:half] + "\n…（中间省略）…\n" + out[-half:]
        cut = True
    return {
        "ok": (not timed_out) and proc.returncode == 0,
        "code": proc.returncode,
        "out": out,
        "truncated": cut,
        "timedOut": timed_out,
        "ms": int((time.perf_counter() - started) * 1000),
        "cwd": str(work),
        "cmd": cmd,
    }


def _decode(raw: bytes) -> str:
    """cmd 的中文输出在简中系统是 GBK；先按 UTF-8 严格试，失败再回退。"""
    if not raw:
        return ""
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gbk")
    except UnicodeDecodeError:
        return raw.decode("gbk", "replace")


def _kill_tree(pid: int) -> None:
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass
