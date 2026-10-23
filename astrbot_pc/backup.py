"""备份与恢复：把「能搬走的东西」打成一个 zip。

包含：配置、实例列表、AstrBot 的 data 目录、NapCat 的配置与二维码。
不包含：虚拟环境、依赖、日志（体积大且可重建）。
恢复前先把当前状态另存一份 safety 包，误操作还能退回来。
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import zipfile
from pathlib import Path
from typing import Any

from . import config, paths

MANIFEST = "backup-manifest.json"
SKIP_DIRS = {"__pycache__", "node_modules", ".git", "venv", ".venv", "site-packages"}

# 备份可能是几百 MB，跑在请求线程里界面只能干等。改成后台任务，界面轮询进度。
_lock = threading.Lock()
_cancel = threading.Event()
_job: dict[str, Any] = {"running": False, "cancel": False, "startedAt": 0, "note": "", "name": "", "result": None}


def _targets() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    if paths.CONFIG_FILE.exists():
        out.append((paths.CONFIG_FILE, "config.json"))
    stack = paths.STACK_DIR
    for sub, arc in (
        (stack / "astrbot" / "data", "astrbot/data"),
        (stack / "napcat" / "config", "napcat/config"),
        (stack / "napcat" / "qc", "napcat/qc"),
    ):
        if sub.exists():
            out.append((sub, arc))
    return out


def _safe_arc(base: Path, p: Path) -> str:
    try:
        return str(p.relative_to(base)).replace("\\", "/")
    except ValueError:
        return p.name


def create(note: str = "", cancel: threading.Event | None = None) -> dict[str, Any]:
    paths.ensure_dirs()
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    name = f"astrbot-pc-{ts}.zip"
    dest = paths.BACKUP_DIR / name
    targets = _targets()
    if not targets:
        return {"ok": False, "err": "还没有可备份的数据，先跑一遍部署"}

    count = 0
    total = 0
    try:
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            manifest = {"createdAt": int(time.time()), "version": 1, "note": note, "files": []}
            for src, arc in targets:
                if src.is_file():
                    zf.write(src, arc)
                    total += src.stat().st_size
                    count += 1
                    manifest["files"].append(arc)
                else:
                    for p in src.rglob("*"):
                        if cancel is not None and cancel.is_set():
                            raise RuntimeError("已取消")
                        if p.is_dir():
                            continue
                        if any(part in SKIP_DIRS for part in p.parts):
                            continue
                        try:
                            if p.stat().st_size > 200 * 1024 * 1024:
                                continue
                        except OSError:
                            continue
                        arcname = f"{arc}/{_safe_arc(src, p)}"
                        zf.write(p, arcname)
                        total += p.stat().st_size
                        count += 1
                        if len(manifest["files"]) < 500:
                            manifest["files"].append(arcname)
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    except Exception as e:
        try:
            dest.unlink()
        except OSError:
            pass
        if str(e) == "已取消":
            return {"ok": False, "err": "备份已取消"}
        return {"ok": False, "err": f"打包失败：{e}"}

    size = dest.stat().st_size
    rec = {"name": name, "path": str(dest), "size": size, "files": count, "raw": total,
           "createdAt": int(time.time()), "note": note}
    hist = [h for h in (config.get("backup.history", []) or []) if h.get("name") != name]
    hist.insert(0, rec)
    config.save({"backup": {"history": hist[:20]}})
    return {"ok": True, **rec}


def list_all() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for h in config.get("backup.history", []) or []:
        p = Path(h.get("path", ""))
        if p.is_file():
            row = dict(h)
            row["size"] = p.stat().st_size
            row["exists"] = True
            rows.append(row)
            seen.add(p.name)
    if paths.BACKUP_DIR.is_dir():
        for p in sorted(paths.BACKUP_DIR.glob("*.zip"), key=lambda x: -x.stat().st_mtime):
            if p.name in seen:
                continue
            rows.append({
                "name": p.name, "path": str(p), "size": p.stat().st_size,
                "createdAt": int(p.stat().st_mtime), "note": "", "files": 0, "exists": True,
            })
    rows.sort(key=lambda r: -int(r.get("createdAt", 0)))
    return rows


def remove(name: str) -> dict[str, Any]:
    hit = next((r for r in list_all() if r["name"] == name), None)
    if not hit:
        return {"ok": False, "err": "备份不存在"}
    try:
        Path(hit["path"]).unlink()
    except OSError as e:
        return {"ok": False, "err": f"删除失败：{e}"}
    hist = [h for h in (config.get("backup.history", []) or []) if h.get("name") != name]
    config.save({"backup": {"history": hist}})
    return {"ok": True}


def restore(name: str) -> dict[str, Any]:
    hit = next((r for r in list_all() if r["name"] == name), None)
    if not hit:
        return {"ok": False, "err": "备份不存在"}
    src = Path(hit["path"])
    if not zipfile.is_zipfile(src):
        return {"ok": False, "err": "这个文件不是有效备份"}

    safety = None
    try:
        res = create(note="恢复前的自动快照")
        if res.get("ok"):
            safety = res.get("name")
    except Exception:
        pass

    staged = paths.TMP_DIR / f"restore-{int(time.time())}"
    try:
        with zipfile.ZipFile(src) as zf:
            for member in zf.namelist():
                if member == MANIFEST or member.endswith("/"):
                    continue
                if ".." in Path(member).parts:
                    continue
                target = staged / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as fsrc, open(target, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
    except Exception as e:
        shutil.rmtree(staged, ignore_errors=True)
        return {"ok": False, "err": f"解包失败：{e}"}

    applied = 0
    try:
        cfg = staged / "config.json"
        if cfg.is_file():
            data = json.loads(cfg.read_text("utf-8-sig"))
            if isinstance(data, dict):
                config.save(data)
                applied += 1
        for arc, dest in (
            ("astrbot/data", paths.STACK_DIR / "astrbot" / "data"),
            ("napcat/config", paths.STACK_DIR / "napcat" / "config"),
            ("napcat/qc", paths.STACK_DIR / "napcat" / "qc"),
        ):
            part = staged / arc
            if not part.is_dir():
                continue
            for p in part.rglob("*"):
                if p.is_dir():
                    continue
                rel = p.relative_to(part)
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, out)
                applied += 1
    except Exception as e:
        shutil.rmtree(staged, ignore_errors=True)
        return {"ok": False, "err": f"写入失败：{e}"}
    finally:
        shutil.rmtree(staged, ignore_errors=True)

    return {"ok": True, "applied": applied, "safety": safety}


def open_folder() -> dict[str, Any]:
    import os

    paths.ensure_dirs()
    try:
        if os.name == "nt":
            os.startfile(str(paths.BACKUP_DIR))  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(paths.BACKUP_DIR)])
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": str(e)}


def job() -> dict[str, Any]:
    with _lock:
        return dict(_job)


def create_async(note: str = "") -> dict[str, Any]:
    """后台打包。立即返回，界面靠 GET /api/backups 里的 job 看进度。"""
    name = f"astrbot-pc-{time.strftime('%Y%m%d-%H%M%S', time.localtime())}.zip"
    with _lock:
        if _job.get("running"):
            return {"ok": False, "err": "已经有一个备份在打包"}
        _job.update({"running": True, "cancel": False, "startedAt": int(time.time()),
                     "note": note, "name": name, "result": None})
    _cancel.clear()

    def _work() -> None:
        try:
            res = create(note, cancel=_cancel)
        except Exception as e:  # create 自己会兜，这里再保一层
            res = {"ok": False, "err": f"打包失败：{type(e).__name__}: {e}"}
        finally:
            _cancel.clear()
        with _lock:
            _job.update({"running": False, "cancel": False, "result": res})
        try:
            from .events import bus

            bus.emit("notice", {
                "level": "success" if res.get("ok") else "error",
                "text": "备份完成：" + (res.get("name") or "") if res.get("ok") else str(res.get("err") or "备份失败"),
            })
        except Exception:
            pass

    threading.Thread(target=_work, name="backup", daemon=True).start()
    return {"ok": True, "name": name, "startedAt": _job["startedAt"]}


def cancel() -> dict[str, Any]:
    with _lock:
        running = bool(_job.get("running"))
        _job["cancel"] = True
    if not running:
        return {"ok": False, "err": "没有正在进行的备份"}
    _cancel.set()
    return {"ok": True, "message": "正在取消，最多等当前文件写完"}


def import_file(src: str) -> dict[str, Any]:
    """把一个外来备份 zip 收进备份目录（之后可在列表里恢复）。

    只接受本机路径：PC 端是桌面程序，文件选择器给的就是绝对路径，
    没必要把几百 MB 塞进 JSON。
    """
    path = Path(str(src or "")).expanduser()
    if not path.is_file():
        return {"ok": False, "err": "找不到这个文件"}
    if path.suffix.lower() != ".zip":
        return {"ok": False, "err": "只支持 .zip 备份文件"}
    if path.stat().st_size > 4 * 1024 * 1024 * 1024:
        return {"ok": False, "err": "文件超过 4 GB，不像是本程序的备份"}
    if not zipfile.is_zipfile(path):
        return {"ok": False, "err": "这个文件不是有效的 zip"}
    note = "外部导入"
    try:
        with zipfile.ZipFile(path) as zf:
            if MANIFEST in zf.namelist():
                data = json.loads(zf.read(MANIFEST).decode("utf-8-sig", "replace"))
                note = str(data.get("note") or note)
    except Exception:
        pass
    paths.ensure_dirs()
    name = path.name
    dest = paths.BACKUP_DIR / name
    n = 1
    while dest.exists():
        dest = paths.BACKUP_DIR / f"{path.stem}-{n}{path.suffix}"
        n += 1
    try:
        shutil.copy2(path, dest)
    except OSError as e:
        return {"ok": False, "err": f"复制失败：{e}"}
    rec = {"name": dest.name, "path": str(dest), "size": dest.stat().st_size,
           "createdAt": int(dest.stat().st_mtime), "note": note, "files": 0}
    hist = [h for h in (config.get("backup.history", []) or []) if h.get("name") != dest.name]
    hist.insert(0, rec)
    config.save({"backup": {"history": hist[:20]}})
    return {"ok": True, **rec}


def maybe_auto_daily() -> dict[str, Any]:
    """每天自动备份一次（开关在设置页）。调用方可以随便高频调，这里自己限速。"""
    if not config.get("backup.autoDaily", False):
        return {"ok": False, "skipped": True, "err": "未开启每日备份"}
    today = time.strftime("%Y-%m-%d", time.localtime())
    if str(config.get("backup.lastAuto") or "") == today:
        return {"ok": False, "skipped": True, "err": "今天已经备过"}
    if job().get("running"):
        return {"ok": False, "skipped": True, "err": "已有备份在跑"}
    res = create_async("每日自动备份")
    if res.get("ok"):
        # 先记日期，失败不记——失败的话下一个整点还能再试
        config.save({"backup": {"lastAuto": today}})
    return res


def usage() -> dict[str, Any]:
    rows = list_all()
    total = sum(int(r.get("size", 0)) for r in rows)
    data: dict[str, Any] = {"count": len(rows), "bytes": total, "items": rows[:20],
                            "job": job()}
    try:
        from . import storage

        snap = storage.scan()
        data.update({
            "total": snap.get("total", 0),
            "disk": snap.get("disk", {}),
            "stack": next((i["bytes"] for i in snap["items"] if i["key"] in ("astrbot", "napcat")), 0),
            "logs": next((i["bytes"] for i in snap["items"] if i["key"] == "logs"), 0),
            "backups": next((i["bytes"] for i in snap["items"] if i["key"] == "backups"), 0),
            "sections": snap.get("items", []),
        })
    except Exception:
        pass
    return data
