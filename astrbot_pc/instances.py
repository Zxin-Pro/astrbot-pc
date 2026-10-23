"""实例管理：一个 QQ 号 = 一个实例，字段与手机版保持一致。

一台机器上 NapCat 与 AstrBot 仍然只有一对进程，所以「实例」在 PC 端的定位是
账号档案 + 一键接线：切换当前实例后，把它的端口和令牌写进 NapCat 与 AstrBot
的配置，再重启两个服务即可换号。
"""

from __future__ import annotations

import re
import socket
import time
from typing import Any

from . import config, probe

QQ_RE = re.compile(r"^\d{5,12}$")


def list_all() -> list[dict[str, Any]]:
    items = config.get("instances", []) or []
    aid = active_id()
    out = []
    for it in items:
        row = dict(it)
        row["onebotOpen"] = probe.tcp_open(int(row.get("port") or 0))
        row["napcatOpen"] = probe.tcp_open(int(row.get("napcatPort") or 0))
        row["active"] = bool(aid) and row.get("id") == aid
        out.append(row)
    return out


def get(iid: str) -> dict[str, Any] | None:
    for it in config.get("instances", []) or []:
        if it.get("id") == iid:
            return dict(it)
    return None


def active_id() -> str:
    aid = str(config.get("app.activeInstance") or "")
    items = config.get("instances", []) or []
    if aid and any(i.get("id") == aid for i in items):
        return aid
    for it in items:
        if it.get("enabled", True):
            return str(it.get("id") or "")
    return str(items[0].get("id") or "") if items else ""


def active() -> dict[str, Any]:
    """当前实例；一个都没有时给一份默认值，部署向导才好写配置。"""
    aid = active_id()
    if aid:
        hit = get(aid)
        if hit:
            return hit
    return {"id": "bot1", "name": "主账号", "qq": "", "token": "", "enabled": True}


def set_active(iid: str) -> dict[str, Any]:
    if not get(iid):
        return {"ok": False, "err": "实例不存在"}
    config.save({"app": {"activeInstance": iid}})
    return {"ok": True, "active": iid}


def apply(iid: str) -> dict[str, Any]:
    """切换当前实例并把接线写进两个配置文件（不自动重启服务）。"""
    if not get(iid):
        return {"ok": False, "err": "实例不存在"}
    config.save({"app": {"activeInstance": iid}})
    from . import deploy

    ok, detail = deploy.write_wiring(active(), False)
    if not ok:
        return {"ok": False, "err": detail}
    return {
        "ok": True,
        "detail": detail,
        "needsRestart": True,
        "instance": active(),
    }


def _all() -> list[dict[str, Any]]:
    return [dict(x) for x in (config.get("instances", []) or [])]


def _save(items: list[dict[str, Any]]) -> None:
    config.save({"instances": items})


def _free(start: int, taken: set[int] | None = None) -> int:
    """从 start 往后找一个能 bind 的端口。"""
    taken = taken or set()
    for port in range(start, start + 200):
        if port in taken or port > 65535:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    return start


def suggest_ports() -> dict[str, Any]:
    """给新实例配一套空闲端口，省得用户自己去数。"""
    used: set[int] = {int(config.get("services.napcat.port", 6099) or 6099),
                      int(config.get("services.astrbot.port", 6185) or 6185)}
    for it in config.get("instances", []) or []:
        for key in ("port", "napcatPort"):
            try:
                used.add(int(it.get(key) or 0))
            except Exception:
                pass
    onebot = _free(int(config.get("services.napcat.port", 6199) or 6199), used)
    used.add(onebot)
    napcat = _free(int(config.get("services.napcat.port", 6099) or 6099), used)
    used.add(napcat)
    return {"ok": True, "port": onebot, "napcatPort": napcat, "used": sorted(used)}


def conflicts() -> list[dict[str, Any]]:
    """哪些实例的端口已经被别的进程占着（多半是另一个 AstrBot / NapCat）。"""
    out: list[dict[str, Any]] = []
    for it in config.get("instances", []) or []:
        for key, label in (("port", "OneBot 端口"), ("napcatPort", "NapCat 端口")):
            try:
                port = int(it.get(key) or 0)
            except Exception:
                continue
            if port and probe.tcp_open(port):
                owner = probe.port_owner(port)
                out.append({
                    "id": it.get("id"),
                    "name": it.get("name"),
                    "key": key,
                    "label": label,
                    "port": port,
                    "owner": owner,
                })
    return out


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
    taken = {int(i.get("port") or 0) for i in items} | {int(i.get("napcatPort") or 0) for i in items}
    port = int(payload.get("port") or _free(int(config.get("services.napcat.port", 6199) or 6199), taken))
    napcat_port = int(payload.get("napcatPort") or _free(int(config.get("services.napcat.port", 6099) or 6099), taken | {port}))
    item = {
        "id": iid,
        "name": name,
        "qq": qq,
        "token": str(payload.get("token") or "").strip(),
        "port": port,
        "napcatPort": napcat_port,
        "enabled": bool(payload.get("enabled", True)),
        "createdAt": int(time.time()),
    }
    items.append(item)
    _save(items)
    patch: dict[str, Any] = {}
    if not active_id():
        patch["activeInstance"] = iid
    if patch:
        config.save({"app": patch})
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
    if active_id() == iid or active_id() not in {i.get("id") for i in nxt}:
        config.save({"app": {"activeInstance": (nxt[0].get("id") if nxt else "")}})
    return {"ok": True, "remaining": len(nxt)}
