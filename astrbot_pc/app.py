"""入口：`python -m astrbot_pc [--web] [--port 17650] [--debug]`。

三种跑法：
- 默认：起本地服务 + pywebview 桌面窗口；
- ``--web``：只起服务，浏览器访问（开发与截图验证都走这条）；
- ``--headless``：只起服务且不开浏览器，给脚本用。
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser

from . import config, paths, server


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="astrbot_pc", description="烛之控制台 · AstrBot PC 端")
    p.add_argument("--web", action="store_true", help="只起 HTTP 服务，用浏览器访问")
    p.add_argument("--headless", action="store_true", help="只起 HTTP 服务，不自动开浏览器")
    p.add_argument("--port", type=int, default=0, help="指定端口，默认 17650，占用则顺延")
    p.add_argument("--host", default="", help="监听地址；默认 127.0.0.1，设置里选「允许局域网」时为 0.0.0.0")
    p.add_argument("--debug", action="store_true", help="打开调试日志与窗口调试器")
    return p


def bootstrap() -> None:
    paths.ensure_dirs()
    config.load()
    _migrate()
    _prewarm()
    _update_check()


def _update_check() -> None:
    """启动时静默查一次新版，失败不影响任何事。"""
    try:
        from . import update

        update.maybe_check_async()
    except Exception:
        pass


def _prewarm() -> None:
    """体检要跑几个子进程，先在后台热一遍，界面首屏就不用等。"""
    from . import envcheck

    def run() -> None:
        try:
            envcheck.snapshot(force=True)
        except Exception:
            pass

    threading.Thread(target=run, name="envcheck-warm", daemon=True).start()


def _migrate() -> None:
    """老配置升级：补版本号，把早期占位的 authMode 正式化。"""
    cfg = config.load()
    patch: dict = {}
    if not cfg.get("app.version"):
        patch["app"] = {"version": __import__("astrbot_pc").__version__, "firstRun": True}
    if (cfg.get("server") or {}).get("authMode") == "none":
        patch.setdefault("server", {})["authMode"] = "local"
    if patch:
        config.save(patch)


def _bind_host() -> str:
    """设置里选了「允许局域网」才绑 0.0.0.0，否则只给本机用。"""
    return "0.0.0.0" if config.get("server.authMode", "local") == "lan" else "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    bootstrap()
    if args.debug:
        config.save({"app": {"debug": True}})

    srv = server.Server(args.host or _bind_host(), args.port)
    try:
        url = srv.start()
    except Exception as e:
        print(f"[错误] 启动失败：{e}", file=sys.stderr)
        return 2

    print(f"[烛之控制台] 服务已就绪：{url}")
    print(f"[烛之控制台] 数据目录：{paths.ROOT}")

    # 上次要是被强杀，子进程还挂着（NapCat 会一直连着 QQ），先收拾干净再干别的
    try:
        from .services import manager as _mgr

        for item in _mgr.reap_stale():
            print(f"[烛之控制台] 已清理残留进程 {item}")
    except Exception as e:
        print(f"[提示] 清理残留进程失败：{e}")

    if args.web or args.headless:
        if args.web:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            srv.stop()
            from .services import manager

            if config.get("app.stopOnExit", True):
                manager.stop_all()
        return 0

    try:
        from . import api, shell

        api.RUNTIME["shell"] = True
        shell.run(url)
    except ImportError:
        print("[提示] 没装 pywebview，已退回浏览器模式。执行 pip install pywebview 可获得桌面窗口。")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    finally:
        srv.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
