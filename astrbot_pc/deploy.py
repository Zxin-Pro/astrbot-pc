"""部署向导：把「从零到能扫码登录」拆成 8 个可观察的步骤。

两条路线：

- ``dryRun``（默认）：只做环境检查与目录准备，下载/安装那几步只报计划不落盘，
  方便先把界面和流程跑通；
- 真实部署：联网拉 NapCat 与 AstrBot、建虚拟环境装依赖、写两边配置、拉起服务。

真实部署全程不断推进度：``progress`` 里有 ``received / total / percent / speed``，
界面据此画进度条，而不是干等一句「执行中…」。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from . import config, download, envcheck, paths, probe
from .events import bus

STAGES: list[dict[str, str]] = [
    {"key": "env", "name": "环境检查", "desc": "确认 Python、磁盘空间与网络都就位"},
    {"key": "dirs", "name": "准备目录", "desc": "建立数据目录与 stack 工作区"},
    {"key": "napcat", "name": "获取 NapCat", "desc": "下载 NapCat 并解压到 stack/napcat"},
    {"key": "astrbot", "name": "获取 AstrBot", "desc": "下载源码包并解压到 stack/astrbot"},
    {"key": "deps", "name": "安装依赖", "desc": "建虚拟环境，装好 AstrBot 的 Python 依赖"},
    {"key": "config", "name": "写入配置", "desc": "接线 OneBot 反向 WS 与 WebUI 端口"},
    {"key": "napcat-run", "name": "启动 NapCat", "desc": "拉起 NapCat 并等二维码出现"},
    {"key": "astrbot-run", "name": "启动 AstrBot", "desc": "拉起 AstrBot 并等 WebUI 就绪"},
]

NAPCAT_ZIP = "https://github.com/NapNeko/NapCatQQ/releases/latest/download/NapCat.Shell.Windows.Node.zip"
ASTRBOT_ZIP = "https://codeload.github.com/AstrBotDevs/AstrBot/zip/refs/heads/master"
ASTRBOT_REPO = "https://github.com/AstrBotDevs/AstrBot.git"

VENV_DIR = "venv"
PROGRESS_MIN_GAP = 0.25  # 进度事件最多每 0.25s 发一条，别把 SSE 淹了


def _accel_on() -> bool:
    """加速镜像默认开；用户填了自定义地址就完全按他填的来，不再掺镜像。"""
    val = config.get("deploy.accel", True)
    return bool(val)


def napcat_sources() -> list[str]:
    custom = (config.get("deploy.napcatUrl") or "").strip()
    if custom:
        return [custom]
    return download.candidates(NAPCAT_ZIP, _accel_on())


def astrbot_sources() -> list[str]:
    custom = (config.get("deploy.astrbotUrl") or "").strip()
    if custom:
        return [custom]
    return download.candidates(ASTRBOT_ZIP, _accel_on())


def stages() -> list[dict[str, Any]]:
    return [dict(s) for s in STAGES]


# ---------- 离线资源 ----------
#
# 离线版把 NapCat 包、AstrBot 源码包和一堆 wheel 放在 exe 旁边的 resources/ 里。
# 这么做的理由很实际：GitHub 直连握手超时是常态，pip 装 309 个包要六七分钟，
# 而这些东西本来就不会变——一次性带在包里，用户点「开始部署」时只做解压。

def local_napcat() -> Path | None:
    p = paths.RESOURCES_DIR / "napcat.zip"
    return p if p.is_file() else None


def local_astrbot() -> Path | None:
    p = paths.RESOURCES_DIR / "astrbot.zip"
    return p if p.is_file() else None


def local_wheels() -> Path | None:
    d = paths.RESOURCES_DIR / "wheels"
    if d.is_dir() and next(d.glob("*.whl"), None):
        return d
    return None


def local_python() -> Path | None:
    """懒人版内置的便携 Python（``resources\\python\\python.exe``）。"""
    p = paths.RESOURCES_DIR / "python" / "python.exe"
    return p if p.is_file() else None


def offline() -> dict[str, Any]:
    """离线包里带了什么。界面拿它决定显示不显示「不用联网」那行提示。"""
    wheels = paths.RESOURCES_DIR / "wheels"
    count = len(list(wheels.glob("*.whl"))) if wheels.is_dir() else 0
    has_napcat = local_napcat() is not None
    has_astrbot = local_astrbot() is not None
    has_python = local_python() is not None
    return {
        "dir": str(paths.RESOURCES_DIR),
        "napcat": has_napcat,
        "astrbot": has_astrbot,
        "wheels": count,
        "python": has_python,
        # 两个源码包都在，装的过程就不用联网了（依赖另说）
        "sources": has_napcat and has_astrbot,
        # 三样齐全才算「一步都不用联网」，界面按这个措辞
        "ready": has_napcat and has_astrbot and count > 0,
        # 连解释器都带上了 = 用户机器上一个 Python 都不用装
        "lazy": has_napcat and has_astrbot and count > 0 and has_python,
    }


def _empty_progress() -> dict[str, Any]:
    return {"key": "", "received": 0, "total": 0, "percent": 0, "speed": 0, "text": ""}


class DeployRunner:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self._last_progress = 0.0
        self._speed_mark = (0.0, 0)
        self.state: dict[str, Any] = {
            "running": False,
            "finished": False,
            "ok": False,
            "dryRun": True,
            "current": "",
            "message": "",
            "startedAt": 0,
            "finishedAt": 0,
            "progress": _empty_progress(),
            "steps": [{"key": s["key"], "name": s["name"], "desc": s["desc"],
                       "status": "pending", "detail": "", "ms": 0} for s in STAGES],
        }

    # ---------- 查询 ----------

    def status(self) -> dict[str, Any]:
        with self.lock:
            data = dict(self.state)
            data["steps"] = [dict(s) for s in self.state["steps"]]
            data["progress"] = dict(self.state["progress"])
        data["offline"] = offline()
        return data

    def _set(self, key: str, status: str, detail: str = "", ms: int = 0) -> None:
        with self.lock:
            for s in self.state["steps"]:
                if s["key"] == key:
                    s["status"] = status
                    if detail:
                        s["detail"] = detail
                    if ms:
                        s["ms"] = ms
            self.state["current"] = key
            self.state["message"] = detail
            if status != "running":
                self.state["progress"] = _empty_progress()
        bus.emit("deploy", self.status())

    def _progress(self, key: str, received: int, total: int, text: str = "") -> None:
        """节流后再发，避免一个 100 MB 的下载把事件总线刷爆。"""
        now = time.time()
        mark_t, mark_b = self._speed_mark
        speed = 0.0
        if now - mark_t >= 0.8:
            speed = max(0.0, (received - mark_b) / (now - mark_t))
            self._speed_mark = (now, received)
        with self.lock:
            self.state["progress"] = {
                "key": key,
                "received": received,
                "total": total,
                "percent": round(received * 100 / total, 1) if total else 0,
                "speed": round(speed / 1024 / 1024, 2),
                "text": text,
            }
            self.state["message"] = text or self.state["message"]
        if now - self._last_progress >= PROGRESS_MIN_GAP:
            self._last_progress = now
            bus.emit("deploy", self.status())

    # ---------- 控制 ----------

    def start(self, dry_run: bool = True) -> dict[str, Any]:
        if self.thread and self.thread.is_alive():
            return {"ok": False, "err": "部署已经在跑了"}
        self.cancel_flag.clear()
        self._speed_mark = (time.time(), 0)
        self._last_progress = 0.0
        with self.lock:
            self.state.update({
                "running": True, "finished": False, "ok": False, "dryRun": bool(dry_run),
                "current": "", "message": "准备开始", "startedAt": int(time.time()), "finishedAt": 0,
                "progress": _empty_progress(),
            })
            self.state["steps"] = [
                {"key": s["key"], "name": s["name"], "desc": s["desc"],
                 "status": "pending", "detail": "", "ms": 0} for s in STAGES
            ]
        self.thread = threading.Thread(target=self._run, args=(bool(dry_run),), daemon=True)
        self.thread.start()
        bus.emit("deploy", self.status())
        return {"ok": True}

    def cancel(self) -> dict[str, Any]:
        self.cancel_flag.set()
        with self.lock:
            self.state["message"] = "正在取消…"
        return {"ok": True}

    def _run(self, dry_run: bool) -> None:
        handlers: list[tuple[str, Callable[[bool], tuple[bool, str]]]] = [
            ("env", self._stage_env),
            ("dirs", self._stage_dirs),
            ("napcat", self._stage_napcat),
            ("astrbot", self._stage_astrbot),
            ("deps", self._stage_deps),
            ("config", self._stage_config),
            ("napcat-run", self._stage_napcat_run),
            ("astrbot-run", self._stage_astrbot_run),
        ]
        all_ok = True
        for key, fn in handlers:
            if self.cancel_flag.is_set():
                self._set(key, "skipped", "已取消")
                all_ok = False
                break
            self._set(key, "running", "执行中…")
            t0 = time.time()
            try:
                ok, detail = fn(dry_run)
            except Exception as e:  # 单步失败不该炸掉整个向导
                ok, detail = False, f"{type(e).__name__}: {e}"
            ms = int((time.time() - t0) * 1000)
            if self.cancel_flag.is_set() and ok:
                self._set(key, "skipped", "已取消", ms)
                all_ok = False
                break
            self._set(key, "done" if ok else "failed", detail, ms)
            if not ok:
                all_ok = False
                break

        with self.lock:
            if all_ok and dry_run:
                final = "演练通过：没有任何文件被安装。关掉演练模式再点一次才会真的装"
            elif all_ok:
                final = "全部完成"
            else:
                final = "未完成，请看失败步骤的说明"
            self.state.update({
                "running": False, "finished": True, "ok": all_ok,
                "message": final,
                "finishedAt": int(time.time()),
                "progress": _empty_progress(),
            })
        bus.emit("deploy", self.status())
        if all_ok and dry_run:
            notice = {"level": "info", "text": "演练结束，什么都没装上；关掉演练模式才会真装"}
        elif all_ok:
            notice = {"level": "success", "text": "部署流程结束"}
        else:
            notice = {"level": "error", "text": "部署中断，请查看步骤详情"}
        bus.emit("notice", notice)
        try:
            envcheck.snapshot(force=True)
        except Exception:
            pass

    # ---------- 各步骤 ----------

    def _stage_env(self, dry_run: bool) -> tuple[bool, str]:
        snap = envcheck.snapshot(force=True)
        # 按 key 判，别按 name——name 是给人看的文案，改一个字这里就静默失效
        missing = [i["key"] for i in snap["items"] if i["status"] == "missing"]
        if "python" in missing:
            return False, "缺少 Python，本机无法安装依赖"
        warn = [i["name"] for i in snap["items"] if i["status"] == "warn"]
        parts = [f"数据目录 {snap['dataRoot']}"]
        if warn:
            parts.append("注意：" + "、".join(warn))
        if not dry_run and "qq" in missing:
            parts.append("没装 QQ NT，NapCat 启动那步会失败")
        off = offline()
        if off["lazy"]:
            parts.append("懒人版：源码、依赖和 Python 都内置，全程不用联网也不用另装 Python")
        elif off["sources"]:
            parts.append("离线包已内置，不必联网")
            if not dry_run and not off["wheels"]:
                parts.append("但依赖还得从网上装")
        elif not dry_run:
            src = download.pick_source(napcat_sources(), timeout=8)
            if not src:
                return False, (
                    "连不上下载源。国内直连 GitHub 经常握手超时，"
                    "可以在设置里打开加速镜像，或填自己的代理地址后再试")
            host = urlsplit(src).netloc
            parts.append(f"下载源可用（{host}）")
        return True, "；".join(parts)

    def _stage_dirs(self, dry_run: bool) -> tuple[bool, str]:
        paths.ensure_dirs()
        for sub in ("astrbot", "napcat"):
            (paths.STACK_DIR / sub).mkdir(parents=True, exist_ok=True)
        (paths.TMP_DIR / "dl").mkdir(parents=True, exist_ok=True)
        return True, f"已准备 {paths.STACK_DIR}"

    def _acquire_zip(self, local: Path | None, urls: list[str], zip_path: Path,
                     key: str, label: str) -> tuple[Path, str, bool]:
        """拿到要解压的那个 zip：优先离线包，没有才联网。

        返回 ``(zip 路径, 进度文案里的来源词, 解压完要不要删)``。
        离线包是常驻资源，解压完不能删。
        """
        if local is not None:
            return local, "离线包", False
        self._progress(key, 0, 0, "正在挑下载源…")
        try:
            download.fetch(urls, zip_path, lambda got, total: self._progress(
                key, got, total, f"下载 {label} {download.human_size(got)}"
                + (f" / {download.human_size(total)}" if total else "")))
        except download.DownloadError as e:
            raise download.DownloadError(
                f"{e}；已试过直连与 {max(0, len(urls) - 1)} 个加速镜像，"
                f"换个网络、填自定义地址，或改用离线版安装包") from e
        return zip_path, "下载", True

    def _stage_napcat(self, dry_run: bool) -> tuple[bool, str]:
        target = paths.STACK_DIR / "napcat"
        existing = _napcat_ready(target)
        if existing:
            return True, f"已就绪：{existing}"
        local = local_napcat()
        if dry_run:
            return True, ("演练模式：解压离线包，不用联网" if local
                          else "演练模式：跳过下载（约 120 MB）")

        zip_path, source_txt, drop = self._acquire_zip(
            local, napcat_sources(), paths.TMP_DIR / "dl" / "napcat.zip", "napcat", "NapCat")

        self._progress("napcat", 100, 100, f"正在解压{source_txt}…")
        download.extract_zip(zip_path, target, lambda i, n: self._progress(
            "napcat", i, n, f"解压 {i}/{n}"))
        if drop:
            zip_path.unlink(missing_ok=True)

        ready = _napcat_ready(target)
        if not ready:
            return False, "解压完了但没找到启动器，检查压缩包内容"
        size = download.dir_size(target) / 1024 / 1024
        return True, f"已就绪（{ready}，{size:.0f} MB，来自{source_txt}）"

    def _stage_astrbot(self, dry_run: bool) -> tuple[bool, str]:
        target = paths.STACK_DIR / "astrbot"
        if (target / "main.py").exists():
            return True, "已存在源码"
        if target.exists() and any(target.iterdir()) and not (target / "main.py").exists():
            keep = {".git", "data", "venv"}
            if any(p.name not in keep for p in target.iterdir()):
                return False, "目录里已有别的内容，请先清空 stack/astrbot"
        local = local_astrbot()
        if dry_run:
            return True, ("演练模式：解压离线包，不用联网" if local
                          else "演练模式：跳过下载（源码包约 8 MB）")

        method = (config.get("deploy.astrbotMethod") or "zip").strip().lower()
        target.mkdir(parents=True, exist_ok=True)

        # 有离线包就别走 git 了——git 还要连 GitHub，正是离线包要躲开的东西
        if method == "git" and local is None:
            git = envcheck.check_git()
            if not git["ok"]:
                return False, "没有 Git，改成「下载压缩包」方式再试"
            mirror = (config.get("deploy.mirror") or "").strip()
            url = mirror or ASTRBOT_REPO
            self._progress("astrbot", 0, 0, "正在克隆 AstrBot 源码…")
            r = subprocess.run([git["path"], "clone", "--depth", "1", url, str(target)],
                               capture_output=True, text=True, timeout=900)
            if r.returncode != 0:
                return False, (r.stderr or r.stdout or "git clone 失败")[-400:]
            return True, f"已克隆到 {target}"

        zip_path, source_txt, drop = self._acquire_zip(
            local, astrbot_sources(), paths.TMP_DIR / "dl" / "astrbot.zip", "astrbot", "AstrBot")

        self._progress("astrbot", 100, 100, f"正在解压{source_txt}…")
        download.extract_zip(zip_path, target, lambda i, n: self._progress(
            "astrbot", i, n, f"解压 {i}/{n}"))
        if drop:
            zip_path.unlink(missing_ok=True)
        if not (target / "main.py").exists():
            found = download.find_dir(target, ("main.py",))
            if not found:
                return False, "解压完了但没找到 main.py"
            target = found
        return True, f"已就绪（{target}，来自{source_txt}）"

    def _stage_deps(self, dry_run: bool) -> tuple[bool, str]:
        target = paths.STACK_DIR / "astrbot"
        req = target / "requirements.txt"
        if not req.exists():
            if dry_run:
                return True, "演练模式：源码未就位，跳过 pip"
            return False, "找不到 requirements.txt"
        if dry_run:
            return True, "演练模式：跳过 pip install（可能耗时数分钟）"

        py = self._ensure_venv()
        if not py:
            base, _ver = envcheck.find_python()
            if not base:
                return False, ("找不到可用的 Python 解释器。建议改用「懒人版」安装包"
                               "（里面自带便携 Python），或自己装一个 3.10 以上版本"
                               "并勾选 Add to PATH")
            return False, f"虚拟环境建不起来（用的是 {base}），看看它的安装是否完整"
        wheels = local_wheels()
        index = (config.get("deploy.pipIndex") or "").strip()
        argv = [str(py), "-m", "pip", "install", "-r", str(req),
                "--disable-pip-version-check", "--no-input", "--progress-bar", "off"]
        if wheels is not None:
            argv += ["--no-index", "--find-links", str(wheels)]
            self._progress("deps", 0, 0, "正在从离线包安装依赖…")
        else:
            if index:
                argv += ["-i", index]
            self._progress("deps", 0, 0, "正在安装依赖，可能要几分钟…")
        code, tail = self._run_stream(argv, "deps", str(target))

        if code != 0 and wheels is not None:
            # 离线 wheel 是按打包时的 Python 版本挑的（cp312）。本机若是 3.13 之类
            # 就装不上——别把用户卡死，退回联网装，并说清楚为什么。
            self._progress("deps", 0, 0, "离线依赖装不上（Python 版本可能不同），改走网络…")
            retry = [str(py), "-m", "pip", "install", "-r", str(req),
                     "--disable-pip-version-check", "--no-input", "--progress-bar", "off"]
            if index:
                retry += ["-i", index]
            code, tail = self._run_stream(retry, "deps", str(target))
            if code == 0:
                return True, "依赖装好了（离线包版本对不上，这次走了网络）"

        if code != 0:
            return False, (tail or "pip 失败")[-600:].replace("\n", " ")
        return True, "依赖安装完成" + ("（来自离线包）" if wheels is not None else "")

    def _run_stream(self, argv: list[str], key: str, cwd: str) -> tuple[int, str]:
        """跑子进程并把最后一行输出当成进度推给界面，避免几分钟一片死寂。"""
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            return 1, f"启动失败：{e}"
        tail: list[str] = []
        last = 0.0
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if not line or line.startswith("Requirement already satisfied"):
                continue
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)
            now = time.time()
            if now - last >= PROGRESS_MIN_GAP:
                last = now
                if self.cancel_flag.is_set():
                    proc.terminate()
                    return 1, "已取消"
                self._progress(key, 0, 0, f"安装依赖 · {line[:80]}")
        return proc.wait(), "\n".join(tail)

    def _stage_config(self, dry_run: bool) -> tuple[bool, str]:
        inst = (config.get("instances") or [{}])[0]
        ws_port = int(inst.get("port") or paths.DEFAULT_PORTS["onebot"])
        napcat_port = int(inst.get("napcatPort") or paths.DEFAULT_PORTS["napcat"])
        webui_port = int(inst.get("astrbotPort") or paths.DEFAULT_PORTS["astrbot"])
        token = inst.get("token") or ""
        if dry_run:
            return True, f"演练模式：将写入 OneBot → ws://127.0.0.1:{ws_port}/ws"

        written: list[str] = []

        # NapCat 运行时先找 onebot11_<QQ>.json，没有就回退读 onebot11.json 再另存。
        # 部署时还不知道 QQ 号，所以写不带后缀的那份，登录后会自动复制过去。
        cfg_dir = paths.STACK_DIR / "napcat" / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "onebot11.json").write_text(
            json.dumps({
                "network": {
                    "websocketClients": [{
                        "name": "astrbot",
                        "enable": True,
                        "url": f"ws://127.0.0.1:{ws_port}/ws",
                        "messagePostFormat": "array",
                        "reportSelfMessage": False,
                        "token": token,
                        "debug": False,
                    }],
                    "httpServers": [],
                    "websocketServers": [],
                },
                "musicSignUrl": "",
                "enableLocalFile2Url": False,
                "parseMultMsg": False,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written.append(f"NapCat OneBot → {ws_port}")

        # AstrBot 只认 data/cmd_config.json，写进 data/config/ 会被当作不存在
        data_dir = paths.STACK_DIR / "astrbot" / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        conf_path = data_dir / "cmd_config.json"
        conf = {}
        if conf_path.exists():
            try:
                conf = json.loads(conf_path.read_text(encoding="utf-8-sig"))
            except Exception:
                conf = {}
        conf.setdefault("dashboard", {})
        conf["dashboard"].update({"enable": True, "host": "127.0.0.1", "port": webui_port})

        platforms = [p for p in (conf.get("platform") or [])
                     if not (isinstance(p, dict) and p.get("type") == "aiocqhttp")]
        platforms.append({
            "id": "astrbot-pc",
            "type": "aiocqhttp",
            "enable": True,
            "ws_reverse_host": "0.0.0.0",
            "ws_reverse_port": ws_port,
            "ws_reverse_token": token,
        })
        conf["platform"] = platforms
        conf_path.write_text(json.dumps(conf, ensure_ascii=False, indent=4), encoding="utf-8")
        written.append(f"AstrBot WebUI → {webui_port}")

        return True, "；".join(written)

    def _stage_napcat_run(self, dry_run: bool) -> tuple[bool, str]:
        if dry_run:
            return True, "演练模式：真机时这里会拉起 NapCat 并等二维码"
        from .services import manager

        res = manager.start("napcat")
        if not res.get("ok"):
            return False, res.get("err", "启动失败")
        port = int(config.get("services.napcat.port", paths.DEFAULT_PORTS["napcat"]))
        if not _wait(lambda: probe.tcp_open(port), 120):
            return False, "120 秒内没等到 NapCat WebUI，检查日志"
        return True, f"NapCat 已就绪，WebUI 端口 {port}"

    def _stage_astrbot_run(self, dry_run: bool) -> tuple[bool, str]:
        if dry_run:
            return True, "演练模式：真机时这里会拉起 AstrBot 并等 WebUI"
        from .services import manager

        res = manager.start("astrbot")
        if not res.get("ok"):
            return False, res.get("err", "启动失败")
        port = int(config.get("services.astrbot.port", paths.DEFAULT_PORTS["astrbot"]))
        if not _wait(lambda: probe.tcp_open(port), 180):
            return False, "180 秒内没等到 AstrBot WebUI，检查日志"
        return True, f"AstrBot 已就绪，WebUI 端口 {port}"

    # ---------- 工具 ----------

    def _ensure_venv(self) -> Path | None:
        """给 AstrBot 单独建虚拟环境，别把依赖装进本程序的 Python。"""
        venv = paths.STACK_DIR / VENV_DIR
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if py.exists():
            return py
        self._progress("deps", 0, 0, "正在创建虚拟环境…")
        # 打包成 exe 后 sys.executable 是 AstrBotPC.exe，它不认 -m venv
        base, _ver = envcheck.find_python()
        if not base:
            return None
        r = subprocess.run([base, "-m", "venv", str(venv)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0 or not py.exists():
            return None
        return py


def venv_python() -> Path | None:
    """AstrBot 用的解释器：有 venv 就用它，否则退回本程序的 Python。"""
    venv = paths.STACK_DIR / VENV_DIR
    for rel in ("Scripts/python.exe", "bin/python"):
        cand = venv / rel
        if cand.exists():
            return cand
    return None


def _napcat_ready(target: Path) -> str:
    """NapCat 装好的标志：能找到一个可执行的启动入口。"""
    for name in ("launcher.bat", "napcat.bat", "NapCatWinBootMain.exe", "napcat.mjs"):
        cand = target / name
        if cand.exists():
            return str(cand)
    found = download.find_dir(target, ("launcher.bat", "NapCatWinBootMain.exe", "napcat.mjs"), 2)
    if found:
        for name in ("launcher.bat", "napcat.bat", "NapCatWinBootMain.exe", "napcat.mjs"):
            if (found / name).exists():
                return str(found / name)
    return ""


def _wait(fn: Callable[[], bool], seconds: int) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def runner() -> DeployRunner:
    global _runner
    if _runner is None:
        _runner = DeployRunner()
    return _runner


_runner: "DeployRunner | None" = None


def status() -> dict[str, Any]:
    return runner().status()
