"""AstrBot 烛版 · PC 控制台（后台服务层）。

这个包只做三件事：
1. 侦测本机的 QQ / NapCat / AstrBot 环境；
2. 启停与守护这两个服务，并把它们的日志读出来；
3. 起一个只监听 127.0.0.1 的 HTTP 服务，把上面这些能力暴露给本地界面。
"""

from __future__ import annotations

from . import paths

__all__ = ["__version__"]

__version__ = paths.APP_VERSION
