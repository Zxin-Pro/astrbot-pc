"""本地 HTTP 服务：同源提供界面、接口与 SSE。

只绑 127.0.0.1，默认端口 17650（被占用就顺延）。没有外部依赖，
用标准库的 ThreadingHTTPServer 就够了 —— 这层薄到可以直接在 pywebview 里跑。
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import api, config, paths, stats
from .events import bus
from .services import manager

MAX_BODY = 4 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "AstrBotPC/1.0"
    protocol_version = "HTTP/1.1"

    # 安静一点：正常访问不打日志，出错才说
    def log_message(self, fmt: str, *args: Any) -> None:
        if getattr(self, "_quiet", True):
            return
        super().log_message(fmt, *args)

    # ---------- 基础 ----------

    def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8",
              extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _json(self, status: int, obj: dict[str, Any]) -> None:
        self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> dict[str, Any]:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n <= 0 or n > MAX_BODY:
            return {}
        raw = self.rfile.read(n)
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ---------- 路由 ----------

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle("HEAD")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle("PATCH")

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle("DELETE")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, b"", extra={"Allow": "GET, POST, PATCH, DELETE, OPTIONS"})

    def _handle(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        method = "GET" if method == "HEAD" else method

        if path in ("/events", "/api/events"):
            return self._sse(query)

        if path.startswith("/api/"):
            body = self._read_body() if method in ("POST", "PATCH", "PUT", "DELETE") else {}
            try:
                status, res = api.dispatch(method, path, query, body)
            except Exception as e:
                status, res = 500, {"ok": False, "err": f"{type(e).__name__}: {e}"}
            return self._json(status, res)

        return self._static(path)

    # ---------- SSE ----------

    def _sse(self, query: dict[str, list[str]]) -> None:
        sid, q = bus.subscribe()
        stop = threading.Event()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            since = int((query.get("since") or ["0"])[0] or 0)
            for msg in bus.since(since)[-50:]:
                self.wfile.write(b"data: " + json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n\n")
            self.wfile.flush()
            for chunk in bus.stream(sid, q, stop):
                try:
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
        except Exception:
            pass
        finally:
            stop.set()
            bus.unsubscribe(sid)

    # ---------- 静态文件 ----------

    def _static(self, path: str) -> None:
        root = paths.UI_DIR.resolve()
        rel = path.lstrip("/") or "index.html"
        if rel.endswith("/"):
            rel += "index.html"
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return self._json(403, {"ok": False, "err": "禁止访问"})

        if not target.is_file():
            if not path.startswith("/assets/"):
                target = root / "index.html"
            if not target.is_file():
                return self._json(404, {"ok": False, "err": "界面资源缺失"})

        ctype, _ = mimetypes.guess_type(str(target))
        ctype = ctype or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        try:
            data = target.read_bytes()
        except OSError as e:
            return self._json(500, {"ok": False, "err": str(e)})
        # 本地应用，文件都在磁盘上，永远让浏览器回源 —— 改了代码刷新就生效
        cache = "no-cache, must-revalidate"
        self._send(200, data, ctype, {"Cache-Control": cache})


class Server:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._tick_stop = threading.Event()

    def bind(self) -> int:
        preferred = self.port or int(config.get("server.preferredPort", 17650))
        last_err: Exception | None = None
        for cand in [preferred] + list(range(preferred + 1, preferred + 12)) + [0]:
            try:
                self.httpd = ThreadingHTTPServer((self.host, cand), Handler)
                self.httpd.daemon_threads = True
                self.port = self.httpd.server_address[1]
                api.set_server_port(self.port)
                return self.port
            except OSError as e:
                last_err = e
                continue
        raise RuntimeError(f"端口都占用了：{last_err}")

    def start(self) -> str:
        if self.httpd is None:
            self.bind()
        assert self.httpd is not None
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True)
        self.thread.start()
        manager.start_monitor()
        self._start_tick()
        self._hook_logs()
        return self.url

    def _start_tick(self) -> None:
        def loop() -> None:
            while not self._tick_stop.wait(2.0):
                try:
                    info = manager.states.get("astrbot")
                    online = bool(info and info.status == "running")
                    stats.tick(online)
                except Exception:
                    continue

        threading.Thread(target=loop, name="stats-tick", daemon=True).start()

    def _hook_logs(self) -> None:
        """日志里见到关键行就记一笔，顺便把异常推给界面。"""
        sid, q = bus.subscribe()

        def pump() -> None:
            while not self._tick_stop.is_set():
                try:
                    msg = q.get(timeout=5)
                except Exception:
                    continue
                if msg.get("kind") != "log":
                    continue
                data = msg.get("data") or {}
                lines = data.get("lines") or []
                levels = data.get("levels") or []
                msgs = sum(1 for l in lines if any(k in l for k in ("收到", "message", "[MSG]", "←")))
                errs = sum(1 for lv in levels if lv == "error")
                if msgs:
                    stats.note("message", msgs)
                if errs:
                    stats.note("error", errs)

        threading.Thread(target=pump, name="log-pump", daemon=True).start()

    @property
    def url(self) -> str:
        # 绑 0.0.0.0 时给用户的地址仍然写 127.0.0.1——打开浏览器得有个能连的地址
        host = "127.0.0.1" if self.host in ("", "0.0.0.0", "::") else self.host
        return f"http://{host}:{self.port}"

    def stop(self) -> None:
        self._tick_stop.set()
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass


def pick_free_port(start: int) -> int:
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_forever(host: str = "127.0.0.1", port: int = 0) -> str:
    srv = Server(host, port)
    url = srv.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
    return url
