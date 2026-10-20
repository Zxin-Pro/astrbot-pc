# -*- coding: utf-8 -*-
"""液态玻璃的两项硬指标：

1. 对比度 —— 玻璃是半透明的，背景颜色会透上来。
   拿截图里每张卡片内部的像素当「实际底色」，再和正文色算 WCAG 对比度。
   这里按最保守的方式取：卡片内边距处的若干采样点里，挑对比度最差的那个。

2. 帧率 —— backdrop-filter 是逐帧重算的。滚动时如果掉到 40fps 以下，
   说明这个页面的玻璃层太多，得减。

用法：先起服务，再 python tools/probe_glass_qa.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:17650"
OUT = Path(__file__).resolve().parent.parent / ".devdata" / "shots-glass"
PAGES = ["dashboard", "deploy", "services", "logs", "instances", "backups", "settings"]

INK = {"light": (15, 23, 42), "dark": (232, 238, 249)}
INK3 = {"light": (85, 103, 126), "dark": (130, 150, 176)}


def parse_color(s: str):
    s = (s or "").strip()
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    if s.startswith("rgb"):
        nums = [float(v) for v in s[s.find("(") + 1 : s.find(")")].replace("/", ",").split(",")[:3]]
        return tuple(int(round(v)) for v in nums)
    return None


def lum(rgb):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def main() -> int:
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    fails: list[str] = []
    report: list[str] = []

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        for theme in ("light", "dark"):
            for glass in ("on", "off"):
                ctx = b.new_context(viewport={"width": 1440, "height": 900})
                page = ctx.new_page()
                page.add_init_script(
                    f"localStorage.setItem('dsh.theme','{theme}');"
                    f"localStorage.setItem('dsh.glass','{'1' if glass == 'on' else '0'}');"
                )
                for name in PAGES:
                    page.goto(f"{BASE}/#/{name}", wait_until="networkidle")
                    page.wait_for_timeout(420)
                    ink = parse_color(
                        page.evaluate(
                            "getComputedStyle(document.documentElement).getPropertyValue('--ink')"
                        )
                    ) or INK[theme]
                    ink3 = parse_color(
                        page.evaluate(
                            "getComputedStyle(document.documentElement).getPropertyValue('--ink-3')"
                        )
                    ) or INK3[theme]
                    page.screenshot(path=str(OUT / f"qa-{theme}-{glass}-{name}.png"))

                    boxes = page.evaluate(
                        """() => {
                        const out = [];
                        document.querySelectorAll('.card, .stat, .log-shell, .qr-stage').forEach((el) => {
                            const r = el.getBoundingClientRect();
                            if (r.width < 60 || r.height < 40) return;
                            if (r.bottom < 0 || r.top > innerHeight) return;
                            if (r.top < 0) return;  // 被顶栏切一半的跳过
                            out.push([Math.round(r.x), Math.round(r.y),
                                      Math.round(r.width), Math.round(r.height)]);
                        });
                        return out;
                        }"""
                    )

                    # 把卡片里的东西藏起来再截一张：这样采到的一定是玻璃本身的颜色，
                    # 而不是恰好压在采样点上的某个小色块（否则会得到和玻璃无关的假读数）。
                    tag = page.add_style_tag(
                        content=(
                            ".card > *, .stat > *, .log-shell > *, .qr-stage > *"
                            " { visibility: hidden !important; }"
                        )
                    )
                    page.wait_for_timeout(160)
                    bare = OUT / f"qa-bare-{theme}-{glass}-{name}.png"
                    page.screenshot(path=str(bare))
                    tag.evaluate("el => el.remove()")

                    img = Image.open(bare).convert("RGB")
                    w, h = img.size
                    worst = 99.0
                    for (x, y, bw, bh) in boxes:
                        ins = 22
                        if bw < ins * 2 + 10 or bh < ins * 2 + 10:
                            continue
                        pts = [
                            (x + ins, y + ins),
                            (x + bw - ins, y + ins),
                            (x + ins, y + bh - ins),
                            (x + bw - ins, y + bh - ins),
                            (x + bw // 2, y + ins),
                            (x + bw // 2, y + bh // 2),
                        ]
                        for (px, py) in pts:
                            if not (0 <= px < w and 0 <= py < h):
                                continue
                            c = img.getpixel((px, py))
                            worst = min(worst, contrast(ink, c), contrast(ink3, c))
                    report.append(f"{theme:5} glass={glass:3} {name:10} 最低对比度 {worst:5.2f}")
                    if glass == "on" and worst < 4.5:
                        fails.append(f"[{theme}] {name} 卡片玻璃底色对比度只有 {worst:.2f}:1")
                ctx.close()

        # ---- 帧率：滚动 dashboard 与 logs（最长的一页） ----
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.add_init_script("localStorage.setItem('dsh.glass','1');")
        for name in ("dashboard", "logs", "settings"):
            page.goto(f"{BASE}/#/{name}", wait_until="networkidle")
            page.wait_for_timeout(500)
            fps = page.evaluate(
                """async () => {
                const el = document.getElementById('content');
                const frames = [];
                let last = performance.now();
                let raf = 0;
                const t0 = performance.now();
                const tick = (t) => {
                    frames.push(t - last);
                    last = t;
                    if (t - t0 < 1400) raf = requestAnimationFrame(tick);
                };
                raf = requestAnimationFrame(tick);
                const start = performance.now();
                while (performance.now() - start < 1300) {
                    const k = (performance.now() - start) / 1300;
                    el.scrollTop = Math.round(k * (el.scrollHeight - el.clientHeight));
                    await new Promise((r) => requestAnimationFrame(r));
                }
                cancelAnimationFrame(raf);
                const use = frames.slice(4).sort((a, b) => a - b);
                if (!use.length) return 0;
                const p95 = use[Math.floor(use.length * 0.95)] || use[use.length - 1];
                return Math.round(1000 / p95);
                }"""
            )
            report.append(f"fps  {name:10} p95 ≈ {fps}")
            if fps and fps < 40:
                fails.append(f"[fps] {name} 滚动只有 {fps}fps（玻璃层太多）")
        ctx.close()
        b.close()

    print("\n".join(report))
    if fails:
        print("\nFAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
