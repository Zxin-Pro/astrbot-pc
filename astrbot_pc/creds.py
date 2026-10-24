"""AstrBot 控制台（Dashboard）账号：读状态、写默认密码、重设密码。

AstrBot 只存哈希（默认 md5，升级后 pbkdf2_sha256），存进去的原文谁也拿不回来。
所以这里不做「把密码显示出来」这种假功能，而是：
- 密码还是出厂默认值（paths.DEFAULT_DASHBOARD_PASSWORD）时，直接把明文告诉你；
- 改过密码了，就给一个「重设」——生成一串强密码、写两套哈希、立刻可复制。
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import string
from pathlib import Path
from typing import Any

from . import paths, runtime

DEFAULT_PASSWORD = paths.DEFAULT_DASHBOARD_PASSWORD
# 1.0.2 及更早的出厂密码。老配置里还是它，也要能认出来并显示明文。
LEGACY_PASSWORDS = ("astrbot",)
ITERATIONS = 600_000


def _conf_path() -> Path:
    return runtime.cmd_path()


def _load() -> dict[str, Any]:
    p = _conf_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _md5(raw: str) -> str:
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _pbkdf2(raw: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def _default_plain(stored: str) -> str:
    """stored 是出厂密码的 md5 时返回明文，否则空串。"""
    if not isinstance(stored, str) or not stored:
        return ""
    low = stored.lower()
    for raw in (DEFAULT_PASSWORD, *LEGACY_PASSWORDS):
        if low == _md5(raw):
            return raw
    return ""


def _is_default(stored: str) -> bool:
    return bool(_default_plain(stored))


def ensure_default_password(dash: dict[str, Any]) -> bool:
    """给还没设密码的 dashboard 写死出厂密码，返回是否改过。

    AstrBot 启动时若发现 dashboard 没有哈希，会自己生成一串随机密码打到日志里。
    部署阶段先把哈希写进去，用户就永远拿到约定的那一个。
    已经有密码（用户改过、或老版本生成的随机串）时绝不动它。
    """
    if not isinstance(dash, dict):
        return False
    if dash.get("pbkdf2_password") or dash.get("password"):
        return False
    dash.update({
        "password": _md5(DEFAULT_PASSWORD),
        "pbkdf2_password": _pbkdf2(DEFAULT_PASSWORD),
        "password_storage_upgraded": True,
        "password_change_required": False,
    })
    return True


def generate() -> str:
    alphabet = string.ascii_letters + string.digits
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        *(secrets.choice(alphabet) for _ in range(13)),
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def info() -> dict[str, Any]:
    conf = _load()
    dash = conf.get("dashboard") if isinstance(conf.get("dashboard"), dict) else {}
    if not dash:
        return {"ok": False, "err": "还没生成 AstrBot 配置，先部署并启动一次 AstrBot"}
    username = str(dash.get("username") or "astrbot")
    stored = str(dash.get("password") or "")
    upgraded = bool(dash.get("password_storage_upgraded"))
    password = ""
    hint = ""
    matched = _default_plain(stored)
    if matched or (not stored and not dash.get("pbkdf2_password")):
        password = matched or DEFAULT_PASSWORD
        hint = "还是出厂密码，建议登录后改掉"
    elif upgraded or str(dash.get("pbkdf2_password") or ""):
        hint = "密码已加密保存，看不到原文；忘了就点「重设密码」"
    else:
        hint = "密码已加密保存，看不到原文；忘了就点「重设密码」"
    try:
        port = int(runtime.port(runtime.active_id(), "astrbot"))
    except Exception:
        port = int(dash.get("port") or paths.DEFAULT_PORTS["astrbot"] or 6185)
    return {
        "ok": True,
        "username": username,
        "password": password,
        "hint": hint,
        "url": f"http://127.0.0.1:{port}",
        "port": port,
        "changeRequired": bool(dash.get("password_change_required")),
        "upgraded": upgraded,
        # 出厂密码常量给前端做提示用（"密码忘了就试这个"）
        "defaultPassword": DEFAULT_PASSWORD,
    }


def reset(username: str = "", password: str = "") -> dict[str, Any]:
    conf = _load()
    dash = conf.get("dashboard") if isinstance(conf.get("dashboard"), dict) else {}
    if not dash:
        return {"ok": False, "err": "还没生成 AstrBot 配置，先部署并启动一次 AstrBot"}
    user = (username or str(dash.get("username") or "astrbot")).strip() or "astrbot"
    if not re.match(r"^[A-Za-z0-9_.@-]{3,32}$", user):
        return {"ok": False, "err": "用户名只能是 3~32 位字母、数字或 _ . @ -"}
    raw = password or generate()
    if len(raw) < 8 or not re.search(r"[A-Z]", raw) or not re.search(r"[a-z]", raw) or not re.search(r"\d", raw):
        return {"ok": False, "err": "密码至少 8 位，且要同时有大写、小写和数字"}
    dash.update({
        "username": user,
        "password": _md5(raw),
        "pbkdf2_password": _pbkdf2(raw),
        "password_storage_upgraded": True,
        "password_change_required": False,
    })
    conf["dashboard"] = dash
    try:
        p = _conf_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=4), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        return {"ok": False, "err": f"写入配置失败：{e}"}
    return {"ok": True, "username": user, "password": raw, "needsRestart": True,
            "message": "控制台密码已重设，重启 AstrBot 后生效"}
