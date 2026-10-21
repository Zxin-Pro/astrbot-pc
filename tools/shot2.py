from playwright.sync_api import sync_playwright
OUT = r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots"
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:17661/#/settings", wait_until="networkidle")
    pg.wait_for_timeout(800)
    pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    pg.wait_for_timeout(500)
    pg.screenshot(path=OUT + r"\settings_bottom.png")
    pg.goto("http://127.0.0.1:17661/#/deploy", wait_until="networkidle")
    pg.wait_for_timeout(900)
    pg.screenshot(path=OUT + r"\deploy_now.png")
    print("errs:", errs[:6])
    b.close()
