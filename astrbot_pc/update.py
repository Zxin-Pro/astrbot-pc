"""检查更新：问一次 GitHub Release，和本地版本比一比。

只做「告诉你有新版本」，不自动下载覆盖——这是个装在本机的程序，
自己替换正在运行的文件很容易把东西搞坏，交给用户点链接更稳。

**只认 PC 端的发布**：同一个仓库里还挂着手机版 ``AstrBot-x.y.z.apk``，
版本号一路涨到 1.1.x，直接拿来比会把桌面版永远判成「有新版」。所以这里
先按 tag（``pc-*`` / ``desktop-*``）或资产名（含 ``PC`` / ``Windows``）
挑出桌面版发布，挑不到就如实说「PC 端还没有发布版本」，而不是拿手机版冒充。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from typing import Any

from . import config, paths

UA = f"AstrBotPC/{paths.APP_VERSION}"
RELEASES = "https://api.github.com/repos/{repo}/releases?per_page={n}"

#: 查一次管半小时，别每次开设置页都去打 GitHub
TTL = 30 * 60
_STATE = "update.json"

#: 发布页：拿来找 PC 端包
PC_TAG = re.compile(r"^(?:pc|desktop|win|windows)[-_/ ]*v?\d", re.I)
PC_ASSET = re.compile(r"(?:^|[^a-z])(?:pc|desktop|win|windows)(?:[^a-z]|$)", re.I)

_lock = threading.Lock()
_cache: dict[str, Any] = {}


def current() -> str:
    return paths.APP_VERSION


def _target() -> str:
    """缓存指纹：换了仓库或渠道，旧结果就该作废。"""
    repo = config.get("update.repo", "Zxin-Pro/astrbot-pc") or "Zxin-Pro/astrbot-pc"
    chan = config.get("update.channel", "stable") or "stable"
    return f"{repo}|{chan}|pc"


def cached() -> dict[str, Any] | None:
    """只读缓存，不联网。首屏用它，避免被网络拖住。"""
    with _lock:
        if _cache:
            return dict(_cache)
        data = config.read_state(_STATE, None)
        if isinstance(data, dict) and data.get("current") == current() \
                and data.get("target") == _target():
            _cache.update(data)
            return dict(data)
    return None


def _norm(tag: str) -> str:
    """``pc-v1.2.0`` / ``v1.2.0`` 都归一成 ``1.2.0``。"""
    t = str(tag or "").strip()
    t = re.sub(r"^(?:pc|desktop|win|windows)[-_/ ]*", "", t, flags=re.I)
    return t.lstrip("vV")


def _parse(tag: str) -> list[int]:
    out: list[int] = []
    for piece in re.split(r"[.\-+]", _norm(tag)):
        m = re.match(r"\d+", piece)
        out.append(int(m.group(0)) if m else 0)
    return out


def is_newer(latest: str, current_tag: str) -> bool:
    a, b = _parse(latest), _parse(current_tag)
    n = max(len(a), len(b), 3)
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a > b


def _fetch(repo: str, channel: str) -> list[dict[str, Any]]:
    url = RELEASES.format(repo=repo, n=30)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=12) as r:
        raw = json.loads(r.read().decode("utf-8", "replace"))
    if not isinstance(raw, list):
        raise ValueError("GitHub 返回了意料之外的数据")
    items = [r for r in raw if isinstance(r, dict) and not r.get("draft")]
    # 稳定渠道不认预发布；beta 渠道才把 prerelease 放进来
    if channel != "beta":
        items = [r for r in items if not r.get("prerelease")]
    return items


def _pc_asset(rel: dict[str, Any]) -> str:
    """返回这条发布里第一个像桌面端的资产名，没有就空串。"""
    for asset in rel.get("assets") or []:
        name = str((asset or {}).get("name") or "")
        if name and PC_ASSET.search(name):
            return name
    return ""


def _pick(releases: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """从新到旧找第一条 PC 端发布，返回 (release, 命中的资产名)。

    先看 tag 前缀，再退回看资产名——将来换成 ``AstrBot-PC-1.0.0.zip``
    这种命名也能认出来。
    """
    for rel in releases:
        tag = str(rel.get("tag_name") or "")
        if not tag:
            continue
        if PC_TAG.match(tag):
            return rel, _pc_asset(rel)
    for rel in releases:
        asset = _pc_asset(rel)
        if asset:
            return rel, asset
    return None, ""


def check(force: bool = False, channel: str = "") -> dict[str, Any]:
    """返回 ``{ok, current, latest, newer, url, notes, ...}``。

    没有 PC 端发布时返回 ``ok: true, noRelease: true``——这是正常状态，不是错误，
    界面照实说一句就行。
    """
    if not force:
        hit = cached()
        if hit and time.time() - float(hit.get("checkedAt") or 0) < TTL:
            return hit

    repo = config.get("update.repo", "Zxin-Pro/astrbot-pc") or "Zxin-Pro/astrbot-pc"
    chan = channel or config.get("update.channel", "stable") or "stable"
    target = _target()
    releases_url = f"https://github.com/{repo}/releases"

    try:
        releases = _fetch(repo, chan)
        rel, asset = _pick(releases)
        if rel is None:
            result: dict[str, Any] = {
                "ok": True,
                "noRelease": True,
                "current": current(),
                "latest": "",
                "newer": False,
                "message": "桌面版会单独出包，手机版更新不影响这里",
                "url": releases_url,
                "checkedAt": int(time.time()),
                "repo": repo,
                "target": target,
            }
        else:
            latest_tag = str(rel.get("tag_name") or "")
            latest = _norm(latest_tag)
            if not latest:
                raise ValueError("发布版本号是空的")
            result = {
                "ok": True,
                "noRelease": False,
                "current": current(),
                "latest": latest,
                "tag": latest_tag,
                "newer": is_newer(latest, current()),
                "url": rel.get("html_url") or releases_url,
                "notes": (rel.get("body") or "").strip()[:4000],
                "publishedAt": rel.get("published_at") or "",
                "asset": asset,
                "checkedAt": int(time.time()),
                "repo": repo,
                "target": target,
            }
    except Exception as e:
        result = {
            "ok": False,
            "err": _explain(e),
            "current": current(),
            "checkedAt": int(time.time()),
            "repo": repo,
            "target": target,
        }

    with _lock:
        _cache.clear()
        _cache.update(result)
    try:
        config.write_state(_STATE, result)
    except Exception:
        pass
    return result


def _explain(e: Exception) -> str:
    text = str(e)
    code = getattr(e, "code", None)
    if code == 404:
        return "仓库不存在，或者还没有任何发布"
    if code == 403:
        return "GitHub 接口被限流了，过一会儿再试"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "连不上 GitHub，检查一下网络"
    if "name or service" in text.lower() or "getaddrinfo" in text.lower():
        return "DNS 解析失败，检查一下网络"
    return f"检查更新失败：{text[:120]}"


def maybe_check_async() -> None:
    """启动时静默查一次，失败就当无事发生。"""
    if not config.get("app.checkUpdate", True):
        return

    def run() -> None:
        try:
            check(force=False)
        except Exception:
            pass

    threading.Thread(target=run, name="update-check", daemon=True).start()
