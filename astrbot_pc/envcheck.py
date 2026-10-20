"""环境侦测：这台电脑上有哪些组件、装在哪、能不能直接用。

探测结果永远是「给界面看的结论」，不抛异常：拿不到就当没装，
但要在 ``detail`` 里写清为什么拿不到。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import paths

QQ_SEARCH = [
    r"C:\Program Files\Tencent\QQNT\QQ.exe",
    r"C:\Program Files (x86)\Tencent\QQNT\QQ.exe",
    r"C:\Program Files\Tencent\QQ\QQ.exe",
    r"C:\Program Files (x86)\Tencent\QQ\QQ.exe",
]

NAPCAT_SEARCH = [
    paths.STACK_DIR / "napcat" / "launcher.bat",
    paths.STACK_DIR / "napcat" / "napcat.bat",
    paths.STACK_DIR / "napcat" / "napcat.mjs",
    paths.STACK_DIR / "napcat" / "NapCatWinBootMain.exe",
]

ASTRBOT_SEARCH = [
    paths.STACK_DIR / "astrbot",
    paths.STACK_DIR / "AstrBot",
]


def _first_existing(cands: list[str] | list[Path]) -> str:
    for c in cands:
        if Path(c).exists():
            return str(c)
    return ""


def _run(cmd: list[str], timeout: float = 6.0) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (p.stdout or b"").decode("utf-8", "replace").strip()
        err = (p.stderr or b"").decode("utf-8", "replace").strip()
        return p.returncode, out or err
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}"


def check_python() -> dict[str, Any]:
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 10)
    return {
        "key": "python",
        "name": "Python 运行时",
        "status": "ok" if ok else "warn",
        "detail": f"{ver}（{sys.executable}）" if ok else f"{ver}，AstrBot 需要 ≥ 3.10",
        "path": sys.executable,
        "required": True,
    }


def check_git() -> dict[str, Any]:
    exe = shutil.which("git") or _first_existing([r"C:\Program Files\Git\cmd\git.exe"])
    if not exe:
        return {
            "key": "git",
            "name": "Git",
            "status": "warn",
            "detail": "没找到 git；用「下载压缩包」方式安装 AstrBot 时可不用它",
            "path": "",
            "required": False,
        }
    code, out = _run([exe, "--version"])
    return {
        "key": "git",
        "name": "Git",
        "status": "ok" if code == 0 else "warn",
        "detail": out.splitlines()[0] if out else "已安装",
        "path": exe,
        "required": False,
    }


def check_qq() -> dict[str, Any]:
    exe = _first_existing(QQ_SEARCH)
    if not exe:
        # 再试一次注册表以外的常见位置
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")):
            if not base:
                continue
            for sub in ("Tencent\\QQNT\\QQ.exe", "Tencent\\QQ\\QQ.exe"):
                cand = Path(base) / sub
                if cand.exists():
                    exe = str(cand)
                    break
    if not exe:
        return {
            "key": "qq",
            "name": "QQ NT 客户端",
            "status": "missing",
            "detail": "没检测到 QQ NT。部署向导会引导你安装（NapCat 必须挂在新版 QQ 上）",
            "path": "",
            "required": True,
        }
    ver = ""
    try:
        import subprocess as sp

        detail = sp.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
            capture_output=True, timeout=5,
            creationflags=getattr(sp, "CREATE_NO_WINDOW", 0),
        )
        ver = detail.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    return {
        "key": "qq",
        "name": "QQ NT 客户端",
        "status": "ok",
        "detail": f"已安装{f' v{ver}' if ver else ''}",
        "path": exe,
        "required": True,
    }


def _dir_size_mb(p: Path, limit_files: int = 4000) -> float:
    total = 0
    n = 0
    try:
        for root, _dirs, files in os.walk(p):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    continue
                n += 1
                if n >= limit_files:
                    raise StopIteration
    except StopIteration:
        pass
    except Exception:
        pass
    return round(total / 1024 / 1024, 1)


def _napcat_launcher() -> Path | None:
    """压缩包解出来的启动器可能嵌在 bootmain/ 这类子目录里，和 deploy 用同一套判定。"""
    hit = _first_existing(NAPCAT_SEARCH)
    if hit:
        return Path(hit)
    base = paths.STACK_DIR / "napcat"
    if not base.is_dir():
        return None
    for name in ("launcher.bat", "napcat.bat", "napcat.mjs", "NapCatWinBootMain.exe"):
        for found in base.rglob(name):
            return found
    return None


def check_napcat() -> dict[str, Any]:
    root = _napcat_launcher()
    if not root:
        return {
            "key": "napcat",
            "name": "NapCat",
            "status": "missing",
            "detail": "未安装。部署向导会从 GitHub Release 拉到本机 stack\\napcat",
            "path": "",
            "required": True,
        }
    base = paths.STACK_DIR / "napcat"
    size_root = base if base.is_dir() else (root.parent if root.is_file() else root)
    return {
        "key": "napcat",
        "name": "NapCat",
        "status": "ok",
        "detail": f"已就绪（{_dir_size_mb(size_root)} MB）",
        "path": str(root),
        "required": True,
    }


def check_astrbot() -> dict[str, Any]:
    root = _first_existing(ASTRBOT_SEARCH)
    if not root:
        return {
            "key": "astrbot",
            "name": "AstrBot",
            "status": "missing",
            "detail": "未安装。部署向导会克隆仓库并装依赖到 stack\\astrbot",
            "path": "",
            "required": True,
        }
    ver = _astrbot_version(Path(root))
    req = Path(root) / "requirements.txt"
    if not req.exists():
        return {
            "key": "astrbot",
            "name": "AstrBot",
            "status": "warn",
            "detail": "源码不完整，缺 requirements.txt，建议重新部署",
            "path": str(root),
            "required": True,
        }
    from .deploy import venv_python

    if venv_python() is None:
        return {
            "key": "astrbot",
            "name": "AstrBot",
            "status": "warn",
            "detail": f"源码已就位{ver}，依赖还没装，部署向导第 5 步会补上",
            "path": str(root),
            "required": True,
        }
    return {
        "key": "astrbot",
        "name": "AstrBot",
        "status": "ok",
        "detail": f"已就绪{ver}（{_dir_size_mb(Path(root))} MB）",
        "path": str(root),
        "required": True,
    }


def _astrbot_version(root: Path) -> str:
    for name in ("pyproject.toml", "main.py"):
        f = root / name
        if not f.exists():
            continue
        try:
            head = "".join(f.read_text(encoding="utf-8", errors="ignore").splitlines(True)[:40])
        except Exception:
            continue
        m = re.search(r'version\s*=\s*["\']([\w.\-]+)["\']', head)
        if m:
            return " v" + m.group(1)
        m = re.search(r'(?:ASTRBOT_VERSION|__version__)\s*=\s*["\']([\w.\-]+)["\']', head)
        if m:
            return " v" + m.group(1)
    return ""


def check_disk() -> dict[str, Any]:
    try:
        import shutil as sh

        usage = sh.disk_usage(str(paths.ROOT.drive + "\\") if paths.ROOT.drive else "C:\\")
        free_gb = round(usage.free / 1024 ** 3, 1)
        return {
            "key": "disk",
            "name": "磁盘空间",
            "status": "ok" if free_gb >= 3 else "warn",
            "detail": f"剩余 {free_gb} GB" + ("" if free_gb >= 3 else "，建议留 3 GB 以上"),
            "path": str(paths.ROOT),
            "required": False,
        }
    except Exception as e:
        return {
            "key": "disk",
            "name": "磁盘空间",
            "status": "warn",
            "detail": f"读取失败：{e}",
            "path": "",
            "required": False,
        }


_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}


def cached() -> dict[str, Any] | None:
    """只读缓存，不触发探测。启动预热还没跑完时返回 None。"""
    return _CACHE["data"]


def snapshot(force: bool = False, ttl: float = 20.0) -> dict[str, Any]:
    """体检结果带缓存：子进程探测一次要一两秒，界面每次拉 bootstrap 都重跑会卡。

    ``force=True`` 用于「重新体检」按钮。
    """
    import time as _time

    now = _time.monotonic()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < ttl:
        return _CACHE["data"]

    items = [check_python(), check_git(), check_qq(), check_napcat(), check_astrbot(), check_disk()]
    required_missing = [i for i in items if i["required"] and i["status"] == "missing"]
    ready = len(required_missing) == 0
    data = {
        "items": items,
        "ready": ready,
        "missing": [i["key"] for i in required_missing],
        "dataRoot": str(paths.ROOT),
        "ts": int(_time.time()),
    }
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data
