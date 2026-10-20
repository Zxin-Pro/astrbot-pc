"""端口 / 进程 / HTTP 探针。全部带短超时，任何一项都不许卡住界面。"""

from __future__ import annotations

import json
import socket
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT = 0.18

#: 端口探测结果缓存：一次 bootstrap 会连着问好几个端口，别重复等超时
_CACHE: dict[tuple[str, int], tuple[float, bool]] = {}
_TTL = 0.8


def tcp_open(port: int, host: str = "127.0.0.1", timeout: float = TIMEOUT) -> bool:
    if not port:
        return False
    key = (host, int(port))
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        opened = s.connect_ex((host, int(port))) == 0
    except OSError:
        opened = False
    finally:
        s.close()
    _CACHE[key] = (now, opened)
    return opened


def port_owner(port: int) -> dict[str, Any]:
    """返回占用端口的进程信息；拿不到就返回空字典。"""
    try:
        import psutil  # type: ignore

        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == int(port) and conn.status == psutil.CONN_LISTEN:
                pid = conn.pid
                if not pid:
                    continue
                try:
                    p = psutil.Process(pid)
                    return {"pid": pid, "name": p.name(), "exe": _safe(p.exe)}
                except Exception:
                    return {"pid": pid, "name": "", "exe": ""}
    except Exception:
        pass
    return {}


def _safe(fn) -> str:
    try:
        return fn() or ""
    except Exception:
        return ""


def http_get(url: str, timeout: float = 1.2, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "AstrBotPC/1.0", **(headers or {})})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096)
            return {
                "ok": True,
                "status": resp.status,
                "ms": int((time.perf_counter() - started) * 1000),
                "body": body.decode("utf-8", "replace"),
                "headers": dict(resp.headers),
            }
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "ms": int((time.perf_counter() - started) * 1000),
            "body": _safe(lambda: e.read(2048).decode("utf-8", "replace")),
            "headers": {},
        }
    except Exception as e:  # 连接被拒、超时、DNS……
        return {
            "ok": False,
            "status": 0,
            "ms": int((time.perf_counter() - started) * 1000),
            "body": "",
            "error": f"{type(e).__name__}: {e}",
            "headers": {},
        }


def http_ok(url: str, timeout: float = 6.0) -> bool:
    """只问「连得上吗」，不读正文。给部署前的联网检查用。"""
    req = urllib.request.Request(url, headers={"User-Agent": "AstrBotPC/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True  # 有响应就说明网是通的
    except Exception:
        return False


def ps_json(command: str, timeout: float = 6.0) -> Any:
    """跑一段 PowerShell 并解析 JSON 输出。失败返回 None。"""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = proc.stdout.decode("utf-8", "replace").strip()
        if not out:
            return None
        return json.loads(out)
    except Exception:
        return None
