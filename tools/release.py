"""给 AstrBotPC 发一个 Release，并把打包好的 zip 当资产传上去。

    set GITHUB_TOKEN=ghp_xxx
    python tools/release.py

资产上传优先走 uploads.github.com；某些网络只放行 api.github.com，
所以在失败时会退回 api 端点再试一次（GitHub 对两者都收）。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "Zxin-Pro/astrbot-pc"
TAG = "pc-v1.0.1"
NAME = "烛之控制台 v1.0.1 · PC 端"
ZIP = Path(__file__).resolve().parent.parent / "dist" / "AstrBotPC-1.0.1-win64.zip"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "AstrBotPC-release",
    "Accept": "application/vnd.github+json",
}

BODY = """## 烛之控制台 v1.0.1 · AstrBot 烛版 PC 端

把手机上那套「QQ 机器人一键包」搬到 Windows：一个自绘界面的桌面客户端，负责装 NapCat 与 AstrBot、看着两个进程、扫码登录、翻日志、备份与恢复。

### 下载

- **AstrBotPC-1.0.1-win64.zip**（约 22 MB）——解压到任意目录，双击 `AstrBotPC.exe`
- 不需要装 Python；Windows 10/11 自带 WebView2，更老的系统补一个 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
- 绿色版：删目录即卸载，配置与日志写在 `%LOCALAPPDATA%\\AstrBotPC`

### 这一版有什么

- 八个页面：概览 / 部署 / 服务 / 日志 / 登录 / 实例 / 备份 / 设置
- 部署向导八步，演练模式默认开启；真实模式断点续传拉 NapCat、建虚拟环境装 AstrBot
- 进程管理：启停、崩溃自愈（2s→5s→10s 退避）、CPU / 内存采样
- 托盘常驻：关窗不退出，右键菜单启停服务、检查更新、退出
- 检查更新只认 PC 端发布，不会拿手机版 APK 冒充
- SSE 推送（status / log / deploy / notice），断线自动回落轮询
- 深浅两套主题、Ctrl+K 命令面板、键盘可达、`prefers-reduced-motion` 生效

### 1.0.1 修的

上一版点「开始部署」即使八步全绿，装完也连不上——配置写到了 AstrBot 不读的路径。这版全部修掉：

- AstrBot 配置改写到它真正会读的 `data/cmd_config.json`（原来写 `data/config/` 等于没写）
- NapCat 改写到 `onebot11.json`（它先找 `onebot11_<QQ号>.json`，找不到才回退读这个）
- 演练模式结束不再写「全部完成」，改成「演练通过：没有任何文件被安装」
- 联网检查改测下载源本身，不再出现「检查通过但下载必挂」
- 下载链路重写：直连 + 三个镜像并发测速取最快、20 秒无新数据换源、换源保留断点、半截包不再当成功
- 子进程补 UTF-8 环境变量，修中文日志乱码与 emoji 导致的 `UnicodeEncodeError`
- 命令带引号时不再报「系统找不到指定的文件」
- 应用被强杀后，下次启动回收残留子进程（只认本程序数据目录）
- 新增「下载加速镜像」开关

### 已知问题

- NapCat 首次登录需要人工扫码，向导只负责把二维码页面准备好
- 更新只提示不自动覆盖安装（本机程序自替换风险太高）
- 第一次安装 AstrBot 依赖要 5–15 分钟，默认走清华 PyPI 镜像

烛心.xyz · QQ 群 1127997343
"""


def call(method: str, url: str, payload: dict | None = None, ctype: str = "application/json",
         raw: bytes | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else raw
    headers = dict(HEADERS)
    headers["Content-Type"] = ctype
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def ensure_release() -> dict:
    api = f"https://api.github.com/repos/{REPO}"
    try:
        rel = call("GET", f"{api}/releases/tags/{TAG}")
        print(f"release exists: {rel['id']}")
        return rel
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    rel = call("POST", f"{api}/releases", {
        "tag_name": TAG,
        "target_commitish": "main",
        "name": NAME,
        "body": BODY,
        "draft": False,
        "prerelease": False,
    })
    print(f"release created: {rel['id']} -> {rel['html_url']}")
    return rel


def upload(release_id: int) -> None:
    if not ZIP.is_file():
        raise SystemExit(f"找不到发布包：{ZIP}，先跑 tools/build_exe.ps1")

    payload = ZIP.read_bytes()
    name = ZIP.name
    for host in ("https://uploads.github.com", "https://api.github.com"):
        url = f"{host}/repos/{REPO}/releases/{release_id}/assets?name={name}"
        print(f"uploading {name} ({len(payload) / 1024 / 1024:.1f} MB) -> {host}")
        try:
            res = call("POST", url, raw=payload, ctype="application/zip", timeout=600)
            print(f"asset id={res['id']} size={res['size']} url={res['browser_download_url']}")
            return
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            print(f"  http {e.code}: {body}", file=sys.stderr)
            if e.code == 422:  # 已经传过同名资产
                print("  同名资产已存在，跳过")
                return
        except Exception as e:
            print(f"  {type(e).__name__}: {e}", file=sys.stderr)
    raise SystemExit("资产上传失败")


def main() -> int:
    if not TOKEN:
        print("GITHUB_TOKEN 没有设置", file=sys.stderr)
        return 2
    rel = ensure_release()
    upload(int(rel["id"]))
    print("RELEASE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
