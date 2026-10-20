"""打包入口：`python launcher.py` 和双击 exe 都走这里。

源码模式下 `python -m astrbot_pc` 也行，这个文件只是给 PyInstaller 一个
明确的起点，顺便保证 `--web` / `--headless` 参数照常透传。
"""

from __future__ import annotations

import sys

from astrbot_pc.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
