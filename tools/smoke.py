"""Playwright 冒烟测试：逐页截图 + 收集控制台错误。

用法：
    python tools/smoke.py [--url http://127.0.0.1:17650] [--out .devdata/shots]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGES = ["dashboard", "deploy", "services", "logs", "login", "instances", "backups", "settings"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:17650")
    ap.add_argument("--out", default=".devdata/shots")
    ap.add_argument("--theme", default="light", choices=["light", "dark"])
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    args = ap.parse_args()

    out = Path(args.out) / args.theme
    out.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    failed: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": args.width, "height": args.height})
        ctx.add_init_script(f"localStorage.setItem('dsh.theme', '{args.theme}')")
        page = ctx.new_page()

        page.on("console", lambda m: errors.append(f"[console.{m.type}] {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        page.on("requestfailed", lambda r: failed.append(f"{r.method} {r.url} :: {r.failure}"))

        page.goto(args.url, wait_until="networkidle")
        page.wait_for_selector(".page", timeout=15000)
        time.sleep(1.2)

        for key in PAGES:
            page.evaluate(f"location.hash = '#/{key}'")
            time.sleep(1.6)
            shot = out / f"{key}.png"
            page.screenshot(path=str(shot), full_page=False)
            print(f"  shot {key} -> {shot.name}")

        # 窄屏检查
        page.set_viewport_size({"width": 390, "height": 844})
        time.sleep(0.6)
        page.evaluate("location.hash = '#/dashboard'")
        time.sleep(1.2)
        page.screenshot(path=str(out / "narrow-dashboard.png"))

        overflow = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})"
        )

        browser.close()

    print("\n=== 控制台错误 ===")
    print("\n".join(errors) if errors else "（无）")
    print("\n=== 失败请求 ===")
    print("\n".join(failed) if failed else "（无）")
    print(f"\n窄屏溢出检查: scrollWidth={overflow['sw']} clientWidth={overflow['cw']} "
          f"{'溢出!' if overflow['sw'] > overflow['cw'] + 1 else 'OK'}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
