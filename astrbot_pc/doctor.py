"""一键体检 + 诊断包。

体检把「为什么跑不起来」拆成一条条能照着做的结论：每条都有状态、说明、
以及一句该点哪里。诊断包把脱敏后的配置、服务状态、崩溃记录和日志尾巴
打成一个 zip，方便发给别人排查。
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

from . import config, crash, envcheck, logs, paths, probe, storage

_TTL = 15.0
_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}

SECRET = re.compile(r"(token|passw|secret|apikey|api_key|auth|^key$)", re.I)


def _item(key: str, label: str, status: str, detail: str, hint: str = "") -> dict[str, Any]:
    return {"key": key, "label": label, "status": status, "detail": detail, "hint": hint}


def _map_env(it: dict[str, Any]) -> dict[str, Any]:
    st = {"ok": "ok", "warn": "warn", "missing": "fail"}.get(it.get("status"), "warn")
    hints = {
        "python": "部署向导第 1 步会说明怎么补",
        "qq": "去 qq.com 装新版 QQ NT，NapCat 必须挂在它上面",
        "napcat": "部署向导第 3 步会拉到 stack\\napcat",
        "astrbot": "部署向导第 4、5 步会拉源码并装依赖",
        "git": "用「下载压缩包」方式安装时可以不装",
        "disk": "清理 backups 或 tmp 能腾出空间",
    }
    return _item(it.get("key", ""), it.get("name", ""), st, it.get("detail", ""), hints.get(it.get("key", ""), ""))


def _writable() -> dict[str, Any]:
    target = paths.STATE_DIR / ".write-test"
    try:
        paths.ensure_dirs()
        target.write_text(str(time.time()), encoding="utf-8")
        target.unlink()
        return _item("writable", "数据目录可写", "ok", str(paths.ROOT))
    except Exception as e:
        return _item("writable", "数据目录可写", "fail", f"写不进去：{e}", "把数据目录换个位置，或用管理员身份运行")


def _json_file(path: Path, key: str, label: str, hint: str) -> dict[str, Any]:
    if not path.is_file():
        return _item(key, label, "warn", "还没生成，部署第 6 步会写", hint)
    try:
        json.loads(path.read_text(encoding="utf-8-sig"))
        return _item(key, label, "ok", str(path))
    except Exception as e:
        return _item(key, label, "fail", f"JSON 解析失败：{e}", "重新跑一次部署的第 6 步可以覆盖写回")


def _ports() -> dict[str, Any]:
    rows = []
    warn = 0
    try:
        from .services import manager

        svc = manager.status()
    except Exception:
        svc = {}
    known = {
        "astrbot": int(config.get("services.astrbot.port", paths.DEFAULT_PORTS["astrbot"])),
        "napcat": int(config.get("services.napcat.port", paths.DEFAULT_PORTS["napcat"])),
        "onebot": int((config.get("instances") or [{}])[0].get("port") or paths.DEFAULT_PORTS["onebot"]),
    }
    for key, label, port in (
        ("astrbot", "AstrBot 控制台端口", known["astrbot"]),
        ("napcat", "NapCat WebUI 端口", known["napcat"]),
        ("onebot", "OneBot 反连端口", known["onebot"]),
    ):
        owner = probe.port_owner(port)
        mine = int((svc.get(key) or {}).get("pid") or 0)
        if not probe.tcp_open(port):
            rows.append(f"{label} {port}：空闲")
            continue
        if owner and mine and int(owner.get("pid") or 0) == mine:
            rows.append(f"{label} {port}：由本程序监听")
            continue
        name = owner.get("name") or "未知程序"
        pid = owner.get("pid") or "?"
        rows.append(f"{label} {port}：被 {name}（PID {pid}）占用")
        warn += 1
    status = "warn" if warn else "ok"
    return _item("ports", "端口占用", status, "；".join(rows) or "没有需要检查的端口", "在「服务」页改端口，或先结束占用的程序")


def _llm() -> dict[str, Any]:
    conf_path = paths.STACK_DIR / "astrbot" / "data" / "cmd_config.json"
    try:
        conf = json.loads(conf_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return _item("llm", "模型接入", "warn", "还没读到 AstrBot 配置", "去「模型」页配一个中转站密钥")
    model = ""
    has_key = False
    for src in conf.get("provider_sources") or []:
        if not isinstance(src, dict):
            continue
        keys = src.get("key") or []
        has_key = has_key or any(str(k).strip() for k in keys if k)
        if src.get("api_base"):
            break
    for p in conf.get("provider") or []:
        if isinstance(p, dict) and p.get("model"):
            model = str(p["model"])
            break
    if model and has_key:
        return _item("llm", "模型接入", "ok", f"已配置 {model}")
    if model and not has_key:
        return _item("llm", "模型接入", "warn", f"选了 {model} 但没填密钥", "去「模型」页补一个密钥")
    return _item("llm", "模型接入", "warn", "还没有配置模型", "去「模型」页选中转站、贴密钥、点保存")


def _crashes() -> dict[str, Any]:
    n = crash.count_since(86400)
    if n:
        return _item("crash", "最近崩溃", "warn", f"24 小时内记录到 {n} 次异常退出", "去「诊断」页看崩溃记录，或导出诊断包")
    return _item("crash", "最近崩溃", "ok", "24 小时内没有异常记录")


def _disk() -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(str(paths.ROOT))
        free_gb = usage.free / 1024 ** 3
        st = "ok" if free_gb >= 3 else ("warn" if free_gb >= 1 else "fail")
        return _item("space", "磁盘余量", st, f"剩余 {free_gb:.1f} GB / 共 {usage.total / 1024 ** 3:.0f} GB", "清理「数据」页里的临时文件与旧备份")
    except Exception as e:
        return _item("space", "磁盘余量", "warn", f"读取失败：{e}")


def run(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _TTL:
        return _CACHE["data"]

    env = envcheck.snapshot(force=force)
    items = [_map_env(it) for it in env.get("items") or []]
    items.append(_writable())
    items.append(_json_file(paths.STACK_DIR / "astrbot" / "data" / "cmd_config.json", "astrbot-config", "AstrBot 配置", "重跑部署第 6 步"))
    items.append(_json_file(paths.STACK_DIR / "napcat" / "config" / "onebot11.json", "napcat-config", "NapCat 接线", "在「实例」页点「一键接线」"))
    items.append(_ports())
    items.append(_llm())
    items.append(_crashes())
    items.append(_disk())
    try:
        st = storage.scan()
        items.append(_item("storage", "存储占用", "ok", f"程序数据合计 {st['total'] / 1024 ** 2:.0f} MB"))
    except Exception:
        pass

    summary = {
        "ok": sum(1 for i in items if i["status"] == "ok"),
        "warn": sum(1 for i in items if i["status"] == "warn"),
        "fail": sum(1 for i in items if i["status"] == "fail"),
    }
    data = {
        "ok": summary["fail"] == 0,
        "items": items,
        "summary": summary,
        "ready": env.get("ready", False),
        "ts": int(time.time()),
        "version": __import__("astrbot_pc").__version__,
    }
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data


def _redact(node: Any) -> Any:
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if SECRET.search(str(k)):
                out[k] = "***" if v not in ("", [], None) else v
            else:
                out[k] = _redact(v)
        return out
    if isinstance(node, list):
        return [_redact(x) for x in node]
    return node


def _log_tails(zf: zipfile.ZipFile) -> None:
    try:
        files = logs.discover()
    except Exception:
        return
    for f in files[:12]:
        try:
            name = str(f.get("name") or "")
            path = str(f.get("path") or "")
            if not path:
                continue
            res = logs.tail(path, 200, compact=True)
            text = "\n".join(res.get("lines") or [])
            if not text:
                continue
            safe = re.sub(r"[^\w.\-]+", "_", f"{f.get('group', '')}-{name}") or "log"
            zf.writestr(f"logs/{safe}.tail.txt", text)
        except Exception:
            continue


def export_bundle() -> dict[str, Any]:
    paths.ensure_dirs()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"astrbot-pc-diag-{stamp}.zip"
    target = paths.DIAG_DIR / name
    report = run(force=True)
    meta = {
        "app": paths.APP_TITLE,
        "version": report.get("version"),
        "platform": platform.platform(),
        "python": sys.version,
        "frozen": paths.is_frozen(),
        "dataRoot": str(paths.ROOT),
        "ports": {"server": config.get("server.preferredPort")},
        "ts": int(time.time()),
    }
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
            try:
                zf.writestr("config.redacted.json", json.dumps(_redact(config.load()), ensure_ascii=False, indent=2))
            except Exception:
                pass
            try:
                from .services import manager

                zf.writestr("services.json", json.dumps(_redact(manager.status()), ensure_ascii=False, indent=2))
            except Exception:
                pass
            try:
                zf.writestr("crashes.json", json.dumps(crash.list_all(), ensure_ascii=False, indent=2))
            except Exception:
                pass
            for label, path in (
                ("astrbot-cmd_config.json", paths.STACK_DIR / "astrbot" / "data" / "cmd_config.json"),
                ("napcat-onebot11.json", paths.STACK_DIR / "napcat" / "config" / "onebot11.json"),
            ):
                try:
                    data = json.loads(path.read_text(encoding="utf-8-sig"))
                    zf.writestr(f"stack/{label}", json.dumps(_redact(data), ensure_ascii=False, indent=2))
                except Exception:
                    continue
            _log_tails(zf)
    except Exception as e:
        return {"ok": False, "err": f"打包失败：{e}"}
    size = target.stat().st_size if target.exists() else 0
    return {"ok": True, "name": name, "path": str(target), "size": size}


def reset_state() -> dict[str, Any]:
    """重置部署进度：清掉残留的服务状态记录，让向导能从第一步重跑。

    已经下载/安装的文件不动——那是十几个 G 的东西，不能因为点了个
    「重置」就重下。
    """
    removed = []
    for pat in ("svc-*.json",):
        for f in paths.STATE_DIR.glob(pat):
            try:
                f.unlink()
                removed.append(f.name)
            except OSError:
                pass
    try:
        from .deploy import runner

        r = runner()
        r.reset()
    except Exception:
        pass
    _CACHE["data"] = None
    return {"ok": True, "removed": removed, "message": "部署进度已重置，已经装好的文件保留"}
