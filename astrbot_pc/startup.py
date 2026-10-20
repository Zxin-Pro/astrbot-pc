"""开机自启：在 HKCU 的 Run 键里放一条命令，卸载时删掉。

只用当前用户（HKCU），不碰 HKLM —— 不需要管理员权限，卸载干净。
命令指向 pythonw.exe + 包里的 `__main__`，所以不会闪黑框。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

APP_KEY = "AstrBotPC"
RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.is_file() else exe)


def _command() -> str:
    """exe 版直接指自己；源码版指 pythonw + launcher。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    root = Path(__file__).resolve().parent.parent
    launcher = root / "launch_gui.pyw"
    if launcher.is_file():
        return f'"{_pythonw()}" "{launcher}"'
    return f'"{_pythonw()}" -m astrbot_pc'


def status() -> dict[str, Any]:
    if os.name != "nt":
        return {"supported": False, "enabled": False, "command": ""}
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_PATH) as key:
            try:
                value, _ = winreg.QueryValueEx(key, APP_KEY)
            except FileNotFoundError:
                return {"supported": True, "enabled": False, "command": ""}
            return {"supported": True, "enabled": bool(value), "command": str(value)}
    except OSError:
        return {"supported": False, "enabled": False, "command": ""}


def set_enabled(enabled: bool) -> dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "err": "这个系统不支持开机自启"}
    try:
        import winreg

        if enabled:
            cmd = _command()
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, RUN_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, APP_KEY, 0, winreg.REG_SZ, cmd)
            return {"ok": True, "enabled": True, "command": cmd}
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, RUN_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            try:
                winreg.DeleteValue(key, APP_KEY)
            except FileNotFoundError:
                pass
        return {"ok": True, "enabled": False, "command": ""}
    except OSError as e:
        return {"ok": False, "err": f"写注册表失败：{e}"}
