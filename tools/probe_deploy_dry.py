"""验证：演练跑完后，部署页副标题不再谎称「可以扫码登录了」。"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from astrbot_pc import app as appmod
from astrbot_pc import paths, server

PORT = 17713


def main() -> int:
    srv = server.Server("127.0.0.1", PORT)
    base = srv.start()
    time.sleep(1.2)
    print("serving", base)

    fails: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        page = b.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(base + "/#/deploy", wait_until="networkidle")
        page.wait_for_timeout(800)

        # 打开「开始部署」，走的是默认演练模式
        page.click('[data-act="start"]')
        page.wait_for_timeout(400)

        sub = ""
        for _ in range(60):
            page.wait_for_timeout(500)
            sub = page.inner_text("#deploy-sub")
            if "演练" in sub or "完成" in sub or "没走通" in sub:
                break

        print("subtitle:", sub)
        if "演练" not in sub:
            fails.append(f"副标题没提演练：{sub}")
        if "可以扫码" in sub:
            fails.append("演练结束还写着可以扫码登录")

        page.screenshot(path=str(paths.ROOT / "state" / "deploy-dry.png"), full_page=False)

        # 步骤明细应带「演练模式」字样
        body = page.inner_text("#steps")
        if "演练" not in body:
            fails.append("步骤明细里没有演练说明")

        if errors:
            fails.append(f"控制台错误：{errors[:3]}")

        b.close()
    srv.stop()

    print("\n=== 结果 ===")
    if fails:
        for f in fails:
            print("FAIL", f)
        return 1
    print("PASS 演练结束文案正确")
    return 0


if __name__ == "__main__":
    sys.exit(main())
