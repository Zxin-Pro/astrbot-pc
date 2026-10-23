"""自检：模型能不能聊、网页里能不能收到回复，一条链跑给用户看。

平时这几段各坏各的，界面上却都只显示「运行中」：

- trial_chat：拿实例里已存的模型配置真发一句话，看回不回、多快、带没带人格；
- e2e：从端口到模型到控制台接口再到网页会话，一段段给结论，能发就真发一句；
- history / clear_history：留最近几次试聊，方便对照「刚才明明能通」。

对别人只读不写：配置、数据库、别人的端口一概不改，唯一落盘的只有自己那份
state 文件。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any

from . import config, probe, runtime

HISTORY_FILE = "selftest-history.json"
HISTORY_KEEP = 50
DEFAULT_PROMPT = "你好，用一句话介绍一下你自己。"
MAX_TOKENS = 512
DEFAULT_TIMEOUT = 45.0


# ---------------- 小工具 ----------------


def _step(key: str, label: str, ok: bool, detail: str, cost: float = 0.0, hint: str = "", **extra: Any) -> dict[str, Any]:
    """一条自检结论：看见什么、成没成、该点哪里。"""
    row = {
        "key": key,
        "label": label,
        "ok": bool(ok),
        "detail": str(detail),
        "ms": int(cost * 1000),
        "hint": str(hint),
    }
    row.update(extra)
    return row


def _why(exc: Exception, timeout: float) -> str:
    """把网络异常翻成一句用户能看懂的中文。"""
    if isinstance(exc, TimeoutError):
        return f"请求超时（{int(timeout)} 秒没等到回应）"
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            return f"请求超时（{int(timeout)} 秒没等到回应）"
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
            return "连不上接口：端口没开或地址写错了"
        return f"连不上接口：{reason}"
    return f"请求失败：{type(exc).__name__}: {exc}"


def _msg(payload: Any) -> str:
    """从各家错误体里挖一句能看的话（OpenAI 的、AstrBot 的都要认）。"""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or "")
        if isinstance(err, str) and err.strip():
            return err.strip()
        for key in ("message", "detail", "msg", "err"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
    if isinstance(payload, str):
        return payload.strip()[:200]
    return ""


def _loads(raw: bytes) -> Any:
    """响应体可能不是 JSON（502 页面之类），别让它把整条链带崩。"""
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except Exception:
        return text[:300]


def _find(node: Any, key: str) -> str:
    """在嵌套响应里找第一个非空字符串字段，省得死磕某一层结构。"""
    if isinstance(node, dict):
        val = node.get(key)
        if isinstance(val, str) and val:
            return val
        for item in node.values():
            got = _find(item, key)
            if got:
                return got
    elif isinstance(node, list):
        for item in node:
            got = _find(item, key)
            if got:
                return got
    return ""


def _get_json(url: str, token: str = "", timeout: float = 3.0) -> tuple[int, Any]:
    """GET 一个 JSON；连接失败给 status=0，不抛。"""
    res = probe.http_get(url, timeout=timeout, headers={"Authorization": f"Bearer {token}"} if token else None)
    status = int(res.get("status") or 0)
    body = str(res.get("body") or "")
    if not body:
        return status, {}
    try:
        return status, json.loads(body)
    except Exception:
        return status, body[:300]


def _post_json(url: str, payload: dict[str, Any], token: str = "", timeout: float = 20.0) -> tuple[int, Any]:
    """POST 一个 JSON；HTTP 错误也当结果返回，只有网络错误才抛。"""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": "AstrBotPC-Selftest",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _loads(exc.read())


def _iid(iid: str | None) -> tuple[str, str]:
    """归一化实例 id：返回 (id, 错误)。不传就用当前选中的实例。"""
    if iid:
        if runtime.get(iid) is None:
            return "", f"没有这个实例：{iid}"
        return iid, ""
    return runtime.active_id(), ""


# ---------------- 模型配置与人格 ----------------


def _model_conf(iid: str) -> dict[str, Any]:
    """从实例的 cmd_config.json 里取「用哪个模型、发到哪、用什么密钥」。

    AstrBot v4 把连接信息拆在 provider_sources 里，provider 只留一个指针；
    老格式则是扁平的。两种都认，否则迁移过一次就读不出配置了。
    """
    path = runtime.cmd_path(iid)
    try:
        conf = json.loads(path.read_text("utf-8-sig"))
    except FileNotFoundError:
        return {"err": "还没部署 AstrBot（找不到 data/cmd_config.json）"}
    except Exception as exc:
        return {"err": f"读不到 AstrBot 配置：{exc}"}
    if not isinstance(conf, dict):
        return {"err": "AstrBot 配置不是对象，可能被改坏了"}

    providers = [x for x in (conf.get("provider") or []) if isinstance(x, dict)]
    if not providers:
        return {"err": "还没有配置模型，先去「模型」页贴一个密钥"}
    runner = (conf.get("agent_runner") or {}).get("config") or {}
    target = str((runner.get("model") or {}).get("provider_id") or "")
    prov = next((x for x in providers if x.get("id") == target), providers[0])

    src = prov
    source_id = str(prov.get("provider_source_id") or "")
    if source_id:
        for item in conf.get("provider_sources") or []:
            if isinstance(item, dict) and item.get("id") == source_id:
                src = item
                break

    base = str(src.get("api_base") or src.get("apiBase") or "").strip()
    model = str(prov.get("model") or "").strip()
    raw_key = src.get("key")
    if isinstance(raw_key, list):
        key = str(raw_key[0] or "") if raw_key else ""
    elif isinstance(raw_key, str):
        key = raw_key
    else:
        key = ""
    if not base or not model:
        return {"err": "模型配置不完整（缺接口地址或模型名）"}
    base = base.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"

    persona_id = str((runner.get("persona") or {}).get("persona_id") or "")
    return {"base": base, "model": model, "key": key.strip(), "personaId": persona_id}


def _persona_prompt(iid: str, persona_id: str) -> str:
    """人格正文在 data_v4.db 的 personas 表里；拿不到就当没有。"""
    if not persona_id:
        return ""
    db = runtime.db_path(iid)
    if not db.is_file():
        return ""
    try:
        con = sqlite3.connect(str(db), timeout=5)
        try:
            row = con.execute("select system_prompt from personas where persona_id = ?", (persona_id,)).fetchone()
        finally:
            con.close()
        return str(row[0] or "") if row else ""
    except Exception:
        return ""


# ---------------- 试聊 ----------------


def _append_history(iid: str, prompt: str, reply: str, latency_ms: int, model: str) -> None:
    """记一笔；写不进去不影响这次试聊的结果。"""
    try:
        items = config.read_state(HISTORY_FILE, [])
        if not isinstance(items, list):
            items = []
        items.insert(0, {
            "ts": int(time.time()),
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "instance": iid,
            "prompt": str(prompt)[:200],
            "reply": str(reply)[:500],
            "latencyMs": int(latency_ms),
            "model": str(model),
        })
        config.write_state(HISTORY_FILE, items[:HISTORY_KEEP])
    except Exception:
        pass


def trial_chat(prompt: str = "", iid: str | None = None, timeout: float = 60.0) -> dict[str, Any]:
    """拿实例里已存的模型配置真发一句话。

    和「测试连接」那种 max_tokens=1 的探针不同，这里要的是完整回复：模型名写错、
    余额不足、账号被限流，都会在这一步现形。

    Args:
        prompt: 要说的话，空的话用一句默认的自我介绍。
        iid: 实例 id，不传就用当前选中的实例。
        timeout: 等待上限（秒）。

    Returns:
        成功 {"ok": True, "reply": ..., "model": ..., "apiBase": ..., "latencyMs": ...,
        "usage": ..., "persona": ...}；失败是 {"ok": False, "err": 中文原因}。
    """
    text = (prompt or "").strip() or DEFAULT_PROMPT
    try:
        sid, why = _iid(iid)
        if why:
            return {"ok": False, "err": why, "instance": sid}
        conf = _model_conf(sid)
        if conf.get("err"):
            return {"ok": False, "err": conf["err"], "instance": sid}

        persona = _persona_prompt(sid, conf["personaId"])
        messages: list[dict[str, str]] = []
        if persona:
            messages.append({"role": "system", "content": persona})
        messages.append({"role": "user", "content": text})
        body = {"model": conf["model"], "messages": messages, "max_tokens": MAX_TOKENS, "stream": False}

        started = time.perf_counter()
        try:
            status, payload = _post_json(conf["base"] + "/chat/completions", body, conf["key"], timeout)
        except Exception as exc:
            return {
                "ok": False,
                "err": _why(exc, timeout),
                "instance": sid,
                "model": conf["model"],
                "apiBase": conf["base"],
                "latencyMs": int((time.perf_counter() - started) * 1000),
            }
        latency = int((time.perf_counter() - started) * 1000)

        if status != 200 or not isinstance(payload, dict):
            detail = _msg(payload)
            if status == 401:
                err = "密钥不对（接口返回 401）"
            elif status == 403:
                err = "密钥没有权限（接口返回 403）"
            elif status == 404:
                err = "接口地址或模型名对不上（接口返回 404）"
            elif status == 429:
                err = "请求被限流或额度用尽（接口返回 429）"
            elif status >= 500:
                err = f"模型服务自己出错（接口返回 {status}）"
            else:
                err = f"接口返回 HTTP {status}"
            if detail:
                err = f"{err}：{detail}"
            return {"ok": False, "err": err, "instance": sid, "model": conf["model"],
                    "apiBase": conf["base"], "latencyMs": latency}

        reply = ""
        try:
            reply = str(payload["choices"][0]["message"].get("content") or "")
        except Exception:
            reply = ""
        if not reply.strip():
            return {"ok": False, "err": "接口通了但回复是空的（模型名可能不对）", "instance": sid,
                    "model": conf["model"], "apiBase": conf["base"], "latencyMs": latency,
                    "usage": payload.get("usage") or {}}

        _append_history(sid, text, reply, latency, conf["model"])
        return {
            "ok": True,
            "instance": sid,
            "reply": reply,
            "model": conf["model"],
            "apiBase": conf["base"],
            "latencyMs": latency,
            "usage": payload.get("usage") or {},
            "persona": conf["personaId"],
        }
    except Exception as exc:  # 兜底：这个模块的约定是「永远返回结论，不抛」
        return {"ok": False, "err": f"试聊失败：{type(exc).__name__}: {exc}", "instance": iid or ""}


def history(limit: int = 20) -> dict[str, Any]:
    """最近的试聊记录，新的在前。"""
    try:
        items = config.read_state(HISTORY_FILE, [])
        if not isinstance(items, list):
            items = []
        try:
            count = max(1, min(int(limit or 20), HISTORY_KEEP))
        except Exception:
            count = 20
        return {"ok": True, "items": items[:count], "total": len(items)}
    except Exception as exc:
        return {"ok": False, "err": f"读不到试聊记录：{exc}", "items": [], "total": 0}


def clear_history() -> dict[str, Any]:
    """把试聊记录清空（日志、配置都不动）。"""
    try:
        config.write_state(HISTORY_FILE, [])
        return {"ok": True, "cleared": True}
    except Exception as exc:
        return {"ok": False, "err": f"清空失败：{exc}"}


# ---------------- 网页会话 ----------------


def _dashboard_login(iid: str) -> tuple[str, str, str]:
    """猜得出控制台密码就返回 (用户名, 密码, "")，猜不出返回 ("", "", 原因)。

    AstrBot 只存哈希，改过的密码取不回来，所以这里只认默认密码，绝不瞎试——
    登录失败那边会故意 sleep 3 秒，猜错一次界面就卡一下。
    """
    try:
        conf = json.loads(runtime.cmd_path(iid).read_text("utf-8-sig"))
    except Exception as exc:
        return "", "", f"读不到 AstrBot 配置（{type(exc).__name__}）"
    if not isinstance(conf, dict):
        return "", "", "AstrBot 配置不是对象"
    dash = conf.get("dashboard") or {}
    user = str(dash.get("username") or "astrbot")
    stored = str(dash.get("password") or "")
    upgraded = str(dash.get("pbkdf2_password") or "")
    if not upgraded and (not stored or stored == hashlib.md5(b"astrbot").hexdigest()):
        return user, "astrbot", ""
    return "", "", "控制台密码不是默认值，这里不猜密码（可在「控制台」页取）"


def _webchat_round(iid: str, root: str, user: str, pwd: str, text: str, timeout: float) -> dict[str, Any]:
    """登录 → 新建 webchat 会话 → 发一句 → 顺着 SSE 把回复拼回来。"""
    status, payload = _post_json(root + "/api/v1/auth/login",
                                 {"username": user, "password": pwd},
                                 timeout=min(timeout, 15.0))
    token = ""
    if isinstance(payload, dict):
        token = str((payload.get("data") or {}).get("token") or "")
    if status != 200 or not token:
        return {"ok": False, "err": f"登录控制台失败：{_msg(payload) or f'HTTP {status}'}"}

    status, payload = _get_json(root + "/api/v1/chat/sessions/new?platform_id=webchat", token,
                                timeout=min(timeout, 10.0))
    session_id = _find(payload, "session_id")
    if not session_id:
        return {"ok": False, "err": f"建不了网页会话：{_msg(payload) or f'HTTP {status}'}"}

    body = json.dumps({"session_id": session_id, "message": text}).encode("utf-8")
    req = urllib.request.Request(
        root + "/api/chat/send",
        data=body,
        headers={
            "User-Agent": "AstrBotPC-Selftest",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=min(timeout, 20.0))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "err": f"发消息被拒：{_msg(_loads(exc.read())) or f'HTTP {exc.code}'}"}
    except Exception as exc:
        return {"ok": False, "err": f"发消息失败：{_why(exc, timeout)}"}

    chunks: list[str] = []
    final = ""
    deadline = time.monotonic() + timeout
    with resp:
        for raw in resp:
            if time.monotonic() > deadline:
                break
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            frame = line[5:].strip()
            if not frame or frame == "[DONE]":
                continue
            try:
                obj = json.loads(frame)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            kind = obj.get("type")
            data = obj.get("data")
            if kind == "plain" and isinstance(data, str) and data:
                if obj.get("streaming"):
                    chunks.append(data)
                else:
                    final = data
            elif kind == "complete" and isinstance(data, str) and data and not obj.get("streaming"):
                final = data
            elif kind == "error":
                return {"ok": False, "err": f"AstrBot 报错：{data or 'WebChat run failed'}"}
            elif kind == "end":
                break

    reply = (final or "".join(chunks)).strip()
    if not reply:
        return {"ok": False, "err": f"网页会话 {int(timeout)} 秒内没拿到回复（AstrBot 可能刚起来还没就绪）",
                "session": session_id}
    return {"ok": True, "reply": reply, "session": session_id}


# ---------------- 一条龙 ----------------


def e2e(iid: str | None = None, text: str | None = None, timeout: float | None = None) -> dict[str, Any]:
    """从端口一路查到网页回复，逐段给结论。

    每一步互不依赖：NapCat 没开也不挡模型试聊，模型没配也不挡端口检查，
    这样用户能一眼看出「到底断在哪一段」。

    Args:
        iid: 实例 id，不传就用当前选中的实例。
        text: 试聊内容，不传就用一句默认的自我介绍。
        timeout: 单个环节的等待上限（秒），默认 45。

    Returns:
        成功 {"ok": True, "instance": ..., "steps": [...], "reply": ..., "ms": ...}；
        失败时 ok 为假，err 是第一处失败的中文原因，steps 照样给全。
    """
    started = time.perf_counter()
    prompt = (text or "").strip() or DEFAULT_PROMPT
    limit = float(timeout or DEFAULT_TIMEOUT)
    steps: list[dict[str, Any]] = []
    reply = ""

    def add(key: str, label: str, ok: bool, detail: str, cost: float = 0.0, hint: str = "", **extra: Any) -> None:
        steps.append(_step(key, label, ok, detail, cost, hint, **extra))

    try:
        sid, why = _iid(iid)
        if why:
            add("instance", "实例", False, why, 0, "去「实例」页确认这个实例还在")
            return {"ok": False, "err": why, "steps": steps, "ms": int((time.perf_counter() - started) * 1000)}
        inst = runtime.spec(sid)
        add("instance", "实例", True, f"{inst['name']}（{sid}）")

        napcat_port = int(inst["napcatPort"] or 0)
        mark = time.perf_counter()
        napcat_up = probe.tcp_open(napcat_port)
        add("napcat", "NapCat 端口", napcat_up,
            f"{napcat_port} " + ("在听" if napcat_up else "没开"),
            time.perf_counter() - mark,
            "" if napcat_up else "去「服务」页启动 NapCat")

        astrbot_port = int(inst["astrbotPort"] or 0)
        mark = time.perf_counter()
        astrbot_up = probe.tcp_open(astrbot_port)
        add("astrbot", "AstrBot 端口", astrbot_up,
            f"{astrbot_port} " + ("在听" if astrbot_up else "没开"),
            time.perf_counter() - mark,
            "" if astrbot_up else "去「服务」页启动 AstrBot")

        mark = time.perf_counter()
        chat = trial_chat(prompt, sid, timeout=limit)
        cost = time.perf_counter() - mark
        if chat.get("ok"):
            detail = f"{chat.get('model')} 回了 {len(str(chat.get('reply') or ''))} 字，{chat.get('latencyMs')} ms"
            if chat.get("persona"):
                detail += f"（人格 {chat['persona']}）"
            add("model", "模型试聊", True, detail, cost)
        else:
            add("model", "模型试聊", False, str(chat.get("err") or "模型没回话"), cost,
                "去「模型」页重新点一次「测试连接」")

        root = str(inst["astrbotUrl"])
        mark = time.perf_counter()
        status, payload = _get_json(root + "/api/v1/auth/setup-status", timeout=3.0)
        cost = time.perf_counter() - mark
        api_ok = status == 200 and isinstance(payload, dict)
        if api_ok:
            need_setup = bool((payload.get("data") or {}).get("setup_required"))
            add("console", "控制台接口", True,
                f"{root}/api/v1 通了" + ("（还没设控制台密码，先做初始化）" if need_setup else ""), cost)
        else:
            add("console", "控制台接口", False,
                f"没回应（HTTP {status}）" if status else "连不上，AstrBot 可能还没起来",
                cost, "去「服务」页启动 AstrBot，等它把控制台拉起来")

        user, pwd, why_pwd = _dashboard_login(sid)
        if not api_ok:
            add("webchat", "网页会诊", True, "跳过：控制台接口没起来", skipped=True)
        elif not pwd:
            add("webchat", "网页会诊", True, f"跳过：{why_pwd}", skipped=True)
        else:
            mark = time.perf_counter()
            res = _webchat_round(sid, root, user, pwd, prompt, limit)
            cost = time.perf_counter() - mark
            if res.get("ok"):
                reply = str(res.get("reply") or "")
                add("webchat", "网页会诊", True, f"回了 {len(reply)} 字，会话 {res.get('session')}", cost)
            else:
                add("webchat", "网页会诊", False, str(res.get("err") or "网页里没收到回复"), cost,
                    "AstrBot 刚起来时多等几秒；还是不通就去「服务」页看一眼日志")

        ok = all(row["ok"] for row in steps)
        out: dict[str, Any] = {
            "ok": ok,
            "instance": sid,
            "steps": steps,
            "ms": int((time.perf_counter() - started) * 1000),
        }
        if reply:
            out["reply"] = reply
        if not ok:
            first = next((row for row in steps if not row["ok"]), None)
            out["err"] = str((first or {}).get("detail") or "自检没通过")
        return out
    except Exception as exc:
        add("internal", "自检过程", False, f"{type(exc).__name__}: {exc}", 0, "把这句话发给开发者")
        return {
            "ok": False,
            "err": f"自检失败：{type(exc).__name__}: {exc}",
            "steps": steps,
            "ms": int((time.perf_counter() - started) * 1000),
        }
