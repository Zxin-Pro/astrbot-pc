"""服务管理：每个实例一对 NapCat / AstrBot 受管子进程。

1.5.0 之前只有全局一对进程；现在状态表和进程表都按 (实例 id, 角色) 索引，
每个实例有自己的 ASTRBOT_ROOT、NAPCAT_WORKDIR、端口和日志。共享的只有源码树、
虚拟环境和 NapCat 安装包。对外仍保留 manager.start("astrbot") 这种写法，
默认操作当前实例，避免旧调用全炸。
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

from . import config, envcheck, paths, probe, runtime
from .events import bus

MAX_LOG_BYTES = 20 * 1024 * 1024
KEEP_LOG_BYTES = 2 * 1024 * 1024
RESTART_BACKOFF = [2, 5, 10, 30, 60]
FAIL_WINDOW_SEC = 600
FAIL_LIMIT = 5
ROLES = ("napcat", "astrbot")


def now() -> int:
    return int(time.time())


def _creationflags() -> int:
    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return flags


def _child_env(iid: str = "", role: str = "") -> dict[str, str]:
    """子进程统一走 UTF-8，并注入实例隔离变量。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if iid:
        env["ASTRBOT_PC_INSTANCE"] = iid
    if role == "astrbot" and iid:
        root = runtime.astrbot_root(iid)
        env["ASTRBOT_ROOT"] = str(root)
        env["DASHBOARD_PORT"] = str(runtime.port(iid, "astrbot"))
        env["ASTRBOT_DASHBOARD_PORT"] = str(runtime.port(iid, "astrbot"))
        env["ASTRBOT_DASHBOARD_HOST"] = "127.0.0.1"
    if role == "napcat" and iid and runtime.protocol(iid) == "snowluma":
        # SnowLuma 的数据目录 = cwd，另外它自己认这几个 SNOWLUMA_* 变量。
        sdir = runtime.snowluma_dir(iid)
        env["SNOWLUMA_ACCEPT_EULA"] = "1"
        env["SNOWLUMA_ACCEPT_PRIVACY"] = "1"
        env["SNOWLUMA_WEBUI_PORT"] = str(runtime.port(iid, "napcat"))
        env["SNOWLUMA_WEBUI_HOST"] = "127.0.0.1"
        env["SNOWLUMA_WEBUI_TLS"] = "0"
        env["SNOWLUMA_ONEBOT_HTTP_PORT"] = "0"
        env["SNOWLUMA_ONEBOT_WS_PORT"] = "0"
        env["SNOWLUMA_HOOK_AUTOLOAD"] = "1"
        env["SNOWLUMA_UPDATE_CHECK"] = "0"
        env["SNOWLUMA_LOG_DIR"] = str(sdir / "logs")
        return env
    if role == "napcat" and iid:
        inst = runtime.get(iid) or {}
        ndir = runtime.napcat_workdir(iid)
        env["NAPCAT_WORKDIR"] = str(ndir)
        env["NAPCAT_WEBUI_PREFERRED_PORT"] = str(runtime.port(iid, "napcat"))
        # 没设就让 NapCat 用出厂令牌，别留空（NapCat 会把空值随机化，用户登不进 WebUI）
        secret = str(inst.get("napcatSecret") or "") or paths.DEFAULT_NAPCAT_SECRET
        env["NAPCAT_WEBUI_SECRET_KEY"] = secret
        base = _napcat_base()
        if base:
            env.setdefault("NAPCAT_MAIN_PATH", str(base / "napcat.mjs"))
            env.setdefault("NAPCAT_INJECT_PATH", str(base / "NapCatWinBootHook.dll"))
            env.setdefault("NAPCAT_LOAD_PATH", str(base / "loadNapCat.js"))
            env.setdefault("NAPCAT_PATCH_PACKAGE", str(base / "qqnt.json"))
            env.setdefault("NAPCAT_LAUNCHER_PATH", str(base / "NapCatWinBootMain.exe"))
    return env


def rotate_log(p: Path) -> None:
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
    iid: str
    key: str
    name: str
    port: int = 0
    pid: int = 0
    started_at: int = 0
    status: str = "stopped"
    message: str = ""
    restarts: int = 0
    fails: list[float] = field(default_factory=list)
    log: str = ""
    command: str = ""


class ServiceManager:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.states: dict[tuple[str, str], ServiceState] = {}
        self._procs: dict[tuple[str, str], subprocess.Popen] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_emit = 0.0

    # ---------- 基础 ----------

    def _iid(self, iid: str | None = None) -> str:
        if iid:
            hit = runtime.get(iid)
            return str((hit or {}).get("id") or iid)
        return runtime.active_id() or "bot1"

    def _get(self, iid: str, key: str) -> ServiceState:
        k = (iid, key)
        if key == "napcat":
            # 同一个 key 可能是 NapCat 也可能是 SnowLuma，名字跟着实例走
            name = "SnowLuma" if runtime.protocol(iid) == "snowluma" else "NapCat"
        else:
            name = "AstrBot"
        if k not in self.states:
            self.states[k] = ServiceState(iid, key, name)
        else:
            self.states[k].name = name
        return self.states[k]

    def _role_enabled(self, iid: str, key: str) -> bool:
        inst = runtime.get(iid) or {}
        if inst and not bool(inst.get("enabled", True)):
            return False
        return bool(config.get(f"services.{key}.autoRestart", True))

    def start_monitor(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="svc-monitor", daemon=True)
        self._thread.start()

    def stop_monitor(self) -> None:
        self._stop.set()

    # ---------- 命令解析 ----------

    def resolve_command(self, key: str, iid: str | None = None) -> tuple[list[str], str]:
        sid = self._iid(iid)
        runtime.ensure(sid)
        cfg = config.get(f"services.{key}", {}) or {}
        custom = (cfg.get("command") or "").strip()
        python = sys.executable

        if key == "astrbot":
            hit = envcheck._first_existing(envcheck.ASTRBOT_SEARCH)
            if custom:
                base = runtime.astrbot_root(sid)
                return _split(custom), str(base if base.exists() else (hit or paths.STACK_DIR))
            if not hit:
                raise RuntimeError("AstrBot 还没装好，请先走一遍部署向导")
            root = Path(hit)
            from .deploy import venv_python

            venv = venv_python()
            runner = str(venv) if venv else python
            for entry in ("main.py", "astrbot.py"):
                if (root / entry).exists():
                    return [runner, str(root / entry)], str(root)
            raise RuntimeError("AstrBot 目录里找不到 main.py，可能装坏了")

        if key == "napcat":
            from . import snowluma

            if runtime.protocol(sid) == "snowluma":
                if custom:
                    cwd = runtime.snowluma_dir(sid)
                    return _split(custom), str(cwd)
                node = snowluma.node_exe()
                mjs = snowluma.index_js()
                if not node or not mjs.exists():
                    raise RuntimeError("SnowLuma 还没装好，请先在「扩展 · 组件更新」里装它")
                snowluma.ensure_dirs(sid)
                # QQ 是宿主，先确保它在跑（SnowLuma 会自己注入进去）
                qq = snowluma.ensure_qq()
                if not qq.get("ok"):
                    raise RuntimeError(str(qq.get("err") or "没能启动 QQ"))
                snowluma.write_config(sid)
                # index.mjs 必须绝对路径；cwd 是实例数据根
                return [str(node), str(mjs.resolve())], str(snowluma.workdir(sid))
            base = _napcat_base()
            if custom:
                cwd = runtime.napcat_workdir(sid)
                return _split(custom), str(cwd if cwd.exists() else (base or paths.STACK_DIR))
            if not base:
                raise RuntimeError("NapCat 还没装好，请先走一遍部署向导")
            inst = runtime.get(sid) or {}
            uin = str(inst.get("qq") or "").strip()
            mjs = base / "napcat.mjs"
            boot = base / "NapCatWinBootMain.exe"
            hook = base / "NapCatWinBootHook.dll"
            user_bat = base / "launcher-user.bat"
            if mjs.exists() and boot.exists():
                qq = _find_qq()
                if qq:
                    argv = [str(boot), qq]
                    if hook.exists():
                        argv.append(str(hook))
                    if uin:
                        argv += ["-q", uin]
                    return argv, str(base)
                if user_bat.exists():
                    return ["cmd", "/c", str(user_bat)], str(base)
                raise RuntimeError("没找到 QQ.exe；NapCat 需要 QQ NT 做宿主")
            if user_bat.exists():
                return ["cmd", "/c", str(user_bat)], str(base)
            if mjs.exists():
                node = base / "node.exe"
                if not node.exists():
                    found = shutil.which("node")
                    node = Path(found) if found else None
                if node and node.exists():
                    return [str(node), str(mjs)], str(base)
                raise RuntimeError("NapCat 需要 node.exe，包解压不完整")
            if boot.exists():
                qq = _find_qq()
                if not qq:
                    raise RuntimeError("没装 QQ NT，NapCat 找不到可注入的宿主")
                argv = [str(boot), qq]
                if uin:
                    argv += ["-q", uin]
                return argv, str(base)
            raise RuntimeError("NapCat 目录里找不到启动器")

        raise RuntimeError(f"未知服务：{key}")

    # ---------- 启停 ----------

    def start(self, key: str, iid: str | None = None) -> dict[str, Any]:
        sid = self._iid(iid)
        st = self._get(sid, key)
        with self.lock:
            if st.status in ("running", "starting"):
                return {"ok": True, "status": st.status, "message": "已经在运行", "iid": sid}
            inst = runtime.get(sid)
            if not inst:
                return {"ok": False, "err": "实例不存在", "iid": sid}
            if not bool(inst.get("enabled", True)):
                return {"ok": False, "err": "这个实例已停用", "iid": sid}
            runtime.ensure(sid)
            try:
                argv, cwd = self.resolve_command(key, sid)
            except RuntimeError as e:
                st.status = "stopped"
                st.message = str(e)
                self._emit()
                return {"ok": False, "err": str(e), "iid": sid}

            log_path = runtime.log_path(sid, key)
            paths.ensure_dirs()
            rotate_log(log_path)
            try:
                fh = open(log_path, "ab", buffering=0)
                fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 {st.name} · {sid} =====\n".encode("utf-8"))
                proc = subprocess.Popen(
                    argv,
                    cwd=cwd,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=_creationflags(),
                    env=_child_env(sid, key),
                )
            except Exception as e:
                st.status = "crashed"
                st.message = f"启动失败：{e}"
                try:
                    from . import crash

                    crash.record("service", f"{st.name} 启动失败", detail=str(e), key=f"{sid}:{key}")
                except Exception:
                    pass
                self._emit()
                return {"ok": False, "err": st.message, "iid": sid}

            self._procs[(sid, key)] = proc
            st.pid = proc.pid
            st.started_at = now()
            st.status = "starting"
            st.message = ""
            st.command = " ".join(argv)
            st.log = str(log_path)
            config.write_state(f"svc-{sid}-{key}.json", {
                "pid": proc.pid, "iid": sid, "role": key,
                "startedAt": st.started_at, "command": st.command, "log": st.log,
            })
            self._emit()
            return {"ok": True, "pid": proc.pid, "status": st.status, "iid": sid}

    def stop(self, key: str, iid: str | None = None, quiet: bool = False) -> dict[str, Any]:
        sid = self._iid(iid)
        st = self._get(sid, key)
        with self.lock:
            proc = self._procs.pop((sid, key), None)
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
                config.state_file(f"svc-{sid}-{key}.json").unlink()
            except Exception:
                pass
            if not quiet:
                self._emit()
            return {"ok": True, "status": st.status, "iid": sid}

    def restart(self, key: str, iid: str | None = None) -> dict[str, Any]:
        self.stop(key, iid, quiet=True)
        time.sleep(1.0)
        return self.start(key, iid)

    def start_all(self, iid: str | None = None) -> dict[str, Any]:
        sid = self._iid(iid)
        out: dict[str, Any] = {}
        for k in ROLES:
            out[k] = self.start(k, sid)
            if k == "napcat" and out[k].get("ok"):
                _wait_port(runtime.port(sid, "napcat"), 20)
        return out

    def start_all_instances(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for inst in runtime.instances():
            sid = str(inst.get("id") or "")
            if sid and inst.get("enabled", True):
                out[sid] = self.start_all(sid)
        return out

    def stop_all(self, iid: str | None = None) -> dict[str, Any]:
        if iid:
            sid = self._iid(iid)
            return {k: self.stop(k, sid) for k in reversed(ROLES)}
        out: dict[str, Any] = {}
        for inst in runtime.instances():
            sid = str(inst.get("id") or "")
            if sid:
                out[sid] = {k: self.stop(k, sid, quiet=True) for k in reversed(ROLES)}
        return out

    def reap_stale(self) -> list[str]:
        killed: list[str] = []
        try:
            files = list(paths.STATE_DIR.glob("svc-*.json"))
        except Exception:
            files = []
        for f in files:
            try:
                data = config.read_state(f.name) or {}
            except Exception:
                continue
            pid = int(data.get("pid") or 0)
            if not pid or not _pid_alive(pid):
                f.unlink(missing_ok=True)
                continue
            if not _owned_by_root(pid):
                f.unlink(missing_ok=True)
                continue
            _kill_tree(pid)
            killed.append(f"{data.get('iid') or 'legacy'}:{data.get('role') or f.stem}:{pid}")
            f.unlink(missing_ok=True)
        return killed

    # ---------- 状态 ----------

    def _status_one(self, sid: str, key: str) -> dict[str, Any]:
        st = self._get(sid, key)
        st.port = runtime.port(sid, key)
        running = bool(st.pid) and _pid_alive(st.pid)
        listening = probe.tcp_open(st.port) if st.port else False
        if st.status == "stopped" and running:
            st.status = "running"
        if running:
            st.status = "running"
        elif st.status in ("running", "starting"):
            st.status = "crashed"
            st.message = "进程已退出"
            _note_crash(sid, key, st)
        inst = runtime.get(sid) or {}
        return {
            "key": key,
            "iid": sid,
            "instance": inst.get("name") or sid,
            "qq": inst.get("qq") or "",
            "name": st.name,
            "status": st.status,
            "pid": st.pid,
            "port": st.port,
            "uptime": max(0, now() - st.started_at) if st.pid else 0,
            "listening": listening,
            "message": st.message,
            "restarts": st.restarts,
            "autoRestart": self._role_enabled(sid, key),
            "log": st.log or str(runtime.log_path(sid, key)),
            "command": st.command,
            "resources": self._resources(st.pid),
        }

    def status(self, iid: str | None = None) -> dict[str, Any]:
        sid = self._iid(iid)
        with self.lock:
            return {key: self._status_one(sid, key) for key in ROLES}

    def status_all(self) -> list[dict[str, Any]]:
        with self.lock:
            active = runtime.active_id()
            out = []
            for inst in runtime.instances():
                sid = str(inst.get("id") or "")
                if not sid:
                    continue
                svc = {key: self._status_one(sid, key) for key in ROLES}
                out.append({
                    "id": sid,
                    "name": inst.get("name") or sid,
                    "qq": inst.get("qq") or "",
                    "enabled": bool(inst.get("enabled", True)),
                    "active": sid == active,
                    "root": str(runtime.instance_dir(sid)),
                    "ports": {
                        "onebot": runtime.port(sid, "onebot"),
                        "napcat": runtime.port(sid, "napcat"),
                        "astrbot": runtime.port(sid, "astrbot"),
                    },
                    "services": svc,
                    "running": any(v.get("status") in ("running", "starting") for v in svc.values()),
                })
            return out

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
        changed = False
        with self.lock:
            keys = list(self.states.keys())
            for sid, key in keys:
                try:
                    info = self._status_one(sid, key)
                except Exception:
                    continue
                st = self._get(sid, key)
                if info["status"] == "crashed" and info["autoRestart"]:
                    st.fails = [t for t in st.fails if time.time() - t < FAIL_WINDOW_SEC]
                    if len(st.fails) >= FAIL_LIMIT:
                        if st.status != "blocked":
                            st.status = "blocked"
                            st.message = "10 分钟内连续失败 5 次，已停止自动重启"
                            bus.emit("notice", {
                                "level": "error",
                                "text": f"{st.name}（{sid}）连续崩溃，已熔断自动重启",
                            })
                            try:
                                from . import crash

                                crash.record("service", f"{st.name} 连续崩溃，已停止自动重启",
                                             detail=f"10 分钟内失败 {len(st.fails)} 次", key=f"{sid}:{key}")
                            except Exception:
                                pass
                            changed = True
                        continue
                    delay = RESTART_BACKOFF[min(len(st.fails), len(RESTART_BACKOFF) - 1)]
                    last = st.fails[-1] if st.fails else 0
                    if time.time() - last >= delay:
                        st.fails.append(time.time())
                        st.restarts += 1
                        bus.emit("notice", {
                            "level": "warn",
                            "text": f"{st.name}（{sid}）掉线，正在第 {st.restarts} 次自动拉起",
                        })
                        self.start(key, sid)
                        changed = True
        if changed or time.time() - self._last_emit > 1.5:
            self._emit()

    def _emit(self) -> None:
        self._last_emit = time.time()
        try:
            bus.emit("status", {
                "services": self.status(),
                "instances": self.status_all(),
                "ts": now(),
            })
        except Exception:
            pass

    def _loop(self) -> None:
        while not self._stop.wait(2.0):
            try:
                self.onepass()
            except Exception:
                continue


def _note_crash(iid: str, key: str, st: ServiceState) -> None:
    try:
        from . import crash, logs

        detail = f"实例 {iid}，端口 {st.port}，PID {st.pid}"
        if st.started_at:
            detail += time.strftime("，启动于 %Y-%m-%d %H:%M:%S", time.localtime(st.started_at))
        try:
            res = logs.tail(str(st.log or runtime.log_path(iid, key)), 40, compact=True)
            tail = "\n".join(res.get("lines") or [])[-1800:]
            if tail:
                detail += "\n\n最后几行：\n" + tail
        except Exception:
            pass
        crash.record("service", f"{st.name} 意外退出", detail=detail, key=f"{iid}:{key}")
    except Exception:
        pass


def _find_qq() -> str:
    hit = envcheck._first_existing(envcheck.QQ_SEARCH)
    if hit:
        return hit
    try:
        import winreg  # type: ignore

        for root, key in (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\QQ"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\QQ"),
        ):
            try:
                with winreg.OpenKey(root, key) as k:
                    val, _ = winreg.QueryValueEx(k, "UninstallString")
                    p = Path(str(val).strip('"')).parent / "QQ.exe"
                    if p.is_file():
                        return str(p)
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _napcat_base() -> Path | None:
    """找到含 napcat.mjs / 启动器的目录。"""
    hit = envcheck._first_existing(envcheck.NAPCAT_SEARCH)
    cands: list[Path] = []
    if hit:
        p = Path(hit)
        cands.append(p if p.is_dir() else p.parent)
    root = paths.STACK_DIR / "napcat"
    if root.is_dir():
        cands.append(root)
        cands.append(root / "napcat")
        cands.append(root / "bootmain")
        try:
            for mjs in root.rglob("napcat.mjs"):
                cands.append(mjs.parent)
                break
        except Exception:
            pass
    seen: set[str] = set()
    for base in cands:
        try:
            key = str(base.resolve()).lower()
        except Exception:
            key = str(base).lower()
        if key in seen:
            continue
        seen.add(key)
        if (base / "napcat.mjs").exists() or (base / "NapCatWinBootMain.exe").exists():
            return base
    return None


def _split(cmd: str) -> list[str]:
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


def _owned_by_root(pid: int) -> bool:
    try:
        import psutil  # type: ignore

        p = psutil.Process(pid)
        exe = (p.exe() or "").lower()
        root = str(paths.ROOT).lower()
        if exe.startswith(root):
            return True
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
