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
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlsplit

CHUNK = 256 * 1024
UA = "AstrBotPC/1.0 (+https://github.com/Zxin-Pro/astrbot-candle)"

#: 这么久一个字节都没进来，就当这个下载源废了，换下一个（还能续传）
STALL_TIMEOUT = 20.0
#: 所有源轮流试几轮再放弃
MAX_ROUNDS = 3

#: 国内直连 GitHub 经常是 TLS 握手卡死、DNS 解析几十秒，套一层加速代理能救回来。
#: 顺序无所谓——真正用哪个由 :func:`pick_source` 并发探测决定。
ACCEL: tuple[str, ...] = (
    "https://gh-proxy.com/{}",
    "https://ghfast.top/{}",
    "https://ghproxy.net/{}",
)


class DownloadError(RuntimeError):
    pass


Progress = Callable[[int, int], None]


def candidates(url: str, accel: bool = True) -> list[str]:
    """把一个直链补成「直连 + 若干加速镜像」的候选列表。"""
    urls = [url]
    if accel:
        urls += [pat.format(url) for pat in ACCEL]
    return urls


def pick_source(urls: Sequence[str], *, timeout: float = 8.0, sample: float = 2.0) -> str | None:
    """并发量一下各源的实际下载速度，返回下载最快的那一个。

    不能用「谁先回应用谁」——镜像之间速度能差几十倍（实测同一时间 190 KB/s 和
    9.6 MB/s 并存），先回应的那个往往不是最快的。所以每个源各读两秒，比字节数。

    这里的超时管不住 DNS（``getaddrinfo`` 不受 socket 超时约束），所以只能并发
    发出去、等到总时限为止；探测线程都是 daemon，不等它们也不会把进程拖住。
    """
    urls = [u for u in urls if u]
    if not urls:
        return None
    if len(urls) == 1:
        return urls[0]

    scores: dict[str, int] = {}
    lock = threading.Lock()

    def probe(u: str) -> None:
        got = 0
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Range": "bytes=0-8388607"})
            with urllib.request.urlopen(req, timeout=min(timeout, sample + 2.5)) as resp:
                begun = time.monotonic()
                while time.monotonic() - begun < sample:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    got += len(chunk)
        except Exception:
            got = 0
        with lock:
            scores[u] = got

    threads = [threading.Thread(target=probe, args=(u,), daemon=True, name="probe") for u in urls]
    for t in threads:
        t.start()
    # 不等慢的：够 sample 秒就收工，卡在 DNS 上的源不该拖着整个人等
    deadline = time.monotonic() + sample + 4.0
    while time.monotonic() < deadline:
        with lock:
            if len(scores) == len(urls):
                break
            # 已经有人量出速度了就别再等剩下的
            if any(v > 0 for v in scores.values()):
                break
        time.sleep(0.05)

    with lock:
        best = max(scores.items(), key=lambda kv: kv[1], default=(None, 0))
    if best[0] and best[1] > 0:
        return best[0]
    return None


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def fetch(
    url: str | Sequence[str],
    dest: Path,
    on_progress: Progress | None = None,
    *,
    timeout: float = 30.0,
    retries: int = 2,
    resume: bool = True,
    stall_timeout: float = STALL_TIMEOUT,
) -> Path:
    """把 ``url`` 下到 ``dest``。中途断了会换源接着传，全都不行才抛 ``DownloadError``。

    ``url`` 可以是一串候选地址。换源时 ``.part`` 是留着的——同一个文件从另一个
    镜像用 ``Range`` 续传，省得几百 MB 从头再来。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if part.exists() and not resume:
        part.unlink()

    if isinstance(url, str):
        pool = [url]
    else:
        pool = [u for u in url if u]
    if not pool:
        raise DownloadError("下载失败：没有可用的下载地址")

    if len(pool) > 1:
        # 直连 GitHub 在国内常常先卡十几秒才失败，别让用户干等：先并发探一下，
        # 把真能读数据的源提到最前面。
        best = pick_source(pool, timeout=min(timeout, 10.0))
        if best:
            pool = [best] + [u for u in pool if u != best]

    errors: list[str] = []
    for _round in range(MAX_ROUNDS):
        for candidate in pool:
            for attempt in range(retries + 1):
                try:
                    expected = _once(candidate, part, on_progress, timeout, stall_timeout)
                except _AlreadyComplete as done:
                    expected = done.have
                except Exception as e:  # noqa: BLE001 - 网络错误种类太多，统一重试
                    errors.append(f"{_host(candidate)}: {_brief(e)}")
                    if attempt < retries:
                        time.sleep(1.0 * (attempt + 1))
                    continue
                have = part.stat().st_size if part.exists() else 0
                if expected and have < expected:
                    # 连接断了但没报错——不校验就会把半截包当成功装上去
                    errors.append(f"{_host(candidate)}: 只拿到 {have}/{expected} 字节")
                    if attempt < retries:
                        time.sleep(1.0 * (attempt + 1))
                    continue
                if dest.exists():
                    dest.unlink()
                part.replace(dest)
                return dest

    if part.exists():
        try:
            part.unlink()
        except OSError:
            pass
    raise DownloadError("下载失败：" + "；".join(errors[-3:]) if errors else "下载失败")


class _AlreadyComplete(Exception):
    def __init__(self, have: int) -> None:
        self.have = have


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc or url[:24]
    except Exception:
        return url[:24]


def _brief(err: Exception) -> str:
    text = str(err) or type(err).__name__
    return text[:80]


def _once(
    url: str,
    part: Path,
    on_progress: Progress | None,
    timeout: float,
    stall_timeout: float,
) -> int:
    """传一趟，返回期望的总字节数（拿不到 Content-Length 就返回 0）。"""
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        if e.code == 416:  # 已经下完了
            raise _AlreadyComplete(have) from None
        raise
    with resp:
        status = getattr(resp, "status", 200)
        if have and status != 206:
            have = 0
            part.unlink(missing_ok=True)
        length = int(resp.headers.get("Content-Length") or 0)
        expected = have + length if length else 0
        got = have
        if on_progress:
            on_progress(got, expected)
        marker = time.monotonic()
        with part.open("ab" if have else "wb") as fh:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if on_progress:
                    on_progress(got, expected)
                now = time.monotonic()
                # 代理经常是「没断，但几十分钟不动」，socket 超时管不到这种：
                # 自己盯着两次收到数据的间隔，太久不动就当这个源废了。
                if now - marker > stall_timeout:
                    raise DownloadError(f"{stall_timeout:.0f} 秒没有新数据")
                marker = now
    if not part.exists() or part.stat().st_size == 0:
        raise DownloadError("服务器返回了空文件")
    return expected
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
