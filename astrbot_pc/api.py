"""HTTP 接口层：路由表 + 处理函数。

约定与手机版一致：成功 {"ok": true, ...}，失败 {"ok": false, "err": "中文原因"}。
这里只做参数校验与编排，真正的活在 services / deploy / backup / logs 里。
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import webbrowser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

from . import backup, config, deploy, envcheck, instances, llm, logs, paths, probe, startup, stats, update
from .events import bus
from .services import manager

ROUTES: list[tuple[str, re.Pattern[str], Callable[..., dict[str, Any]]]] = []


def route(method: str, pattern: str) -> Callable:
    rx = re.compile("^" + pattern + "$")

    def deco(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        ROUTES.append((method.upper(), rx, fn))
        return fn

    return deco


def dispatch(method: str, path: str, query: dict[str, list[str]], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    for m, rx, fn in ROUTES:
        if m != method.upper():
            continue
        hit = rx.match(path)
        if not hit:
            continue
        try:
            res = fn(query=query, body=body, **hit.groupdict())
        except TypeError as e:
            return 500, {"ok": False, "err": f"参数不匹配：{e}"}
        except Exception as e:
            return 500, {"ok": False, "err": f"{type(e).__name__}: {e}"}
        if not isinstance(res, dict):
            res = {"ok": True, "data": res}
        # 业务层失败（ok=false）依旧是 200：前端靠 ok 字段判断，
        # 只有参数不匹配与内部异常才用非 2xx，避免控制台刷红。
        return 200, res
    return 404, {"ok": False, "err": f"没有这个接口：{method} {path}"}


def _b(**kw: Any) -> dict[str, Any]:
    return {k: v for k, v in kw.items()}


# ---------------- 启动快照 ----------------

@route("GET", r"/api/bootstrap")
def bootstrap(**_: Any) -> dict[str, Any]:
    import sys as _sys

    svc = manager.status()
    return {
        "ok": True,
        "version": __import__("astrbot_pc").__version__,
        "app": {
            "title": paths.APP_TITLE,
            "subtitle": paths.APP_SUBTITLE,
            "platform": os.name,
            "python": f"{_sys.version_info.major}.{_sys.version_info.minor}",
            "dataRoot": str(paths.ROOT),
            "shell": bool(RUNTIME.get("shell")),
        },
        "config": config.load(),
        "env": envcheck.cached() or {
            "items": [], "pending": True, "ready": False, "missing": [], "dataRoot": str(paths.ROOT),
        },
        "services": svc,
        "overview": stats.overview(svc),
        "deploy": deploy.status(),
        "stages": deploy.stages(),
        "instances": instances.list_all(),
        "backups": backup.usage(),
        "server": _server_info(),
        "update": update.cached(),
    }


@route("GET", r"/api/env")
def env_get(**_: Any) -> dict[str, Any]:
    """首次进界面时会先拿到 pending，再回来取一次真结果。"""
    return {"ok": True, "env": envcheck.snapshot()}


@route("GET", r"/api/env/check")
def env_check(**_: Any) -> dict[str, Any]:
    """「重新体检」按下去走这里，跳过缓存。"""
    return {"ok": True, "env": envcheck.snapshot(force=True)}


@route("GET", r"/api/health")
def health(**_: Any) -> dict[str, Any]:
    ports: dict[str, bool] = {}
    try:
        ports[str(_server_info().get("port", ""))] = True
        for label, default in (
            ("astrbot", paths.DEFAULT_PORTS["astrbot"]),
            ("napcat", paths.DEFAULT_PORTS["napcat"]),
            ("onebot", paths.DEFAULT_PORTS["onebot"]),
        ):
            port = int(config.get(f"services.{label}.port", default) or default)
            ports[str(port)] = bool(probe.tcp_open(port))
    except Exception:
        pass
    return {
        "ok": True,
        "ts": int(time.time()),
        "ready": bool(manager.status().get("napcat", {}).get("status") == "running"),
        "ports": ports,
    }


@route("GET", r"/api/state")
def state(**_: Any) -> dict[str, Any]:
    svc = manager.status()
    return {"ok": True, "services": svc, "overview": stats.overview(svc), "ts": int(time.time())}


# ---------------- 服务控制 ----------------

@route("POST", r"/api/services/(?P<key>napcat|astrbot|all)/(?P<action>start|stop|restart)")
def service_action(key: str, action: str, **_: Any) -> dict[str, Any]:
    if key == "all":
        if action == "stop":
            return {"ok": True, "result": manager.stop_all()}
        if action == "start":
            return {"ok": True, "result": manager.start_all()}
        manager.stop_all()
        time.sleep(1)
        return {"ok": True, "result": manager.start_all()}
    fn = {"start": manager.start, "stop": manager.stop, "restart": manager.restart}[action]
    res = fn(key)
    manager.onepass()
    return {"ok": bool(res.get("ok")), **res, "services": manager.status()}


# ---------------- 部署 ----------------

@route("GET", r"/api/deploy/status")
def deploy_status(**_: Any) -> dict[str, Any]:
    return {"ok": True, **deploy.status()}


@route("POST", r"/api/deploy/start")
def deploy_start(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    dry = body.get("dryRun")
    if dry is None:
        dry = bool(config.get("deploy.dryRun", True))
    return {"ok": True, **deploy.runner().start(bool(dry))}


@route("POST", r"/api/deploy/cancel")
def deploy_cancel(**_: Any) -> dict[str, Any]:
    return deploy.runner().cancel()


# ---------------- 日志 ----------------

@route("GET", r"/api/logs")
def logs_list(**_: Any) -> dict[str, Any]:
    return {"ok": True, "items": logs.discover()}


@route("GET", r"/api/logs/tail")
def logs_tail(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    path = (query.get("path") or [""])[0]
    lines = int((query.get("lines") or ["400"])[0] or 400)
    compact = (query.get("compact") or ["1"])[0] not in ("0", "false", "no")
    if not path:
        items = logs.discover()
        if not items:
            return {"ok": True, "path": "", "name": "无日志", "size": 0,
                    "lines": [], "levels": [], "empty": True}
        prefer = next((i for i in items if i["name"] == "astrbot.log"), items[0])
        path = prefer["path"]
    return logs.tail(path, lines, compact)


@route("POST", r"/api/logs/follow")
def logs_follow(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    path = str(body.get("path") or "")
    if not path:
        return {"ok": False, "err": "缺少 path"}
    return logs.follower.follow(path)


@route("POST", r"/api/logs/unfollow")
def logs_unfollow(**_: Any) -> dict[str, Any]:
    return logs.follower.unfollow()


# ---------------- 实例 ----------------

@route("GET", r"/api/instances")
def inst_list(**_: Any) -> dict[str, Any]:
    return {"ok": True, "items": instances.list_all()}


@route("POST", r"/api/instances")
def inst_create(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return instances.create(body)


@route("PATCH", r"/api/instances/(?P<iid>[A-Za-z0-9_-]+)")
def inst_update(iid: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return instances.update(iid, body)


@route("DELETE", r"/api/instances/(?P<iid>[A-Za-z0-9_-]+)")
def inst_delete(iid: str, **_: Any) -> dict[str, Any]:
    return instances.remove(iid)


# ---------------- 二维码 ----------------

@route("GET", r"/api/qr")
def qr(**_: Any) -> dict[str, Any]:
    roots = [paths.STACK_DIR / "napcat", paths.STACK_DIR / "napcat" / "cache"]
    cands: list[Path] = []
    for r in roots:
        if not r.is_dir():
            continue
        for p in r.rglob("*.png"):
            low = p.name.lower()
            if "qr" in low or "qrcode" in low:
                try:
                    cands.append(p)
                except OSError:
                    continue
    cands = [p for p in cands if p.is_file()]
    if not cands:
        return {"ok": True, "exists": False, "reason": "还没有二维码，先去启动 NapCat"}
    newest = max(cands, key=lambda p: p.stat().st_mtime)
    age = int(time.time() - newest.stat().st_mtime)
    data = base64.b64encode(newest.read_bytes()).decode("ascii")
    return {
        "ok": True,
        "exists": True,
        "dataUrl": f"data:image/png;base64,{data}",
        "path": str(newest),
        "mtime": int(newest.stat().st_mtime),
        "age": age,
        "stale": age > 120,
    }


# ---------------- 统计 ----------------

@route("GET", r"/api/stats")
def stats_get(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    svc = manager.status()
    data = stats.overview(svc)
    if (query.get("full") or ["0"])[0] == "1":
        data["today"] = stats.today()
        data["trend"] = stats.trend(14)
    return {"ok": True, **data}


# ---------------- 备份 ----------------

@route("GET", r"/api/backups")
def backup_list(**_: Any) -> dict[str, Any]:
    return {"ok": True, **backup.usage()}


@route("POST", r"/api/backups")
def backup_create(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return backup.create(note=str(body.get("note") or ""))


@route("POST", r"/api/backups/open")
def backup_open(**_: Any) -> dict[str, Any]:
    return backup.open_folder()


@route("POST", r"/api/backups/(?P<name>[^/]+)/restore")
def backup_restore(name: str, **_: Any) -> dict[str, Any]:
    return backup.restore(name)


@route("DELETE", r"/api/backups/(?P<name>[^/]+)")
def backup_delete(name: str, **_: Any) -> dict[str, Any]:
    return backup.remove(name)


# ---------------- 设置 ----------------

@route("POST", r"/api/settings")
def settings_save(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    patch = body.get("patch")
    if not isinstance(patch, dict):
        return {"ok": False, "err": "缺少 patch"}

    app_patch = patch.get("app") if isinstance(patch.get("app"), dict) else {}
    if "autoStart" in app_patch:
        res = startup.set_enabled(bool(app_patch["autoStart"]))
        if not res.get("ok"):
            return {"ok": False, "err": res.get("err") or "设置开机自启失败"}

    config.save(patch)
    return {"ok": True, "config": config.load(), "autoStart": startup.status()}


@route("POST", r"/api/reset")
def settings_reset(**_: Any) -> dict[str, Any]:
    config.reset()
    return {"ok": True, "config": config.load()}


# ---------------- 系统动作 ----------------

@route("POST", r"/api/open")
def open_target(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    # 外部链接：只放行 http(s)，别让这个口子变成能启动任意程序
    link = str(body.get("url") or "").strip()
    if link:
        if not re.match(r"^https?://", link, re.I):
            return {"ok": False, "err": "只支持 http/https 链接"}
        webbrowser.open(link)
        return {"ok": True, "url": link}

    target = str(body.get("target") or "")
    mapping = {
        "data": paths.ROOT,
        "logs": paths.LOG_DIR,
        "backups": paths.BACKUP_DIR,
        "stack": paths.STACK_DIR,
    }
    if target == "webui":
        port = int(config.get("services.astrbot.port", paths.DEFAULT_PORTS["astrbot"]))
        webbrowser.open(f"http://127.0.0.1:{port}")
        return {"ok": True, "url": f"http://127.0.0.1:{port}"}
    if target == "napcat":
        port = int(config.get("services.napcat.port", paths.DEFAULT_PORTS["napcat"]))
        webbrowser.open(f"http://127.0.0.1:{port}/webui/")
        return {"ok": True, "url": f"http://127.0.0.1:{port}/webui/"}
    p = mapping.get(target)
    if not p:
        return {"ok": False, "err": "未知目标"}
    paths.ensure_dirs()
    try:
        if os.name == "nt":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "path": str(p)}
    except Exception as e:
        return {"ok": False, "err": str(e)}


# ---------------- 模型与人格（写进 AstrBot 自己的配置） ----------------

@route("GET", r"/api/llm")
def llm_state(**_: Any) -> dict[str, Any]:
    return llm.current()


@route("POST", r"/api/llm/model")
def llm_model(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return llm.apply_model(
        str(body.get("apiBase") or ""),
        str(body.get("apiKey") or ""),
        str(body.get("model") or ""),
    )


@route("POST", r"/api/llm/persona")
def llm_persona(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return llm.apply_persona(str(body.get("personaId") or ""), str(body.get("prompt") or ""))


@route("POST", r"/api/llm/models")
def llm_models(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return llm.list_models(str(body.get("apiKey") or ""), str(body.get("apiBase") or ""))


@route("GET", r"/api/relay")
def relay_info(**_: Any) -> dict[str, Any]:
    return llm.relay_info()


@route("GET", r"/api/update/check")
def update_check(**_: Any) -> dict[str, Any]:
    return update.check(force=True)


@route("GET", r"/api/update")
def update_cached(**_: Any) -> dict[str, Any]:
    return {"ok": True, "update": update.cached()}


_server_port = {"port": 0}


def set_server_port(port: int) -> None:
    _server_port["port"] = port


#: 运行形态：桌面窗口 / 浏览器。由 app.py 在起窗口前置位。
RUNTIME: dict[str, Any] = {"shell": False}


def _server_info() -> dict[str, Any]:
    return {
        "port": _server_port["port"],
        "url": f"http://127.0.0.1:{_server_port['port']}",
        "shell": bool(RUNTIME.get("shell")),
    }


@route("GET", r"/api/events/poll")
def events_poll(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    """SSE 不可用时的兜底：按 seq 拉增量事件。"""
    seq = int((query.get("seq") or ["0"])[0] or 0)
    items = bus.since(seq)
    return {"ok": True, "items": items, "seq": bus.last_seq()}
