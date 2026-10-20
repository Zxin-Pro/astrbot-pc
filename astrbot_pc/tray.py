"""托盘常驻：关掉窗口后程序还在后台跑，右键托盘点两下就能回来。

依赖 ``pystray`` + ``Pillow``（Windows 下走 ctypes 调 Shell，不需要 pywin32）。
任一缺失就安静地退回「关窗即退出」，不弹错误——托盘是加分项，不该拦住主流程。
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from . import config, paths

_icon: Any = None
_thread: threading.Thread | None = None
_callbacks: dict[str, Callable[[], None]] = {}


def available() -> bool:
    try:
        import PIL.Image  # noqa: F401
        import pystray  # noqa: F401
    except Exception:
        return False
    return True


def _make_image(size: int = 64) -> Any:
    """托盘图标：蓝底圆角方块 + 白色弯月 + 橙色圆点，和 favicon 一致。"""
    from PIL import Image, ImageDraw

    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 渐变底：从 #3B82F6 到 #2563EB
    top, bottom = (59, 130, 246), (37, 99, 235)
    radius = int(s * 0.26)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=radius, fill=255)
    grad = Image.new("RGBA", (s, s))
    gd = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / max(1, s - 1)
        gd.line([(0, y), (s, y)], fill=(
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
            255,
        ))
    img.paste(grad, (0, 0), mask)

    # 白色 S 形曲线：两段圆弧拼起来
    w = int(s * 0.11)
    pad = int(s * 0.24)
    d.arc((pad, pad - int(s * 0.02), s - pad, int(s * 0.56)), start=20, end=300, fill=(255, 255, 255, 255), width=w)
    d.arc((pad, int(s * 0.44), s - pad, s - pad - int(s * 0.02)), start=200, end=120, fill=(255, 255, 255, 255), width=w)

    # 暖色圆点
    r = int(s * 0.075)
    cx, cy = int(s * 0.76), int(s * 0.28)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(234, 88, 12, 255))

    return img.resize((size, size), Image.LANCZOS)


def _service_action(kind: str, want_running: bool) -> Callable[[], None]:
    """托盘菜单里的启停：丢到后台线程跑。

    停服务要等子进程收摊（最长十秒），起服务要等端口就绪（NapCat 最多二十秒）。
    直接写在菜单回调里会把 pystray 的消息循环堵死，右键菜单跟着卡住。
    """

    def run() -> None:
        try:
            from .services import manager

            if not want_running:
                res = manager.stop_all() or {}
                _balloon("已全部停止", "NapCat 与 AstrBot 都已退出"
                         if all(v.get("ok") for v in res.values()) else "有一个没停下来，看日志页")
            elif kind == "all":
                res = manager.start_all() or {}
                bad = [(k, v) for k, v in res.items() if not v.get("ok")]
                if bad:
                    _balloon("有服务没起来", str(bad[0][1].get("err") or "看日志页")[:120])
                else:
                    _balloon("已全部启动", "回到窗口可以看状态")
            else:
                res = manager.start(kind)
                _balloon("已启动" if res.get("ok") else "启动失败",
                         res.get("err") or "回到窗口看「服务」页")
            _notify_ui("status")
        except Exception as e:
            _balloon("操作失败", str(e)[:120] or "看日志页")

    def dispatch() -> None:
        _balloon("正在处理…", "完成后会再提示")
        threading.Thread(target=run, name="tray-action", daemon=True).start()

    return dispatch


def _notify_ui(reason: str) -> None:
    """推一条事件给界面，让托盘里的操作和窗口里的状态对得上。"""
    try:
        from .events import bus
        from .services import manager

        data = {"services": manager.status()} if reason == "status" else {}
        bus.emit(reason, data)
    except Exception:
        pass


def start(
    on_show: Callable[[], None] | None = None,
    on_quit: Callable[[], None] | None = None,
) -> bool:
    """起托盘线程。返回是否真的起来了。"""
    global _icon, _thread
    if _icon is not None:
        return True
    if not available():
        return False

    import pystray

    _callbacks["show"] = on_show or (lambda: None)
    _callbacks["quit"] = on_quit or (lambda: None)

    def show(icon: Any = None, item: Any = None) -> None:
        _callbacks["show"]()

    def quit_all(icon: Any = None, item: Any = None) -> None:
        _callbacks["quit"]()

    def start_all(icon: Any = None, item: Any = None) -> None:
        _service_action("all", True)()
        _notify_ui("status")

    def stop_all(icon: Any = None, item: Any = None) -> None:
        _service_action("all", False)()
        _notify_ui("status")

    def check_update(icon: Any = None, item: Any = None) -> None:
        from . import update

        res = update.check(force=True)
        if res.get("ok") and res.get("newer"):
            _balloon(f"发现新版本 {res['latest']}", "打开界面在「设置 → 关于」里看更新说明")
        elif res.get("ok"):
            _balloon("已经是最新版本", f"当前 v{res.get('current')}")
        else:
            _balloon("检查更新失败", res.get("err") or "稍后再试")

    menu = pystray.Menu(
        pystray.MenuItem("打开烛之控制台", show, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("全部启动", start_all),
        pystray.MenuItem("全部停止", stop_all),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("检查更新", check_update),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_all),
    )

    try:
        _icon = pystray.Icon(
            "astrbot_pc",
            _make_image(),
            f"{paths.APP_TITLE} · {paths.APP_SUBTITLE}",
            menu,
        )
    except Exception:
        _icon = None
        return False

    _thread = threading.Thread(target=_run_icon, name="tray", daemon=True)
    _thread.start()
    return True


def _run_icon() -> None:
    try:
        _icon.run()  # type: ignore[union-attr]
    except Exception:
        pass


def _balloon(title: str, text: str) -> None:
    try:
        _icon.notify(text, title)  # type: ignore[union-attr]
    except Exception:
        pass


def notify(title: str, text: str = "") -> None:
    if _icon is not None:
        _balloon(title, text)


def stop() -> None:
    global _icon, _thread
    icon, _icon = _icon, None
    _thread = None
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass


def running() -> bool:
    return _icon is not None


def wanted() -> bool:
    """用户是否希望关窗后留在托盘。"""
    return bool(config.get("app.minimizeToTray", True))
