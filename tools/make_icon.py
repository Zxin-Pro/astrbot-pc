"""把 ``ui/assets/favicon.svg`` 渲染成多尺寸 .ico，给 exe 和托盘共用。

不重画——直接拿界面里那个 SVG 去渲染，免得图标和界面里的品牌标记长得不一样。
做法是在无头 Edge 里把 SVG 画进 canvas 再取 dataURL，比整页截图稳
（截图会受窗口尺寸 / 字体加载 / 并发浏览器实例影响，偶尔报 Unable to capture screenshot）。
"""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "ui" / "assets" / "favicon.svg"
OUT = ROOT / "build" / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
BASE = 512


def render_png(dest: Path, size: int = BASE) -> Path:
    from playwright.sync_api import sync_playwright

    svg = SVG.read_text("utf-8")
    svg = svg.replace('width="64" height="64"', f'width="{size}" height="{size}"', 1)

    html = (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0;background:transparent'></body></html>"
    )

    with tempfile.TemporaryDirectory() as td:
        page_file = Path(td) / "blank.html"
        page_file.write_text(html, encoding="utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            try:
                page = browser.new_page(viewport={"width": size, "height": size})
                page.goto(page_file.as_uri(), wait_until="load")
                data_url = page.evaluate(
                    """async ({ svg, size }) => {
                        const blob = new Blob([svg], { type: 'image/svg+xml' });
                        const url = URL.createObjectURL(blob);
                        try {
                            const img = new Image();
                            img.src = url;
                            await img.decode();
                            const c = document.createElement('canvas');
                            c.width = c.height = size;
                            const g = c.getContext('2d');
                            g.clearRect(0, 0, size, size);
                            g.drawImage(img, 0, 0, size, size);
                            return c.toDataURL('image/png');
                        } finally {
                            URL.revokeObjectURL(url);
                        }
                    }""",
                    {"svg": svg, "size": size},
                )
            finally:
                browser.close()

    raw = base64.b64decode(data_url.split(",", 1)[1])
    dest.write_bytes(raw)
    return dest


def main() -> int:
    from PIL import Image

    OUT.parent.mkdir(parents=True, exist_ok=True)
    png = OUT.with_suffix(".png")
    render_png(png)

    img = Image.open(png).convert("RGBA")
    if img.size != (256, 256):
        img = img.resize((256, 256), Image.LANCZOS)
    img.save(png)
    img.save(OUT, format="ICO", sizes=[(n, n) for n in SIZES])
    print(f"icon -> {OUT} ({', '.join(str(n) for n in SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
