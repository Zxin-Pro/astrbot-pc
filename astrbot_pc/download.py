"""带进度、断点续传与解压的下载工具。

部署向导里那两个几百 MB 的包，用 ``urllib`` 裸读会把界面卡成「执行中…」，
所以这里做了三件事：

- 流式读，边读边把 ``received / total / speed`` 回调出去；
- 先写 ``.part``，中断后下次接着传（断网、关窗口都不白下）；
- 解压按 zip 条目逐个放行，遇到路径穿越直接跳过。
"""

from __future__ import annotations

import os
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

CHUNK = 256 * 1024
UA = "AstrBotPC/1.0 (+https://github.com/Zxin-Pro/astrbot-candle)"


class DownloadError(RuntimeError):
    pass


Progress = Callable[[int, int], None]


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def fetch(
    url: str,
    dest: Path,
    on_progress: Progress | None = None,
    *,
    timeout: float = 30.0,
    retries: int = 2,
    resume: bool = True,
) -> Path:
    """把 ``url`` 下到 ``dest``。中途断了会重试，重试用完抛 ``DownloadError``。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if part.exists() and not resume:
        part.unlink()

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            _once(url, part, on_progress, timeout=timeout)
            if dest.exists():
                dest.unlink()
            part.replace(dest)
            return dest
        except Exception as e:  # noqa: BLE001 - 网络错误种类太多，统一重试
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass
    raise DownloadError(f"下载失败：{last_err}")


def _once(url: str, part: Path, on_progress: Progress | None, timeout: float) -> None:
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # 已经下完了
            return
        raise
    with resp:
        status = getattr(resp, "status", 200)
        if have and status != 206:
            have = 0
            part.unlink(missing_ok=True)
        length = int(resp.headers.get("Content-Length") or 0)
        total = have + length if length else 0
        got = have
        if on_progress:
            on_progress(got, total)
        with part.open("ab" if have else "wb") as fh:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if on_progress:
                    on_progress(got, total)
    if not part.exists() or part.stat().st_size == 0:
        raise DownloadError("服务器返回了空文件")


def extract_zip(
    zip_path: Path,
    target: Path,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """解压到 ``target``。压缩包里若只有一层同名目录，会自动剥掉。"""
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.infolist() if not m.is_dir()]
        top = _single_root(members)
        total = len(members)
        base = target.resolve()
        for i, m in enumerate(members, 1):
            name = m.filename
            if top:
                name = name[len(top):].lstrip("/\\")
            if not name:
                continue
            out = (base / name).resolve()
            if base not in out.parents and out != base:
                continue  # 路径穿越，跳过
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst, CHUNK)
            if on_progress:
                on_progress(i, total)
    return target


def _single_root(members: list[zipfile.ZipInfo]) -> str:
    """压缩包里所有文件都在同一个顶层目录下时返回该目录名，否则返回空串。"""
    if not members:
        return ""
    first = members[0].filename.replace("\\", "/").split("/")[0]
    if "/" not in members[0].filename.replace("\\", "/"):
        return ""
    for m in members:
        name = m.filename.replace("\\", "/")
        if not name.startswith(first + "/"):
            return ""
    return first + "/"


def find_dir(root: Path, candidates: tuple[str, ...], depth: int = 2) -> Path | None:
    """在 ``root`` 下找第一个含 ``candidates`` 里某个文件/目录的位置。"""
    root = Path(root)
    if not root.exists():
        return None
    for name in candidates:
        if (root / name).exists():
            return root
    if depth <= 0:
        return None
    try:
        children = [p for p in root.iterdir() if p.is_dir()]
    except OSError:
        return None
    for child in children:
        hit = find_dir(child, candidates, depth - 1)
        if hit:
            return hit
    return None


def dir_size(path: Path, limit: int = 8000) -> int:
    total = 0
    n = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                continue
            n += 1
            if n >= limit:
                return total
    return total
