"""全局路径与产品常量。

数据目录默认落在 ``%LOCALAPPDATA%\\AstrBotPC``，可以用环境变量
``ASTRBOT_PC_HOME`` 覆盖（便携版、测试环境都靠它）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AstrBotPC"
APP_TITLE = "烛之控制台"
APP_SUBTITLE = "AstrBot 烛版 · PC 端"
APP_VERSION = "1.0.2"


def is_frozen() -> bool:
    """是不是 PyInstaller 打出来的 exe。"""
    return bool(getattr(sys, "frozen", False))


def _data_root() -> Path:
    env = os.environ.get("ASTRBOT_PC_HOME")
    if env:
        return Path(env).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _app_dir() -> Path:
    """源码模式在项目根；exe 模式在 PyInstaller 解出来的 `_MEIPASS`。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
UI_DIR = APP_DIR / "ui"


def _res_dir() -> Path:
    """离线资源目录：跟 exe 放在一起的 ``resources/``。

    不能用 ``APP_DIR``——PyInstaller 6 的 onedir 布局里 ``sys._MEIPASS`` 指向
    ``_internal/``，而用户解压出来看到的是 ``AstrBotPC.exe`` 和它旁边的文件夹。
    资源要出现在用户能看见的地方，所以认 ``sys.executable`` 的父目录。
    （单文件版同样适用：onefile 的 ``sys.executable`` 也是用户双击的那个真路径。）
    """
    if is_frozen():
        beside = Path(sys.executable).parent / "resources"
        if beside.is_dir():
            return beside
        meipass = Path(getattr(sys, "_MEIPASS", beside.parent))
        return meipass / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


RESOURCES_DIR = _res_dir()

ROOT = _data_root()
CONFIG_FILE = ROOT / "config.json"
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
BACKUP_DIR = ROOT / "backups"
STACK_DIR = ROOT / "stack"
INSTANCES_DIR = ROOT / "instances"
TMP_DIR = ROOT / "tmp"
DIAG_DIR = ROOT / "diagnostics"

#: 三个组件的默认端口（与手机版保持一致，方便两边串着用）
DEFAULT_PORTS = {
    "napcat": 6099,      # NapCat WebUI
    "astrbot": 6185,     # AstrBot 控制台
    "onebot": 6199,      # NapCat -> AstrBot 的反向 WebSocket
}

DIRS = (ROOT, STATE_DIR, LOG_DIR, BACKUP_DIR, STACK_DIR, INSTANCES_DIR, TMP_DIR, DIAG_DIR)


def ensure_dirs() -> None:
    for d in DIRS:
        d.mkdir(parents=True, exist_ok=True)


def rel(path: str | Path) -> str:
    """把绝对路径转成相对数据根的展示路径。"""
    try:
        p = Path(path).resolve()
        return str(p.relative_to(ROOT))
    except Exception:
        return str(path)
