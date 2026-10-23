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

from . import (appearance, backup, components, config, console, creds, crash, deploy, doctor,
               envcheck, failover, instances, llm, logs, metrics, paths, plugins, probe,
               selftest, startup, stats, storage, update)
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
        UI_PORT = _server_info().get("port") or 0
        if UI_PORT:
            ports[str(UI_PORT)] = True
        from . import runtime

        sid = runtime.active_id() or "bot1"
        for label in ("astrbot", "napcat", "onebot"):
            port = runtime.port(sid, label)
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

@route("GET", r"/api/services/status")
def service_status(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    iid = (query.get("iid") or [""])[0] or None
    return {"ok": True, "services": manager.status(iid), "instances": manager.status_all()}


@route("POST", r"/api/services/(?P<key>napcat|astrbot|all)/(?P<action>start|stop|restart)")
def service_action(key: str, action: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    iid = str(body.get("iid") or "").strip() or None
    if key == "all":
        if action == "stop":
            return {"ok": True, "result": manager.stop_all(iid)}
        if action == "start":
            return {"ok": True, "result": manager.start_all_instances() if not iid else manager.start_all(iid)}
        manager.stop_all(iid)
        time.sleep(1)
        return {
            "ok": True,
            "result": manager.start_all_instances() if not iid else manager.start_all(iid),
        }
    fn = {"start": manager.start, "stop": manager.stop, "restart": manager.restart}[action]
    res = fn(key, iid)
    manager.onepass()
    return {"ok": bool(res.get("ok")), **res, "services": manager.status(iid)}


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
def qr(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    from . import runtime

    iid = (query.get("iid") or [""])[0] or None
    base = runtime.napcat_workdir(iid)
    roots = [base, base / "cache", paths.STACK_DIR / "napcat", paths.STACK_DIR / "napcat" / "cache"]
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
    # 大目录打包要几十秒到几分钟，放后台跑，界面轮询 job 状态
    return backup.create_async(note=str(body.get("note") or ""))


@route("POST", r"/api/backups/cancel")
def backup_cancel(**_: Any) -> dict[str, Any]:
    return backup.cancel()


@route("POST", r"/api/backups/import")
def backup_import(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    path = str(body.get("path") or "").strip()
    if path:
        return backup.import_file(path)
    data_url = str(body.get("dataUrl") or "")
    if data_url.startswith("data:") and ";base64," in data_url:
        import base64 as _b64

        raw = data_url.split(";base64,", 1)[1]
        try:
            payload = _b64.b64decode(raw)
        except Exception:
            return {"ok": False, "err": "备份内容不是有效的 base64"}
        paths.ensure_dirs()
        tmp = paths.TMP_DIR / f"import-{int(time.time())}.zip"
        tmp.write_bytes(payload)
        res = backup.import_file(str(tmp))
        try:
            tmp.unlink()
        except OSError:
            pass
        return res
    return {"ok": False, "err": "缺少文件路径（桌面窗口里用「选择文件」，网页模式请填绝对路径）"}


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
    if target in ("webui", "napcat"):
        from . import runtime

        sid = str(body.get("iid") or runtime.active_id() or "bot1")
        if target == "webui":
            port = runtime.port(sid, "astrbot")
            url = f"http://127.0.0.1:{port}"
        else:
            port = runtime.port(sid, "napcat")
            url = f"http://127.0.0.1:{port}/webui/"
        webbrowser.open(url)
        return {"ok": True, "url": url, "iid": sid}
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


_server_port = {"port": 0, "host": "127.0.0.1"}


def set_server_port(port: int) -> None:
    _server_port["port"] = port


def set_server_host(host: str) -> None:
    _server_port["host"] = host or "127.0.0.1"


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


# ---------------- 体检 / 诊断包 / 部署重置 ----------------

@route("GET", r"/api/doctor")
def doctor_get(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    force = (query.get("force") or ["0"])[0] == "1"
    return doctor.run(force=force)


@route("POST", r"/api/diag/export")
def diag_export(**_: Any) -> dict[str, Any]:
    return doctor.export_bundle()


@route("GET", r"/api/diag")
def diag_list(**_: Any) -> dict[str, Any]:
    items = []
    if paths.DIAG_DIR.is_dir():
        for p in sorted(paths.DIAG_DIR.glob("*.zip"), key=lambda x: -x.stat().st_mtime):
            st = p.stat()
            items.append({"name": p.name, "size": st.st_size, "createdAt": int(st.st_mtime)})
    return {"ok": True, "dir": str(paths.DIAG_DIR), "items": items}


@route("DELETE", r"/api/diag/(?P<name>[^/]+)")
def diag_delete(name: str, **_: Any) -> dict[str, Any]:
    p = paths.DIAG_DIR / Path(name).name
    if not p.is_file():
        return {"ok": False, "err": "诊断包不存在"}
    try:
        p.unlink()
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "err": f"删除失败：{e}"}


@route("POST", r"/api/deploy/reset")
def deploy_reset(**_: Any) -> dict[str, Any]:
    return doctor.reset_state()


# ---------------- 命令行 ----------------

@route("POST", r"/api/terminal/run")
def terminal_run(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    cmd = str(body.get("cmd") or "").strip()
    if not cmd:
        return {"ok": False, "err": "命令是空的"}
    return console.run(cmd, str(body.get("cwd") or ""), int(body.get("timeout") or 60))


# ---------------- 存储 ----------------

@route("GET", r"/api/storage")
def storage_get(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    force = (query.get("force") or ["0"])[0] == "1"
    return storage.scan(force=force)


@route("POST", r"/api/storage/clean")
def storage_clean(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return storage.clean(str(body.get("what") or "quick"))


# ---------------- 崩溃记录 ----------------

@route("GET", r"/api/crashes")
def crashes_get(**_: Any) -> dict[str, Any]:
    return crash.list_all()


@route("DELETE", r"/api/crashes")
def crashes_clear(**_: Any) -> dict[str, Any]:
    return crash.clear()


# ---------------- 日志清理 ----------------

@route("POST", r"/api/logs/clear")
def logs_clear(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return logs.clear(str(body.get("path") or ""))


@route("DELETE", r"/api/logs")
def logs_delete(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    path = (query.get("path") or [""])[0]
    return logs.delete(path)


# ---------------- 实例接线 ----------------

@route("POST", r"/api/instances/(?P<iid>[A-Za-z0-9_-]+)/apply")
def inst_apply(iid: str, **_: Any) -> dict[str, Any]:
    return instances.apply(iid)


@route("POST", r"/api/instances/(?P<iid>[A-Za-z0-9_-]+)/active")
def inst_active(iid: str, **_: Any) -> dict[str, Any]:
    return instances.set_active(iid)


@route("POST", r"/api/instances/suggest")
def inst_suggest(**_: Any) -> dict[str, Any]:
    return instances.suggest_ports()


@route("GET", r"/api/instances/conflicts")
def inst_conflicts(**_: Any) -> dict[str, Any]:
    return {"ok": True, "items": instances.conflicts()}


# ---------------- 控制台账号 ----------------

@route("GET", r"/api/console/creds")
def console_creds(**_: Any) -> dict[str, Any]:
    return creds.info()


@route("POST", r"/api/console/creds")
def console_creds_reset(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return creds.reset(str(body.get("username") or ""), str(body.get("password") or ""))


# ---------------- 模型连通性 ----------------

@route("POST", r"/api/llm/test")
def llm_test(**_: Any) -> dict[str, Any]:
    return llm.test_connection()


# ---------------- 外观 ----------------

@route("GET", r"/api/appearance")
def appearance_get(**_: Any) -> dict[str, Any]:
    return appearance.info()


@route("POST", r"/api/appearance/background")
def appearance_bg(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return appearance.set_bg(str(body.get("dataUrl") or ""))


@route("DELETE", r"/api/appearance/background")
def appearance_bg_clear(**_: Any) -> dict[str, Any]:
    return appearance.clear_bg()


@route("POST", r"/api/appearance/level")
def appearance_level(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return appearance.set_level(str(body.get("level") or "soft"))


# ---------------- 局域网 ----------------

def _lan_ip() -> str:
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        try:
            return str(socket.gethostbyname(socket.gethostname()))
        except Exception:
            return ""


@route("GET", r"/api/lan")
def lan_info(**_: Any) -> dict[str, Any]:
    mode = str(config.get("server.authMode", "local") or "local")
    port = int(_server_port.get("port") or 0)
    host = str(_server_port.get("host") or "127.0.0.1")
    ip = _lan_ip()
    return {
        "ok": True,
        "mode": mode,
        "host": host,
        "ip": ip,
        "port": port,
        "localUrl": f"http://127.0.0.1:{port}",
        "lanUrl": f"http://{ip}:{port}" if ip and mode == "lan" and host not in ("127.0.0.1", "localhost") else "",
        "needRestart": mode == "lan" and host in ("127.0.0.1", "localhost"),
        "note": "手机与电脑连同一个 Wi-Fi，就能用手机浏览器打开这个地址" if mode == "lan" else "只有本机能访问；在设置里打开「允许局域网访问」后重启程序即可",
    }


# ---------------- 组件更新中心 ----------------

@route("GET", r"/api/components")
def components_inventory(**_: Any) -> dict[str, Any]:
    return components.inventory()


@route("POST", r"/api/components/check")
def components_check(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return components.check(bool(body.get("force")))


@route("POST", r"/api/components/snapshot")
def components_snapshot(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return components.snapshot(str(body.get("label") or ""))


@route("GET", r"/api/components/snapshots")
def components_snapshots(**_: Any) -> dict[str, Any]:
    return components.snapshots()


@route("POST", r"/api/components/rollback")
def components_rollback(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return components.rollback(str(body.get("name") or ""))


@route("POST", r"/api/components/upgrade")
def components_upgrade(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return components.upgrade(str(body.get("key") or ""))


# ---------------- 插件管理器 ----------------

@route("GET", r"/api/plugins/failed")
def plugins_failed(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return plugins.failed((query.get("iid") or [""])[0] or None)


@route("GET", r"/api/plugins")
def plugins_list(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return plugins.list_all((query.get("iid") or [""])[0] or None)


@route("POST", r"/api/plugins/install")
def plugins_install(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    iid = str(body.get("iid") or "").strip() or None
    url = str(body.get("url") or "").strip()
    if url:
        return plugins.install_github(url, iid)
    path = str(body.get("path") or "").strip()
    if path:
        return plugins.install_zip(path, iid)
    data_url = str(body.get("dataUrl") or "")
    if data_url.startswith("data:") and ";base64," in data_url:
        raw = data_url.split(";base64,", 1)[1]
        try:
            payload = base64.b64decode(raw)
        except Exception:
            return {"ok": False, "err": "插件包内容不是有效的 base64"}
        paths.ensure_dirs()
        tmp = paths.TMP_DIR / f"plugin-{int(time.time())}.zip"
        tmp.write_bytes(payload)
        try:
            return plugins.install_zip(str(tmp), iid)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    return {"ok": False, "err": "请提供插件 zip 路径、上传文件或 GitHub 链接"}


@route("GET", r"/api/plugins/(?P<pid>[A-Za-z0-9_.-]+)")
def plugins_detail(pid: str, query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return plugins.detail(pid, (query.get("iid") or [""])[0] or None)


@route("PATCH", r"/api/plugins/(?P<pid>[A-Za-z0-9_.-]+)")
def plugins_enabled(pid: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return plugins.set_enabled(pid, bool(body.get("enabled")), str(body.get("iid") or "").strip() or None)


@route("DELETE", r"/api/plugins/(?P<pid>[A-Za-z0-9_.-]+)")
def plugins_remove(pid: str, query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return plugins.remove(pid, (query.get("iid") or [""])[0] or None)


@route("GET", r"/api/plugins/(?P<pid>[A-Za-z0-9_.-]+)/config")
def plugins_config_get(pid: str, query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return plugins.config_get(pid, (query.get("iid") or [""])[0] or None)


@route("POST", r"/api/plugins/(?P<pid>[A-Za-z0-9_.-]+)/config")
def plugins_config_save(pid: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return plugins.config_save(pid, body.get("config", body.get("data", {})), str(body.get("iid") or "").strip() or None)


@route("GET", r"/api/plugins/(?P<pid>[A-Za-z0-9_.-]+)/logs")
def plugins_logs(pid: str, query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    lines = int((query.get("lines") or ["300"])[0] or 300)
    return plugins.logs(pid, (query.get("iid") or [""])[0] or None, lines)


# ---------------- 模型多线路 ----------------

@route("GET", r"/api/llm/routes")
def llm_routes(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    iid = (query.get("iid") or [""])[0] or None
    listed = failover.list_routes(iid)
    if listed.get("ok"):
        listed["current"] = failover.current(iid)
    return listed


@route("POST", r"/api/llm/routes")
def llm_routes_save(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    iid = str(body.get("iid") or "").strip() or None
    saved = failover.save_routes(body.get("routes") or [], iid)
    if not saved.get("ok"):
        return saved
    if body.get("apply", True):
        rows = config.get("llm.routes", []) or []
        applied = llm.apply_routes(rows, iid)
        saved["apply"] = applied
        if not applied.get("ok"):
            saved["ok"] = False
            saved["err"] = applied.get("err") or "线路已保存，但写入 AstrBot 失败"
    return saved


@route("DELETE", r"/api/llm/routes/(?P<rid>[A-Za-z0-9_.-]+)")
def llm_routes_remove(rid: str, query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return failover.remove_route(rid, (query.get("iid") or [""])[0] or None)


@route("POST", r"/api/llm/routes/health")
def llm_routes_health(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    iid = str(body.get("iid") or "").strip() or None
    return failover.health(iid, bool(body.get("force")))


@route("POST", r"/api/llm/routes/apply")
def llm_routes_apply(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    iid = str(body.get("iid") or "").strip() or None
    return llm.apply_routes(body.get("routes") or config.get("llm.routes", []) or [], iid)


@route("GET", r"/api/llm/routes/current")
def llm_routes_current(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return failover.current((query.get("iid") or [""])[0] or None)


# ---------------- 资源看板与报错解释 ----------------

@route("GET", r"/api/metrics")
def metrics_samples(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    hours = float((query.get("hours") or ["24"])[0] or 24)
    limit = int((query.get("limit") or ["720"])[0] or 720)
    return metrics.samples(hours, limit)


@route("GET", r"/api/metrics/summary")
def metrics_summary(**_: Any) -> dict[str, Any]:
    return metrics.summary()


@route("GET", r"/api/metrics/history")
def metrics_history(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    hours = float((query.get("hours") or ["1"])[0] or 1)
    return {"ok": True, "items": metrics.history(hours)}


@route("GET", r"/api/metrics/errors")
def metrics_errors(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    limit = int((query.get("limit") or ["30"])[0] or 30)
    return metrics.errors(limit)


@route("POST", r"/api/metrics/explain")
def metrics_explain(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    if body.get("path"):
        return metrics.explain_log(str(body.get("path")), int(body.get("lineNo") or body.get("line") or 1))
    return metrics.explain(str(body.get("text") or ""))


@route("DELETE", r"/api/metrics")
def metrics_clear(**_: Any) -> dict[str, Any]:
    return metrics.clear()

# ---------------- 试聊与端到端自检 ----------------

@route("GET", r"/api/selftest/trial_chat")
def selftest_trial(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    prompt = (query.get("prompt") or [""])[0]
    return selftest.trial_chat(prompt, (query.get("iid") or [""])[0] or None)


@route("GET", r"/api/selftest/e2e")
def selftest_e2e(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return selftest.e2e((query.get("iid") or [""])[0] or None)


@route("GET", r"/api/selftest/history")
def selftest_history(query: dict[str, list[str]], **_: Any) -> dict[str, Any]:
    return selftest.history(int((query.get("limit") or ["20"])[0] or 20))


@route("POST", r"/api/selftest/history/clear")
@route("DELETE", r"/api/selftest/history")
def selftest_history_clear(**_: Any) -> dict[str, Any]:
    return selftest.clear_history()


@route("POST", r"/api/selftest/chat")
def selftest_chat(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return selftest.trial_chat(str(body.get("prompt") or ""), str(body.get("iid") or "").strip() or None)


@route("POST", r"/api/selftest/e2e")
def selftest_e2e_post(body: dict[str, Any], **_: Any) -> dict[str, Any]:
    return selftest.e2e(str(body.get("iid") or "").strip() or None)
