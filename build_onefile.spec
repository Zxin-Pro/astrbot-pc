# -*- mode: python ; coding: utf-8 -*-
"""单文件版：一个 AstrBotPC.exe 双击即用，不需要旁边那堆文件。

代价是启动时要把自身解压到 %TEMP%\\_MEIxxxx，冷启动多 2–4 秒、体积约 45 MB；
对「拷一个文件到别人机器上就能跑」这种场景更省事，所以和 onedir 版一起发。
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

# onefile：binaries / datas 全部塞进 EXE，不生成 _internal
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="AstrBotPC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="build/app.ico",
    version="build/version_info.txt",
)
