import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("console", lambda m: errs.append(("console", m.type, m.text)) if m.type in ("error","warning") else None)
    pg.on("pageerror", lambda e: errs.append(("pageerror", str(e))))
    pg.goto("http://127.0.0.1:17658/#/logs", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    info = pg.evaluate("""() => {
      const body = document.querySelector('#log-body');
      if (!body) return {none: true};
      const em = body.querySelector('.log-empty');
      const cs = em ? getComputedStyle(em) : null;
      return {
        html: body.innerHTML.slice(0, 300),
        bodyH: body.clientHeight,
        emExist: !!em,
        emRect: em ? em.getBoundingClientRect().toJSON() : null,
        emMinH: cs ? cs.minHeight : null,
        emDisplay: cs ? cs.display : null,
        emColor: cs ? cs.color : null,
        scrollH: body.scrollHeight,
      };
    }""")
    print(json.dumps(info, ensure_ascii=False, indent=1))
    print("ERRS:", json.dumps(errs, ensure_ascii=False)[:800])
    b.close()
