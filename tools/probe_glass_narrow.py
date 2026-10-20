# -*- coding: utf-8 -*-
"""窄屏：玻璃在 390px 下会不会糊成一片、会不会横向溢出。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:17650"
OUT = Path(__file__).resolve().parent.parent / ".devdata" / "shots-glass"
PAGES = ["dashboard", "deploy", "services", "instances", "settings"]


def main() -> int:
    bad: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        for theme in ("light", "dark"):
            ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
            page = ctx.new_page()
            errs: list[str] = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.add_init_script(
                f"localStorage.setItem('dsh.theme','{theme}');localStorage.setItem('dsh.glass','1');"
            )
            for name in PAGES:
                page.goto(f"{BASE}/#/{name}", wait_until="networkidle")
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"narrow-{theme}-{name}.png"))
                ov = page.evaluate(
                    "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]"
                )
                if ov[0] > ov[1] + 1:
                    bad.append(f"[{theme}] {name} 横向溢出 {ov[0]} > {ov[1]}")
            if errs:
                bad.append(f"[{theme}] 控制台错误 {errs[:3]}")
            ctx.close()
        b.close()
    if bad:
        print("FAIL")
        for x in bad:
            print(" -", x)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
