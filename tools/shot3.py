from playwright.sync_api import sync_playwright
OUT = r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots"
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://127.0.0.1:17661/#/settings", wait_until="networkidle")
    pg.wait_for_timeout(800)
    info = pg.evaluate("""() => {
      const out = [];
      for (const el of document.querySelectorAll('*')) {
        const s = getComputedStyle(el);
        if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 20) {
          out.push({tag: el.tagName, cls: el.className, sh: el.scrollHeight, ch: el.clientHeight});
        }
      }
      return out;
    }""")
    print(info)
    pg.evaluate("""() => {
      for (const el of document.querySelectorAll('*')) {
        const s = getComputedStyle(el);
        if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 20) {
          el.scrollTop = el.scrollHeight;
        }
      }
    }""")
    pg.wait_for_timeout(400)
    pg.screenshot(path=OUT + r"\settings_bottom.png")
    b.close()
