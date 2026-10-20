# -*- coding: utf-8 -*-
"""浮层与降级：弹窗、吐司、prefers-reduced-transparency / -motion 的兜底。"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:17650"
OUT = Path(__file__).resolve().parent.parent / ".devdata" / "shots-glass"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bad: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        for theme in ("light", "dark"):
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            errs: list[str] = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.add_init_script(
                f"localStorage.setItem('dsh.theme','{theme}');localStorage.setItem('dsh.glass','1');"
            )
            page.goto(f"{BASE}/#/instances", wait_until="networkidle")
            page.wait_for_timeout(500)
            # 弹窗：实例页的「添加实例」
            page.click("text=新建实例")
            page.wait_for_timeout(450)
            page.screenshot(path=str(OUT / f"ov-{theme}-modal.png"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(320)

            # 吐司：reload 之后点「刷新」之类不可靠，直接调内部 API
            page.evaluate(
                """async () => {
                const m = await import('/js/components.js');
                m.notify.info('演练结束，什么都没装上；关掉演练模式才会真装');
                m.notify.ok('已保存');
                }"""
            )
            page.wait_for_timeout(420)
            page.screenshot(path=str(OUT / f"ov-{theme}-toast.png"))
            if errs:
                bad.append(f"[{theme}] 控制台错误 {errs[:3]}")

            # prefers-reduced-transparency: reduce —— 玻璃必须退回实色
            cdp = ctx.new_cdp_session(page)
            cdp.send(
                "Emulation.setEmulatedMedia",
                {"features": [{"name": "prefers-reduced-transparency", "value": "reduce"}]},
            )
            page.goto(f"{BASE}/#/dashboard", wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / f"ov-{theme}-notrans.png"))
            blur = page.evaluate(
                """() => {
                const el = document.querySelector('.card');
                return el ? getComputedStyle(el).backdropFilter : 'none';
                }"""
            )
            # 兜底不是把 backdrop-filter 删掉，而是把模糊半径和饱和度归零，
            # 所以这里要判「是否还在真的糊」，不能只判字符串是不是 none。
            import re as _re

            m = _re.search(r"blur\(([\d.]+)px\)", blur or "")
            if m and float(m.group(1)) > 0.01:
                bad.append(f"[{theme}] 关了半透明，卡片还在模糊背景：{blur}")

            # prefers-reduced-motion: reduce —— 入场动画要停
            cdp.send(
                "Emulation.setEmulatedMedia",
                {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]},
            )
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(300)
            dur = page.evaluate(
                """() => {
                const el = document.querySelector('.page');
                return el ? getComputedStyle(el).animationDuration : '';
                }"""
            )

            def secs(v: str) -> float:
                v = (v or "").strip()
                try:
                    if v.endswith("ms"):
                        return float(v[:-2]) / 1000
                    if v.endswith("s"):
                        return float(v[:-1])
                    return float(v)
                except ValueError:
                    return 0.0

            if secs(dur) > 0.05:
                bad.append(f"[{theme}] 关了动效，页面还在播入场动画：{dur}")
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
