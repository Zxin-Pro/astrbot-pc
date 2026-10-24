"""SnowLuma 协议端：与 NapCat 并存的另一种 QQ → OneBot 后端。

为什么要有这个文件：NapCat 守着 QQ 的启动链（注入 Hook 后拉 QQ），SnowLuma 反过来
——先有 QQ 在跑，它再挂上去，把会话翻成 OneBot v11。两套东西对 AstrBot 来说是同一
件事（都是反向 WS 连到 ws://127.0.0.1:<onebotPort>/ws），所以差异全部收在这里：
安装位置、启动命令、环境变量、配置文件名。

两条实测得来的硬约束（别改）：
1. SnowLuma 的数据目录就是进程的工作目录（config/、logs/ 都按 cwd 找）。
   每个实例必须给独立 cwd，否则多开会互相抢配置。
2. index.mjs 必须传绝对路径启动；传相对路径 + cwd=数据目录会报
   Cannot find module ...\\index.mjs。
"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from . import config, download, envcheck, paths, runtime

REPO = "SnowLuma/SnowLuma"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ZIP_SUFFIX = "win-x64.zip"
ZIP_SUFFIX_LITE = "win-x64-lite.zip"
FALLBACK_VERSION = "2.1.1"
FALLBACK_URL = (
    f"https://github.com/{REPO}/releases/download/v{FALLBACK_VERSION}/"
    f"SnowLuma-v{FALLBACK_VERSION}-win-x64.zip"
)
CACHE_SEC = 1800


def base() -> Path:
    """共享安装目录（一份程序，多个实例各自跑）。"""
    return paths.STACK_DIR / "snowluma"


def index_js() -> Path:
    return base() / "index.mjs"


def node_exe() -> Path | None:
    local = base() / "node.exe"
    if local.is_file():
        return local
    try:
        import shutil

        hit = shutil.which("node")
    except Exception:
        hit = None
    return Path(hit) if hit and Path(hit).is_file() else None


def ready() -> str:
    """装好了就返回一句人话，没装返回空串。"""
    if not index_js().is_file():
        return ""
    node = node_exe()
    if not node:
        return ""
    ver = version()
    return f"SnowLuma {ver}（{node.name}）" if ver else f"SnowLuma（{node.name}）"


def version() -> str:
    try:
        data = json.loads((base() / "release.json").read_text(encoding="utf-8"))
        return str(data.get("version") or "").strip()
    except Exception:
        return ""


def workdir(iid: str | None = None) -> Path:
    """实例私有数据目录（SnowLuma 的 cwd）。"""
    return runtime.instance_dir(iid) / "snowluma"


def config_dir(iid: str | None = None) -> Path:
    return workdir(iid) / "config"


def ensure_dirs(iid: str | None = None) -> None:
    for p in (config_dir(iid), workdir(iid) / "logs"):
        try:
            p.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


# ---------- 版本与下载 ----------

def _cache_file() -> Path:
    return paths.STATE_DIR / "snowluma-release.json"


def release(force: bool = False) -> dict[str, Any]:
    """最新发行版（30 分钟缓存）。失败时退回内置版本号，不让页面挂掉。"""
    try:
        cached = json.loads(_cache_file().read_text(encoding="utf-8"))
    except Exception:
        cached = {}
    if not force and cached and time.time() - float(cached.get("ts") or 0) < CACHE_SEC:
        return cached

    out: dict[str, Any] = {"version": FALLBACK_VERSION, "url": FALLBACK_URL,
                           "notes": "", "ts": time.time()}
    try:
        import urllib.request

        req = urllib.request.Request(API_LATEST, headers={
            "User-Agent": f"AstrBotPC/{paths.APP_VERSION}",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        tag = str(data.get("tag_name") or "").strip().lstrip("vV")
        best = None
        for asset in data.get("assets") or []:
            name = str(asset.get("name") or "")
            if not name.endswith(ZIP_SUFFIX) or name.endswith(ZIP_SUFFIX_LITE):
                continue
            best = asset
            break
        if tag:
            out["version"] = tag
        if best:
            out["url"] = str(best.get("browser_download_url") or out["url"])
            out["bytes"] = int(best.get("size") or 0)
        out["notes"] = str(data.get("body") or "")[:400]
        out["ok"] = True
    except Exception as e:
        out["err"] = f"{type(e).__name__}: {e}"
    try:
        paths.ensure_dirs()
        _cache_file().write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return out


def sources(force: bool = False) -> list[str]:
    custom = (config.get("deploy.snowlumaUrl") or "").strip()
    if custom:
        return [custom]
    url = str(release(force).get("url") or FALLBACK_URL)
    return download.candidates(url, bool(config.get("deploy.accel", True)))


def install(zip_path: Path, progress=None) -> tuple[bool, str]:
    """把发行包解开到 stack/snowluma。"""
    target = base()
    target.mkdir(parents=True, exist_ok=True)
    try:
        download.extract_zip(zip_path, target, progress or (lambda i, n: None))
    except Exception as e:
        return False, f"解压失败：{e}"
    if not index_js().is_file():
        found = download.find_dir(target, ("index.mjs",))
        if found and found != target:
            for item in list(found.iterdir()):
                dest = target / item.name
                if dest.exists():
                    continue
                try:
                    item.rename(dest)
                except Exception:
                    pass
    if not index_js().is_file():
        return False, "解压完了但没找到 index.mjs，检查压缩包内容"
    if not (base() / "node.exe").is_file():
        return False, "包里没有 node.exe（是不是下了 -lite 版？要完整版）"
    ver = version()
    return True, (f"SnowLuma {ver} 已就绪" if ver else "SnowLuma 已就绪") + f"（{base()}）"


# ---------- 配置 ----------

def onebot_config(iid: str | None = None) -> dict[str, Any]:
    """一份把 AstrBot 接进来的 OneBot 配置：只留反向 WS 客户端。"""
    inst = runtime.get(iid) or {}
    token = str(inst.get("token") or "").strip()
    port = runtime.port(iid, "onebot")
    sid = str(inst.get("id") or iid or "bot1")
    client: dict[str, Any] = {
        "name": f"astrbot-{sid}",
        "enabled": True,
        "url": f"ws://127.0.0.1:{port}/ws",
        "role": "Universal",
        "messageFormat": "array",
        "reportSelfMessage": False,
        "reconnectIntervalMs": 3000,
    }
    if token:
        client["accessToken"] = token
    # httpServers / wsServers 一律留空：多实例并行时 3000/3001 会撞，
    # 而 AstrBot 只认反向 WS，用不到它们。
    return {
        "networks": {
            "httpServers": [],
            "httpClients": [],
            "wsServers": [],
            "wsClients": [client],
        },
        "statusCommand": {"enabled": False, "swallow": False,
                          "cooldownSeconds": 5, "trigger": "#sl"},
        "historySync": {"enabled": False},
        "notifications": {"channelIds": []},
    }


def write_config(iid: str | None = None) -> dict[str, Any]:
    """写 runtime.json 与 OneBot 配置。幂等，可反复调。"""
    sid = runtime.active_id() if iid is None else iid
    inst = runtime.get(sid) or {}
    if not inst:
        return {"ok": False, "err": "实例不存在"}
    ensure_dirs(sid)
    cfg = config_dir(sid)
    port = runtime.port(sid, "napcat")
    written: list[str] = []

    runtime_cfg = {
        "webuiPort": int(port or 5099),
        "webuiHost": "127.0.0.1",
        "hookAutoLoad": True,
        "webuiTls": {"enabled": False},
        "trustProxy": "",
        "logMaxTotalMb": 256,
        "logRetainDays": 3,
        "logPerUin": False,
    }
    try:
        (cfg / "runtime.json").write_text(
            json.dumps(runtime_cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append("runtime.json")
    except Exception as e:
        return {"ok": False, "err": f"写 runtime.json 失败：{e}"}

    body = onebot_config(sid)
    try:
        (cfg / "onebot.json").write_text(
            json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append("onebot.json")
        uin = str(inst.get("qq") or "").strip()
        if uin:
            # 有 QQ 号时再写一份 per-uin 快照，SnowLuma 优先读它
            snapshot = dict(body)
            snapshot["mode"] = "snapshot"
            (cfg / f"onebot_{uin}.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written.append(f"onebot_{uin}.json")
    except Exception as e:
        return {"ok": False, "err": f"写 OneBot 配置失败：{e}"}

    return {
        "ok": True,
        "iid": sid,
        "files": written,
        "workdir": str(workdir(sid)),
        "webui": f"http://127.0.0.1:{port}",
        "ws": f"ws://127.0.0.1:{runtime.port(sid, 'onebot')}/ws",
    }


def info(iid: str | None = None) -> dict[str, Any]:
    sid = runtime.active_id() if iid is None else iid
    inst = runtime.get(sid) or {}
    rel = release()
    have = version()
    return {
        "ok": True,
        "iid": sid,
        "installed": bool(ready()),
        "ready": ready(),
        "version": have,
        "latest": rel.get("version") or "",
        "newer": bool(have and rel.get("version") and have != rel.get("version")),
        "base": str(base()),
        "workdir": str(workdir(sid)),
        "port": runtime.port(sid, "napcat"),
        "webui": f"http://127.0.0.1:{runtime.port(sid, 'napcat')}",
        "ws": f"ws://127.0.0.1:{runtime.port(sid, 'onebot')}/ws",
        "qq": str(inst.get("qq") or ""),
        "repo": f"https://github.com/{REPO}",
    }


# ---------- QQ 宿主 ----------

def _qq_running() -> bool:
    try:
        import psutil

        for p in psutil.process_iter(["name"]):
            if str(p.info.get("name") or "").lower() == "qq.exe":
                return True
        return False
    except Exception:
        pass
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq QQ.exe", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return "qq.exe" in (out.stdout or "").lower()
    except Exception:
        return False


def ensure_qq() -> dict[str, Any]:
    """SnowLuma 挂在 QQ 上跑，QQ 没开就先开一个。"""
    if _qq_running():
        return {"ok": True, "started": False, "note": "QQ 已在运行"}
    qq = None
    for cand in envcheck.QQ_SEARCH:
        p = Path(str(cand))
        if p.is_file():
            qq = p
            break
    if not qq:
        return {"ok": False, "started": False, "err": "没找到 QQ.exe，SnowLuma 需要 QQ NT 做宿主"}
    try:
        subprocess.Popen([str(qq)], cwd=str(qq.parent),
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except Exception as e:
        return {"ok": False, "started": False, "err": f"启动 QQ 失败：{e}"}
    for _ in range(12):
        time.sleep(0.5)
        if _qq_running():
            break
    return {"ok": True, "started": True, "qq": str(qq)}


# ---------- 安装（后台任务） ----------
#
# 发行包 41 MB 起，同步下载会把 HTTP 请求拖到超时，所以丢到线程里跑，
# 界面拿 install_job() 轮询进度。全局只允许一个安装任务。

_JOB: dict[str, Any] = {"running": False, "ok": None, "message": "", "text": "",
                        "received": 0, "total": 0, "startedAt": 0, "finishedAt": 0}
_LOCK = threading.Lock()


def install_job() -> dict[str, Any]:
    with _LOCK:
        return dict(_JOB)


def _job_set(**kw: Any) -> None:
    with _LOCK:
        _JOB.update(kw)


def _install_worker(force: bool) -> None:
    try:
        _job_set(message="正在找下载地址…", text="")
        urls = sources(force=force)
        dest = paths.TMP_DIR / "dl" / "snowluma.zip"
        paths.ensure_dirs()
        dest.parent.mkdir(parents=True, exist_ok=True)
        local = paths.RESOURCES_DIR / "snowluma.zip"
        if local.is_file():
            _job_set(message="使用离线包…")
            ok, detail = install(local)
        else:
            def on_progress(p) -> None:
                _job_set(received=int(getattr(p, "received", 0) or 0),
                         total=int(getattr(p, "total", 0) or 0),
                         text=str(getattr(p, "text", "") or ""))

            _job_set(message="正在下载 SnowLuma…")
            download.fetch(urls, dest, on_progress)
            _job_set(message="正在解压…")
            ok, detail = install(dest, lambda i, n: _job_set(text=f"解压 {i}/{n}"))
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
        _job_set(running=False, ok=bool(ok), message=detail,
                 finishedAt=int(time.time()))
        if ok:
            # 装完顺手把当前实例的配置写好，省得用户再点一次
            try:
                write_config()
            except Exception:
                pass
    except Exception as e:
        _job_set(running=False, ok=False, finishedAt=int(time.time()),
                 message=f"{type(e).__name__}: {e}")


def install_start(force: bool = False) -> dict[str, Any]:
    with _LOCK:
        if _JOB.get("running"):
            return {"ok": True, "already": True, "job": dict(_JOB)}
        _JOB.update(running=True, ok=None, message="准备下载…", text="",
                    received=0, total=0, startedAt=int(time.time()), finishedAt=0)
        snap = dict(_JOB)
    threading.Thread(target=_install_worker, args=(force,), name="snowluma-install",
                     daemon=True).start()
    return {"ok": True, "started": True, "job": snap}

