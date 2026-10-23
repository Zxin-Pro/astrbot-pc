"""模型线路故障转移：配置、健康检查与排序。

线路（route）是一份**有序列表**，每条线路是一组 OpenAI 兼容的
apiBase / apiKey / model。真正在多个模型之间来回切换的是 AstrBot 原生的
fallback_provider_ids —— 主 provider 请求失败时它按顺序换下一个。

本模块不接管那次切换，只做 PC 管理端需要的三件事：

1. 配置：线路列表存在我们自己的 config.json 的 llm.routes 里。apiKey 是明文，
   只留在后端；回给前端的一律打码。
2. 健康：对每条启用的线路发一次 max_tokens=1 的探测请求，结果缓存 30 秒，
   界面反复刷新也不会把接口打爆。
3. 排序：order() 给出「健康优先、再按 priority」的顺序，current() 给出现在
   该当作主线路的那一条。

兼容旧配置：没有 llm.routes 时，用 config 的 llm.apiBase / llm.model 和当前
实例 cmd_config.json 里 provider_sources 的密钥拼成唯一的一条线路。

所有导出函数都返回 dict，内部异常一律转成 {"ok": False, "err": "..."}，
界面层不需要再包 try。
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import config, paths, runtime

__all__ = [
    "list_routes",
    "save_routes",
    "remove_route",
    "health",
    "order",
    "current",
]

#: 健康结果的缓存文件（config.write_state 会放到 state/ 下）
HEALTH_FILE = "failover-health.json"
#: 缓存多久算过期（秒）。健康探测要真打接口，界面轮询不能每次都打。
HEALTH_TTL = 30
#: 单条线路的探测超时（秒）
TIMEOUT = 12.0
#: 同时探测几条线路（线路多时不至于串行等 12 秒 × N）
MAX_PARALLEL = 6
#: 旧配置只有一条线路时给它一个固定 id，重复保存就是原地改
LEGACY_ID = "default"

# 同一个健康检查不要并发跑两遍（前端两个页面同时点「检测」时）
_HEALTH_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _err(msg: Any) -> dict[str, Any]:
    text = str(msg or "").strip() or "未知错误"
    return {"ok": False, "err": text}


def _now() -> int:
    return int(time.time())


def _pick(raw: dict[str, Any], *names: str) -> Any:
    """按顺序取第一个存在的字段（兼容 apiBase / api_base 两种写法）。"""
    for name in names:
        if name in raw and raw.get(name) is not None:
            return raw.get(name)
    return None


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("", "none", "null"):
        return default
    return text not in ("0", "false", "no", "off", "n")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        return int(float(str(value).strip()))
    except Exception:
        return default


def _sane_id(raw: Any) -> str:
    """线路 id 只留字母数字和 - _，避免拼进 state 文件名时出岔子。"""
    keep = [c for c in str(raw or "").strip() if c.isalnum() or c in "-_"]
    return "".join(keep)[:64]


def _unique_id(base: str, seen: set[str]) -> str:
    rid = base
    n = 2
    while rid in seen:
        rid = f"{base}-{n}"
        n += 1
    return rid


def _mask(key: Any) -> str:
    """给前端看的密钥：sk-t…3456。空 key 回空串。"""
    text = str(key or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}…{text[-4:]}"


def _looks_masked(key: Any) -> bool:
    """前端可能把打码后的值原样提交回来，那种值不能当密钥存。"""
    text = str(key or "")
    return "…" in text or "***" in text


def _norm_base(base: Any) -> str:
    return str(base or "").strip().rstrip("/")


def _valid_base(base: Any) -> bool:
    text = str(base or "").strip()
    if not re.match(r"^https?://", text, re.I):
        return False
    rest = text.split("://", 1)[1]
    return bool(rest) and not rest.startswith("/")


def _v1(base: Any) -> str:
    """把接口地址规范成以 /v1 结尾；填了完整 .../chat/completions 也能救回来。"""
    text = _norm_base(base)
    if not text:
        return ""
    low = text.lower()
    if low.endswith("/chat/completions"):
        text = text[: -len("/chat/completions")].rstrip("/")
        low = text.lower()
    if low.endswith("/v1"):
        return text
    return text + "/v1"


def _first_key(raw: Any) -> str:
    if isinstance(raw, list):
        for item in raw:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    if isinstance(raw, dict):
        return _first_key(raw.get("key"))
    return str(raw or "").strip()


# ---------------------------------------------------------------------------
# AstrBot cmd_config.json（旧配置的密钥来源）
# ---------------------------------------------------------------------------


def _cmd_files(iid: str | None = None) -> list[Path]:
    out: list[Path] = []
    try:
        out.append(runtime.cmd_path(iid))
    except Exception:
        pass
    # 老版本没有实例根时，模型配置还在 stack/astrbot/data 下
    out.append(paths.STACK_DIR / "astrbot" / "data" / "cmd_config.json")
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def _pick_connection(data: dict[str, Any]) -> tuple[str, str, str]:
    """从 cmd_config 里取（api_base, key, model）。

    v4 把连接信息放 provider_sources、模型名放 provider；老格式是扁平的。
    优先认 agent_runner 当前选中的那个 provider，认不出来就用第一条启用的。
    """
    providers = [p for p in (data.get("provider") or []) if isinstance(p, dict)]
    sources = [s for s in (data.get("provider_sources") or []) if isinstance(s, dict)]
    by_id = {str(s.get("id") or ""): s for s in sources}

    runner = data.get("agent_runner") or {}
    runner_cfg = runner.get("config") if isinstance(runner, dict) else {}
    active = str(((runner_cfg or {}).get("model") or {}).get("provider_id") or "")

    entry = next((p for p in providers if str(p.get("id") or "") == active), None)
    if entry is None:
        entry = next((p for p in providers if p.get("enable", True)), None)
    if entry is None:
        entry = providers[0] if providers else {}

    src = by_id.get(str(entry.get("provider_source_id") or "")) or entry
    base = _norm_base(_pick(src, "api_base", "apiBase") or _pick(entry, "api_base", "apiBase"))
    key = _first_key(src.get("key")) or _first_key(entry.get("key"))
    model = str(entry.get("model") or src.get("model") or "").strip()

    if not key:
        # 选中的那项没 key 时，随便找一条带 key 的来源，总比空着强
        for source in sources:
            key = _first_key(source.get("key"))
            if key:
                break
    if not base:
        for source in sources:
            base = _norm_base(_pick(source, "api_base", "apiBase"))
            if base:
                break
    return base, key, model


def _legacy_connection(iid: str | None = None) -> tuple[str, str, str]:
    for path in _cmd_files(iid):
        try:
            data = json.loads(Path(path).read_text("utf-8-sig"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        base, key, model = _pick_connection(data)
        if base or key or model:
            return base, key, model
    return "", "", ""


def _legacy_route(iid: str | None = None) -> list[dict[str, Any]]:
    """没有 llm.routes 时，用旧配置拼出唯一的一条线路。"""
    base = _norm_base(config.get("llm.apiBase", ""))
    model = str(config.get("llm.model", "") or "").strip()
    cmd_base, cmd_key, cmd_model = _legacy_connection(iid)
    base = base or cmd_base
    model = model or cmd_model
    if not base and not model and not cmd_key:
        return []
    return [
        {
            "id": LEGACY_ID,
            "name": "默认线路",
            "apiBase": base,
            "apiKey": cmd_key,
            "model": model,
            "enabled": True,
            "priority": 10,
        }
    ]


# ---------------------------------------------------------------------------
# 线路数据结构
# ---------------------------------------------------------------------------


def _coerce_route(raw: dict[str, Any], idx: int) -> dict[str, Any]:
    rid = _sane_id(raw.get("id")) or f"route-{idx + 1}"
    return {
        "id": rid,
        "name": str(raw.get("name") or "").strip() or f"线路 {idx + 1}",
        "apiBase": _norm_base(_pick(raw, "apiBase", "api_base", "baseUrl", "base_url")),
        "apiKey": str(_pick(raw, "apiKey", "api_key", "key") or "").strip(),
        "model": str(_pick(raw, "model", "modelName") or "").strip(),
        "enabled": _as_bool(raw.get("enabled"), True),
        "priority": _as_int(raw.get("priority"), 10 * (idx + 1)),
    }


def _sorted(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # 稳定排序：priority 相同的保持列表里的先后
    return sorted(routes, key=lambda r: _as_int(r.get("priority"), 0))


def _enabled(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in routes if r.get("enabled")]


def _raw_routes(iid: str | None = None) -> tuple[list[dict[str, Any]], bool]:
    """读出线路列表 + 是否来自旧配置兼容。"""
    raw = config.get("llm.routes", None)
    if isinstance(raw, list) and raw:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, entry in enumerate(raw):
            if not isinstance(entry, dict):
                continue
            route = _coerce_route(entry, idx)
            route["id"] = _unique_id(route["id"], seen)
            seen.add(route["id"])
            items.append(route)
        if items:
            return _sorted(items), False
    return _legacy_route(iid), True


def _public(route: dict[str, Any], primary_id: str) -> dict[str, Any]:
    return {
        "id": route["id"],
        "name": route["name"],
        "apiBase": route["apiBase"],
        "model": route["model"],
        "enabled": bool(route["enabled"]),
        "priority": int(route["priority"]),
        "primary": route["id"] == primary_id,
        "maskedKey": _mask(route["apiKey"]),
    }


def _sig(routes: list[dict[str, Any]]) -> str:
    """线路指纹：判断缓存结果还对不对得上现在这批线路。

    密钥只进哈希，state 文件里不会出现明文。
    """
    parts: list[list[Any]] = []
    for route in routes:
        key = str(route.get("apiKey") or "")
        parts.append(
            [
                str(route.get("id") or ""),
                _v1(route.get("apiBase") or ""),
                str(route.get("model") or ""),
                1 if route.get("enabled") else 0,
                _as_int(route.get("priority"), 0),
                hashlib.sha1(key.encode("utf-8")).hexdigest()[:12],
            ]
        )
    blob = json.dumps(parts, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


def _http_err(body: str, status: int) -> str:
    msg = ""
    try:
        payload = json.loads(body)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("type") or "")
        elif err:
            msg = str(err)
        msg = msg or str(payload.get("message") or payload.get("msg") or "")
    if not msg:
        msg = (body or "").strip().replace("\n", " ")[:120]
    if status == 401:
        return "密钥不对（HTTP 401）"
    if status == 403:
        return f"没有权限（HTTP 403）{('：' + msg) if msg else ''}"
    if status == 404:
        return f"接口地址不对（HTTP 404）{('：' + msg) if msg else ''}"
    if status == 429:
        return f"被限流了（HTTP 429）{('：' + msg) if msg else ''}"
    return f"HTTP {status}{('：' + msg) if msg else ''}".strip()


def _probe(route: dict[str, Any]) -> dict[str, Any]:
    """对一条线路发一次 max_tokens=1 的探测，永远返回 dict。"""
    rid = str(route.get("id") or "")
    base = _v1(route.get("apiBase") or "")
    if not base:
        return {"id": rid, "ok": False, "latencyMs": 0, "status": 0, "err": "没有填接口地址"}

    url = base + "/chat/completions"
    payload = {
        "model": str(route.get("model") or ""),
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "User-Agent": "AstrBotPC",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    key = str(route.get("apiKey") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    started = time.time()
    status = 0
    body = ""
    try:
        # 地址里混进控制字符时 Request() 本身就会抛，一起兜住
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            body = resp.read(8192).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = int(e.code or 0)
        try:
            body = e.read(8192).decode("utf-8", "replace")
        except Exception:
            body = ""
    except Exception as e:
        latency = int((time.time() - started) * 1000)
        if isinstance(e, (socket.timeout, TimeoutError)):
            msg = f"超时（{int(TIMEOUT)} 秒）"
        elif isinstance(e, urllib.error.URLError):
            reason = getattr(e, "reason", e)
            msg = f"连不上：{type(reason).__name__}: {reason}"
        else:
            msg = f"连不上：{type(e).__name__}: {e}"
        return {"id": rid, "ok": False, "latencyMs": latency, "status": 0, "err": msg[:200]}

    latency = int((time.time() - started) * 1000)
    if 200 <= status < 300:
        return {"id": rid, "ok": True, "latencyMs": latency, "status": status, "err": ""}
    return {"id": rid, "ok": False, "latencyMs": latency, "status": status, "err": _http_err(body, status)[:200]}


def _probe_all(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(routes) <= 1:
        return [_probe(r) for r in routes]
    workers = min(MAX_PARALLEL, len(routes))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="failover") as pool:
        return list(pool.map(_probe, routes))


def _cached_health(routes: list[dict[str, Any]], max_age: int | None) -> dict[str, Any] | None:
    """读缓存。max_age=None 表示不设有效期（排序用上次结论即可）。"""
    if not routes:
        return None
    data = config.read_state(HEALTH_FILE, None)
    if not isinstance(data, dict):
        return None
    if str(data.get("sig") or "") != _sig(routes):
        return None
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        return None
    items = [i for i in raw_items if isinstance(i, dict)]
    if len(items) != len(routes):
        return None
    ts = _as_int(data.get("ts"), 0)
    if ts <= 0:
        return None
    age = _now() - ts
    if age < 0 or (max_age is not None and age >= max_age):
        return None
    healthy = [str(i.get("id") or "") for i in items if i.get("ok")]
    return {"items": items, "healthy": healthy, "ts": ts}


def _known_health(routes: list[dict[str, Any]]) -> tuple[list[str] | None, int]:
    """最近一次健康检查的结论（不限龄）。没有或对不上就返回 (None, 0)。"""
    hit = _cached_health(routes, None)
    if not hit:
        return None, 0
    return hit["healthy"], _as_int(hit["ts"], 0)


def _primary_id(routes: list[dict[str, Any]], healthy: list[str] | None) -> str:
    """第一条健康且启用的；都不健康就退回第一条启用的。"""
    enabled = _enabled(routes)
    if not enabled:
        return ""
    if healthy:
        ok_ids = set(healthy)
        for route in enabled:
            if route["id"] in ok_ids:
                return route["id"]
    return str(enabled[0]["id"])


# ---------------------------------------------------------------------------
# 导出：配置
# ---------------------------------------------------------------------------


def list_routes(iid: str | None = None) -> dict[str, Any]:
    """线路列表。密钥只回打码后的 maskedKey。"""
    try:
        routes, legacy = _raw_routes(iid)
        routes = _sorted(routes)
        healthy, ts = _known_health(_enabled(routes))
        primary = _primary_id(routes, healthy)
        items = [_public(r, primary) for r in routes]
        return {
            "ok": True,
            "items": items,
            "count": len(items),
            "enabled": len(_enabled(routes)),
            "legacy": legacy,
            "currentId": primary,
            "checkedAt": ts,
        }
    except Exception as e:
        return _err(f"读取线路失败：{type(e).__name__}: {e}")


def save_routes(routes: Any, iid: str | None = None) -> dict[str, Any]:
    """校验并保存整份线路列表。

    校验：至少一条、地址是 http(s)、模型名非空、id 不重复、至少一条启用。
    apiKey 留空表示沿用这条线路已存的密钥（旧配置的密钥来自 cmd_config）。
    """
    try:
        if not isinstance(routes, list):
            return _err("routes 必须是数组")
        if not routes:
            return _err("至少要有一条线路")

        try:
            existing, _legacy = _raw_routes(iid)
        except Exception:
            existing = []
        old_keys = {str(r.get("id") or ""): str(r.get("apiKey") or "") for r in existing}

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, raw in enumerate(routes):
            no = idx + 1
            if not isinstance(raw, dict):
                return _err(f"第 {no} 条线路格式不对（要对象）")

            rid = _sane_id(raw.get("id"))
            if rid and rid in seen:
                return _err(f"线路 id 重复：{rid}")
            # 没填 id 的（新加的空行）给一个不冲突的名字，别让界面卡住
            rid = rid or _unique_id(f"route-{no}", seen)

            base = _norm_base(_pick(raw, "apiBase", "api_base", "baseUrl", "base_url"))
            if not base:
                return _err(f"第 {no} 条线路缺少接口地址（apiBase）")
            if not _valid_base(base):
                return _err(f"第 {no} 条线路的接口地址必须以 http:// 或 https:// 开头")

            model = str(_pick(raw, "model", "modelName") or "").strip()
            if not model:
                return _err(f"第 {no} 条线路缺少模型名（model）")

            key = str(_pick(raw, "apiKey", "api_key", "key") or "").strip()
            if not key or _looks_masked(key):
                # 空 key / 打码值 = 不改；沿用这条线路原来的密钥
                key = old_keys.get(rid, "")

            items.append(
                {
                    "id": rid,
                    "name": str(raw.get("name") or "").strip() or f"线路 {no}",
                    "apiBase": base,
                    "apiKey": key,
                    "model": model,
                    "enabled": _as_bool(raw.get("enabled"), True),
                    "priority": _as_int(raw.get("priority"), 10 * no),
                }
            )
            seen.add(rid)

        if not _enabled(items):
            return _err("至少要启用一条线路")

        items = _sorted(items)
        config.save({"llm": {"routes": items}})

        primary = _primary_id(items, _known_health(_enabled(items))[0])
        return {
            "ok": True,
            "items": [_public(r, primary) for r in items],
            "count": len(items),
            "enabled": len(_enabled(items)),
            "currentId": primary,
            "legacy": False,
        }
    except Exception as e:
        return _err(f"保存线路失败：{type(e).__name__}: {e}")


def remove_route(rid: Any, iid: str | None = None) -> dict[str, Any]:
    """删一条线路。不能把线路删空，也不能删到一条启用的都不剩。"""
    try:
        target = str(rid or "").strip()
        if not target:
            return _err("缺少线路 id")

        routes, _legacy = _raw_routes(iid)
        keep = [r for r in routes if str(r.get("id") or "") != target]
        if len(keep) == len(routes):
            return _err(f"没有这条线路：{target}")
        if not keep:
            return _err("至少要保留一条线路，不能全删")
        if not _enabled(keep):
            return _err("删掉后就没有启用的线路了，先启用另一条再删")

        keep = _sorted(keep)
        config.save({"llm": {"routes": keep}})

        primary = _primary_id(keep, _known_health(_enabled(keep))[0])
        return {
            "ok": True,
            "removed": target,
            "items": [_public(r, primary) for r in keep],
            "count": len(keep),
            "currentId": primary,
        }
    except Exception as e:
        return _err(f"删除线路失败：{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# 导出：健康 / 排序
# ---------------------------------------------------------------------------


def _finish_health(
    routes: list[dict[str, Any]],
    items: list[dict[str, Any]],
    healthy: list[str],
    ts: int,
    cached: bool,
) -> dict[str, Any]:
    ok_set = set(healthy)
    primary = next((r["id"] for r in routes if r["id"] in ok_set), "")
    if not primary and routes:
        # 全都不健康时仍然给一条「会先被尝试」的，界面不至于空着
        primary = str(routes[0]["id"])
    out: dict[str, Any] = {
        "ok": bool(healthy),
        "items": items,
        "healthy": list(healthy),
        "primary": primary,
        "ts": ts,
        "cached": cached,
        "degraded": not healthy,
        "count": len(items),
    }
    if not healthy:
        reasons = "；".join(
            f"{i.get('id')}：{i.get('err') or '未知原因'}" for i in items if not i.get("ok")
        )
        out["err"] = ("所有线路都连不通：" + reasons)[:400] if reasons else "所有线路都连不通"
    return out


def health(iid: str | None = None, force: bool = False) -> dict[str, Any]:
    """给每条启用的线路发一次 ping，结果缓存 30 秒（force=True 跳过缓存）。"""
    try:
        with _HEALTH_LOCK:
            routes = _enabled(_sorted(_raw_routes(iid)[0]))
            if not routes:
                return {
                    "ok": False,
                    "err": "没有启用的线路",
                    "items": [],
                    "healthy": [],
                    "primary": "",
                    "ts": _now(),
                    "cached": False,
                    "degraded": True,
                    "count": 0,
                }

            if not force:
                hit = _cached_health(routes, HEALTH_TTL)
                if hit:
                    return _finish_health(routes, hit["items"], hit["healthy"], hit["ts"], True)

            items = _probe_all(routes)
            ts = _now()
            healthy = [str(i.get("id") or "") for i in items if i.get("ok")]
            try:
                config.write_state(
                    HEALTH_FILE,
                    {"ts": ts, "sig": _sig(routes), "items": items, "healthy": healthy},
                )
            except Exception:
                # 缓存写不进去不影响这次结果
                pass
            return _finish_health(routes, items, healthy, ts, False)
    except Exception as e:
        return _err(f"健康检查失败：{type(e).__name__}: {e}")


def order(iid: str | None = None) -> dict[str, Any]:
    """启用的线路 id，健康的在前，其余按 priority 升序。"""
    try:
        routes = _enabled(_sorted(_raw_routes(iid)[0]))
        if not routes:
            return {"ok": False, "err": "没有启用的线路", "ids": [], "primary": "", "healthy": [], "checkedAt": 0}

        healthy, ts = _known_health(routes)
        ok_ids = set(healthy or [])
        first = [r["id"] for r in routes if r["id"] in ok_ids]
        rest = [r["id"] for r in routes if r["id"] not in ok_ids]
        ids = first + rest
        return {
            "ok": True,
            "ids": ids,
            "primary": ids[0] if ids else "",
            "healthy": first,
            "checkedAt": ts,
            "known": healthy is not None,
        }
    except Exception as e:
        return _err(f"计算线路顺序失败：{type(e).__name__}: {e}")


def current(iid: str | None = None) -> dict[str, Any]:
    """当前主线路：第一条健康且启用的；都不健康就退回第一条启用的。"""
    try:
        routes = _enabled(_sorted(_raw_routes(iid)[0]))
        if not routes:
            return {"ok": False, "err": "没有启用的线路", "id": "", "route": {}, "degraded": True}

        healthy, ts = _known_health(routes)
        ok_ids = set(healthy or [])
        target = next((r for r in routes if r["id"] in ok_ids), None)
        degraded = target is None
        if target is None:
            target = routes[0]
        rid = str(target["id"])
        return {
            "ok": True,
            "id": rid,
            "route": _public(target, rid),
            "healthy": None if healthy is None else (not degraded),
            "degraded": degraded,
            "checkedAt": ts,
            "count": len(routes),
        }
    except Exception as e:
        return _err(f"读取当前线路失败：{type(e).__name__}: {e}")
