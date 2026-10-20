"""桌面窗口入口（无控制台）。开机自启注册的就是这个文件。

用 .pyw 后缀，双击或从 Run 键启动都不会弹黑框。
"""

import os
import runpy
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

runpy.run_module("astrbot_pc", run_name="__main__")
