"""实例运行时：每个 QQ 号一套独立的 AstrBot 数据根和 NapCat 工作目录。

为什么不是「一个 stack 跑所有号」：AstrBot 把 data/、插件、人格库、日志全挂在
ASTRBOT_ROOT 下；NapCat 把 config/、cache/、日志全挂在 NAPCAT_WORKDIR 下。
两个号共用一份就会互相覆盖配置、抢端口。这里只共享只读的源码树/虚拟环境/安装包，
把可写状态按实例分到 ROOT/instances/<id>/。

目录约定::

    ROOT/instances/<id>/astrbot/        -> ASTRBOT_ROOT
    ROOT/instances/<id>/astrbot/data/   -> data_v4.db、cmd_config.json、plugins/
    ROOT/instances/<id>/napcat/         -> NAPCAT_WORKDIR（里面再有 config/）
    ROOT/logs/<role>-<id>.log           -> 子进程 stdout

老版本只有 stack/astrbot/data 和 stack/napcat/config，第一次给 bot1
建实例根时会把它们复制过来，用户不用重新配模型和人格。
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from . import config, paths


def instances() -> list[dict[str, Any]]:
    return [dict(x) for x in (config.get("instances", []) or []) if isinstance(x, dict)]


def get(iid: str | None = None) -> dict[str, Any] | None:
    if iid:
        for it in instances():
            if it.get("id") == iid:
                return it
        return None
    return active()


def active_id() -> str:
    aid = str(config.get("app.activeInstance") or "")
    items = instances()
    if aid and any(i.get("id") == aid for i in items):
        return aid
    for it in items:
        if it.get("enabled", True):
            return str(it.get("id") or "")
    return str(items[0].get("id") or "") if items else ""


def active() -> dict[str, Any]:
    aid = active_id()
    if aid:
        hit = get(aid)
        if hit:
            return hit
    return {"id": "bot1", "name": "主账号", "qq": "", "token": "", "enabled": True}


def _safe(iid: str | None) -> str:
    # 实例 id 会拼进路径，只允许字母数字下划线短横线
    raw = str(iid or active_id() or "bot1")
    keep = [c for c in raw if c.isalnum() or c in "_-"]
    return "".join(keep)[:40] or "bot1"


def instance_dir(iid: str | None = None) -> Path:
    return paths.INSTANCES_DIR / _safe(iid)


def astrbot_root(iid: str | None = None) -> Path:
    return instance_dir(iid) / "astrbot"


def astrbot_data(iid: str | None = None) -> Path:
    return astrbot_root(iid) / "data"


def napcat_workdir(iid: str | None = None) -> Path:
    return instance_dir(iid) / "napcat"


def napcat_config(iid: str | None = None) -> Path:
    return napcat_workdir(iid) / "config"


def snowluma_dir(iid: str | None = None) -> Path:
    """SnowLuma 的数据根（它的 cwd）：config/、logs/ 都在下面。"""
    return instance_dir(iid) / "snowluma"


def snowluma_config(iid: str | None = None) -> Path:
    return snowluma_dir(iid) / "config"


def protocol(iid: str | None = None) -> str:
    """这个实例用哪个协议端：napcat（默认）或 snowluma。"""
    inst = get(iid) or {}
    val = str(inst.get("protocol") or "napcat").strip().lower()
    return val if val in ("napcat", "snowluma") else "napcat"


def log_path(iid: str | None, role: str) -> Path:
    return paths.LOG_DIR / f"{role}-{_safe(iid)}.log"


def astrbot_log(iid: str | None = None) -> Path:
    return astrbot_data(iid) / "logs" / "astrbot.log"


def cmd_path(iid: str | None = None) -> Path:
    return astrbot_data(iid) / "cmd_config.json"


def db_path(iid: str | None = None) -> Path:
    return astrbot_data(iid) / "data_v4.db"


def prefs_path(iid: str | None = None) -> Path:
    return astrbot_data(iid) / "shared_preferences.json"


def port(iid: str | None, role: str) -> int:
    """实例端口；老配置没有字段时回落到全局 services.*.port。"""
    inst = get(iid) or {}
    key = {"astrbot": "astrbotPort", "napcat": "napcatPort", "onebot": "port"}.get(role, role)
    value = inst.get(key)
    if value in (None, ""):
        value = config.get(f"services.{role}.port", paths.DEFAULT_PORTS.get(role, 0))
    try:
        return int(value or 0)
    except Exception:
        return int(paths.DEFAULT_PORTS.get(role, 0))


def spec(iid: str | None = None) -> dict[str, Any]:
    inst = get(iid) or {}
    sid = _safe(iid or inst.get("id") or "bot1")
    return {
        **inst,
        "id": sid,
        "name": inst.get("name") or sid,
        "qq": str(inst.get("qq") or ""),
        "onebotPort": port(sid, "onebot"),
        "napcatPort": port(sid, "napcat"),
        "astrbotPort": port(sid, "astrbot"),
        "root": str(instance_dir(sid)),
        "astrbotRoot": str(astrbot_root(sid)),
        "napcatRoot": str(napcat_workdir(sid)),
        "astrbotUrl": f"http://127.0.0.1:{port(sid, 'astrbot')}",
        "napcatUrl": f"http://127.0.0.1:{port(sid, 'napcat')}",
        "protocol": protocol(sid),
        "protocolName": "SnowLuma" if protocol(sid) == "snowluma" else "NapCat",
        "snowlumaRoot": str(snowluma_dir(sid)),
    }


def _copy_file(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception:
        pass


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.is_dir() or dst.exists():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
    except Exception:
        pass


def _copy_data(src: Path, dst: Path) -> None:
    """只复制用户资产，不复制日志/缓存/下载残留。"""
    if not src.is_dir() or not dst.exists():
        return
    for name in ("cmd_config.json", "data_v4.db", "shared_preferences.json"):
        _copy_file(src / name, dst / name)
    for name in ("config", "plugins", "plugin_data", "knowledge_base"):
        _copy_tree(src / name, dst / name)


def _legacy_data() -> Path:
    return paths.STACK_DIR / "astrbot" / "data"


def _legacy_napcat_config() -> Path:
    return paths.STACK_DIR / "napcat" / "config"


def ensure(iid: str | None = None, seed_from: str | None = None) -> dict[str, Any]:
    """建好实例目录。第一次运行时把老 stack 里的模型/人格/插件迁过来。

    seed_from 用于新建实例：复制当前实例的 cmd_config 和人格库，不复制插件，
    这样新号一上来就能用同一个模型，插件由用户自己装。
    """
    sid = _safe(iid)
    root = astrbot_root(sid)
    data = astrbot_data(sid)
    ndir = napcat_workdir(sid)
    created_data = not data.exists()
    created_napcat = not ndir.exists()

    data.mkdir(parents=True, exist_ok=True)
    napcat_config(sid).mkdir(parents=True, exist_ok=True)
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)

    if created_data:
        _copy_data(_legacy_data(), data)
        if seed_from and _safe(seed_from) != sid:
            _copy_data(astrbot_data(seed_from), data)
        # AstrBot 自己能建，但先放一个合法空对象，界面读配置时不会 404
        if not cmd_path(sid).exists():
            try:
                cmd_path(sid).write_text("{}\n", "utf-8")
            except Exception:
                pass

    if created_napcat:
        legacy = _legacy_napcat_config()
        if legacy.is_dir():
            for p in legacy.glob("*.json"):
                if p.name.startswith("onebot11") or p.name in ("napcat.json", "webui.json"):
                    _copy_file(p, napcat_config(sid) / p.name)
        if seed_from and _safe(seed_from) != sid:
            src = napcat_config(seed_from)
            if src.is_dir():
                for p in src.glob("*.json"):
                    _copy_file(p, napcat_config(sid) / p.name)

    # 实例记录补上旧版没有的字段（只在内存里补，不动用户配置）
    inst = get(sid) or {}
    if inst:
        inst.setdefault("id", sid)

    return {
        "ok": True,
        "id": sid,
        "root": str(instance_dir(sid)),
        "astrbotRoot": str(root),
        "data": str(data),
        "napcatRoot": str(ndir),
        "createdData": created_data,
        "createdNapcat": created_napcat,
    }


def ensure_all() -> list[dict[str, Any]]:
    out = []
    for it in instances():
        iid = str(it.get("id") or "")
        if iid:
            out.append(ensure(iid))
    return out


def migrate_ports() -> list[dict[str, Any]]:
    """给老实例补 astrbotPort，并保证同机端口不重复。

    只写 config，不在导入时执行；由 instances.ensure_defaults() 调用。
    """
    items = instances()
    # 只避开界面端口。services.* 是旧版的全局单例端口，新架构下每个实例
    # 各用自己的端口，若把它们也占住，第一个实例会被无缘无故挤到 6100/6186。
    used: set[int] = {int(config.get("server.preferredPort", 17650) or 17650)}
    changed = False
    for idx, it in enumerate(items):
        for key, default in (("port", paths.DEFAULT_PORTS["onebot"]),
                             ("napcatPort", paths.DEFAULT_PORTS["napcat"]),
                             ("astrbotPort", paths.DEFAULT_PORTS["astrbot"] + idx * 3)):
            val = it.get(key)
            try:
                num = int(val) if val not in (None, "") else default
            except Exception:
                num = default
            while num in used and num < 65535:
                num += 1
            used.add(num)
            if it.get(key) != num:
                it[key] = num
                changed = True
        # 令牌也给出厂值：老版本留空（等于不校验）或随机，用户根本对不上两边的配置。
        if not str(it.get("token") or "").strip():
            it["token"] = paths.DEFAULT_ONEBOT_TOKEN
            changed = True
        if not it.get("napcatSecret"):
            it["napcatSecret"] = paths.DEFAULT_NAPCAT_SECRET
            changed = True
    if changed:
        config.save({"instances": items})
    return items


def auth_password_hint(iid: str | None = None) -> str:
    """默认 dashboard 密码；改过就返回空（AstrBot 只存哈希，取不回来）。"""
    try:
        data = json.loads(cmd_path(iid).read_text("utf-8-sig"))
    except Exception:
        return ""
    dash = data.get("dashboard") or {}
    if dash.get("pbkdf2_password") or dash.get("password"):
        return ""
    return paths.DEFAULT_DASHBOARD_PASSWORD


def api_base(iid: str | None = None) -> str:
    return f"http://127.0.0.1:{port(iid, 'astrbot')}/api/v1"


def now() -> int:
    return int(time.time())
