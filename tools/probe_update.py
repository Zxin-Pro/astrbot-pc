"""验证标题栏的版本 chip：用假数据看它会不会出现、点开有没有更新说明。

真实仓库目前还没有 PC 端发布，所以这里拦截 ``/api/bootstrap`` 的响应，
把 update 字段换成「有新版本」，其余数据照旧。这样不用等发版也能验证前端。

用法：
    python tools/probe_update.py [--url http://127.0.0.1:17650]
"""

from __future__ import annotations

import argparse
import sys
import time

from playwright.sync_api import sync_playwright

FAKE = {
    "ok": True,
    "noRelease": False,
    "current": "1.0.0",
    "latest": "1.0.1",
    "newer": True,
    "url": "https://github.com/Zxin-Pro/astrbot-candle/releases",
    "notes": "## 1.0.1\n\n- 托盘菜单不再卡住\n- 更新检查只认 PC 端发布",
    "publishedAt": "2026-10-20T00:00:00Z",
    "checkedAt": int(time.time()),
    "repo": "Zxin-Pro/astrbot-candle",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:17650")
    args = ap.parse_args()

    errors: list[str] = []
    ok = True

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})

        def handler(route):
            resp = route.fetch()
            data = resp.json()
            data["update"] = FAKE
            route.fulfill(response=resp, json=data)

        ctx.route("**/api/bootstrap", handler)
        page = ctx.new_page()
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(args.url, wait_until="networkidle")
        page.wait_for_selector(".page", timeout=15000)
        time.sleep(1.0)

        chip = page.locator("#btn-update")
        if not chip.is_visible():
            print("[失败] 有新版本时 chip 没显示")
            ok = False
        else:
            print(f"[通过] chip 可见：{chip.inner_text().strip()}")

        badge = page.locator('[data-badge="settings"]')
        if badge.is_visible():
            print(f"[通过] 设置项有「{badge.inner_text().strip()}」提示")
        else:
            print("[失败] 设置项没有新版提示")
            ok = False

        chip.click()
        time.sleep(0.8)
        modal = page.locator(".modal")
        if modal.count():
            title = modal.locator("h3").inner_text()
            body = modal.locator(".update-notes__body").inner_text()
            print(f"[通过] 弹层打开：{title}")
            print(f"       说明首行：{body.splitlines()[0] if body else '(空)'}")
            if "1.0.1" not in title:
                print("[失败] 弹层标题里没有新版本号")
                ok = False
        else:
            print("[失败] 点 chip 没有弹出更新说明")
            ok = False

        page.screenshot(path=".devdata/shots/verify/update-modal.png")
        browser.close()

    if errors:
        print("\n=== 控制台错误 ===")
        print("\n".join(errors))
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
