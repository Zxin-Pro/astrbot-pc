"""从 ``build/app-icon.png`` 生成 exe 图标与网页 favicon。

图源是手机版那张插画（1254×1254）。不重画、不描摹，就是同一张图，
免得桌面端和手机版看起来像两个产品。

源图放在 ``build/`` 而不是 ``ui/assets/``：整个 ``ui/`` 会被原样打进 exe，
2.5 MB 的原图放进去纯属白占体积，运行时真正要的只有 mark-44 和 favicon-32。

一个小尺寸的取舍：插画直接缩到 16px 会糊成一团深色。所以**小尺寸帧单独出**——
按脸部裁一张方图再缩，16/24/32 用这张，48 以上用整张。
这样任务栏和 Alt+Tab 里能看出是人脸，而不是一块黑。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "build" / "app-icon.png"
ASSETS = ROOT / "ui" / "assets"
ICO = ROOT / "build" / "app.ico"
ICO_PNG = ROOT / "build" / "app.png"

SIZES = [16, 24, 32, 48, 64, 128, 256]
SMALL = [16, 24, 32]
BASE = 1024

# 脸部方框：在 1254 的原图上量出来的（左, 上, 右, 下），正方形，
# 把猫耳到下巴框进去，两侧留一点背景让人觉得是张画而不是证件照。
FACE_BOX = (560, 130, 1180, 750)


def master(img, box=None) -> "object":
    from PIL import Image

    if box:
        img = img.crop(box)
    return img.convert("RGB").resize((BASE, BASE), Image.LANCZOS)


def main() -> int:
    from PIL import Image

    if not SRC.is_file():
        raise SystemExit(f"找不到源图：{SRC}")

    base = Image.open(SRC)
    full = master(base)
    face = master(base, FACE_BOX)

    ICO.parent.mkdir(parents=True, exist_ok=True)

    # 256 那一帧给 build/app.png 用（打包和 README 都用得上）
    full.resize((256, 256), Image.LANCZOS).save(ICO_PNG)

    frames = []
    for n in SIZES:
        src = face if n in SMALL else full
        frames.append(src.resize((n, n), Image.LANCZOS))

    # Pillow 的 ICO 写入器自己会缩放，想控制每一帧就得手写；
    # 这里用最大的 256 当底图、把其余帧挂上去。
    head = next(f for f, n in zip(frames, SIZES) if n == 256)
    rest = [f for n, f in zip(SIZES, frames) if n != 256]
    head.save(ICO, format="ICO", sizes=[(n, n) for n in SIZES], append_images=rest)

    # 网页用：标签页 32、桌面快捷方式 180
    full.resize((32, 32), Image.LANCZOS).save(ASSETS / "favicon-32.png")
    full.resize((180, 180), Image.LANCZOS).save(ASSETS / "favicon-180.png")
    # 标题栏那个小标记，44px 给 2x 屏
    face.resize((44, 44), Image.LANCZOS).save(ASSETS / "mark-44.png")

    print(f"icon -> {ICO} ({', '.join(str(n) for n in SIZES)})")
    print(f"png  -> {ICO_PNG}, favicon-32 / favicon-180 / mark-44")
    return 0


if __name__ == "__main__":
    sys.exit(main())
