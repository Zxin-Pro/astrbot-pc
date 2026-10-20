"""今日数据：在线时长、消息量、异常数、重启次数、流量。

数字来源分两层：
- 进程层由守护线程每 2 秒 tick 一次累加在线时长与重启次数；
- 行为层由日志跟随器见到关键行时 note 一下，避免去猜 AstrBot 的内部结构。
所有计数都落到 ``state/stats-YYYY-MM-DD.json``，跨天自动换文件，历史保留 30 天。
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from . import config, paths

HISTORY_DAYS = 30


def _day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts if ts is not None else time.time()))


def _file(day: str):
    return paths.state_file(f"stats-{day}.json")


def _blank(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "onlineSec": 0,
        "messages": 0,
        "errors": 0,
        "warns": 0,
        "restarts": 0,
        "bytes": 0,
        "hours": {},
    }


def _read(day: str | None = None) -> dict[str, Any]:
    day = day or _day()
    data = config.read_state(f"stats-{day}.json", None)
    if not isinstance(data, dict):
        return _blank(day)
    base = _blank(day)
    base.update({k: v for k, v in data.items() if k in base})
    if not isinstance(base.get("hours"), dict):
        base["hours"] = {}
    return base


def _write(data: dict[str, Any]) -> None:
    config.write_state(f"stats-{data['date']}.json", data)


def tick(online: bool, restarts: int = 0) -> None:
    """守护线程调用：累加在线时长与重启次数。"""
    data = _read()
    if online:
        data["onlineSec"] = int(data.get("onlineSec", 0)) + 2
    if restarts:
        data["restarts"] = int(data.get("restarts", 0)) + int(restarts)
    _write(data)


def note(kind: str, n: int = 1, size: int = 0) -> None:
    """日志跟随器调用：记一次消息 / 异常 / 告警。"""
    data = _read()
    key = {"message": "messages", "error": "errors", "warn": "warns"}.get(kind)
    hour = time.strftime("%H", time.localtime())
    bucket = data["hours"].get(hour) or {"m": 0, "e": 0}
    if key:
        data[key] = int(data.get(key, 0)) + n
        if key == "messages":
            bucket["m"] = int(bucket.get("m", 0)) + n
        if key == "errors":
            bucket["e"] = int(bucket.get("e", 0)) + n
    if size:
        data["bytes"] = int(data.get("bytes", 0)) + int(size)
    data["hours"][hour] = bucket
    _write(data)


def today() -> dict[str, Any]:
    d = _read()
    d["onlineText"] = _hms(int(d.get("onlineSec", 0)))
    d["bytesText"] = _bytes(int(d.get("bytes", 0)))
    return d


def series(hours: int = 24) -> list[dict[str, Any]]:
    d = _read()
    now_h = int(time.strftime("%H", time.localtime()))
    out = []
    for i in range(hours - 1, -1, -1):
        h = (now_h - i) % 24
        bucket = d["hours"].get(f"{h:02d}") or {}
        out.append({"hour": f"{h:02d}:00", "m": int(bucket.get("m", 0)), "e": int(bucket.get("e", 0))})
    return out


def trend(days: int = 7) -> list[dict[str, Any]]:
    out = []
    for i in range(days - 1, -1, -1):
        ts = time.time() - i * 86400
        day = _day(ts)
        d = _read(day)
        out.append({
            "date": day,
            "label": time.strftime("%m-%d", time.localtime(ts)),
            "onlineSec": int(d.get("onlineSec", 0)),
            "messages": int(d.get("messages", 0)),
            "errors": int(d.get("errors", 0)),
        })
    return out


def overview(services: dict[str, Any]) -> dict[str, Any]:
    d = today()
    arr = list(services.values())
    running = [s for s in arr if s.get("status") == "running"]
    health = "ok"
    if not running:
        health = "down"
    elif any(s.get("status") in ("crashed", "blocked") for s in arr):
        health = "warn"
    elif len(running) < len(arr):
        health = "warn"
    return {
        "today": d,
        "trend": trend(7),
        "series": series(24),
        "health": health,
        "running": len(running),
        "total": len(arr),
        "ts": int(time.time()),
    }


def _hms(sec: int) -> str:
    sec = max(0, int(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h} 小时 {m} 分"
    if m:
        return f"{m} 分 {s} 秒"
    return f"{s} 秒"


def _bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    v = float(max(0, n))
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.0f} {u}" if u == "B" else f"{v:.1f} {u}"
        v /= 1024
    return f"{v:.1f} GB"
