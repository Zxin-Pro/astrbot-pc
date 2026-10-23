"""AstrBot 实例插件管理：扫描、启停、安装、配置与日志。

只读写实例数据目录下的 plugins、config 和 shared_preferences.json，
不碰 AstrBot 的数据库；安装与删除的落点都会先做路径收敛校验。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from . import paths, runtime

__all__ = [
    "list_all",
    "detail",
    "set_enabled",
    "install_zip",
    "install_github",
    "remove",
    "config_get",
    "config_save",
    "logs",
    "failed",
]

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_WIN_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_META_NAMES = ("metadata.yaml", "metadata.yml")
_STAGING_PREFIXES = (".plugin-install-", ".plugin-upload-", ".plugin-backup-")
_MAX_UNZIP_BYTES = 2 * 1024 * 1024 * 1024
_MAX_UNZIP_FILES = 20000
_UA = "AstrBotPC/1.0"


def _sid(iid: str | None = None) -> str:
    """解析实例 id；没有实例时与 runtime 一样退回 bot1。"""
    return str(iid or runtime.active_id() or "bot1")


def _check_id(plugin_id: Any) -> str:
    """校验插件目录名，挡住路径穿越和 Windows 不允许的名字。"""
    pid = str(plugin_id) if plugin_id is not None else ""
    if not pid:
        raise ValueError("缺少插件 ID")
    if len(pid) > 120:
        raise ValueError("插件 ID 太长")
    if (
        not _ID_RE.fullmatch(pid)
        or pid in (".", "..")
        or ".." in pid
        or pid.endswith(".")
    ):
        raise ValueError("插件 ID 不合法（只允许字母、数字、下划线、短横线和点）")
    return pid


def _valid_id(name: str) -> bool:
    try:
        _check_id(name)
        return True
    except ValueError:
        return False


def _inside(base: Path, target: Path) -> bool:
    """target 解析后是否仍在 base 内；两者都可以还不存在。"""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _plugins_dir(iid: str | None = None) -> Path:
    return runtime.astrbot_data(_sid(iid)) / "plugins"


def _config_path(plugin_id: str, iid: str | None = None) -> Path:
    return runtime.astrbot_data(_sid(iid)) / "config" / f"{_check_id(plugin_id)}_config.json"


def _plugin_dir(plugin_id: Any, iid: str | None = None) -> Path:
    """取插件目录，并确认解析后的真实位置仍在 plugins 目录内。"""
    pid = _check_id(plugin_id)
    root = _plugins_dir(iid)
    path = root / pid
    try:
        inside = _inside(root, path)
        same = path.resolve() == root.resolve()
        is_dir = path.is_dir()
    except (OSError, RuntimeError, ValueError):
        # 符号链接环、权限错误等一律按路径不合法处理，避免异常逸出公开函数
        raise ValueError("插件路径不合法") from None
    if not inside or same:
        raise ValueError("插件路径不合法")
    if not is_dir:
        raise ValueError(f"插件不存在：{pid}")
    return path


def _metadata_path(plugin_dir: Path) -> Path | None:
    for name in _META_NAMES:
        path = plugin_dir / name
        if path.is_file():
            return path
    return None


def _parse_metadata(path: Path) -> dict[str, str]:
    """按行解析 metadata.yaml 的顶层 key: value，不引入 PyYAML。"""
    text = path.read_text(encoding="utf-8-sig")
    meta: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("- "):
            continue
        # 缩进行是子字段或列表内容，不属于插件顶层信息
        if raw[:1] in (" ", "\t"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if not key:
            continue
        if value[:1] in ("'", '"'):
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            # 行内注释只有「空格 + #」才算，URL 里的 # 不砍
            cut = value.find(" #")
            if cut > 0:
                value = value[:cut].strip()
        meta[key] = value
    return meta


def _load_meta(plugin_dir: Path) -> tuple[dict[str, str], bool]:
    path = _metadata_path(plugin_dir)
    if path is None:
        return {}, False
    try:
        return _parse_metadata(path), True
    except (OSError, UnicodeError):
        return {}, False


def _module_name(plugin_dir: Path) -> str:
    """main.py 优先，否则取目录里按文件名排序的第一个非下划线 .py。"""
    try:
        if (plugin_dir / "main.py").is_file():
            return "main"
        files = sorted(
            (
                path
                for path in plugin_dir.iterdir()
                if path.is_file() and path.suffix == ".py" and not path.name.startswith("_")
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError:
        return ""
    return files[0].stem if files else ""


def _dir_size(root: Path) -> int:
    """统计插件目录的文件大小；读不了的文件跳过。"""
    total = 0
    try:
        for base, _dirs, files in os.walk(root, followlinks=False):
            for name in files:
                try:
                    total += os.lstat(os.path.join(base, name)).st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _build_item(
    data_root: Path,
    name: str,
    plugin_dir: Path,
    inactive: set[str],
) -> dict[str, Any]:
    meta, meta_ok = _load_meta(plugin_dir)
    module = _module_name(plugin_dir)
    module_path = f"data.plugins.{name}.{module}" if module else ""
    try:
        has_config = (data_root / "config" / f"{name}_config.json").is_file()
    except OSError:
        has_config = False
    return {
        "id": name,
        "name": str(meta.get("name") or name),
        "version": str(meta.get("version") or ""),
        "desc": str(meta.get("desc") or meta.get("description") or ""),
        "author": str(meta.get("author") or ""),
        "repo": str(meta.get("repo") or ""),
        "path": str(plugin_dir),
        "enabled": module_path not in inactive,
        "modulePath": module_path,
        "hasConfig": has_config,
        "invalid": (not meta_ok) or (not module) or (not _valid_id(name)),
        "size": _dir_size(plugin_dir),
    }


def _plugin_names(root: Path) -> list[str]:
    """列出 plugins 下真正的目录，忽略 AstrBot 的安装中转目录。"""
    names: list[str] = []
    with os.scandir(root) as it:
        for entry in it:
            name = entry.name
            if name == "__pycache__" or name.startswith(_STAGING_PREFIXES):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    names.append(name)
            except OSError:
                continue
    names.sort(key=str.casefold)
    return names


def _read_prefs(iid: str | None = None) -> tuple[dict[str, Any], list[Any]]:
    """读取 shared_preferences.json 顶层对象和 inactivated_plugins 数组。"""
    path = runtime.prefs_path(_sid(iid))
    if not path.is_file():
        return {}, []
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as e:
        raise ValueError(f"读取 shared_preferences.json 失败：{e}") from e
    if not raw.strip():
        return {}, []
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as e:
        raise ValueError(f"shared_preferences.json 不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise ValueError("shared_preferences.json 顶层必须是对象")
    items = data.get("inactivated_plugins", [])
    if items is None:
        items = []
    if not isinstance(items, list):
        raise ValueError("shared_preferences.json 的 inactivated_plugins 必须是数组")
    return data, items


def _write_prefs(iid: str | None, data: dict[str, Any]) -> None:
    """原子写回，避免 AstrBot 正好重启时读到半个 JSON。"""
    path = runtime.prefs_path(_sid(iid))
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _tail_text(path: Path, max_bytes: int) -> str:
    """从文件尾读一段，丢掉被截断的第一行。"""
    max_bytes = max(1, max_bytes)
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size > max_bytes:
            fh.seek(-max_bytes, os.SEEK_END)
            data = fh.read()
            cut = data.find(b"\n")
            if cut >= 0:
                data = data[cut + 1:]
        else:
            fh.seek(0)
            data = fh.read()
    return data.decode("utf-8", "replace")


def _has_metadata(path: Path) -> bool:
    return any((path / name).is_file() for name in _META_NAMES)


def _find_plugin_root(tmp_root: Path) -> tuple[Path, bool]:
    """返回 (插件根目录, 是否 zip 根直接就是插件)。"""
    if _has_metadata(tmp_root):
        return tmp_root, True
    candidates: list[Path] = []
    with os.scandir(tmp_root) as it:
        for entry in it:
            if not entry.is_dir(follow_symlinks=False):
                continue
            path = tmp_root / entry.name
            if _has_metadata(path):
                candidates.append(path)
    if not candidates:
        raise ValueError("压缩包里没有找到 metadata.yaml 或 metadata.yml")
    if len(candidates) > 1:
        raise ValueError("压缩包里包含多个插件，请一次安装一个")
    return candidates[0], False


def _clean_name(name: str) -> str:
    """把 zip 里的目录名收敛成插件 ID 允许的字符。"""
    text = str(name or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip(" .")
    while ".." in text:
        text = text.replace("..", ".")
    if not text or not re.search(r"[A-Za-z0-9]", text):
        text = "plugin"
    if _WIN_RESERVED.match(text.split(".")[0]):
        text += "_"
    text = text[:80].rstrip(" .")
    if not text:
        text = "plugin"
    return text if _valid_id(text) else "plugin"


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """安全解压：拒绝绝对路径、..、符号链接和 Windows 特殊文件名。"""
    root = dest.resolve()
    infos = zf.infolist()
    if len(infos) > _MAX_UNZIP_FILES:
        raise ValueError("压缩包文件数量过多，已拒绝安装")
    total = 0
    for info in infos:
        raw_name = info.filename
        if not raw_name:
            continue
        name = raw_name.replace("\\", "/")
        if "\x00" in name:
            raise ValueError("压缩包包含非法文件名，已拒绝安装")
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
            raise ValueError("压缩包包含绝对路径，已拒绝安装")
        parts = [part for part in name.split("/") if part not in ("", ".")]
        if any(part == ".." for part in parts):
            raise ValueError("压缩包包含 .. 路径，已拒绝安装")
        if not parts:
            continue
        for part in parts:
            if part.rstrip(" .") != part:
                raise ValueError("压缩包包含 Windows 不允许的文件名，已拒绝安装")
            if _WIN_RESERVED.match(part.split(".")[0]):
                raise ValueError("压缩包包含 Windows 保留文件名，已拒绝安装")
            if any(ch in part for ch in ':*?"<>|'):
                raise ValueError("压缩包包含 Windows 不允许的字符，已拒绝安装")
        mode = info.external_attr >> 16
        if mode and stat.S_ISLNK(mode):
            raise ValueError("压缩包包含符号链接，已拒绝安装")
        if info.flag_bits & 0x1:
            raise ValueError("压缩包包含加密文件，无法安装")
        target = root.joinpath(*parts)
        if not _inside(root, target):
            raise ValueError("压缩包路径越界，已拒绝安装")
        target = target.resolve()
        # resolve 之后再确认一次，挡住解压过程中被替换成符号链接的情况
        if not _inside(root, target):
            raise ValueError("压缩包路径越界，已拒绝安装")
        if info.is_dir() or name.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UNZIP_BYTES:
                    raise ValueError("压缩包解压后体积过大，已拒绝安装")
                dst.write(chunk)


def list_all(iid: str | None = None) -> dict[str, Any]:
    """列出实例下的全部插件目录。"""
    sid = _sid(iid)
    root = _plugins_dir(sid)
    data_root = runtime.astrbot_data(sid)
    inactive: set[str] = set()
    warn = ""
    try:
        _, saved = _read_prefs(sid)
        inactive = {str(x) for x in saved}
    except ValueError as e:
        warn = str(e)

    items: list[dict[str, Any]] = []
    if root.is_dir():
        try:
            names = _plugin_names(root)
        except OSError as e:
            return {"ok": False, "err": f"读取插件目录失败：{e}"}
        for name in names:
            try:
                items.append(_build_item(data_root, name, root / name, inactive))
            except Exception:
                items.append({
                    "id": name,
                    "name": name,
                    "version": "",
                    "desc": "",
                    "author": "",
                    "repo": "",
                    "path": str(root / name),
                    "enabled": True,
                    "modulePath": "",
                    "hasConfig": False,
                    "invalid": True,
                    "size": 0,
                })

    out: dict[str, Any] = {"ok": True, "items": items, "dir": str(root)}
    if warn:
        out["warn"] = warn
    return out


def detail(plugin_id: str, iid: str | None = None) -> dict[str, Any]:
    """返回插件详情、配置和 README 摘要。"""
    try:
        pid = _check_id(plugin_id)
        sid = _sid(iid)
        plugin_dir = _plugin_dir(pid, sid)
    except ValueError as e:
        return {"ok": False, "err": str(e)}

    data_root = runtime.astrbot_data(sid)
    inactive: set[str] = set()
    try:
        _, saved = _read_prefs(sid)
        inactive = {str(x) for x in saved}
    except ValueError:
        pass
    try:
        item = _build_item(data_root, pid, plugin_dir, inactive)
    except Exception as e:
        return {"ok": False, "err": f"读取插件信息失败：{e}"}

    config: dict[str, Any] = {}
    cfg = data_root / "config" / f"{pid}_config.json"
    if cfg.is_file():
        try:
            raw = cfg.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as e:
            return {"ok": False, "err": f"读取插件配置失败：{e}"}
        try:
            loaded = json.loads(raw if raw.strip() else "{}")
        except (json.JSONDecodeError, RecursionError) as e:
            return {"ok": False, "err": f"插件配置不是合法 JSON：{e}"}
        if not isinstance(loaded, dict):
            return {"ok": False, "err": "插件配置必须是 JSON 对象"}
        config = loaded

    readme = ""
    readme_path = plugin_dir / "README.md"
    if readme_path.is_file():
        try:
            with readme_path.open("r", encoding="utf-8-sig", errors="replace") as fh:
                readme = fh.read(4000)
        except OSError:
            readme = ""
    return {"ok": True, "item": item, "config": config, "readme": readme}


def set_enabled(plugin_id: str, enabled: bool, iid: str | None = None) -> dict[str, Any]:
    """只改 shared_preferences.json 的 inactivated_plugins，不碰数据库。"""
    try:
        pid = _check_id(plugin_id)
        sid = _sid(iid)
        plugin_dir = _plugin_dir(pid, sid)
    except ValueError as e:
        return {"ok": False, "err": str(e)}

    module = _module_name(plugin_dir)
    if not module:
        return {"ok": False, "err": "插件没有可加载的 .py 入口，无法启停"}
    module_path = f"data.plugins.{pid}.{module}"
    want = bool(enabled)

    try:
        data, items = _read_prefs(sid)
    except ValueError as e:
        return {"ok": False, "err": str(e)}

    new_items = [x for x in items if x != module_path]
    if not want:
        new_items.append(module_path)
    data["inactivated_plugins"] = new_items
    try:
        _write_prefs(sid, data)
    except Exception as e:
        return {"ok": False, "err": f"保存启停状态失败：{e}"}
    return {"ok": True, "enabled": want, "needsRestart": True}


def install_zip(path: str, iid: str | None = None) -> dict[str, Any]:
    """从本机 zip 安装插件，返回新目录 id 与展示名。"""
    raw_path = str(path or "")
    if not raw_path.strip():
        return {"ok": False, "err": "请提供 zip 文件路径"}
    try:
        src = Path(raw_path).expanduser().resolve()
        src_is_file = src.is_file()
    except (OSError, RuntimeError, ValueError) as e:
        return {"ok": False, "err": f"zip 路径无效：{e}"}
    if not src_is_file:
        return {"ok": False, "err": f"找不到 zip 文件：{src}"}
    try:
        is_zip = zipfile.is_zipfile(src)
    except Exception:
        is_zip = False
    if not is_zip:
        return {"ok": False, "err": "不是有效的 zip 文件"}

    sid = _sid(iid)
    root = _plugins_dir(sid)
    try:
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
        tmp_root = Path(tempfile.mkdtemp(prefix="astrbot-plugin-", dir=str(paths.TMP_DIR)))
    except (OSError, RuntimeError, ValueError) as e:
        return {"ok": False, "err": f"准备安装目录失败：{e}"}

    try:
        with zipfile.ZipFile(src) as zf:
            _safe_extract(zf, tmp_root)
        plugin_root, from_zip_root = _find_plugin_root(tmp_root)

        if from_zip_root:
            # zip 根直接是插件：目录名只能从文件名推断，冲突时自动加 -2
            base = _clean_name(src.stem)
            final = base
            n = 2
            while os.path.lexists(root / final):
                if n > 99:
                    return {"ok": False, "err": "同名插件目录太多，无法生成新名称"}
                final = f"{base}-{n}"
                n += 1
        else:
            # 压缩包里有明确的顶层目录：重名视为冲突，避免覆盖已有插件
            final = _clean_name(plugin_root.name)
            if os.path.lexists(root / final):
                return {"ok": False, "err": f"插件目录已存在：{final}"}

        _check_id(final)
        dest = root / final
        if not _inside(root, dest):
            return {"ok": False, "err": "安装目标越界，已拒绝"}
        meta, _ = _load_meta(plugin_root)
        display = str(meta.get("name") or final)
        shutil.move(str(plugin_root), str(dest))
        return {"ok": True, "id": final, "name": display}
    except Exception as e:
        return {"ok": False, "err": f"安装失败：{e}"}
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def install_github(url: str, iid: str | None = None) -> dict[str, Any]:
    """从 GitHub 仓库的 main/master 分支下载 zip 并安装。"""
    raw = str(url or "").strip()
    if raw.endswith("/"):
        raw = raw[:-1]
    if raw.endswith(".git"):
        raw = raw[:-4].rstrip("/")
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)",
        raw,
    )
    if not match:
        return {"ok": False, "err": "只支持 https://github.com/<owner>/<repo> 形式的仓库地址"}
    owner, repo = match.group(1), match.group(2)
    if ".." in owner or ".." in repo or owner in (".", "..") or repo in (".", ".."):
        return {"ok": False, "err": "GitHub 仓库地址不合法"}

    try:
        paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "err": f"准备下载目录失败：{e}"}

    errors: list[str] = []
    for branch in ("main", "master"):
        target = paths.TMP_DIR / f"plugin-{repo}-{branch}-{os.getpid()}-{time.time_ns()}.zip"
        api = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        try:
            req = urllib.request.Request(api, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=60) as resp, target.open("wb") as fh:
                shutil.copyfileobj(resp, fh, 1024 * 1024)
            if not zipfile.is_zipfile(target):
                raise ValueError("下载内容不是有效的 zip")
            return install_zip(str(target), iid)
        except urllib.error.HTTPError as e:
            errors.append(f"{branch}: HTTP {e.code}")
            try:
                e.close()
            except Exception:
                pass
        except urllib.error.URLError as e:
            errors.append(f"{branch}: {e.reason}")
        except Exception as e:
            errors.append(f"{branch}: {e}")
        finally:
            try:
                target.unlink()
            except OSError:
                pass
    return {"ok": False, "err": "GitHub 下载失败：" + "；".join(errors)}


def remove(plugin_id: str, iid: str | None = None) -> dict[str, Any]:
    """把插件目录移到 backups/plugins-trash，不直接删除。"""
    try:
        pid = _check_id(plugin_id)
        sid = _sid(iid)
        plugin_dir = _plugin_dir(pid, sid)
    except ValueError as e:
        return {"ok": False, "err": str(e)}

    trash_dir = paths.BACKUP_DIR / "plugins-trash"
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "err": f"创建回收站失败：{e}"}
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    trash = trash_dir / f"{pid}-{stamp}"
    n = 2
    while os.path.lexists(trash):
        trash = trash_dir / f"{pid}-{stamp}-{n}"
        n += 1
    try:
        shutil.move(str(plugin_dir), str(trash))
    except Exception as e:
        return {"ok": False, "err": f"删除失败：{e}"}
    return {"ok": True, "trash": str(trash)}


def config_get(plugin_id: str, iid: str | None = None) -> dict[str, Any]:
    """读取插件配置；文件不存在时返回空对象。"""
    try:
        pid = _check_id(plugin_id)
    except ValueError as e:
        return {"ok": False, "err": str(e)}
    path = _config_path(pid, iid)
    if not path.is_file():
        return {"ok": True, "data": {}}
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as e:
        return {"ok": False, "err": f"读取插件配置失败：{e}"}
    try:
        data = json.loads(raw if raw.strip() else "{}")
    except (json.JSONDecodeError, RecursionError) as e:
        return {"ok": False, "err": f"插件配置不是合法 JSON：{e}"}
    if not isinstance(data, dict):
        return {"ok": False, "err": "插件配置必须是 JSON 对象"}
    return {"ok": True, "data": data}


def config_save(plugin_id: str, data: Any, iid: str | None = None) -> dict[str, Any]:
    """保存插件配置；先做 JSON 序列化校验，再原子替换。"""
    try:
        pid = _check_id(plugin_id)
    except ValueError as e:
        return {"ok": False, "err": str(e)}
    if not isinstance(data, dict):
        return {"ok": False, "err": "插件配置必须是 JSON 对象"}
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    except (TypeError, ValueError, RecursionError) as e:
        return {"ok": False, "err": f"配置无法序列化为 JSON：{e}"}

    path = _config_path(pid, iid)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, UnicodeError) as e:
        return {"ok": False, "err": f"保存插件配置失败：{e}"}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
    return {"ok": True, "data": data}


def logs(plugin_id: str, iid: str | None = None, lines: int = 300) -> dict[str, Any]:
    """读取 AstrBot 日志尾部，只保留与该插件相关的行。"""
    try:
        pid = _check_id(plugin_id)
        sid = _sid(iid)
    except ValueError as e:
        return {"ok": False, "err": str(e)}
    try:
        limit = int(lines)
    except (TypeError, ValueError, OverflowError):
        limit = 300
    log_path = runtime.astrbot_log(sid)
    if limit <= 0:
        return {"ok": True, "lines": [], "path": str(log_path)}

    terms = [pid]
    try:
        plugin_dir = _plugin_dir(pid, sid)
        meta, _ = _load_meta(plugin_dir)
        name = str(meta.get("name") or "").strip()
        if name and name != pid:
            terms.append(name)
    except ValueError:
        pass

    if not log_path.is_file():
        return {"ok": True, "lines": [], "path": str(log_path)}
    try:
        text = _tail_text(
            log_path,
            min(8 * 1024 * 1024, max(256 * 1024, limit * 1024)),
        )
    except OSError as e:
        return {"ok": False, "err": f"读取日志失败：{e}"}

    raw_lines = text.splitlines()[-limit:]
    needles = [item.casefold() for item in terms]
    matched = [line for line in raw_lines if any(n in line.casefold() for n in needles)]
    return {"ok": True, "lines": matched, "path": str(log_path)}


def failed(iid: str | None = None) -> dict[str, Any]:
    """列出缺 metadata 或缺 .py 入口的插件目录。"""
    sid = _sid(iid)
    root = _plugins_dir(sid)
    data_root = runtime.astrbot_data(sid)
    inactive: set[str] = set()
    try:
        _, saved = _read_prefs(sid)
        inactive = {str(x) for x in saved}
    except ValueError:
        pass
    if not root.is_dir():
        return {"ok": True, "items": []}
    try:
        names = _plugin_names(root)
    except OSError as e:
        return {"ok": False, "err": f"读取插件目录失败：{e}"}

    items: list[dict[str, Any]] = []
    for name in names:
        plugin_dir = root / name
        try:
            # 严格按“没有 metadata 或没有 .py”判断，目录名不合法不在此列
            _meta, meta_ok = _load_meta(plugin_dir)
            module = _module_name(plugin_dir)
        except Exception:
            continue
        if meta_ok and module:
            continue
        try:
            item = _build_item(data_root, name, plugin_dir, inactive)
        except Exception:
            continue
        items.append(item)
    return {"ok": True, "items": items}
