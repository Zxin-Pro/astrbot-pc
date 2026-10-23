"""AstrBot 的模型与人格配置：替用户写好，只让他贴一个密钥。

AstrBot v4 把这两样放在完全不同的地方，改错位置等于没改：

- **模型**在 ``data/cmd_config.json`` 的 ``provider`` 数组里；真正决定「用哪个」
  的是 ``agent_runner.config.model.provider_id``。
- **人格**在 ``data/data_v4.db`` 的 ``personas`` 表里（SQLite）。``cmd_config.json``
  里的 ``persona`` 字段在 v4 已标记 deprecated，写它不会生效。

两处都是 AstrBot **启动时读一次**，所以改完必须重启 AstrBot 才会用上。
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from . import config, paths

# 中转站（烛心推荐的这家）。地址写死成默认值，用户可以在界面上改。
RELAY_BASE = "https://worldcodes.online"
RELAY_API = RELAY_BASE + "/v1"
RELAY_REGISTER = RELAY_BASE + "/register?invite_code=CZLT"
RELAY_SETTINGS = RELAY_BASE + "/api/v1/settings/public"
RELAY_HEALTH = RELAY_BASE + "/health"

# 我们写进 provider 数组的那一项的 id。用固定值，重复保存就是原地改。
PROVIDER_ID = "worldcodes"
# AstrBot v4 会把「连接信息」和「模型」拆成两层：
#   provider_sources 存 base_url / key / 超时
#   provider 存模型名，用 provider_source_id 指回上面
# 我们直接按这个结构写，免得每次启动都被它迁移一遍（迁移会重写配置文件）。
SOURCE_ID = "worldcodes_source"

DEFAULT_MODEL = "gpt-4o-mini"


def _stack() -> Path:
    return paths.STACK_DIR


def cmd_path() -> Path:
    return _stack() / "astrbot" / "data" / "cmd_config.json"


def db_path() -> Path:
    return _stack() / "astrbot" / "data" / "data_v4.db"


def installed() -> bool:
    return cmd_path().exists()


# ---------------- cmd_config.json ----------------


def _read_cmd() -> dict[str, Any]:
    p = cmd_path()
    if not p.exists():
        raise FileNotFoundError("还没部署 AstrBot，找不到 data/cmd_config.json")
    # utf-8-sig：用户可能用记事本改过，带 BOM 也能读
    return json.loads(p.read_text("utf-8-sig"))


def _write_cmd(data: dict[str, Any]) -> None:
    p = cmd_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(p)


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def _provider_entry(data: dict[str, Any]) -> dict[str, Any] | None:
    for item in data.get("provider") or []:
        if isinstance(item, dict) and item.get("id") == PROVIDER_ID:
            return item
    return None


def _connection(entry: dict[str, Any], data: dict[str, Any]) -> tuple[str, str]:
    """从 provider 项里取出接口地址和密钥。

    v4 把它们放在 ``provider_sources`` 里，provider 项只留一个
    ``provider_source_id`` 指过去；老格式（扁平）则直接写在 provider 项上。
    两种都要认，否则 AstrBot 迁移过一次之后界面就读不出已配置的东西了。
    """
    src: dict[str, Any] = entry
    sid = str(entry.get("provider_source_id") or "").strip()
    if sid:
        for item in data.get("provider_sources") or []:
            if isinstance(item, dict) and item.get("id") == sid:
                src = item
                break

    base = str(src.get("api_base") or "")
    keys = src.get("key") or []
    if isinstance(keys, list):
        first = keys[0] if keys else ""
    elif isinstance(keys, str):
        first = keys
    else:
        first = ""
    return base, str(first)


def _stored_key(data: dict[str, Any]) -> str:
    """已经存下来的密钥：先顺着 provider 项找，再单独看 v4 的连接信息。"""
    entry = _provider_entry(data)
    if entry:
        key = _connection(entry, data)[1]
        if key:
            return key
    for item in data.get("provider_sources") or []:
        if not isinstance(item, dict) or item.get("id") != SOURCE_ID:
            continue
        keys = item.get("key") or []
        if isinstance(keys, list):
            return str(keys[0]) if keys else ""
        return str(keys)
    return ""


def current() -> dict[str, Any]:
    """界面用：现在配的是哪个模型、哪个人格。密钥只回打码后的。"""
    if not installed():
        return {"ok": True, "installed": False, "configured": False}

    out: dict[str, Any] = {"ok": True, "installed": True, "configured": False}
    try:
        data = _read_cmd()
    except Exception as e:
        return {"ok": False, "installed": True, "err": f"读不到 AstrBot 配置：{e}"}

    entry = _provider_entry(data)
    runner = data.get("agent_runner") or {}
    runner_cfg = runner.get("config") or {}
    active_id = ((runner_cfg.get("model") or {}).get("provider_id") or "").strip()

    if entry:
        api_base, first = _connection(entry, data)
        out["provider"] = {
            "id": entry.get("id"),
            "apiBase": api_base,
            "model": entry.get("model") or "",
            "key": _mask(first),
            "hasKey": bool(first),
            "active": active_id == PROVIDER_ID,
        }
        out["configured"] = bool(first) and bool(entry.get("model")) and active_id == PROVIDER_ID

    out["activeProviderId"] = active_id
    out["persona"] = _current_persona(data, runner_cfg)
    out["relay"] = {
        "base": config.get("llm.relayBase", RELAY_BASE),
        "register": RELAY_REGISTER,
    }
    return out


def _current_persona(data: dict[str, Any], runner_cfg: dict[str, Any]) -> dict[str, Any]:
    pid = ((runner_cfg.get("persona") or {}).get("persona_id") or "").strip()
    info: dict[str, Any] = {"id": pid, "custom": False, "prompt": ""}
    if not pid:
        return info
    try:
        conn = sqlite3.connect(str(db_path()), timeout=10)
        try:
            row = conn.execute(
                "select system_prompt from personas where persona_id = ?", (pid,)
            ).fetchone()
        finally:
            conn.close()
        if row:
            info["prompt"] = row[0] or ""
            info["custom"] = pid != "default"
    except Exception:
        pass
    return info


def apply_model(api_base: str, api_key: str, model: str) -> dict[str, Any]:
    """把中转站写成一个 OpenAI 兼容 provider，并设为默认模型。"""
    api_base = (api_base or "").strip().rstrip("/")
    api_key = (api_key or "").strip()
    model = (model or "").strip()
    if not api_base:
        return {"ok": False, "err": "接口地址不能为空"}
    if not model:
        return {"ok": False, "err": "模型名不能为空"}

    try:
        data = _read_cmd()
    except Exception as e:
        return {"ok": False, "err": str(e)}

    if not api_key:
        # 界面允许「密钥留空 = 不改」，这时沿用已经存下的那把
        api_key = _stored_key(data)
        if not api_key:
            return {"ok": False, "err": "API 密钥不能为空"}

    entry: dict[str, Any]
    if "provider_sources" in data:
        # v4 结构：连接信息单独一份，provider 只留模型名和来源引用。
        # 直接照它的最终形态写，避免它启动时再迁移一遍（迁移会重写整个文件）。
        sources = [s for s in (data.get("provider_sources") or []) if isinstance(s, dict)]
        source = {
            "id": SOURCE_ID,
            "type": "openai_chat_completion",
            "provider": "openai",
            "provider_type": "chat_completion",
            "key": [api_key],
            "api_base": api_base,
            "timeout": 120,
            "proxy": "",
            "custom_headers": {},
        }
        for i, item in enumerate(sources):
            if item.get("id") == SOURCE_ID:
                sources[i] = source
                break
        else:
            sources.append(source)
        data["provider_sources"] = sources

        entry = {
            "id": PROVIDER_ID,
            "enable": True,
            "model": model,
            "provider_source_id": SOURCE_ID,
            "modalities": [],
            "custom_extra_body": {},
        }
    else:
        # 老版本 AstrBot（没有 provider_sources）只有扁平结构
        entry = {
            # 字段跟 AstrBot 内置的「OpenAI Compatible」模板一致，少一个都会在读配置时炸
            "id": PROVIDER_ID,
            "type": "openai_chat_completion",
            "provider": "openai",
            "provider_type": "chat_completion",
            "enable": True,
            "key": [api_key],
            "api_base": api_base,
            "model": model,
            "timeout": 120,
            "proxy": "",
            "custom_headers": {},
        }

    providers = [p for p in (data.get("provider") or []) if isinstance(p, dict)]
    replaced = False
    for i, item in enumerate(providers):
        if item.get("id") == PROVIDER_ID:
            providers[i] = entry
            replaced = True
            break
    if not replaced:
        providers.append(entry)
    data["provider"] = providers

    runner = data.setdefault("agent_runner", {})
    runner["runner_type"] = runner.get("runner_type") or "local"
    rcfg = runner.setdefault("config", {})
    rcfg.setdefault("model", {})["provider_id"] = PROVIDER_ID

    try:
        _write_cmd(data)
    except Exception as e:
        return {"ok": False, "err": f"写 AstrBot 配置失败：{e}"}

    # 顺手记进我们自己的配置，重装/换机时能回填界面
    config.save({"llm": {"apiBase": api_base, "model": model, "providerId": PROVIDER_ID}})
    return {"ok": True, "providerId": PROVIDER_ID, "model": model, "apiBase": api_base}


def apply_persona(persona_id: str, prompt: str) -> dict[str, Any]:
    """写入 personas 表并设为默认人格。"""
    persona_id = (persona_id or "").strip() or "烛心"
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "err": "人格提示词不能为空"}
    if not db_path().exists():
        return {"ok": False, "err": "还没部署 AstrBot，找不到 data_v4.db（先启动一次 AstrBot 再设人格）"}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        conn = sqlite3.connect(str(db_path()), timeout=30)
        try:
            conn.execute(
                """
                insert into personas
                    (created_at, updated_at, persona_id, system_prompt,
                     begin_dialogs, tools, skills, custom_error_message, folder_id, sort_order)
                values (?, ?, ?, ?, '[]', 'null', 'null', null, null, 0)
                on conflict(persona_id) do update set
                    system_prompt = excluded.system_prompt,
                    updated_at = excluded.updated_at
                """,
                (now, now, persona_id, prompt),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {"ok": False, "err": f"写人格到数据库失败：{e}"}

    try:
        data = _read_cmd()
    except Exception as e:
        return {"ok": False, "err": str(e)}
    runner = data.setdefault("agent_runner", {})
    rcfg = runner.setdefault("config", {})
    rcfg.setdefault("persona", {})["persona_id"] = persona_id
    try:
        _write_cmd(data)
    except Exception as e:
        return {"ok": False, "err": f"写 AstrBot 配置失败：{e}"}

    config.save({"llm": {"personaId": persona_id}})
    return {"ok": True, "personaId": persona_id}


# ---------------- 中转站 ----------------


def _get_json(url: str, timeout: float = 12.0, key: str = "") -> tuple[int, Any]:
    headers = {"User-Agent": "AstrBotPC", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:200]


def relay_info() -> dict[str, Any]:
    """查中转站在线状态与站点版本号。

    Sub2API 面板把版本号放在公开设置接口里（``data.version``），首页 HTML 里没有。
    """
    base = str(config.get("llm.relayBase", RELAY_BASE) or RELAY_BASE).rstrip("/")
    started = time.time()
    info: dict[str, Any] = {"ok": True, "base": base, "online": False}

    try:
        status, payload = _get_json(base + "/api/v1/settings/public", timeout=12)
        elapsed = int((time.time() - started) * 1000)
        if status == 200 and isinstance(payload, dict):
            data = payload.get("data") or {}
            info.update(
                {
                    "online": True,
                    "siteName": data.get("site_name") or "",
                    "subtitle": data.get("site_subtitle") or "",
                    "version": data.get("version") or "",
                    "latencyMs": elapsed,
                }
            )
            return info
        info["err"] = f"站点返回 HTTP {status}"
    except Exception as e:
        info["err"] = f"连不上中转站：{type(e).__name__}"

    # 设置接口挂了也再试一次健康检查，能回 ok 就算在线（只是拿不到版本号）
    try:
        status, payload = _get_json(base + "/health", timeout=8)
        if status == 200 and isinstance(payload, dict) and payload.get("status") == "ok":
            info["online"] = True
            info.pop("err", None)
    except Exception:
        pass
    return info


def list_models(api_key: str = "", api_base: str = "") -> dict[str, Any]:
    """拉模型列表。有密钥时顺便验证密钥是否可用。"""
    base = (api_base or str(config.get("llm.apiBase", RELAY_API)) or RELAY_API).rstrip("/")
    if not base.endswith("/v1"):
        base = base + "/v1"
    key = (api_key or "").strip()
    try:
        status, payload = _get_json(base + "/models", timeout=15, key=key)
    except Exception as e:
        return {"ok": False, "err": f"连不上接口：{type(e).__name__}"}

    if status == 401:
        return {"ok": False, "err": "密钥不对（接口返回 401）"}
    if status != 200:
        msg = ""
        if isinstance(payload, dict):
            msg = payload.get("message") or payload.get("error") or ""
        return {"ok": False, "err": f"接口返回 HTTP {status} {msg}".strip()}

    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return {"ok": False, "err": "接口返回的格式不认识（没有 data 数组）"}

    models = []
    for it in items:
        if isinstance(it, dict) and it.get("id"):
            models.append(str(it["id"]))
        elif isinstance(it, str):
            models.append(it)
    models.sort()
    return {"ok": True, "models": models, "count": len(models), "apiBase": base}


def _post_json(url: str, payload: dict[str, Any], key: str, timeout: float = 30.0) -> tuple[int, Any]:
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": "AstrBotPC",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw[:300]


def test_connection() -> dict[str, Any]:
    """拿已保存的模型配置真发一次请求。

    「密钥填了、地址填了」不等于能聊——401、模型名写错、余额不足都是保存时
    看不出来的。这里发一个 max_tokens=1 的短请求，把真实结果摆出来。
    """
    if not installed():
        return {"ok": False, "err": "还没部署 AstrBot"}
    try:
        conf = _read_cmd()
    except Exception as e:
        return {"ok": False, "err": f"读不到 AstrBot 配置：{e}"}

    sources = conf.get("provider_sources") or []
    providers = conf.get("provider") or []
    if not isinstance(providers, list) or not providers:
        return {"ok": False, "err": "还没有配置模型，先把上面的表单填好保存"}
    target = str(((conf.get("agent_runner") or {}).get("config") or {}).get("model", {}).get("provider_id") or "")
    prov = next((p for p in providers if isinstance(p, dict) and p.get("id") == target), None)
    if prov is None:
        prov = next((p for p in providers if isinstance(p, dict)), None) or {}
    src = next((s for s in sources if isinstance(s, dict) and s.get("id") == prov.get("provider_source_id")), {})
    base = str(src.get("api_base") or src.get("apiBase") or "").strip()
    model = str(prov.get("model") or "").strip()
    key = ""
    raw_key = src.get("key")
    if isinstance(raw_key, list) and raw_key:
        key = str(raw_key[0] or "")
    elif isinstance(raw_key, str):
        key = raw_key
    if not base or not model:
        return {"ok": False, "err": "模型配置不完整（缺 API 地址或模型名）"}
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"

    started = time.time()
    try:
        status, payload = _post_json(
            base + "/chat/completions",
            {"model": model, "messages": [{"role": "user", "content": "ping"}],
             "max_tokens": 1, "stream": False},
            key,
            timeout=30,
        )
    except Exception as e:
        return {"ok": False, "err": f"连不上模型接口：{type(e).__name__}: {e}", "model": model, "apiBase": base}
    latency = int((time.time() - started) * 1000)

    if status == 200 and isinstance(payload, dict):
        reply = ""
        try:
            reply = str(payload["choices"][0]["message"].get("content") or "")
        except Exception:
            reply = ""
        usage = payload.get("usage") or {}
        return {"ok": True, "model": model, "apiBase": base, "latencyMs": latency,
                "reply": reply[:60], "usage": usage}
    msg = ""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("type") or "")
        elif err:
            msg = str(err)
        msg = msg or str(payload.get("message") or "")
    if status == 401:
        return {"ok": False, "err": "密钥不对（接口返回 401）", "model": model, "apiBase": base, "latencyMs": latency}
    return {"ok": False, "err": f"接口返回 HTTP {status} {msg}".strip(), "model": model,
            "apiBase": base, "latencyMs": latency}
