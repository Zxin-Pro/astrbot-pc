import json, time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:17661/#/dashboard", wait_until="networkidle")
    pg.wait_for_timeout(800)
    # 键盘可达性：Tab 能到第一个导航项
    pg.keyboard.press("Tab")
    pg.keyboard.press("Tab")
    focused = pg.evaluate("() => { const a = document.activeElement; return a ? (a.id || a.className || a.tagName) : null }")
    print("focused:", focused)
    # 焦点环是否可见
    ring = pg.evaluate("""() => {
      const a = document.activeElement;
      if (!a) return null;
      const cs = getComputedStyle(a);
      return {outline: cs.outlineStyle + ' ' + cs.outlineWidth, shadow: cs.boxShadow.slice(0, 40)};
    }""")
    print("ring:", ring)
    # Ctrl+K 命令面板
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(500)
    panel = pg.evaluate("() => { const el = document.querySelector('.palette, .cmdk, [data-palette]'); return el ? el.className : null }")
    print("palette:", panel)
    pg.screenshot(path=r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\palette.png")
    pg.keyboard.press("Escape")
    print("errors:", errs[:5])
    b.close()
