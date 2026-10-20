# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：onedir + 无控制台窗口。

要点：
- `ui/` 必须原样带进去，`paths.UI_DIR` 在 exe 里指向 `_MEIPASS/ui`
- pywebview 自带 `__pyinstaller/hook-webview.py`，显式加进 hookspath 才稳
- Windows 后端靠 pythonnet（`clr`）+ WinForms，运行时 DLL 要一起收
- pystray 的后端是私有模块，PyInstaller 静态分析看不到，手动 hiddenimport
"""

import os

import webview
from PyInstaller.utils.hooks import collect_data_files

hook_dir = os.path.join(os.path.dirname(webview.__file__), "__pyinstaller")

datas = [("ui", "ui")]
datas += collect_data_files("pythonnet")

hiddenimports = [
    "clr",
    "pystray._win32",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[hook_dir],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc_data",
        "setuptools",
        "pip",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "webview.platforms.cef",
        "webview.platforms.android",
        "webview.platforms.cocoa",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AstrBotPC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="build/app.ico",
    version="build/version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AstrBotPC",
)
