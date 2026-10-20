"""服务管理：把 NapCat 与 AstrBot 当两个受管子进程来带。

设计要点（和手机版对齐）：
- 每个服务一个 pid 文件、一个日志文件、一份最近状态；
- 停止走进程树（``taskkill /T /F``），不留孤儿 Chromium；
- 守护线程每 2 秒体检一次，掉线按退避策略自动拉起，连续失败会熔断；
- 所有状态变化都往事件总线发一条，界面不用轮询也能实时变色。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, envcheck, paths, probe
from .events import bus

MAX_LOG_BYTES = 20 * 1024 * 1024
KEEP_LOG_BYTES = 2 * 1024 * 1024
RESTART_BACKOFF = [2, 5, 10, 30, 60]
FAIL_WINDOW_SEC = 600
FAIL_LIMIT = 5


def now() -> int:
    return int(time.time())


def _creationflags() -> int:
    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def _child_env() -> dict[str, str]:
    """子进程统一走 UTF-8。

    输出被重定向到文件时，Windows 上的 Python 会退回 GBK，中文日志变乱码，
    带 emoji 的日志行还会抛 UnicodeEncodeError 直接丢掉。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def rotate_log(p: Path) -> None:
    """日志超过 20 MB 就截成末尾 2 MB，跟手机版同一条规则。"""
    try:
        if not p.exists() or p.stat().st_size <= MAX_LOG_BYTES:
            return
        with p.open("rb") as f:
            f.seek(-KEEP_LOG_BYTES, os.SEEK_END)
            tail = f.read()
        p.write_bytes("…（前文已截断）\n".encode("utf-8") + tail)
    except Exception:
        pass


@dataclass
class ServiceState:
    key: str
    name: str
    port: int = 0
    pid: int = 0
    started_at: int = 0
    status: str = "stopped"          # stopped | starting | running | crashed | blocked
    message: str = ""
    restarts: int = 0
    fails: list[float] = field(default_factory=list)
    log: str = ""
    command: str = ""


class ServiceManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.states: dict[str, ServiceState] = {
            "napcat": ServiceState("napcat", "NapCat"),
            "astrbot": ServiceState("astrbot", "AstrBot"),
        }
        self._procs: dict[str, subprocess.Popen] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_emit = 0.0

    # ---------- 生命周期 ----------

    def start_monitor(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="svc-monitor", daemon=True)
        self._thread.start()

    def stop_monitor(self) -> None:
        self._stop.set()

    # ---------- 命令解析 ----------

    def resolve_command(self, key: str) -> tuple[list[str], str]:
        """返回 (argv, cwd)。没装好就抛 RuntimeError，消息直接给界面看。"""
        cfg = config.get(f"services.{key}", {}) or {}
        custom = (cfg.get("command") or "").strip()
        python = sys.executable

        if key == "astrbot":
            hit = envcheck._first_existing(envcheck.ASTRBOT_SEARCH)
            if custom:
                return _split(custom), str(hit or paths.STACK_DIR)
            if not hit:
                raise RuntimeError("AstrBot 还没装好，请先走一遍部署向导")
            root = Path(hit)
            # 有虚拟环境就用它，依赖才装得全
            from .deploy import venv_python

            venv = venv_python()
            runner = str(venv) if venv else python
            for entry in ("main.py", "astrbot.py"):
                if (root / entry).exists():
                    return [runner, entry], str(root)
            raise RuntimeError("AstrBot 目录里找不到 main.py，可能装坏了")

        if key == "napcat":
            hit = envcheck._first_existing(envcheck.NAPCAT_SEARCH)
            if custom:
                base = Path(hit) if hit else paths.STACK_DIR
                return _split(custom), str(base.parent if base.is_file() else base)
            if not hit:
                raise RuntimeError("NapCat 还没装好，请先走一遍部署向导")
            root = Path(hit)
            base = root.parent if root.is_file() else root
            for name in ("launcher.bat", "napcat.bat", "start.bat"):
                cand = base / name
                if cand.exists():
                    return ["cmd", "/c", str(cand)], str(base)
            # NapCat.Shell.Windows.Node 包里自带 node，直接跑 napcat.mjs
            mjs = base / "napcat.mjs"
            if mjs.exists():
                node = base / "node.exe"
                if not node.exists():
                    node = Path(shutil.which("node") or "")
                if node and Path(node).exists():
                    return [str(node), str(mjs)], str(base)
                raise RuntimeError("NapCat 需要 node.exe，包解压不完整")
            boot = base / "NapCatWinBootMain.exe"
            if boot.exists():
                qq = envcheck._first_existing(envcheck.QQ_SEARCH)
                if not qq:
                    raise RuntimeError("没装 QQ NT，NapCat 找不到可注入的宿主")
                return [str(boot), qq], str(base)
            raise RuntimeError("NapCat 目录里找不到启动器")

        raise RuntimeError(f"未知服务：{key}")

    # ---------- 启停 ----------

    def start(self, key: str) -> dict[str, Any]:
        st = self.states[key]
        with self.lock:
            if st.status in ("running", "starting"):
                return {"ok": True, "status": st.status, "message": "已经在运行"}
            try:
                argv, cwd = self.resolve_command(key)
            except RuntimeError as e:
                st.status = "stopped"
                st.message = str(e)
                self._emit()
                return {"ok": False, "err": str(e)}

            log_path = paths.LOG_DIR / f"{key}.log"
            paths.ensure_dirs()
            rotate_log(log_path)
            try:
                fh = open(log_path, "ab", buffering=0)
                fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 {st.name} =====\n".encode("utf-8"))
                proc = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=_creationflags(),
                    env=_child_env(),
                )
            except Exception as e:
                st.status = "crashed"
                st.message = f"启动失败：{e}"
                self._emit()
                return {"ok": False, "err": st.message}

            self._procs[key] = proc
            st.pid = proc.pid
            st.started_at = now()
            st.status = "starting"
            st.message = ""
            st.command = " ".join(argv)
            st.log = str(log_path)
            config.write_state(f"svc-{key}.json", {
                "pid": proc.pid, "startedAt": st.started_at, "command": st.command, "log": st.log,
            })
            self._emit()
            return {"ok": True, "pid": proc.pid, "status": st.status}

    def stop(self, key: str, quiet: bool = False) -> dict[str, Any]:
        st = self.states[key]
        with self.lock:
            proc = self._procs.pop(key, None)
            pid = st.pid or (proc.pid if proc else 0)
            if pid:
                _kill_tree(pid)
            if proc:
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
            st.pid = 0
            st.status = "stopped"
            st.started_at = 0
            st.message = "已手动停止"
            try:
                config.state_file(f"svc-{key}.json").unlink()
            except Exception:
                pass
            if not quiet:
                self._emit()
            return {"ok": True, "status": st.status}

    def restart(self, key: str) -> dict[str, Any]:
        self.stop(key, quiet=True)
        time.sleep(1.0)
        return self.start(key)

    def start_all(self) -> dict[str, Any]:
        order = ["napcat", "astrbot"]
        out = {}
        for k in order:
            out[k] = self.start(k)
            # NapCat 没起来就别干等端口，干等只会让「一键启动」显得卡住
            if k == "napcat" and out[k].get("ok"):
                _wait_port(self.states[k].port or paths.DEFAULT_PORTS["napcat"], 20)
        return out

    def stop_all(self) -> dict[str, Any]:
        return {k: self.stop(k) for k in ("astrbot", "napcat")}

    def reap_stale(self) -> list[str]:
        """清掉上一次没正常退出留下的子进程。

        应用被强制结束（任务管理器、断电、崩溃）时子进程会变孤儿：NapCat 还连着
        QQ，下次启动再拉一个就会端口冲突。这里按记录下来的 PID 收拾，且只认
        本程序数据目录下的可执行文件，避免 PID 复用误杀别人的进程。
        """
        killed: list[str] = []
        for key in ("astrbot", "napcat"):
            try:
                data = config.read_state(f"svc-{key}.json") or {}
            except Exception:
                continue
            pid = int(data.get("pid") or 0)
            if not pid or not _pid_alive(pid):
                if pid:
                    config.state_file(f"svc-{key}.json").unlink(missing_ok=True)
                continue
            if not _owned_by_stack(pid):
                config.state_file(f"svc-{key}.json").unlink(missing_ok=True)
                continue
            _kill_tree(pid)
            killed.append(f"{key}:{pid}")
            config.state_file(f"svc-{key}.json").unlink(missing_ok=True)
        return killed

    # ---------- 状态 ----------

    def status(self) -> dict[str, Any]:
        with self.lock:
            items = {}
            for key, st in self.states.items():
                port = config.get(f"services.{key}.port", paths.DEFAULT_PORTS[key])
                st.port = int(port or 0)
                running = bool(st.pid) and _pid_alive(st.pid)
                listening = probe.tcp_open(st.port) if st.port else False
                if st.status == "stopped" and running:
                    st.status = "running"
                if running and st.status != "blocked":
                    st.status = "running" if listening else ("starting" if now() - st.started_at < 90 else "running")
                elif not running and st.status in ("running", "starting"):
                    st.status = "crashed"
                    st.message = "进程已退出"
                items[key] = {
                    "key": key,
                    "name": st.name,
                    "status": st.status,
                    "pid": st.pid,
                    "port": st.port,
                    "uptime": max(0, now() - st.started_at) if st.pid else 0,
                    "listening": listening,
                    "message": st.message,
                    "restarts": st.restarts,
                    "log": st.log or str(paths.LOG_DIR / f"{key}.log"),
                    "command": st.command,
                    "autoRestart": bool(config.get(f"services.{key}.autoRestart", True)),
                    "resources": self._resources(st.pid),
                }
            return items

    def _resources(self, pid: int) -> dict[str, Any]:
        if not pid:
            return {"cpu": 0.0, "rss": 0, "procs": 0}
        try:
            import psutil  # type: ignore

            try:
                root = psutil.Process(pid)
            except Exception:
                return {"cpu": 0.0, "rss": 0, "procs": 0}
            procs = [root]
            try:
                procs += root.children(recursive=True)
            except Exception:
                pass
            rss = 0
            cpu = 0.0
            for p in procs:
                try:
                    rss += p.memory_info().rss
                    cpu += p.cpu_percent(interval=None)
                except Exception:
                    continue
            return {"cpu": round(cpu, 1), "rss": rss, "procs": len(procs)}
        except Exception:
            return {"cpu": 0.0, "rss": 0, "procs": 0}

    def onepass(self) -> None:
        """一次体检：刷新状态、必要时自动重启。"""
        st_all = self.status()
        changed = False
        for key, st in self.states.items():
            info = st_all[key]
            if info["status"] == "crashed" and info["autoRestart"]:
                st.fails = [t for t in st.fails if time.time() - t < FAIL_WINDOW_SEC]
                if len(st.fails) >= FAIL_LIMIT:
                    if st.status != "blocked":
                        st.status = "blocked"
                        st.message = "10 分钟内连续失败 5 次，已停止自动重启"
                        bus.emit("notice", {
                            "level": "error",
                            "text": f"{st.name} 连续崩溃，已熔断自动重启",
                        })
                        changed = True
                    continue
                delay = RESTART_BACKOFF[min(len(st.fails), len(RESTART_BACKOFF) - 1)]
                last = st.fails[-1] if st.fails else 0
                if time.time() - last >= delay:
                    st.fails.append(time.time())
                    st.restarts += 1
                    bus.emit("notice", {
                        "level": "warn",
                        "text": f"{st.name} 掉线，正在第 {st.restarts} 次自动拉起",
                    })
                    self.start(key)
                    changed = True
        if changed or time.time() - self._last_emit > 1.5:
            self._emit()

    def _emit(self) -> None:
        self._last_emit = time.time()
        bus.emit("status", {"services": self.status(), "ts": now()})

    def _loop(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.onepass()
            except Exception:
                continue


def _split(cmd: str) -> list[str]:
    """按 Windows 习惯拆命令。

    posix=False 会把引号留在 token 里，`"C:\\Python\\python.exe" ...` 直接找不到文件，
    而 Windows 上带空格的路径几乎一定要加引号，所以这里手工剥一层。
    """
    import shlex

    try:
        parts = shlex.split(cmd, posix=False)
    except Exception:
        parts = cmd.split()
    out: list[str] = []
    for p in parts:
        if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'":
            p = p[1:-1]
        out.append(p)
    return out


def _owned_by_stack(pid: int) -> bool:
    """PID 是否属于本程序数据目录下的进程（防止 PID 复用误杀）。"""
    try:
        import psutil  # type: ignore

        p = psutil.Process(pid)
        exe = (p.exe() or "").lower()
        root = str(paths.STACK_DIR).lower()
        if exe.startswith(root):
            return True
        # cmd.exe / 系统解释器本身不在 stack 下，看命令行有没有引用 stack
        try:
            cmd = " ".join(p.cmdline() or []).lower()
        except Exception:
            cmd = ""
        return root in cmd or root in exe
    except Exception:
        return False


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        import psutil  # type: ignore

        return psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except Exception:
        return False


def _kill_tree(pid: int) -> None:
    try:
        if not _pid_alive(pid):
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def _wait_port(port: int, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if probe.tcp_open(port):
            return True
        time.sleep(0.4)
    return False


manager = ServiceManager()
