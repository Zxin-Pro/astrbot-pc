"""资源看板 + 报错解释。

给「概览」页供数据，纯本地、无网络、不依赖前端：

- **资源采样**：每 30 秒采一次本机 CPU / 内存 / 磁盘 / 网络，以及受管进程
  （NapCat、AstrBot）的 CPU 与 RSS，追加到 `state/metrics.json`。
  文件只留最近 2880 条（30 秒 × 2880 = 24 小时），读取时再按时间窗口过滤。
- **报错解释**：从日志尾部挑出报错行，用规则给出中文的「原因 + 怎么修」。
  规则离线跑，不调用任何外部模型，断网也能用。

约定：
- 所有对外函数返回 dict（`history` 例外，直接给数组，方便画 sparkline）；
- 采样失败一律给 0，绝不抛异常——看板不能因为某个计数器读不到就整页白掉；
- 写盘走「临时文件 + os.replace」，读的人永远看不到半截 JSON。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import paths

try:  # psutil 是运行依赖，但没装也得让界面起得来，只是数字全是 0
    import psutil  # type: ignore
except Exception:  # pragma: no cover - 环境问题
    psutil = None  # type: ignore[assignment]

__all__ = [
    "start",
    "stop",
    "running",
    "sample_once",
    "samples",
    "summary",
    "history",
    "errors",
    "explain",
    "explain_log",
    "clear",
]

INTERVAL = 30.0               # 采样间隔（秒）
KEEP = 2880                   # 环形缓冲长度：30 秒 × 2880 ≈ 24 小时
FILE = "metrics.json"         # 落在 STATE_DIR 下
TAIL_LINES = 400              # 每个日志文件只看最后 400 行
TAIL_BYTES = 2 * 1024 * 1024  # 单个日志文件最多读 2 MB

# _LOCK 护住内存缓冲与 metrics.json；_SAMPLE_LOCK 保证同一时刻只有一个人在采样
# （网络计数、进程 CPU 时间的差值是全局状态，并发采样会算出乱七八糟的百分比）。
_LOCK = threading.RLock()
_SAMPLE_LOCK = threading.RLock()

_thread: threading.Thread | None = None
_stop = threading.Event()
_items: list[dict[str, Any]] | None = None   # 内存环形缓冲，None 表示还没从磁盘读过
_net_prev: dict[str, float] = {}             # 上一帧的网络计数，用来算速率
_proc_prev: dict[int, tuple[float, float]] = {}  # pid -> (累计 CPU 秒, 墙钟)，算进程 CPU 用


# ---------------------------------------------------------------- 存储

def _file() -> Path:
    return paths.STATE_DIR / FILE


def _blank(ts: int) -> dict[str, Any]:
    """全 0 的一帧：采不到硬件指标时的兜底，字段与正常帧保持一致。"""
    return {
        "ts": int(ts),
        "cpu": 0.0,
        "mem": {"total": 0, "used": 0, "percent": 0.0},
        "disk": {"total": 0, "used": 0, "free": 0, "percent": 0.0},
        "net": {"sent": 0, "recv": 0, "up": 0, "down": 0},
        "procs": [],
    }


def _load_locked() -> list[dict[str, Any]]:
    """读环形缓冲。调用方必须持有 _LOCK。文件不存在 / 坏了都当空列表。"""
    global _items
    if _items is not None:
        return _items
    raw: Any = []
    try:
        p = _file()
        if p.is_file():
            # utf-8-sig：记事本改过的文件带 BOM 也能读
            raw = json.loads(p.read_text("utf-8-sig"))
    except Exception:
        raw = []
    if isinstance(raw, dict):          # 容忍老格式 {"items": [...]}
        raw = raw.get("items") or []
    if not isinstance(raw, list):
        raw = []
    rows = [x for x in raw if isinstance(x, dict) and isinstance(x.get("ts"), (int, float))]
    rows.sort(key=lambda x: float(x.get("ts") or 0))
    _items = rows[-KEEP:]
    return _items


def _save_locked(rows: list[dict[str, Any]]) -> None:
    """原子落盘：先写 .tmp 再 os.replace。调用方必须持有 _LOCK。"""
    try:
        p = _file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), "utf-8")
        os.replace(tmp, p)
    except Exception:
        pass  # 磁盘满、文件被占用都不该把采样线程带走


# ---------------------------------------------------------------- 采样

def _cpu() -> float:
    """整机 CPU 占用百分比。"""
    if psutil is None:
        return 0.0
    try:
        # interval 用 0.15 秒：非阻塞模式第一次取到的恒为 0.0，看板开头会多一条假低谷
        return round(float(psutil.cpu_percent(interval=0.15)), 1)
    except Exception:
        return 0.0


def _mem() -> dict[str, Any]:
    """物理内存：total / used / percent（字节 + 百分比）。"""
    if psutil is None:
        return {"total": 0, "used": 0, "percent": 0.0}
    try:
        vm = psutil.virtual_memory()
        return {
            "total": int(getattr(vm, "total", 0) or 0),
            "used": int(getattr(vm, "used", 0) or 0),
            "percent": round(float(getattr(vm, "percent", 0.0) or 0.0), 1),
        }
    except Exception:
        return {"total": 0, "used": 0, "percent": 0.0}


def _disk() -> dict[str, Any]:
    """数据目录所在磁盘的占用。"""
    if psutil is None:
        return {"total": 0, "used": 0, "free": 0, "percent": 0.0}
    target = paths.ROOT if paths.ROOT.exists() else Path.home()
    try:
        du = psutil.disk_usage(str(target))
    except Exception:
        return {"total": 0, "used": 0, "free": 0, "percent": 0.0}
    total = int(getattr(du, "total", 0) or 0)
    used = int(getattr(du, "used", 0) or 0)
    free = int(getattr(du, "free", 0) or 0)
    try:
        percent = round(float(getattr(du, "percent", 0.0) or 0.0), 1)
    except Exception:
        percent = round(used * 100.0 / total, 1) if total else 0.0
    return {"total": total, "used": used, "free": free, "percent": percent}


def _net() -> dict[str, Any]:
    """累计收发字节 + 相对上一帧的速率（字节/秒，down 是下载、up 是上传）。"""
    if psutil is None:
        return {"sent": 0, "recv": 0, "up": 0, "down": 0}
    try:
        io = psutil.net_io_counters()
        sent = int(getattr(io, "bytes_sent", 0) or 0)
        recv = int(getattr(io, "bytes_recv", 0) or 0)
    except Exception:
        return {"sent": 0, "recv": 0, "up": 0, "down": 0}
    now = time.monotonic()
    up = down = 0.0
    prev_ts = float(_net_prev.get("ts") or 0)
    if prev_ts > 0:
        dt = now - prev_ts
        if dt > 0:
            # 计数器回绕（换了网卡 / 重启网卡驱动）时会变成负数，按 0 处理
            up = max(0.0, (sent - float(_net_prev.get("sent") or 0)) / dt)
            down = max(0.0, (recv - float(_net_prev.get("recv") or 0)) / dt)
    _net_prev.update({"ts": now, "sent": float(sent), "recv": float(recv)})
    return {"sent": sent, "recv": recv, "up": int(up), "down": int(down)}


def _proc_usage(pid: int) -> tuple[float, int]:
    """返回 (CPU 百分比, RSS 字节)，按进程树（本体 + 子进程）汇总。

    CPU 用「两次采样的 CPU 时间差 / 墙钟差」算：psutil 的 cpu_percent 每次新建
    Process 对象都从 0 开始计，30 秒采一次等于永远读到 0，只有自己记差值才准。
    """
    if not pid or psutil is None:
        return 0.0, 0
    total_cpu = 0.0
    rss = 0
    seen = 0
    try:
        root = psutil.Process(pid)
        procs = [root]
        try:
            procs.extend(root.children(recursive=True))
        except Exception:
            pass
        for proc in procs:  # 子进程可能刚退出，每项单独兜异常
            try:
                times = proc.cpu_times()
                total_cpu += float(getattr(times, "user", 0.0)) + float(getattr(times, "system", 0.0))
                rss += int(proc.memory_info().rss)
                seen += 1
            except Exception:
                continue
    except Exception:
        _proc_prev.pop(pid, None)
        return 0.0, 0
    if not seen:
        _proc_prev.pop(pid, None)
        return 0.0, 0
    now = time.monotonic()
    prev = _proc_prev.get(pid)
    _proc_prev[pid] = (total_cpu, now)
    if not prev:
        return 0.0, rss  # 第一次见到这个 pid，先记基准，下帧才有百分比
    dt = now - prev[1]
    if dt <= 0:
        return 0.0, rss
    percent = (total_cpu - prev[0]) / dt * 100.0
    cores = 0
    try:
        cores = int(psutil.cpu_count() or 0)
    except Exception:
        cores = 0
    ceiling = 100.0 * (cores or 1)  # 多线程进程可以超过 100%，上限是核数 × 100
    percent = max(0.0, min(percent, ceiling))
    return round(percent, 1), rss


def _procs() -> list[dict[str, Any]]:
    """受管进程一栏：从 services.manager 拿状态/端口/PID（惰性 import，避免循环导入）。"""
    rows: list[dict[str, Any]] = []
    live: set[int] = set()
    groups: list[dict[str, Any]] = []
    try:
        from .services import manager

        # 多实例后 status() 只给当前实例，进程列表要遍历所有实例
        groups = manager.status_all()
    except Exception:
        groups = []
    if not groups:
        groups = [{"id": "", "services": {}}]
    for inst in groups:
        sid = str(inst.get("id") or "")
        svc = inst.get("services") or {}
        for key, item in svc.items():
            if not isinstance(item, dict):
                continue
            try:
                pid = int(item.get("pid") or 0)
            except Exception:
                pid = 0
            cpu, rss = _proc_usage(pid)
            if pid:
                live.add(pid)
            rows.append({"role": str(key), "iid": sid, "pid": pid, "cpu": cpu, "rss": rss})
    # 已经停掉 / 换过 pid 的进程别在缓存里越积越多
    for stale in [p for p in _proc_prev if p not in live]:
        _proc_prev.pop(stale, None)
    return rows


def sample_once() -> dict[str, Any]:
    """采一帧、追加进环形缓冲并落盘，返回这一帧。

    Returns:
        含 ts / cpu / mem / disk / net / procs 的 dict，任何一项读不到就给 0。
    """
    global _items
    ts = int(time.time())
    with _SAMPLE_LOCK:
        try:
            sample = {
                "ts": ts,
                "cpu": _cpu(),
                "mem": _mem(),
                "disk": _disk(),
                "net": _net(),
                "procs": _procs(),
            }
        except Exception:
            sample = _blank(ts)
    try:
        with _LOCK:
            rows = list(_load_locked())
            rows.append(sample)
            _items = rows[-KEEP:]
            _save_locked(_items)
    except Exception:
        pass
    return sample


# ---------------------------------------------------------------- 后台线程

def _loop() -> None:
    while not _stop.is_set():
        try:
            sample_once()  # 先采一帧再睡，界面一打开就有数
        except Exception:
            pass
        if _stop.wait(INTERVAL):
            break


def start() -> dict[str, Any]:
    """启动后台采样线程；重复调用是安全的，只有第一次真的起线程。"""
    global _thread
    with _LOCK:
        if _thread is not None and _thread.is_alive():
            return {"ok": True, "running": True, "interval": INTERVAL, "already": True}
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="metrics-sampler", daemon=True)
        _thread.start()
    return {"ok": True, "running": True, "interval": INTERVAL, "already": False}


def stop() -> dict[str, Any]:
    """停掉后台线程（最多等 2 秒），可重复调用。"""
    _stop.set()
    t = _thread
    if t is not None and t.is_alive() and t is not threading.current_thread():
        try:
            t.join(timeout=2.0)
        except Exception:
            pass
    return {"ok": True, "running": running()}


def running() -> bool:
    """采样线程是否在跑。"""
    t = _thread
    return bool(t is not None and t.is_alive())


# ---------------------------------------------------------------- 读历史

def _window(hours: float) -> list[dict[str, Any]]:
    """取最近 hours 小时内的样本，按时间升序。hours <= 0 表示不限。"""
    try:
        h = float(hours)
    except Exception:
        h = 24.0
    with _LOCK:
        rows = list(_load_locked())
    if h > 0:
        cutoff = time.time() - h * 3600.0
        rows = [x for x in rows if float(x.get("ts") or 0) >= cutoff]
    rows.sort(key=lambda x: float(x.get("ts") or 0))
    return rows


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """窗口内的 CPU / 内存聚合。points 是参与统计的原始样本数。"""
    cpus: list[float] = []
    mems: list[float] = []
    for x in rows:
        try:
            cpus.append(float(x.get("cpu") or 0.0))
        except Exception:
            cpus.append(0.0)
        mem = x.get("mem") if isinstance(x.get("mem"), dict) else {}
        try:
            mems.append(float((mem or {}).get("percent") or 0.0))
        except Exception:
            mems.append(0.0)
    n = len(rows)
    return {
        "cpuAvg": round(sum(cpus) / n, 1) if n else 0.0,
        "cpuMax": round(max(cpus), 1) if cpus else 0.0,
        "memAvg": round(sum(mems) / n, 1) if n else 0.0,
        "memMax": round(max(mems), 1) if mems else 0.0,
        "points": n,
    }


def _thin(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """超过 limit 条就等距抽稀（首尾必留），这样 24 小时也能塞进一张图。"""
    n = len(rows)
    if limit <= 0 or n <= limit:
        return rows
    if limit == 1:
        return [rows[-1]]
    step = (n - 1) / float(limit - 1)
    idx = sorted({int(round(i * step)) for i in range(limit)})
    return [rows[i] for i in idx]


def samples(hours: float = 24, limit: int = 720) -> dict[str, Any]:
    """看板主数据：窗口内的样本 + 最新一帧 + 聚合。

    Args:
        hours: 往前看多少小时，默认 24。
        limit: 返回条数上限，默认 720；超出时等距抽稀（summary 仍按完整窗口统计）。

    Returns:
        {"ok": True, "items": [...], "latest": {...} | None, "summary": {...}, "ts": 时间戳}
    """
    try:
        lim = int(limit)
    except Exception:
        lim = 720
    rows = _window(hours)
    latest = rows[-1] if rows else None
    return {
        "ok": True,
        "items": _thin(rows, lim),
        "latest": latest,
        "summary": _aggregate(rows),
        "ts": int(time.time()),
    }


def summary() -> dict[str, Any]:
    """概览页顶部卡片：最新一帧 + 24 小时聚合 + 今日重启 / 错误数。"""
    rows = _window(24)
    latest = rows[-1] if rows else None
    today: dict[str, Any] = {"restarts": 0, "errors": 0, "warns": 0, "messages": 0, "onlineSec": 0}
    try:
        from . import stats  # 惰性 import：统计模块自己也要读 state，没必要互相拖累

        data = stats.today() or {}
        today = {
            "restarts": int(data.get("restarts") or 0),
            "errors": int(data.get("errors") or 0),
            "warns": int(data.get("warns") or 0),
            "messages": int(data.get("messages") or 0),
            "onlineSec": int(data.get("onlineSec") or 0),
            "onlineText": str(data.get("onlineText") or ""),
        }
    except Exception:
        pass  # 今日统计读不出来不影响看板
    return {
        "ok": True,
        "latest": latest,
        "summary": _aggregate(rows),
        "today": today,
        "running": running(),
        "ts": int(time.time()),
    }


def history(hours: float = 1) -> list[dict[str, Any]]:
    """给前端画 sparkline 的轻量序列：[{ts, cpu, mem}]，按时间升序。

    只带 ts / cpu / mem 三个数，比 samples() 小一个数量级；点数超过 720 会抽稀。
    """
    out: list[dict[str, Any]] = []
    for x in _thin(_window(hours), 720):
        try:
            mem = x.get("mem") if isinstance(x.get("mem"), dict) else {}
            out.append({
                "ts": int(x.get("ts") or 0),
                "cpu": round(float(x.get("cpu") or 0.0), 1),
                "mem": round(float((mem or {}).get("percent") or 0.0), 1),
            })
        except Exception:
            continue
    return out


def clear() -> dict[str, Any]:
    """清空历史（文件保留，内容写成 []）。"""
    global _items
    with _LOCK:
        try:
            n = len(_load_locked())
        except Exception:
            n = 0
        _items = []
        _save_locked([])
    return {"ok": True, "removed": n}


# ---------------------------------------------------------------- 日志里的报错

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ERROR_RE = re.compile(r"\b(?:error|critical|traceback|exception)\b|错误|异常|失败", re.I)
_DATE_TS = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[ T](\d{1,2}):(\d{2}):(\d{2})")
_TIME_TS = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})")
_HEAD_DATE = re.compile(r"^[\s\[\(]*\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}:\d{2}[.,]?\d*[\s\]\)]*")
_HEAD_TIME = re.compile(r"^[\s\[\(]*\d{1,2}:\d{2}:\d{2}[.,]?\d*[\s\]\)]*")
_WS = re.compile(r"\s+")


def _clean_line(line: str) -> str:
    """去掉 ANSI 颜色、NUL 和行尾换行——日志里这两样最常见。"""
    text = _ANSI.sub("", str(line or ""))
    return text.replace("\x00", "").rstrip("\r\n")


def _clip(line: str, n: int = 600) -> str:
    """单行太长（比如整段 JSON）就截断，别让接口响应爆掉。"""
    text = (line or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _dedup_key(line: str) -> str:
    """去重用的键：掐掉行首时间戳，同一条报错刷屏时只留最新一次。"""
    text = _HEAD_DATE.sub("", line or "")
    text = _HEAD_TIME.sub("", text)
    return _WS.sub(" ", text).strip()[:300]


def _level_of(line: str) -> str:
    """报错级别。UI 只认 error / warn，CRITICAL 也归到 error。"""
    low = (line or "").lower()
    if "critical" in low or "fatal" in low or "严重" in (line or ""):
        return "error"
    if "warn" in low or "警告" in (line or ""):
        return "warn"
    return "error"


def _parse_ts(line: str, default: float) -> int:
    """从日志行里抠时间戳；抠不到就用调用方给的兜底值（一般是文件 mtime）。"""
    hit = _DATE_TS.search(line or "")
    if hit:
        try:
            return int(time.mktime((
                int(hit.group(1)), int(hit.group(2)), int(hit.group(3)),
                int(hit.group(4)), int(hit.group(5)), int(hit.group(6)), 0, 0, -1,
            )))
        except (ValueError, OverflowError):
            pass
    hit = _TIME_TS.search(line or "")
    if hit:
        now = time.localtime()
        try:
            ts = int(time.mktime((
                now.tm_year, now.tm_mon, now.tm_mday,
                int(hit.group(1)), int(hit.group(2)), int(hit.group(3)), 0, 0, -1,
            )))
            # 日志只有「时:分:秒」时，凌晨 0 点刚过看到的 23:59 属于昨天
            if ts > int(time.time()) + 3600:
                ts -= 86400
            return ts
        except (ValueError, OverflowError):
            pass
    return int(default)


def _read_tail(p: Path, max_lines: int = TAIL_LINES, max_bytes: int = TAIL_BYTES) -> list[str]:
    """读文件尾部若干行，最多读 max_bytes 字节（日志可能几十 MB）。"""
    try:
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > max_bytes:
                fh.seek(-max_bytes, os.SEEK_END)
                raw = fh.read()
                cut = raw.find(b"\n")
                if cut >= 0:  # 丢掉被截断的半行
                    raw = raw[cut + 1:]
            else:
                raw = fh.read()
    except Exception:
        return []
    return raw.decode("utf-8", "replace").splitlines()[-max_lines:]


def _error_files() -> list[Path]:
    """要扫的日志：LOG_DIR 下所有 *.log + 每个实例的 AstrBot 日志。"""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            if not p.is_file():
                return
            key = str(p.resolve()).lower()
        except Exception:
            return
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    try:
        for p in sorted(paths.LOG_DIR.glob("*.log")):
            add(p)
    except Exception:
        pass
    try:
        from . import runtime  # 惰性 import：实例模块会读配置，避免导入期互相牵扯

        for inst in runtime.instances():
            iid = str(inst.get("id") or "")
            if not iid:
                continue
            try:
                add(runtime.astrbot_log(iid))
            except Exception:
                continue
    except Exception:
        pass
    return out


def errors(limit: int = 30) -> dict[str, Any]:
    """最近报错：扫日志尾部，按时间倒序，同样的报错只留最新一条。

    Returns:
        {"ok": True, "items": [{"ts", "level", "line", "source", "path"}], "count": n}
    """
    try:
        lim = int(limit)
    except Exception:
        lim = 30
    lim = max(0, lim)
    if lim == 0:
        return {"ok": True, "items": [], "count": 0}
    now = int(time.time())
    found: list[dict[str, Any]] = []
    for p in _error_files():
        try:
            mtime = int(p.stat().st_mtime)
        except Exception:
            mtime = now
        lines = _read_tail(p)
        total = len(lines)
        for idx, raw in enumerate(lines):
            line = _clean_line(raw)
            if not line or not _ERROR_RE.search(line):
                continue
            # 没有时间戳的行按 mtime 往前推，越靠后的行越新，排序才不会乱
            ts = _parse_ts(line, default=mtime - (total - idx))
            if ts > now + 300:
                ts = now
            found.append({
                "ts": ts,
                "level": _level_of(line),
                "line": _clip(line),
                "source": p.name,
                "path": str(p),
            })
    found.sort(key=lambda x: int(x.get("ts") or 0), reverse=True)
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in found:
        key = (str(item.get("source") or ""), _dedup_key(str(item.get("line") or "")))
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= lim:
            break
    return {"ok": True, "items": items, "count": len(items)}


# ---------------------------------------------------------------- 报错解释（规则）

# 顺序有讲究：越具体的规则越靠前，通用的放最后。
_RULES: list[tuple[re.Pattern[str], str, str, str, str]] = [
    (
        re.compile(r"address already in use|eaddrinuse|winerror\s*10048|"
                   r"only one usage of each socket address|端口.{0,8}(?:被占用|占用|冲突)", re.I),
        "端口被占用，服务起不来",
        "这个端口已经有别的程序在监听了。最常见的是上一次的 NapCat / AstrBot 没退干净还挂在后台，"
        "或者控制台与手机版同时抢同一个端口。",
        "① 到「服务」页把两个服务都停掉再启动；② 还不行就开任务管理器结束残留的 NapCat.exe / python.exe；"
        "③ 想立刻确认是谁占的：命令提示符里跑 netstat -ano | findstr :6185，最后一列就是 PID；"
        "④ 实在冲突就在「设置」里给这个服务换一个端口。",
        "error",
    ),
    (
        re.compile(r"\b401\b|unauthori[sz]ed|invalid[ _-]?api[ _-]?key|incorrect api key|"
                   r"authentication (?:failed|error)|api[ _-]?key.{0,16}(?:invalid|无效|错误|缺失)|密钥|令牌", re.I),
        "API Key 无效或没有权限（401）",
        "模型服务（或中转站）拒绝了这次请求：Key 填错、被停用、余额/额度用完，或者账号没有这个模型的权限。"
        "401 只说明「身份没通过」，跟网络无关。",
        "① 到「模型」页重新粘贴 API Key，注意别把引号、空格、换行一起复制进去；"
        "② 确认接口地址是中转站给的 /v1 地址（例如 https://worldcodes.online/v1）；③ 点「测一下」看返回；"
        "④ 还报 401 就登录中转站后台看这个 Key 是不是被停用或欠费了。",
        "error",
    ),
    (
        re.compile(r"\b429\b|rate[ _-]?limit|too many requests|请求.{0,6}(?:过于频繁|过多)|限流", re.I),
        "请求太频繁，被限流了（429）",
        "上游在限速：短时间内请求太多、并发超了套餐额度，或者这个 Key 正被别处一起用。一般等一会儿自己会好。",
        "① 等 30~60 秒再试；② 少开几个实例，或先停掉正在刷屏的插件；"
        "③ 经常这样就是额度不够，换更高的套餐 / Key，或在「模型」里把请求频率降下来。",
        "warn",
    ),
    (
        re.compile(r"timed?\s*out|timeout|超时|etimedout|deadline exceeded", re.I),
        "请求超时",
        "等对方回应等超时了：网速慢、代理/加速没生效、对方服务卡住，或者国内直连海外网关。"
        "下载依赖时超时，多半是镜像没走对。",
        "① 到「排障」页点一次体检看看网络；② 在「设置」里打开下载加速或填代理；"
        "③ 模型请求超时就先换个中转站 / 模型试试；④ 下载卡住就重试一次，国内直连 GitHub 本来就容易超时。",
        "warn",
    ),
    (
        re.compile(r"modulenotfounderror|no module named", re.I),
        "缺少 Python 依赖",
        "启动时找不到某个模块：依赖没装、装进了另一个 Python 环境，或者虚拟环境没生效。"
        "日志里 No module named 'xxx' 的 xxx 就是缺的那个包。",
        "① 到「部署」页重跑一次依赖安装；② 确认 AstrBot 用的是 stack/.venv 里的解释器；"
        "③ 手动补装：在 AstrBot 目录执行 .venv\\Scripts\\python.exe -m pip install xxx（xxx 换成日志里的包名）；"
        "④ 装完重启服务。",
        "error",
    ),
    (
        re.compile(r"importerror|cannot import name|dll load failed|undefined symbol", re.I),
        "导入模块失败",
        "包在，但导入时报错：版本对不上、缺 DLL（Windows 上常见于 torch / pillow / cryptography），"
        "或者目录里有同名文件把包盖住了。",
        "① 按日志里的包名重装：pip install -U 包名；② 装一遍微软 VC++ 运行库；"
        "③ 检查 AstrBot 目录里有没有和包同名的 .py 文件；④ 还不行在「部署」里重装依赖。",
        "error",
    ),
    (
        re.compile(r"permissionerror|access is denied|winerror\s*5\b|拒绝访问|权限不足|eacces|"
                   r"operation not permitted", re.I),
        "没有权限访问",
        "要读写的文件或目录被挡住了：被杀毒软件锁着、装在 C:\\Program Files 这类需要管理员的地方，"
        "或者文件是只读属性。",
        "① 把数据目录（默认 %LOCALAPPDATA%\\AstrBotPC）加进杀毒软件白名单；"
        "② 确认程序没装在需要管理员权限的目录；③ 右键以管理员身份运行一次控制台；"
        "④ 看看那个文件是不是正被记事本 / 编辑器占着。",
        "error",
    ),
    (
        re.compile(r"filenotfounderror|no such file or directory|找不到文件|系统找不到指定的(?:文件|路径)|"
                   r"winerror\s*[23]\b|cannot find the path", re.I),
        "文件或目录不存在",
        "要用的文件被删了、挪了，或者路径拼错。常见于手动清理过 stack 目录、实例目录没建好、"
        "配置里写了不存在的路径。",
        "① 照日志里的路径去资源管理器看一眼；② 到「部署」页重跑安装，缺的文件会补回来；"
        "③ 实例目录缺失就去「实例」页重建；④ 自己改过配置的话，把路径改回实际位置。",
        "error",
    ),
    (
        re.compile(r"database is locked|database table is locked|database is busy|"
                   r"sqlite.{0,30}(?:locked|busy)|sqlite3\.operationalerror", re.I),
        "数据库被锁住了",
        "SQLite 同一时刻只允许一个写入者。同一个实例被启动了两份、插件在长事务里没提交，"
        "或者上一次的进程还没退干净，都会报 database is locked。",
        "① 任务管理器里看有没有多个 python.exe 在跑同一个实例，全部结束再启动；"
        "② 到「服务」页重启一次；③ 频繁出现就先停服务，备份 data_v4.db 再启动；"
        "④ 别把数据目录放在网盘 / 共享盘上。",
        "warn",
    ),
    (
        re.compile(r"websocket|连接被拒绝|connection refused|winerror\s*10061|econnrefused|"
                   r"could not connect|连接失败|无法连接|积极拒绝|connection reset|连接被重置", re.I),
        "连接被拒绝",
        "要连的端口上没有服务在监听：NapCat 或 AstrBot 没起来、OneBot 反向 WS 地址/端口填错，"
        "或者被防火墙挡了。",
        "① 到「服务」页确认 NapCat 与 AstrBot 都是「运行中」；"
        "② 核对 OneBot 反向 WS 地址（默认 ws://127.0.0.1:6199/ws）与 NapCat 配置里的端口是否一致；"
        "③ 两边都重启一次重新握手；④ 还不行就到「日志」页看另一侧的日志。",
        "error",
    ),
    (
        re.compile(r"\bcuda\b|out of memory|内存不足|显存|memoryerror|not enough memory|\boom\b", re.I),
        "内存 / 显存不够",
        "一次性要的内存超过了可用量：模型太大、图片/语音任务并发太多，或者机器本身内存就小。"
        "带 CUDA 的是显卡显存不够。",
        "① 关掉不用的程序，给 AstrBot 腾内存；② 换小一点的模型或降低并发；"
        "③ 显存不够就在模型配置里关掉本地 GPU 推理，改用 API；④ 长期吃紧就加内存条。",
        "error",
    ),
    (
        re.compile(r"requires? python|python_requires|unsupported python|python\s*版本|python版本|"
                   r"版本过低|venv|virtualenv|虚拟环境", re.I),
        "Python 版本或虚拟环境不对",
        "AstrBot 需要 Python 3.10 及以上；当前解释器太老，或者依赖装在系统 Python 里、实际跑的却是另一个 venv。",
        "① 到「排障」页看体检里的 Python 版本，低于 3.10 就装新版；② 到「部署」页重建 .venv 并重装依赖；"
        "③ 别把系统 Python 和 .venv 的包混着用；④ 重建后重启服务。",
        "error",
    ),
    (
        re.compile(r"ssl|certificate verify|证书|tls handshake", re.I),
        "HTTPS 证书校验失败",
        "对方证书过期 / 自签名，或者本机时间不对、代理在做中间人。公司网络和用了代理时很常见。",
        "① 校准系统时间；② 关掉或换一个代理；③ 用浏览器打开那个地址确认证书正常；"
        "④ 内网自签证书就把它导入系统信任区。",
        "warn",
    ),
]

_GENERIC = (
    "暂时没归类的问题",
    "这条日志没命中常见错误特征，得看上下文才能判断——真正的报错通常在上一行或下面的 Traceback 里。",
    "① 在「日志」页点这一行看前后几行；② 把完整报错发到群里问；③ 不确定就先重启对应服务试试。",
    "error",
)


def explain(text: str) -> dict[str, Any]:
    """给一段报错文本一个中文解释（纯规则，不联网、不调模型）。

    Returns:
        {"ok": True, "title", "reason", "fix", "level"}，level 取 error / warn / info。
    """
    raw = str(text or "").strip()
    if not raw:
        return {
            "ok": True,
            "title": "没有可解释的内容",
            "reason": "传进来的日志是空的。",
            "fix": "在「日志」页选中一条报错再点解释。",
            "level": "info",
        }
    probe = raw[:4000]  # 规则只看前 4000 字，避免超长堆栈拖慢匹配
    for rx, title, reason, fix, level in _RULES:
        if rx.search(probe):
            return {"ok": True, "title": title, "reason": reason, "fix": fix, "level": level}
    title, reason, fix, level = _GENERIC
    return {"ok": True, "title": title, "reason": reason, "fix": fix, "level": level}


def _allowed_log(raw: str) -> Path | None:
    """只允许解释 LOG_DIR 或 ROOT/instances 下的文件（resolve 后比前缀，防 ../ 穿越）。"""
    try:
        p = Path(str(raw or "")).resolve()
        target = os.path.normcase(str(p))
    except Exception:
        return None
    for root in (paths.LOG_DIR, paths.INSTANCES_DIR):
        try:
            base = os.path.normcase(str(Path(root).resolve()))
        except Exception:
            continue
        if target == base or target.startswith(base + os.sep):
            return p
    return None


def explain_log(path: str, line_no: int = 1) -> dict[str, Any]:
    """解释某条日志的某一行，附带 ±3 行上下文。

    Args:
        path: 日志文件路径，必须落在 paths.LOG_DIR 或 ROOT/instances 下。
        line_no: 行号，从 1 开始。

    Returns:
        explain(text) 的全部字段 + {"path", "lineNo", "line", "context"}；
        路径越界 / 文件不存在 / 行号越界返回 {"ok": False, "err": ...}。
    """
    p = _allowed_log(path)
    if p is None:
        return {"ok": False, "err": "只能解释日志目录或实例目录下的文件"}
    try:
        if not p.is_file():
            return {"ok": False, "err": "日志文件不存在"}
    except Exception:
        return {"ok": False, "err": "日志文件不存在"}
    try:
        no = int(line_no)
    except Exception:
        return {"ok": False, "err": "行号必须是整数"}
    if no < 1:
        return {"ok": False, "err": "行号从 1 开始"}
    start = max(1, no - 3)
    end = no + 3
    buf: list[str] = []
    last = 0
    try:
        # 逐行读、读到目标行就停：几十 MB 的日志也不用整个进内存
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for idx, raw in enumerate(fh, 1):
                if idx > end:
                    break
                last = idx
                if idx >= start:
                    buf.append(_clean_line(raw))
    except Exception as e:
        return {"ok": False, "err": f"读取失败：{e}"}
    offset = no - start
    if offset >= len(buf):
        if last <= 0:
            return {"ok": False, "err": "日志文件是空的"}
        return {"ok": False, "err": f"文件只有 {last} 行，没有第 {no} 行"}
    text = buf[offset]
    out = explain(text)
    out.update({"path": str(p), "lineNo": no, "line": text, "context": buf})
    return out
