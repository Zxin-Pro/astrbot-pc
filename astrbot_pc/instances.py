"""实例管理：一个 QQ 号 = 一个实例 = 一套独立进程与数据目录。

1.0.0 起每个实例有自己的 AstrBot 数据根、NapCat 工作目录、三个端口
（OneBot 反向 WS / NapCat WebUI / AstrBot Dashboard）和日志，可以同时在线。
共享的是只读源码树、虚拟环境和 NapCat 安装包，细节见 runtime.py。
"""

from __future__ import annotations

import re
import shutil
import socket
import time
from typing import Any

from . import config, paths, probe, runtime

QQ_RE = re.compile(r"^\d{5,12}$")


def list_all() -> list[dict[str, Any]]:
    aid = active_id()
    out = []
    for it in runtime.instances():
        row = dict(it)
        spec = runtime.spec(str(row.get("id") or ""))
        row.update({
            "port": spec["onebotPort"],
            "napcatPort": spec["napcatPort"],
            "astrbotPort": spec["astrbotPort"],
            "root": spec["root"],
        })
        row["onebotOpen"] = probe.tcp_open(int(row["port"]))
        row["napcatOpen"] = probe.tcp_open(int(row["napcatPort"]))
        row["astrbotOpen"] = probe.tcp_open(int(row["astrbotPort"]))
        row["active"] = bool(aid) and row.get("id") == aid
        out.append(row)
    return out


def get(iid: str) -> dict[str, Any] | None:
    return runtime.get(iid)


def active_id() -> str:
    return runtime.active_id()


def active() -> dict[str, Any]:
    return runtime.active()


def set_active(iid: str) -> dict[str, Any]:
    if not get(iid):
        return {"ok": False, "err": "实例不存在"}
    config.save({"app": {"activeInstance": iid}})
    return {"ok": True, "active": iid}


def apply(iid: str) -> dict[str, Any]:
    """把实例端口写进它自己的 NapCat / AstrBot 配置，不重启进程。"""
    inst = get(iid)
    if not inst:
        return {"ok": False, "err": "实例不存在"}
    config.save({"app": {"activeInstance": iid}})
    from . import deploy

    ok, detail = deploy.write_wiring(runtime.active(), False)
    if not ok:
        return {"ok": False, "err": detail}
    running = False
    try:
        from .services import manager

        running = any(v.get("status") in ("running", "starting") for v in manager.status(iid).values())
    except Exception:
        pass
    return {
        "ok": True,
        "detail": detail,
        "needsRestart": running,
        "instance": runtime.active(),
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


def _used_ports(extra: set[int] | None = None) -> set[int]:
    used: set[int] = {int(config.get("server.preferredPort", 17650) or 17650)}
    for it in _all():
        for key in ("port", "napcatPort", "astrbotPort"):
            try:
                if it.get(key) not in (None, ""):
                    used.add(int(it.get(key)))
            except Exception:
                pass
    if extra:
        used |= extra
    return used


def suggest_ports() -> dict[str, Any]:
    """给新实例配一套空闲端口：OneBot 6199、NapCat 6099、Dashboard 6185 起。"""
    used = _used_ports()
    onebot = _free(int(paths.DEFAULT_PORTS.get("onebot", 6199)), used)
    used.add(onebot)
    napcat = _free(int(paths.DEFAULT_PORTS.get("napcat", 6099)), used)
    used.add(napcat)
    astrbot = _free(int(paths.DEFAULT_PORTS.get("astrbot", 6185)), used)
    used.add(astrbot)
    return {"ok": True, "port": onebot, "napcatPort": napcat, "astrbotPort": astrbot, "used": sorted(used)}


def conflicts() -> list[dict[str, Any]]:
    """哪些实例的端口已经被别的进程占着（多半是另一个 AstrBot / NapCat）。"""
    out: list[dict[str, Any]] = []
    for it in list_all():
        for key, label in (("port", "OneBot 端口"), ("napcatPort", "NapCat 端口"), ("astrbotPort", "Dashboard 端口")):
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


def _unique(iid: str, raw: str) -> str:
    base = re.sub(r"[^0-9A-Za-z_-]", "", str(raw or "bot"))[:30] or "bot"
    used = {str(i.get("id") or "") for i in _all()}
    if base not in used:
        return base
    n = 2
    while f"{base}{n}" in used:
        n += 1
    return f"{base}{n}"


def create(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip() or "新实例"
    qq = str(payload.get("qq") or "").strip()
    if qq and not QQ_RE.match(qq):
        return {"ok": False, "err": "QQ 号应该是 5~12 位数字"}
    items = _all()
    iid = _unique("", str(payload.get("id") or "bot"))
    used = _used_ports()
    port = int(payload.get("port") or _free(int(paths.DEFAULT_PORTS.get("onebot", 6199)), used))
    used.add(port)
    napcat_port = int(payload.get("napcatPort") or _free(int(paths.DEFAULT_PORTS.get("napcat", 6099)), used))
    used.add(napcat_port)
    astrbot_port = int(payload.get("astrbotPort") or _free(int(paths.DEFAULT_PORTS.get("astrbot", 6185)), used))
    item = {
        "id": iid,
        "name": name,
        "qq": qq,
        "token": str(payload.get("token") or "").strip(),
        "port": port,
        "napcatPort": napcat_port,
        "astrbotPort": astrbot_port,
        "enabled": bool(payload.get("enabled", True)),
        "createdAt": int(time.time()),
    }
    items.append(item)
    _save(items)
    if len(items) == 1:
        config.save({"app": {"activeInstance": iid}})
        runtime.ensure(iid)
    else:
        runtime.ensure(iid, seed_from=active_id() or None)
    return {"ok": True, "item": item}


def _port_dup(items: list[dict[str, Any]], iid: str, key: str, value: int) -> str:
    for it in items:
        if it.get("id") == iid:
            continue
        for other in ("port", "napcatPort", "astrbotPort"):
            try:
                if int(it.get(other) or 0) == value:
                    label = {"port": "OneBot", "napcatPort": "NapCat", "astrbotPort": "Dashboard"}.get(other, other)
                    return f"端口 {value} 已被实例「{it.get('name') or it.get('id')}」的 {label} 占用"
            except Exception:
                continue
    return ""


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
        for key, default in (("port", 6199), ("napcatPort", 6099), ("astrbotPort", 6185)):
            if key not in payload:
                continue
            try:
                val = int(payload.get(key) or it.get(key) or default)
            except Exception:
                return {"ok": False, "err": "端口必须是数字"}
            if not (1 <= val <= 65535):
                return {"ok": False, "err": f"端口 {val} 超出范围"}
            dup = _port_dup(items, iid, key, val)
            if dup:
                return {"ok": False, "err": dup}
            it[key] = val
        if "enabled" in payload:
            it["enabled"] = bool(payload.get("enabled"))
        items[i] = it
        _save(items)
        needs = False
        if active_id() == iid and any(k in payload for k in ("port", "napcatPort", "astrbotPort", "token")):
            from . import deploy

            ok, _detail = deploy.write_wiring(it, False)
            needs = bool(ok)
        return {"ok": True, "item": it, "needsRestart": needs, "instance": runtime.spec(iid)}
    return {"ok": False, "err": "实例不存在"}


def remove(iid: str, purge: bool = False) -> dict[str, Any]:
    items = _all()
    nxt = [i for i in items if i.get("id") != iid]
    if len(nxt) == len(items):
        return {"ok": False, "err": "实例不存在"}
    try:
        from .services import manager

        manager.stop_all(iid)
    except Exception:
        pass
    _save(nxt)
    if active_id() == iid or active_id() not in {i.get("id") for i in nxt}:
        config.save({"app": {"activeInstance": (nxt[0].get("id") if nxt else "")}})
    if purge:
        target = runtime.instance_dir(iid)
        try:
            if target.is_dir() and paths.INSTANCES_DIR in target.parents:
                shutil.rmtree(target, ignore_errors=True)
        except Exception:
            pass
    return {"ok": True, "remaining": len(nxt), "purged": bool(purge)}


def ensure_defaults() -> list[dict[str, Any]]:
    """老配置补端口/密钥，并给每个实例建好目录。"""
    items = runtime.migrate_ports()
    for it in items:
        iid = str(it.get("id") or "")
        if iid:
            runtime.ensure(iid)
    return items
