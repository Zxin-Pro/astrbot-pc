"""崩溃与异常记录：服务意外退出、部署失败都记一笔，界面能翻回去看。

只留最近 50 条，同一条 2 分钟内重复出现就合并计数——掉线重连这种循环
不该把列表刷满。
"""

from __future__ import annotations

import time
from typing import Any

from . import config

MAX = 50
_FILE = "crashes.json"


def _load() -> list[dict[str, Any]]:
    data = config.read_state(_FILE, [])
    if isinstance(data, dict):
        data = data.get("items") or []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _save(items: list[dict[str, Any]]) -> None:
    config.write_state(_FILE, items[:MAX])


def record(source: str, summary: str, detail: str = "", key: str = "") -> dict[str, Any]:
    """记一条。source 用于区分来源（service / deploy / app）。"""
    now = int(time.time())
    items = _load()
    if items:
        last = items[0]
        same = last.get("source") == source and last.get("summary") == summary
        if same and now - int(last.get("ts") or 0) < 120:
            last["count"] = int(last.get("count") or 1) + 1
            last["ts"] = now
            if detail:
                last["detail"] = detail[-4000:]
            _save(items)
            return last
    item = {
        "id": f"c{now}-{len(items)}",
        "source": source,
        "key": key,
        "summary": summary,
        "detail": (detail or "")[-4000:],
        "ts": now,
        "count": 1,
    }
    items.insert(0, item)
    _save(items)
    return item


def list_all() -> dict[str, Any]:
    items = _load()
    return {"ok": True, "items": items, "max": MAX, "count": len(items)}


def clear() -> dict[str, Any]:
    items = _load()
    _save([])
    return {"ok": True, "removed": len(items)}


def count_since(seconds: int) -> int:
    cutoff = int(time.time()) - max(0, int(seconds))
    return sum(1 for x in _load() if int(x.get("ts") or 0) >= cutoff)
