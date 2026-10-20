"""实例管理：一个 QQ 号 = 一个实例，字段与手机版保持一致。"""

from __future__ import annotations

import re
import time
from typing import Any

from . import config, probe

QQ_RE = re.compile(r"^\d{5,12}$")


def list_all() -> list[dict[str, Any]]:
    items = config.get("instances", []) or []
    out = []
    for it in items:
        row = dict(it)
        row["onebotOpen"] = probe.tcp_open(int(row.get("port") or 0))
        row["napcatOpen"] = probe.tcp_open(int(row.get("napcatPort") or 0))
        out.append(row)
    return out


def get(iid: str) -> dict[str, Any] | None:
    for it in config.get("instances", []) or []:
        if it.get("id") == iid:
            return dict(it)
    return None


def _all() -> list[dict[str, Any]]:
    return [dict(x) for x in (config.get("instances", []) or [])]


def _save(items: list[dict[str, Any]]) -> None:
    config.save({"instances": items})


def create(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip() or "新实例"
    qq = str(payload.get("qq") or "").strip()
    if qq and not QQ_RE.match(qq):
        return {"ok": False, "err": "QQ 号应该是 5~12 位数字"}
    items = _all()
    used = {i.get("id") for i in items}
    n = 1
    while f"bot{n}" in used:
        n += 1
    iid = payload.get("id") or f"bot{n}"
    port = int(payload.get("port") or config.get("services.napcat.port", 6199) + len(items))
    item = {
        "id": iid,
        "name": name,
        "qq": qq,
        "token": str(payload.get("token") or "").strip(),
        "port": port,
        "napcatPort": int(payload.get("napcatPort") or config.get("services.napcat.port", 6099)),
        "enabled": bool(payload.get("enabled", True)),
        "createdAt": int(time.time()),
    }
    items.append(item)
    _save(items)
    return {"ok": True, "item": item}


def update(iid: str, payload: dict[str, Any]) -> dict[str, Any]:
    items = _all()
    for i, it in enumerate(items):
        if it.get("id") != iid:
            continue
        if "qq" in payload:
            qq = str(payload.get("qq") or "").strip()
            if qq and not QQ_RE.match(qq):
                return {"ok": False, "err": "QQ 号应该是 5~12 位数字"}
            it["qq"] = qq
        if "name" in payload:
            it["name"] = str(payload.get("name") or "").strip() or it.get("name", "实例")
        if "token" in payload:
            it["token"] = str(payload.get("token") or "").strip()
        if "port" in payload:
            it["port"] = int(payload.get("port") or it.get("port", 6199))
        if "napcatPort" in payload:
            it["napcatPort"] = int(payload.get("napcatPort") or it.get("napcatPort", 6099))
        if "enabled" in payload:
            it["enabled"] = bool(payload.get("enabled"))
        items[i] = it
        _save(items)
        return {"ok": True, "item": it}
    return {"ok": False, "err": "实例不存在"}


def remove(iid: str) -> dict[str, Any]:
    items = _all()
    nxt = [i for i in items if i.get("id") != iid]
    if len(nxt) == len(items):
        return {"ok": False, "err": "实例不存在"}
    _save(nxt)
    return {"ok": True, "remaining": len(nxt)}
