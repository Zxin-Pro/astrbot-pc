from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:17661/#/dashboard", wait_until="networkidle")
    pg.wait_for_timeout(700)
    pg.keyboard.press("Control+k")
    pg.wait_for_timeout(400)
    pg.screenshot(path=r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\palette3.png", clip={"x": 380, "y": 80, "width": 680, "height": 540})
    print("errs:", errs)
    b.close()
