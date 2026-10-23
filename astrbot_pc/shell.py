"""桌面壳：用 pywebview 把界面装进一个无边框窗口。

无边框 + 自绘标题栏才有原生桌面感，所以窗口控制（最小化/最大化/关闭）
走 ``js_api`` 暴露给前端；纯浏览器模式（``--web``）下前端会隐藏这些按钮。

关窗行为跟设置里「关闭时最小化到托盘」走：开着就只隐藏窗口，
程序留在托盘里继续跑；关掉才真的退出。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

from . import config, paths, tray

#: 由 run() 填好，供托盘线程跨线程调用
_ref: dict[str, Any] = {"window": None, "quitting": False}

#: 无边框窗口会丢掉 WS_MINIMIZEBOX：任务栏点图标不响应「最小化」，
#: 从任务栏还原也没有系统的窗口过渡动画（Windows 只在窗口可最小化时才做）。
#: WinForms 的 FormBorderStyle.None 不写这个样式位，只能自己补。
_GWL_STYLE = -16
_WS_MINIMIZEBOX = 0x00020000
_WS_SYSMENU = 0x00080000
_SWP_KEEP = 0x0001 | 0x0002 | 0x0004 | 0x0020  # NOSIZE | NOMOVE | NOZORDER | FRAMECHANGED
_SW_HIDE, _SW_SHOW, _SW_MINIMIZE, _SW_RESTORE, _SW_MAXIMIZE = 0, 5, 6, 9, 3
_GWL_WNDPROC = -4
_WM_GETMINMAXINFO = 0x0024
_MONITOR_DEFAULTTONEAREST = 2
#: 无边框窗口拿不到系统的还原动画（Windows 只给带标题栏的窗口做），只能自己淡入一段。
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_LWA_ALPHA = 0x00000002
_WM_SYSCOMMAND = 0x0112
_SC_RESTORE = 0xF120
_SC_MAXIMIZE = 0xF030
_SPI_GETCLIENTAREAANIMATION = 0x1042
_FADE_MS = 170
_FADE_START = 42

_ENUM_PROC: Any = None

try:  # 只在 Windows 桌面壳里装配，导入失败时整段退回 pywebview
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        _user32: Any = ctypes.WinDLL("user32", use_last_error=True)
        _user32.FindWindowW.restype = wintypes.HWND
        _user32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
        _user32.EnumWindows.restype = wintypes.BOOL
        _user32.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
        _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        _user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        _user32.GetWindowTextLengthW.restype = ctypes.c_int
        _user32.GetWindowTextLengthW.argtypes = (wintypes.HWND,)
        _user32.GetWindowTextW.restype = ctypes.c_int
        _user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        _user32.GetWindowLongW.restype = ctypes.c_long
        _user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        _user32.SetWindowLongW.restype = ctypes.c_long
        _user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
        _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        _user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
        _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        _user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
        _user32.CallWindowProcW.restype = ctypes.c_ssize_t
        _user32.CallWindowProcW.argtypes = (
            ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        )
        _user32.MonitorFromWindow.restype = wintypes.HANDLE
        _user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
        _user32.GetMonitorInfoW.restype = wintypes.BOOL
        _user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
        _user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        _user32.DefWindowProcW.restype = ctypes.c_ssize_t
        _user32.DefWindowProcW.argtypes = (
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        )

        _WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        class _POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        class _MINMAXINFO(ctypes.Structure):
            _fields_ = [
                ("ptReserved", _POINT),
                ("ptMaxSize", _POINT),
                ("ptMaxPosition", _POINT),
                ("ptMinTrackSize", _POINT),
                ("ptMaxTrackSize", _POINT),
            ]
        _user32.SetWindowPos.restype = wintypes.BOOL
        _user32.SetWindowPos.argtypes = (
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        )
        _user32.ShowWindow.restype = wintypes.BOOL
        _user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        _user32.IsIconic.restype = wintypes.BOOL
        _user32.IsIconic.argtypes = (wintypes.HWND,)
        _user32.IsZoomed.restype = wintypes.BOOL
        _user32.IsZoomed.argtypes = (wintypes.HWND,)
        _user32.IsWindowVisible.restype = wintypes.BOOL
        _user32.IsWindowVisible.argtypes = (wintypes.HWND,)
        _user32.SetForegroundWindow.restype = wintypes.BOOL
        _user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
        _user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
        _user32.SetLayeredWindowAttributes.argtypes = (
            wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD,
        )
        _user32.SystemParametersInfoW.restype = wintypes.BOOL
        _user32.SystemParametersInfoW.argtypes = (
            wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT,
        )
        _user32.RedrawWindow.restype = wintypes.BOOL
        _user32.RedrawWindow.argtypes = (
            wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
        )
    else:
        _user32 = None
        _WNDPROC = None
except Exception:  # pragma: no cover - 缺 ctypes 的怪环境
    _user32 = None
    _WNDPROC = None

#: WM_GETMINMAXINFO 子类化的状态：hwnd / 原窗口过程 / 回调（必须留着引用，否则被回收后崩）
_MMI: dict[str, Any] = {"hwnd": None, "prev": None, "proc": None}


def _title() -> str:
    return f"{paths.APP_TITLE} · {paths.APP_SUBTITLE}"


def _hwnd() -> Any:
    """找回**本进程**主窗口的 HWND；拿不到就返回 None，调用方退回 pywebview。

    不能按标题直接 FindWindowW：同时开着两个版本时标题一模一样，会抓错窗口。
    """
    if _user32 is None:
        return None
    try:
        pid = os.getpid()
        hit: list[int] = []
        title = _title()

        def _visit(hwnd: Any, _lparam: Any) -> bool:
            wpid = wintypes.DWORD(0)
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value != pid:
                return True
            size = _user32.GetWindowTextLengthW(hwnd)
            if size <= 0:
                return True
            buf = ctypes.create_unicode_buffer(size + 1)
            _user32.GetWindowTextW(hwnd, buf, size + 1)
            if buf.value == title:
                hit.append(hwnd)
                return False
            return True

        _user32.EnumWindows(_ENUM_PROC(_visit), 0)
        return hit[0] if hit else None
    except Exception:
        return None


def _ensure_frame(hwnd: Any) -> None:
    """补上最小化/系统菜单样式位，任务栏点图标才会最小化、还原才有动画。"""
    if _user32 is None or not hwnd:
        return
    style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
    want = style | _WS_MINIMIZEBOX | _WS_SYSMENU
    if want == style:
        return
    _user32.SetWindowLongW(hwnd, _GWL_STYLE, want)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, _SWP_KEEP)


_fade_lock = threading.Lock()
_fade_state: dict[str, Any] = {"busy": False}


def _anim_enabled() -> bool:
    """跟着系统的「显示动画」开关走：关掉动画的用户不该被我们硬塞一段。"""
    if _user32 is None:
        return False
    try:
        flag = wintypes.BOOL(1)
        ok = _user32.SystemParametersInfoW(
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(flag), 0
        )
        return bool(flag.value) if ok else True
    except Exception:
        return True


def _fade_begin(hwnd: Any) -> Any:
    """把窗口切成半透明分层窗口，返回原来的扩展样式；失败返回 None。

    必须在窗口显示**之前**调用：等它已经画出来了再压透明度，会先亮一帧再变暗。
    """
    if _user32 is None or not hwnd or not _anim_enabled():
        return None
    try:
        ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & 0xFFFFFFFF
        if ex & _WS_EX_LAYERED:
            return None
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex | _WS_EX_LAYERED))
        if not _user32.SetLayeredWindowAttributes(hwnd, 0, _FADE_START, _LWA_ALPHA):
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex))
            return None
        return ex
    except Exception:
        return None


def _fade_end(hwnd: Any, ex: Any) -> None:
    """把 _fade_begin 压下去的透明度淡回不透明，然后摘掉分层样式。"""
    if _user32 is None or not hwnd or ex is None:
        return
    with _fade_lock:
        if _fade_state["busy"]:
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex))
            return
        _fade_state["busy"] = True

    def _work() -> None:
        try:
            steps = 12
            gap = (_FADE_MS / 1000.0) / steps
            for i in range(steps + 1):
                t = i / steps
                alpha = int(_FADE_START + (255 - _FADE_START) * (1 - (1 - t) ** 3))
                _user32.SetLayeredWindowAttributes(hwnd, 0, alpha, _LWA_ALPHA)
                time.sleep(gap)
        except Exception:
            pass
        finally:
            try:
                _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex))
                # 摘掉分层后必须让客户区自己重画，否则会留一层旧的半透明位图
                _user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0080 | 0x0100)
            except Exception:
                pass
            with _fade_lock:
                _fade_state["busy"] = False

    threading.Thread(target=_work, name="win-fade", daemon=True).start()


def _fade_out(hwnd: Any, ms: int = 120) -> Any:
    """最小化前淡出，返回原扩展样式；调用方在窗口缩下去之后再 _fade_off()。

    无边框窗口没有系统的最小化动画，直接缩下去像"啪"地消失。淡到 70/255 再缩，
    观感上接近系统过渡。透明度必须在窗口缩下去之后再摘，否则会先亮回来一下。
    """
    if _user32 is None or not hwnd or not _anim_enabled():
        return None
    try:
        ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & 0xFFFFFFFF
        if ex & _WS_EX_LAYERED:
            return None
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex | _WS_EX_LAYERED))
        if not _user32.SetLayeredWindowAttributes(hwnd, 0, 255, _LWA_ALPHA):
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex))
            return None
        steps = 8
        gap = (ms / 1000.0) / steps
        for i in range(1, steps + 1):
            t = i / steps
            alpha = int(255 - (255 - 70) * (1 - (1 - t) ** 2))
            _user32.SetLayeredWindowAttributes(hwnd, 0, max(alpha, 70), _LWA_ALPHA)
            time.sleep(gap)
        return ex
    except Exception:
        return None


def _fade_off(hwnd: Any, ex: Any) -> None:
    """把 _fade_out 留下的分层样式摘掉；此时窗口已经最小化，看不见这一次跳变。"""
    if _user32 is None or not hwnd or ex is None:
        return
    try:
        _user32.SetLayeredWindowAttributes(hwnd, 0, 255, _LWA_ALPHA)
        _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ctypes.c_long(ex))
    except Exception:
        pass


def _dbg(msg: str) -> None:
    try:
        from . import paths

        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (paths.LOG_DIR / "shell.log").open("a", encoding="utf-8") as fh:
            fh.write(time.strftime("%H:%M:%S ") + msg + "\n")
    except Exception:
        pass


def _work_area(hwnd: Any) -> Any:
    """返回 (工作区, 显示器区域)；失败返回 None。"""
    try:
        mon = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        ptr = ctypes.cast(ctypes.byref(info), ctypes.c_void_p)
        if not mon or not _user32.GetMonitorInfoW(mon, ptr):
            return None
        return info.rcWork, info.rcMonitor
    except Exception as exc:  # pragma: no cover
        _dbg(f"WORKAREA-FAIL {exc!r}")
        return None


def _wndproc(hwnd: Any, msg: int, wparam: Any, lparam: Any) -> Any:
    """给无边框窗口补最大化边界：默认会连任务栏一起盖住，最大化后点不到任务栏。

    顺序很关键：先让原窗口过程按默认逻辑填一遍，再覆盖 MINMAXINFO。
    反过来写会被 WinForms/DefWindowProc 自己算的值盖回去，等于没改。
    """
    prev = _MMI.get("prev")
    # 从任务栏/最大化按钮还原之前先压透明度，等默认过程把窗口显示出来再淡回不透明，
    # 这样窗口不会先亮一帧。begin 拿不到（非 Windows/动画被关）就照常走。
    fade_ex = None
    if msg == _WM_SYSCOMMAND and (int(wparam) & 0xFFF0) in (_SC_RESTORE, _SC_MAXIMIZE):
        fade_ex = _fade_begin(hwnd)
    try:
        if prev:
            ret = _user32.CallWindowProcW(prev, hwnd, msg, wparam, lparam)
        else:
            ret = _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    except Exception as exc:  # pragma: no cover
        _dbg(f"WNDPROC-FAIL {exc!r}")
        ret = 0
    if fade_ex is not None:
        _fade_end(hwnd, fade_ex)
    if msg == _WM_GETMINMAXINFO and lparam:
        try:
            area = _work_area(hwnd)
            if area is not None:
                work, mon = area
                mmi = _MINMAXINFO.from_address(lparam)
                mmi.ptMaxPosition.x = work.left - mon.left
                mmi.ptMaxPosition.y = work.top - mon.top
                mmi.ptMaxSize.x = work.right - work.left
                mmi.ptMaxSize.y = work.bottom - work.top
            if area is None:
                _dbg("MMI-NOAREA")
        except Exception as exc:  # pragma: no cover
            _dbg(f"MMI-FAIL {exc!r}")
    return ret


def _hook_minmax(hwnd: Any) -> None:
    """装一次 WM_GETMINMAXINFO 钩子；WinForms 若重置了窗口过程就再装回去。"""
    if _user32 is None or _WNDPROC is None or not hwnd:
        return
    try:
        proc = _MMI.get("proc")
        if _MMI.get("hwnd") == hwnd and proc is not None:
            now = _user32.GetWindowLongPtrW(hwnd, _GWL_WNDPROC)
            if now == _cast_proc(proc):
                return
        fresh = _WNDPROC(_wndproc)
        prev = _user32.SetWindowLongPtrW(hwnd, _GWL_WNDPROC, _cast_proc(fresh))
        _MMI.update(hwnd=hwnd, prev=prev, proc=fresh)
        now = _user32.GetWindowLongPtrW(hwnd, _GWL_WNDPROC)
        _dbg(f"HOOK hwnd={hwnd} prev={prev} now={now} mine={_cast_proc(fresh)}")
    except Exception as exc:  # pragma: no cover
        _MMI.update(hwnd=None, prev=None, proc=None)
        _dbg(f"HOOK-FAIL {exc!r}")


def _cast_proc(proc: Any) -> int:
    return ctypes.cast(proc, ctypes.c_void_p).value or 0


def _watch_frame() -> None:
    """有别的框架会重置样式（缩放/DPI 变化），低频补一遍，别做重活。"""
    while not _ref.get("quitting"):
        hwnd = _hwnd()
        if hwnd:
            _ensure_frame(hwnd)
            _hook_minmax(hwnd)
        time.sleep(1.5)


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
        """最小化走 pywebview（WinForms WindowState）：WebView2 的合成表面会跟着状态走。

        早先这里直接调 ShowWindow(SW_MINIMIZE)，窗口是缩下去了，但 WebView2 不知道
        自己被最小化，还原后经常只剩一块白板。系统过渡动画由 WS_MINIMIZEBOX
        样式位决定（_ensure_frame 负责补），跟从哪条路调用无关。
        """
        try:
            hwnd = _hwnd()
            fade = None
            if hwnd:
                _ensure_frame(hwnd)
                fade = _fade_out(hwnd)
            self._window.minimize()
            _fade_off(hwnd, fade)
            return {"ok": True}
        except Exception as e:
            try:
                hwnd = _hwnd()
                if hwnd:
                    _user32.ShowWindow(hwnd, _SW_MINIMIZE)
                    return {"ok": True}
            except Exception:
                pass
            return {"ok": False, "err": str(e)}

    def toggle_max(self) -> dict[str, Any]:
        """最大化/还原同样交给 pywebview：WinForms 才知道 WebView2 要重排。

        最大化边界由 _wndproc 里的 WM_GETMINMAXINFO 钩子限制在工作区，
        所以无论走哪条路都不会盖住任务栏。
        """
        try:
            hwnd = _hwnd()
            if hwnd:
                _ensure_frame(hwnd)
                maximized = bool(_user32.IsZoomed(hwnd))
                if maximized:
                    self._window.restore()
                else:
                    self._window.maximize()
                self._maximized = not maximized
                return {"ok": True, "maximized": not maximized}
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
    """从托盘/任务栏叫回窗口。

    最小化状态用 SW_RESTORE：既保留「最大化时最小化」的原状态，又有系统还原动画；
    已经藏起来（托盘）的窗口用 pywebview 的 show() 把可见性状态同步回去。
    """
    win = _ref.get("window")
    try:
        hwnd = _hwnd()
        if hwnd:
            _ensure_frame(hwnd)
            if _user32.IsIconic(hwnd):
                # 还原交给 pywebview：直接 ShowWindow 会把 WebView2 的合成表面晾成白板。
                # 无边框窗口没有系统过渡动画，前后各补一段淡入。
                fade = _fade_begin(hwnd)
                if win is not None:
                    try:
                        win.restore()
                    except Exception:
                        _user32.ShowWindow(hwnd, _SW_RESTORE)
                else:
                    _user32.ShowWindow(hwnd, _SW_RESTORE)
                _fade_end(hwnd, fade)
                _user32.SetForegroundWindow(hwnd)
                return {"ok": True}
            if not _user32.IsWindowVisible(hwnd) and win is not None:
                fade = _fade_begin(hwnd)
                win.show()
                _fade_end(hwnd, fade)
            _user32.SetForegroundWindow(hwnd)
            return {"ok": True}
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
        hwnd = _hwnd()
        _ensure_frame(hwnd)
        _hook_minmax(hwnd)
        threading.Thread(target=_watch_frame, daemon=True).start()
        # 窗口起来之后再挂托盘，避免托盘图标先于窗口出现
        if tray.wanted() and tray.start(on_show=_show_window, on_quit=_quit_app):
            tray.notify("托盘已就绪", "点右上角 × 只会收起窗口，右键托盘图标可恢复或退出")

    def heartbeat() -> None:
        time.sleep(1.2)

    threading.Thread(target=heartbeat, daemon=True).start()
    webview.start(after_start, debug=bool(config.get("app.debug", False)), private_mode=False)
    tray.stop()
