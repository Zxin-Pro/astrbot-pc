"""桌面壳：用 pywebview 把界面装进一个无边框窗口。

无边框 + 自绘标题栏才有原生桌面感，所以窗口控制（最小化/最大化/关闭）
走 ``js_api`` 暴露给前端；纯浏览器模式（``--web``）下前端会隐藏这些按钮。

关窗行为跟设置里「关闭时最小化到托盘」走：开着就只隐藏窗口，
程序留在托盘里继续跑；关掉才真的退出。
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

from . import config, paths, tray

#: 由 run() 填好，供托盘线程跨线程调用
_ref: dict[str, Any] = {"window": None, "quitting": False}


class WinApi:
    """前端能直接调到的窗口能力。

    注意：pywebview 会把 js_api 对象的**非下划线属性**递归当成命名空间暴露，
    所以窗口引用必须叫 ``_window``——叫 ``window`` 的话它会顺着
    ``Window.native`` 一路递归到栈溢出（Windows 上表现为启动即崩）。
    """

    def __init__(self) -> None:
        self._window: Any = None
        self._maximized = False

    def bind(self, window: Any) -> None:
        self._window = window

    def minimize(self) -> dict[str, Any]:
        try:
            self._window.minimize()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "err": str(e)}

    def toggle_max(self) -> dict[str, Any]:
        try:
            if self._maximized:
                self._window.restore()
            else:
                self._window.maximize()
            self._maximized = not self._maximized
            return {"ok": True, "maximized": self._maximized}
        except Exception as e:
            return {"ok": False, "err": str(e)}

    def close(self) -> dict[str, Any]:
        """右上角 × —— 按设置决定「藏到托盘」还是「真退出」。"""
        try:
            if _to_tray():
                self._window.hide()
                tray.notify("还在后台跑", "双击托盘图标可以叫回窗口")
                return {"ok": True, "hidden": True}
            _on_close()
            _ref["quitting"] = True
            tray.stop()
            self._window.destroy()
            return {"ok": True, "hidden": False}
        except Exception as e:
            return {"ok": False, "err": str(e)}

    def pick(self, kind: str = "zip") -> dict[str, Any]:
        """弹系统文件选择框，给「从文件恢复备份」用。

        Args:
            kind: zip 只筛 .zip，other 放开所有文件。

        Returns:
            {"ok": True, "path": 选中路径或空串}，失败时带 err。
        """
        import webview  # type: ignore

        try:
            types = ("备份包 (*.zip)",) if kind == "zip" else ("所有文件 (*.*)",)
            picked = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False, file_types=types)
            path = picked[0] if picked else ""
            return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "err": str(e)}

    def show(self) -> dict[str, Any]:
        return _show_window()

    def platform(self) -> dict[str, Any]:
        return {"ok": True, "os": sys.platform, "shell": True, "tray": tray.running()}

    def win(self, action: str) -> dict[str, Any]:
        """前端标题栏按钮的统一入口：min / max / close。"""
        act = (action or "").strip().lower()
        if act in ("min", "minimize"):
            return self.minimize()
        if act in ("max", "toggle", "toggle_max"):
            return self.toggle_max()
        if act in ("close", "quit", "exit"):
            return self.close()
        if act in ("show", "restore"):
            return self.show()
        return {"ok": False, "err": f"未知窗口操作：{action}"}


def _to_tray() -> bool:
    return tray.running() and tray.wanted()


def _show_window() -> dict[str, Any]:
    win = _ref.get("window")
    try:
        if win is not None:
            win.show()
            win.restore()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def _on_close() -> None:
    from .services import manager

    if config.get("app.stopOnExit", True):
        try:
            manager.stop_all()
        except Exception:
            pass


def _quit_app() -> None:
    """托盘菜单里的「退出」：真的收摊。"""
    _ref["quitting"] = True
    _on_close()
    tray.stop()
    win = _ref.get("window")
    try:
        if win is not None:
            win.destroy()
    except Exception:
        pass


def run(url: str) -> None:
    import webview  # type: ignore

    config.load()
    api = WinApi()
    window = webview.create_window(
        title=f"{paths.APP_TITLE} · {paths.APP_SUBTITLE}",
        url=url,
        width=1360,
        height=860,
        min_size=(1080, 720),
        frameless=True,
        easy_drag=True,
        js_api=api,
    )
    api.bind(window)
    _ref["window"] = window

    def on_closing() -> bool:
        # 点托盘「退出」时 _ref["quitting"] 已经是 True，这里直接放行
        if _ref.get("quitting"):
            return True
        if _to_tray():
            window.hide()
            tray.notify("还在后台跑", "右键托盘图标可以退出")
            return False
        _on_close()
        return True

    window.events.closing += on_closing

    def after_start() -> None:
        # 窗口起来之后再挂托盘，避免托盘图标先于窗口出现
        if tray.wanted() and tray.start(on_show=_show_window, on_quit=_quit_app):
            tray.notify("托盘已就绪", "点右上角 × 只会收起窗口，右键托盘图标可恢复或退出")

    def heartbeat() -> None:
        time.sleep(1.2)

    threading.Thread(target=heartbeat, daemon=True).start()
    webview.start(after_start, debug=bool(config.get("app.debug", False)), private_mode=False)
    tray.stop()
