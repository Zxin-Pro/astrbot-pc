"""配置读写：一个 JSON 文件 + 深合并默认值 + 原子落盘。"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

from . import paths

DEFAULTS: dict[str, Any] = {
    "app": {
        "theme": "auto",          # light | dark | auto
        "firstRun": True,
        "autoStart": False,       # 开机自启
        "minimizeToTray": True,
        "checkUpdate": True,
        "glass": True,            # 兼容老配置：等价于 glassLevel != "off"
        "glassLevel": "soft",     # off | soft | strong —— 玻璃厚度
        "compact": False,         # 精简模式：隐藏次要说明，一屏看更多
        "background": {"enabled": False, "file": ""},  # 自定义背景图（文件存在 state/ 下）
        "analytics": False,       # 匿名统计（默认关；开了也不上报任何账号信息）
        "analyticsId": "",
        "stopOnExit": True,       # 关窗时是否停掉 NapCat / AstrBot
        "lastTab": "dashboard",
    },
    "server": {
        "preferredPort": 17650,
        "authMode": "local",      # local | lan —— 决定界面只绑本机还是允许局域网
        "password": "",
    },
    "deploy": {
        "dryRun": True,           # 演练模式：走完整状态机但不真的下载
        "proxy": "",
        "mirror": "auto",         # auto | tencent | github
        "accel": True,            # 下载 NapCat / AstrBot 时走加速镜像（国内直连常握手超时）
        "pipIndex": "https://pypi.tuna.tsinghua.edu.cn/simple",
        "astrbotMethod": "zip",   # zip | git
    },
    "services": {
        "napcat": {
            "autoRestart": True,
            "port": paths.DEFAULT_PORTS["napcat"],
            "command": "",
        },
        "astrbot": {
            "autoRestart": True,
            "port": paths.DEFAULT_PORTS["astrbot"],
            "command": "",
        },
    },
    "instances": [
        {
            "id": "bot1",
            "name": "主号",
            "qq": "",
            "token": "",
            "port": paths.DEFAULT_PORTS["onebot"],
            "napcatPort": paths.DEFAULT_PORTS["napcat"],
            "enabled": True,
            "createdAt": 0,
        }
    ],
    "llm": {
        # 中转站（烛心推荐的那家）。改这里可以换成别的 OpenAI 兼容网关。
        "relayBase": "https://worldcodes.online",
        "apiBase": "https://worldcodes.online/v1",
        "model": "",
        "personaId": "",
        # 多线路：按 priority 升序，第一条是主线路，其余交给 AstrBot 的
        # fallback_provider_ids 自动切换。
        "routes": [],
    },
    "backup": {
        "keep": 10,
        "scope": "all",
        "autoDaily": False,   # 每天第一次打开界面时自动备份一次
        "lastAuto": "",       # 上次自动备份的日期 YYYY-MM-DD
    },
    "terminal": {"cwd": "", "timeout": 60},
    "logs": {"maxLines": 2000, "compact": True, "autoScroll": True},
    "update": {"repo": "Zxin-Pro/astrbot-pc", "channel": "stable"},
}

_LOCK = threading.RLock()
_cache: dict[str, Any] | None = None


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict[str, Any]:
    global _cache
    with _LOCK:
        if _cache is not None:
            return _cache
        data: dict[str, Any] = {}
        try:
            if paths.CONFIG_FILE.exists():
                # utf-8-sig：Windows 记事本 / PowerShell 存出来的 BOM 也能读
                data = json.loads(paths.CONFIG_FILE.read_text("utf-8-sig"))
        except Exception:
            data = {}
        _cache = _deep_merge(DEFAULTS, data if isinstance(data, dict) else {})
        return _cache


def get(path: str, default: Any = None) -> Any:
    """``get("services.napcat.port")``。"""
    node: Any = load()
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def save(patch: dict[str, Any] | None = None) -> dict[str, Any]:
    """深合并 patch 后落盘，返回最新配置。"""
    global _cache
    with _LOCK:
        cur = copy.deepcopy(load())
        nxt = _deep_merge(cur, patch or {})
        paths.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = paths.CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(nxt, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, paths.CONFIG_FILE)
        _cache = nxt
        return nxt


def reset() -> dict[str, Any]:
    global _cache
    with _LOCK:
        _cache = None
        try:
            paths.CONFIG_FILE.unlink()
        except FileNotFoundError:
            pass
        return load()


def state_file(name: str) -> Path:
    paths.ensure_dirs()
    return paths.STATE_DIR / name


def read_state(name: str, default: Any = None) -> Any:
    p = state_file(name)
    try:
        return json.loads(p.read_text("utf-8-sig"))
    except Exception:
        return default


def write_state(name: str, value: Any) -> None:
    p = state_file(name)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, p)


def stamp() -> int:
    return int(time.time())
