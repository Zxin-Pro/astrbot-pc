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
TAG = "pc-v1.1.1"
NAME = "烛之控制台 v1.1.1 · PC 端"
ZIP = Path(__file__).resolve().parent.parent / "dist" / "AstrBotPC-1.1.1-win64.zip"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "AstrBotPC-release",
    "Accept": "application/vnd.github+json",
}

BODY = """## 烛之控制台 v1.1.1 · AstrBot 烛版 PC 端

把手机上那套「QQ 机器人一键包」搬到 Windows：一个自绘界面的桌面客户端，负责装 NapCat 与 AstrBot、看着两个进程、扫码登录、翻日志、备份与恢复。

### 下载

- **AstrBotPC-1.1.1-win64.zip**（约 22 MB）——解压到任意目录，双击 `AstrBotPC.exe`
- **AstrBotPC-1.1.1-win64-single.exe**——单文件版，拷一个文件就能跑（冷启动约 2 秒）
- 不需要装 Python；Windows 10/11 自带 WebView2，更老的系统补一个 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
- 绿色版：删目录即卸载，配置与日志写在 `%LOCALAPPDATA%\\AstrBotPC`

### 1.1.1：图标换成手机版那张

- 程序图标、任务栏、托盘、网页标签页统一用手机版同一张插画（`ui/assets/app-icon.png`）
- 小尺寸（16/24/32）单独按脸部裁一张再缩——整张画缩到这个尺寸只剩一块深色
- 托盘图标不再手绘，直接读同一份资源；文件缺失时才退回手绘兜底
- 顺带：标题栏左边那个蓝色方块也换成同一个人

### 1.1.0：整套界面换成液态玻璃

- 底图层：四块压进内容区下方的大模糊色块 + 一层极细颗粒，玻璃后面终于有东西可透
- 玻璃层：侧栏、标题栏、卡片、弹层、命令面板、吐司换成玻璃；面板里的面板保持薄实色
- 开关：「设置 → 外观 → 液态玻璃材质」。关掉即回到原来的实色界面，不是打折版
- 可读性：玻璃会提亮背景，所以整条文字色阶压深一档。实测卡片内最低对比度浅色 4.89、深色 4.50
- 系统偏好：开了「降低透明度」就退成实色；开了「降低动效」就不动
- 帧率：八页滚动 p95 实测 59–60fps，玻璃层不做连续动效
- 顺带修：390px 下顶栏标题折行把搜索框挤出屏幕
- 顺带修：窄屏侧栏的「一键启动」被切掉一角
- 顺带修：新建实例弹窗里，浅色主题下输入框白底白边等于看不见

### 功能一览

- 八个页面：概览 / 部署 / 服务 / 日志 / 登录 / 实例 / 备份 / 设置
- 部署向导八步，演练模式默认开启；真实模式断点续传拉 NapCat、建虚拟环境装 AstrBot
- 进程管理：启停、崩溃自愈（2s→5s→10s 退避）、CPU / 内存采样
- 托盘常驻：关窗不退出，右键菜单启停服务、检查更新、退出
- 检查更新只认 PC 端发布，不会拿手机版 APK 冒充
- SSE 推送（status / log / deploy / notice），断线自动回落轮询
- 深浅两套主题、Ctrl+K 命令面板、键盘可达

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
