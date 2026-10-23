# -*- coding: utf-8 -*-
"""液态玻璃观感检查：十页 x 深浅两套 x 玻璃开关，截图 + 控制台错误。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:17650"
OUT = Path(__file__).resolve().parent.parent / ".devdata" / "shots-glass"
PAGES = ["dashboard", "deploy", "model", "services", "logs", "login", "diag", "instances", "backups", "settings"]


def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        for theme in ("light", "dark"):
            for glass in ("on", "off"):
                ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
                page = ctx.new_page()
                errs: list[str] = []
                page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errs.append(str(e)))
                page.add_init_script(
                    f"localStorage.setItem('dsh.theme','{theme}');"
                    f"localStorage.setItem('dsh.glass','{'1' if glass == 'on' else '0'}');"
                )
                page.goto(f"{BASE}/#/dashboard", wait_until="networkidle")
                page.wait_for_timeout(600)
                for name in PAGES:
                    page.goto(f"{BASE}/#/{name}", wait_until="networkidle")
                    page.wait_for_timeout(420)
                    tag = f"{theme}-{glass}"
                    page.screenshot(path=str(OUT / f"{tag}-{name}.png"))
                # 顶栏 + 侧栏近景，玻璃描边最值得看
                page.goto(f"{BASE}/#/dashboard", wait_until="networkidle")
                page.wait_for_timeout(500)
                page.screenshot(path=str(OUT / f"{tag}-crop.png"), clip={"x": 0, "y": 0, "width": 900, "height": 520})
                # 弹层：玻璃在浮层上最明显
                page.keyboard.press("Control+k")
                page.wait_for_timeout(420)
                page.screenshot(path=str(OUT / f"{tag}-palette.png"))
                if errs:
                    problems.append(f"[{theme}/{glass}] 控制台错误: {errs[:4]}")
                ctx.close()
        b.close()

    for name in PAGES:
        f = OUT / f"light-on-{name}.png"
        if not f.exists():
            problems.append(f"缺截图 {f.name}")

    if problems:
        print("FAIL")
        for p_ in problems:
            print(" -", p_)
        return 1
    print(f"PASS · {len(list(OUT.glob('*.png')))} 张截图 → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
