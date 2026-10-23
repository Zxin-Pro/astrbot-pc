"""组件更新中心：清点组件、查上游版本、打快照、按快照回滚。

和 backup 的分工：backup 管用户资产（模型、人格、插件数据），整包恢复；
这里管组件本身——PC 外壳、AstrBot 源码树、NapCat、各实例插件。

PC 端装在本机，后台替换正在运行的文件很容易把东西搞坏，所以升级一律走
「先生成快照 → 跳官方发布页 → 用户自己动手」，不自动下载覆盖。

快照包落在 ROOT/backups/components/组件快照-YYYYmmdd-HHMMSS.zip，结构::

    manifest.json                    版本、标签、时间、文件清单
    stack/astrbot/...                AstrBot 源码树（不含 data/venv/.git 等）
    instance/<id>/cmd_config.json    当前实例的三件配置
    instance/<id>/data_v4.db
    instance/<id>/shared_preferences.json

回滚只覆盖 stack/astrbot；实例 data 是用户资产，要整包恢复请走「备份」页。
对外函数都返回 dict，失败是 {"ok": False, "err": "中文原因"}。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterator

from . import config, paths, runtime, update

__all__ = ["inventory", "check", "snapshot", "snapshots", "rollback", "upgrade"]

#: GitHub 只要有个能认出来的 UA 就行；这里固定成客户端签名，别跟着版本号漂
UA = "AstrBotPC/1.0"

#: 组件 key -> 上游仓库。PC 端的仓库从 config.update.repo 读，不写死在这里
REPOS: dict[str, str] = {
    "astrbot": "AstrBotDevs/AstrBot",
    "napcat": "NapNeko/NapCatQQ",
}
LABELS: dict[str, str] = {
    "pc": paths.APP_TITLE,
    "astrbot": "AstrBot",
    "napcat": "NapCat",
}

#: 查一次管半小时；有组件没查成功时只缓存两分钟，别让用户被一次断网卡住
CHECK_FILE = "components-check.json"
CHECK_TTL = 30 * 60
CHECK_FAIL_TTL = 2 * 60

SNAPSHOT_DIR_NAME = "components"
SNAPSHOT_PREFIX = "组件快照"
MANIFEST_NAME = "manifest.json"
STACK_PREFIX = "stack/astrbot"
INSTANCE_PREFIX = "instance"

#: 源码树里不打包的目录：缓存、版本库、虚拟环境、构建产物
SKIP_DIRS = {
    "__pycache__", ".git", "venv", ".venv", "dist", "node_modules",
    "site-packages", ".pytest_cache", ".mypy_cache", ".idea", ".vscode",
}
SKIP_SUFFIX = (".pyc", ".pyo")
SKIP_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_MANIFEST_FILES = 5000

_CHECK_LOCK = threading.Lock()
_SNAP_LOCK = threading.Lock()

_VER_IN_INIT = re.compile(r"""__version__\s*[:=]\s*['"]([^'"]+)['"]""")
_VER_IN_TOML = re.compile(r"""^\s*version\s*=\s*['"]([^'"]+)['"]""", re.M)
#: NapCat 的版本号长这样：4.18.38。package.json 里写的是 0.0.1，不能拿来做判断
_VER_4X = re.compile(r"(?<![\d.])4\.\d{1,3}\.\d{1,3}(?![\d.])")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_text(path: Path, limit: int = 4 * 1024 * 1024) -> str:
    """按需读一段文本；读不到就当空串，版本探测不该抛异常。"""
    try:
        with path.open("rb") as f:
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _dir_has_files(path: Path) -> bool:
    try:
        if not path.is_dir():
            return False
        with os.scandir(path) as it:
            return any(True for _ in it)
    except OSError:
        return False


def _clean_version(tag: Any) -> str:
    """v4.5.0 / astrbot-v4.5.0 / 4.5.0 都归一成 4.5.0。"""
    text = str(tag or "").strip()
    hit = re.search(r"\d+(?:\.\d+)+", text)
    return hit.group(0) if hit else ""


def _version_astrbot() -> str:
    """AstrBot 版本：先看 astrbot/__init__.py 的 __version__，再退回 pyproject.toml。"""
    root = paths.STACK_DIR / "astrbot"
    hit = _VER_IN_INIT.search(_read_text(root / "astrbot" / "__init__.py"))
    if hit:
        return hit.group(1).strip()

    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return ""
    text = _read_text(pyproject)
    try:
        import tomllib  # Python 3.11+ 自带，3.10 及以下会走正则兜底

        data = tomllib.loads(text)
        version = str((data.get("project") or {}).get("version") or "").strip()
        if version:
            return version
        version = str(((data.get("tool") or {}).get("poetry") or {}).get("version") or "").strip()
        if version:
            return version
    except Exception:
        pass
    hit = _VER_IN_TOML.search(text)
    return hit.group(1).strip() if hit else ""


def _find_napcat_js() -> Path | None:
    """找 napcat.mjs；发布包有时会多套一层目录，往下找三层够用了。"""
    root = paths.STACK_DIR / "napcat"
    if not root.is_dir():
        return None
    direct = root / "napcat.mjs"
    if direct.is_file():
        return direct
    found: Path | None = None
    try:
        for cur, dirs, names in os.walk(root):
            base = Path(cur)
            try:
                depth = len(base.relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth >= 3:
                dirs[:] = []
            if "napcat.mjs" in names:
                cand = base / "napcat.mjs"
                if found is None or len(cand.parts) < len(found.parts):
                    found = cand
    except OSError:
        return found
    return found


def _version_napcat() -> str:
    """NapCat 版本：读 napcat.mjs 里的 4.x.y，不读 package.json 的 0.0.1。"""
    js = _find_napcat_js()
    if js is None:
        return ""
    text = _read_text(js, 12 * 1024 * 1024)
    hits = list(_VER_4X.finditer(text))
    if not hits:
        return ""
    # 优先取紧挨着 version 字样的那个，避免抓到日志/依赖里无关的 4.x.y
    for hit in hits:
        if "version" in text[max(0, hit.start() - 80):hit.start()].lower():
            return hit.group(0)
    return hits[0].group(0)


def _pc_path() -> str:
    """PC 外壳自己的位置：exe 模式给可执行文件，源码模式给项目根。"""
    try:
        if paths.is_frozen():
            return str(Path(sys.executable))
    except Exception:
        pass
    return str(paths.APP_DIR)


def _instance_rows() -> list[tuple[str, str]]:
    """(实例 id, 展示名)。配置里没有实例时，退回扫 instances 目录。"""
    rows: list[tuple[str, str]] = []
    try:
        for item in runtime.instances():
            iid = str(item.get("id") or "")
            if iid:
                rows.append((iid, str(item.get("name") or iid)))
    except Exception:
        rows = []
    if rows:
        return rows
    try:
        return [(p.name, p.name) for p in sorted(paths.INSTANCES_DIR.iterdir()) if p.is_dir()]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# 插件清单（metadata.yaml 逐行解析，不引第三方 YAML）
# ---------------------------------------------------------------------------

def _yaml_scalar(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text[0] in ("'", '"'):
        quote = text[0]
        end = text.find(quote, 1)
        return text[1:end] if end > 0 else text[1:]
    # 行内注释只有「空格 + #」才算，URL 里的 # 不能砍
    cut = text.find(" #")
    if cut > 0:
        text = text[:cut]
    return text.strip()


def _parse_metadata(path: Path) -> dict[str, str]:
    """metadata.yaml 只取顶层的 key: value，够读 name / version 了。"""
    out: dict[str, str] = {}
    text = _read_text(path, 128 * 1024)
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[:1] in (" ", "\t", "-"):
            continue  # 缩进的是子字段，- 开头的是列表项
        key, sep, value = raw.partition(":")
        if not sep:
            continue
        out[key.strip().lower()] = _yaml_scalar(value)
    return out


def _plugin_items() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for iid, inst_name in _instance_rows():
        folder = runtime.astrbot_data(iid) / "plugins"
        if not folder.is_dir():
            continue
        try:
            dirs = sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
        except OSError:
            continue
        for plugin_dir in dirs:
            if plugin_dir.name.startswith(".") or plugin_dir.name.startswith("__"):
                continue
            meta: dict[str, str] = {}
            for filename in ("metadata.yaml", "metadata.yml"):
                cand = plugin_dir / filename
                if cand.is_file():
                    meta = _parse_metadata(cand)
                    break
            rows.append({
                "key": f"plugin:{iid}:{plugin_dir.name}",
                "label": str(meta.get("name") or plugin_dir.name),
                "version": str(meta.get("version") or ""),
                "installed": True,
                "path": str(plugin_dir),
                "source": f"实例「{inst_name}」",
                "kind": "plugin",
                "instance": iid,
                "plugin": plugin_dir.name,
            })
    return rows


# ---------------------------------------------------------------------------
# 组件清单
# ---------------------------------------------------------------------------

def inventory() -> dict[str, Any]:
    """本机组件清单：PC / AstrBot / NapCat，外加每个实例装了的插件。"""
    try:
        astrbot_root = paths.STACK_DIR / "astrbot"
        napcat_root = paths.STACK_DIR / "napcat"
        astrbot_ok = _dir_has_files(astrbot_root) and (
            (astrbot_root / "astrbot").is_dir() or (astrbot_root / "pyproject.toml").is_file()
        )
        napcat_ok = _dir_has_files(napcat_root)

        items: list[dict[str, Any]] = [
            {
                "key": "pc",
                "label": LABELS["pc"],
                "version": paths.APP_VERSION,
                "installed": True,
                "path": _pc_path(),
                "source": "内置",
                "kind": "app",
            },
            {
                "key": "astrbot",
                "label": LABELS["astrbot"],
                "version": _version_astrbot(),
                "installed": bool(astrbot_ok),
                "path": str(astrbot_root),
                "source": paths.rel(astrbot_root),
                "kind": "service",
            },
            {
                "key": "napcat",
                "label": LABELS["napcat"],
                "version": _version_napcat(),
                "installed": bool(napcat_ok),
                "path": str(napcat_root),
                "source": paths.rel(napcat_root),
                "kind": "service",
            },
        ]
        items.extend(_plugin_items())
        return {"ok": True, "items": items, "ts": int(time.time())}
    except Exception as e:
        return {"ok": False, "err": f"读取组件清单失败：{type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# 查上游版本
# ---------------------------------------------------------------------------

def _pc_releases() -> str:
    """PC 端发布页；能从更新缓存里拿到就用缓存里的那条。"""
    repo = str(config.get("update.repo", "Zxin-Pro/astrbot-pc") or "Zxin-Pro/astrbot-pc")
    fallback = f"https://github.com/{repo}/releases"
    try:
        hit = update.cached() or {}
        url = str(hit.get("url") or "")
        if url.startswith("http"):
            return url
    except Exception:
        pass
    return fallback


def _net_err(label: str, error: Exception) -> str:
    text = str(error).lower()
    code = getattr(error, "code", None)
    if code == 404:
        return f"{label}：仓库或发布不存在（404）"
    if code in (403, 429):
        return f"{label}：GitHub 接口被限流了，过一会儿再试"
    if "timed out" in text or "timeout" in text:
        return f"{label}：连接 GitHub 超时，检查一下网络"
    if "getaddrinfo" in text or "name or service" in text or "temporary failure" in text:
        return f"{label}：DNS 解析失败，检查一下网络"
    return f"{label}：检查失败 {type(error).__name__}: {str(error)[:120]}"


def _check_pc() -> dict[str, Any]:
    """PC 端复用 update.check（它会自己挑桌面版的发布，不拿手机版糊弄）。"""
    page = _pc_releases()
    base: dict[str, Any] = {
        "key": "pc", "label": LABELS["pc"], "kind": "app",
        "current": paths.APP_VERSION, "latest": "", "newer": False,
        "url": page, "notes": "",
    }
    try:
        res = update.check(force=True)
    except Exception as e:
        return {**base, "ok": False, "err": f"检查 PC 端更新失败：{e}"}
    if not isinstance(res, dict):
        return {**base, "ok": False, "err": "检查 PC 端更新失败：返回了意料之外的数据"}
    ok = bool(res.get("ok", True))
    item = {
        **base,
        "ok": ok,
        "current": str(res.get("current") or paths.APP_VERSION),
        "latest": str(res.get("latest") or ""),
        "newer": bool(res.get("newer")),
        "url": str(res.get("url") or page),
        "notes": str(res.get("notes") or ""),
        "noRelease": bool(res.get("noRelease")),
        "checkedAt": _as_int(res.get("checkedAt"), int(time.time())),
    }
    if not ok:
        item["err"] = str(res.get("err") or "检查 PC 端更新失败")
    elif res.get("message"):
        item["message"] = str(res.get("message"))
    return item


def _github_latest(key: str) -> dict[str, Any]:
    """问一次 GitHub 的 releases/latest。网络问题只影响这一条，不抛给上层。"""
    repo = REPOS[key]
    label = LABELS[key]
    page = f"https://github.com/{repo}/releases"
    current = _version_astrbot() if key == "astrbot" else _version_napcat()
    base: dict[str, Any] = {
        "key": key, "label": label, "kind": "service",
        "current": current, "latest": "", "newer": False,
        "url": page, "notes": "",
    }
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as e:
        return {**base, "ok": False, "err": _net_err(label, e)}
    if not isinstance(raw, dict):
        return {**base, "ok": False, "err": f"{label}：GitHub 返回了意料之外的数据"}
    tag = str(raw.get("tag_name") or "").strip()
    latest = _clean_version(tag)
    if not latest:
        return {**base, "ok": False, "err": f"{label}：没从这次发布里读到版本号"}
    return {
        **base,
        "ok": True,
        "current": current,
        "latest": latest,
        "tag": tag,
        "newer": bool(current) and update.is_newer(latest, current),
        "url": str(raw.get("html_url") or page),
        "notes": str(raw.get("body") or "").strip()[:4000],
        "publishedAt": str(raw.get("published_at") or ""),
        "checkedAt": int(time.time()),
    }


def _ttl(items: list[Any]) -> int:
    rows = [i for i in items if isinstance(i, dict)]
    return CHECK_FAIL_TTL if any(not i.get("ok") for i in rows) else CHECK_TTL


def _cached_check(force: bool) -> dict[str, Any] | None:
    if force:
        return None
    cached = config.read_state(CHECK_FILE, {})
    if not isinstance(cached, dict):
        return None
    raw_items = cached.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return None
    items = [i for i in raw_items if isinstance(i, dict)]
    if not items:
        return None
    ts = _as_int(cached.get("ts"), 0)
    age = int(time.time()) - ts
    if ts <= 0 or age < 0 or age >= _ttl(items):
        return None
    ok = all(bool(i.get("ok")) for i in items)
    out: dict[str, Any] = {"ok": ok, "items": items, "ts": ts, "cached": True}
    if not ok:
        out["err"] = "上次检查没成功，过一会儿会自动重试"
    return out


def check(force: bool = False) -> dict[str, Any]:
    """查 PC / AstrBot / NapCat 的最新版本，结果缓存 30 分钟。

    单个组件查不到只让那一条 ok=False，整体仍带着其余结果返回；全都失败时
    整体 ok=False 并给一句中文原因——前端不该因为断网就白屏。
    """
    hit = _cached_check(force)
    if hit is not None:
        return hit
    with _CHECK_LOCK:
        hit = _cached_check(force)
        if hit is not None:
            return hit
        items = [_check_pc(), _github_latest("astrbot"), _github_latest("napcat")]
        ts = int(time.time())
        failed = [i for i in items if not i.get("ok")]
        data: dict[str, Any] = {
            "ok": not failed,
            "items": items,
            "ts": ts,
            "cached": False,
            "failed": len(failed),
        }
        if failed:
            data["err"] = "；".join(str(i.get("err") or "") for i in failed)[:300]
        try:
            config.write_state(CHECK_FILE, data)
        except Exception:
            pass
        return data


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------

def _snapshot_dir() -> Path:
    return paths.BACKUP_DIR / SNAPSHOT_DIR_NAME


def _iter_tree(root: Path, prefix: str) -> Iterator[tuple[Path, str]]:
    """遍历源码树；顶层 data 与缓存目录一律不进快照。"""
    for cur, dirs, names in os.walk(root):
        base = Path(cur)
        try:
            rel_dir = base.relative_to(root)
        except ValueError:
            continue
        keep: list[str] = []
        for name in dirs:
            if name in SKIP_DIRS:
                continue
            if not rel_dir.parts and name == "data":
                continue  # stack/astrbot/data 是用户资产，备份页负责
            keep.append(name)
        dirs[:] = keep
        for name in names:
            if name in SKIP_FILES or name.lower().endswith(SKIP_SUFFIX):
                continue
            path = base / name
            try:
                if path.is_symlink():
                    continue
                stat = path.stat()
                if not path.is_file() or stat.st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path, f"{prefix}/{path.relative_to(root).as_posix()}"


def snapshot(label: str = "") -> dict[str, Any]:
    """把 AstrBot 源码树 + 当前实例的三件配置打成一个快照包。

    不打包整个 data 目录，也不打包插件目录——那些走「备份」页，体积大得多。
    """
    paths.ensure_dirs()
    folder = _snapshot_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "err": f"建不了快照目录：{e}"}

    created = int(time.time())
    stem = f"{SNAPSHOT_PREFIX}-{time.strftime('%Y%m%d-%H%M%S', time.localtime(created))}"
    with _SNAP_LOCK:
        dest = folder / f"{stem}.zip"
        n = 2
        while dest.exists():
            dest = folder / f"{stem}-{n}.zip"
            n += 1

        entries: list[tuple[Path, str]] = []
        source = paths.STACK_DIR / "astrbot"
        if source.is_dir():
            entries.extend(_iter_tree(source, STACK_PREFIX))

        iid = runtime.active_id()
        if iid:
            for path, name in (
                (runtime.cmd_path(iid), "cmd_config.json"),
                (runtime.db_path(iid), "data_v4.db"),
                (runtime.prefs_path(iid), "shared_preferences.json"),
            ):
                if path.is_file():
                    entries.append((path, f"{INSTANCE_PREFIX}/{iid}/{name}"))
        if not entries:
            return {"ok": False, "err": "还没有可快照的内容：先完成部署（stack/astrbot）或建好实例再试"}

        files: list[str] = []
        skipped: list[str] = []
        raw = 0
        try:
            with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                for path, arc in entries:
                    try:
                        zf.write(path, arc)
                    except OSError as e:
                        # 文件被占用（多半是正在写的 data_v4.db）就跳过，别让整包失败
                        skipped.append(f"{arc}（{type(e).__name__}）")
                        continue
                    files.append(arc)
                    try:
                        raw += path.stat().st_size
                    except OSError:
                        pass
                manifest = {
                    "kind": "components",
                    "version": _version_astrbot(),
                    "appVersion": paths.APP_VERSION,
                    "label": str(label or "").strip(),
                    "createdAt": created,
                    "instance": iid,
                    "fileCount": len(files),
                    "bytes": raw,
                    "files": files[:MAX_MANIFEST_FILES],
                }
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        except Exception as e:
            try:
                dest.unlink()
            except OSError:
                pass
            return {"ok": False, "err": f"打包失败：{type(e).__name__}: {e}"}

        if not files:
            try:
                dest.unlink()
            except OSError:
                pass
            return {"ok": False, "err": "打包失败：没有一个文件能读出来（可能正被占用）"}

        try:
            size = dest.stat().st_size
        except OSError:
            size = 0
        return {
            "ok": True,
            "name": dest.name,
            "path": str(dest),
            "bytes": size,
            "createdAt": created,
            "label": manifest["label"],
            "version": manifest["version"],
            "files": len(files),
            "skipped": skipped[:20],
        }


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read(MANIFEST_NAME)
        data = json.loads(raw.decode("utf-8-sig", "replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _valid_manifest(man: dict[str, Any]) -> bool:
    if not isinstance(man, dict):
        return False
    if not isinstance(man.get("files"), list):
        return False
    if not man.get("createdAt"):
        return False
    return bool(man.get("files")) or _as_int(man.get("fileCount"), 0) > 0


def snapshots() -> dict[str, Any]:
    """列出所有组件快照；manifest 坏掉的也照样列出来，只是标 valid=False。"""
    folder = _snapshot_dir()
    rows: list[dict[str, Any]] = []
    if folder.is_dir():
        try:
            zips = sorted(folder.glob("*.zip"))
        except OSError:
            zips = []
        for path in zips:
            try:
                if not path.is_file():
                    continue
                stat = path.stat()
            except OSError:
                continue
            man = _read_manifest(path)
            rows.append({
                "name": path.name,
                "path": str(path),
                "bytes": stat.st_size,
                "createdAt": _as_int(man.get("createdAt"), int(stat.st_mtime)),
                "label": str(man.get("label") or ""),
                "version": str(man.get("version") or ""),
                "valid": _valid_manifest(man),
                "files": _as_int(man.get("fileCount"), len(man.get("files") or []) if isinstance(man.get("files"), list) else 0),
            })
    rows.sort(key=lambda r: (-_as_int(r.get("createdAt"), 0), str(r.get("name") or "")))
    return {"ok": True, "items": rows, "dir": str(folder)}


# ---------------------------------------------------------------------------
# 回滚
# ---------------------------------------------------------------------------

def _resolve_snapshot(name: str) -> Path | None:
    """只认 backups/components 下面真实存在的 zip，别的一概不碰。"""
    raw = str(name or "").strip()
    if not raw:
        return None
    base = _snapshot_dir().resolve()
    filename = Path(raw.replace("\\", "/")).name
    if not filename.lower().endswith(".zip"):
        return None
    try:
        cand = (base / filename).resolve()
    except OSError:
        return None
    if cand.parent != base or not cand.is_file():
        return None
    return cand


def _plan_restore(zf: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, str]], int]:
    """挑出 stack/astrbot 里的文件，顺便挡住越界路径。返回 (计划, 可疑条数)。"""
    plan: list[tuple[zipfile.ZipInfo, str]] = []
    unsafe = 0
    root = (paths.STACK_DIR / "astrbot").resolve()
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        lowered = name.lower()
        if name.startswith("/") or re.match(r"^[a-z]:", lowered) or ".." in name.split("/"):
            unsafe += 1
            continue
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if len(parts) < 3 or parts[0] != "stack" or parts[1] != "astrbot":
            continue  # manifest.json、instance/... 一律不还原
        rel = "/".join(parts[2:])
        try:
            target = (root / Path(rel)).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            unsafe += 1
            continue
        plan.append((info, rel))
    return plan, unsafe


def rollback(name: str) -> dict[str, Any]:
    """按快照覆盖 stack/astrbot 源码树。

    只覆盖快照里有的文件，不删除快照外的文件；实例 data 一根手指都不碰。
    动手前先自动打一份「回滚前自动快照」，后悔了还能再滚一次。
    """
    src = _resolve_snapshot(name)
    if src is None:
        return {"ok": False, "err": "找不到这个快照，只能回滚 backups/components 下的 zip"}
    if not zipfile.is_zipfile(src):
        return {"ok": False, "err": "这个快照不是有效的 zip，文件可能已损坏"}
    man = _read_manifest(src)
    if not _valid_manifest(man):
        return {"ok": False, "err": "快照里的 manifest.json 缺失或已损坏，不敢回滚"}

    try:
        with zipfile.ZipFile(src) as zf:
            plan, unsafe = _plan_restore(zf)
    except zipfile.BadZipFile:
        return {"ok": False, "err": "快照解不开，文件可能已损坏"}
    except Exception as e:
        return {"ok": False, "err": f"读快照失败：{type(e).__name__}: {e}"}
    if unsafe:
        return {"ok": False, "err": "快照里有越界路径，为保证安全已拒绝回滚"}
    if not plan:
        return {"ok": False, "err": "这个快照里没有 stack/astrbot 源码文件，没有可回滚的内容"}

    safety = snapshot("回滚前自动快照")
    if not safety.get("ok"):
        return {"ok": False, "err": f"回滚前自动快照失败，已中止：{safety.get('err')}"}

    staged = paths.TMP_DIR / f"components-rollback-{int(time.time() * 1000)}"
    try:
        with zipfile.ZipFile(src) as zf:
            for info, rel in plan:
                target = staged / Path(rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as fsrc, open(target, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
    except Exception as e:
        shutil.rmtree(staged, ignore_errors=True)
        return {"ok": False, "err": f"解包失败：{type(e).__name__}: {e}"}

    root = paths.STACK_DIR / "astrbot"
    restored: list[str] = []
    try:
        root.mkdir(parents=True, exist_ok=True)
        for path in staged.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(staged)
            out = root / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out)
            restored.append(rel.as_posix())
    except Exception as e:
        return {
            "ok": False,
            "err": f"写入源码树失败：{type(e).__name__}: {e}（可用「{safety.get('name')}」再滚一次）",
            "restored": restored[:500],
            "safety": safety.get("name"),
        }
    finally:
        shutil.rmtree(staged, ignore_errors=True)

    restored.sort()
    return {
        "ok": True,
        "name": src.name,
        "restored": restored[:500],
        "count": len(restored),
        "safety": str(safety.get("name") or ""),
        "version": str(man.get("version") or ""),
        "createdAt": _as_int(man.get("createdAt"), 0),
        "note": "只覆盖了源码树，实例数据未改动",
    }


# ---------------------------------------------------------------------------
# 升级入口
# ---------------------------------------------------------------------------

def upgrade(key: str) -> dict[str, Any]:
    """升级向导：一律「先快照、再跳官方发布页」，不偷偷下载覆盖。"""
    name = str(key or "").strip().lower()
    if name == "pc":
        return {
            "ok": True,
            "key": "pc",
            "manual": True,
            "url": _pc_releases(),
            "note": "PC 端请下载新版本覆盖安装",
        }
    if name not in REPOS:
        if name.startswith("plugin:"):
            return {"ok": False, "err": "插件请到 AstrBot 插件市场里更新，组件页只做快照"}
        return {"ok": False, "err": f"未知组件：{key}"}

    snap = snapshot("升级前自动快照")
    if not snap.get("ok"):
        return {"ok": False, "err": f"生成快照失败，已中止升级：{snap.get('err')}"}
    return {
        "ok": True,
        "key": name,
        "manual": True,
        "url": f"https://github.com/{REPOS[name]}/releases/latest",
        "note": "已生成快照；请在组件页确认后按官方方式升级",
        "snapshot": str(snap.get("name") or ""),
        "snapshotPath": str(snap.get("path") or ""),
        "current": _version_astrbot() if name == "astrbot" else _version_napcat(),
    }
