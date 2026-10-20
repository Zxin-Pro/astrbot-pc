from playwright.sync_api import sync_playwright
OUT = r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots"
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    for path, name in [("dashboard", "fresh_dashboard"), ("logs", "fresh_logs"), ("login", "fresh_login")]:
        pg.goto(f"http://127.0.0.1:17670/#/{path}", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{OUT}/{name}.png")
    print("errs:", errs[:6])
    b.close()
