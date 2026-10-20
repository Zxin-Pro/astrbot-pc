from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    for theme in ("light", "dark"):
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.add_init_script(f"localStorage.setItem('dsh.theme','{theme}')")
        pg.goto("http://127.0.0.1:17658/#/logs", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=rf"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\probe_logs_{theme}.png")
        print(theme, pg.evaluate("() => { const p = document.querySelector('.log-empty p'); return p ? [getComputedStyle(p).color, getComputedStyle(p).fontSize, p.getBoundingClientRect().top] : null }"))
    b.close()
