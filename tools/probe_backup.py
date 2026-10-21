from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto("http://127.0.0.1:17658/#/backups", wait_until="networkidle")
    pg.wait_for_timeout(1200)
    print(pg.evaluate("""() => {
      const el = document.querySelector('.usage-bar');
      return {
        legend: document.querySelector('.usage-legend')?.innerText,
        head: document.querySelector('.card-head')?.innerText,
        segs: el ? el.innerHTML.length : -1,
        html: el ? el.innerHTML : '',
      };
    }"""))
    b.close()
