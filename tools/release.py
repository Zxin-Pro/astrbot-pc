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
TAG = "pc-v1.0.3"
NAME = "烛之控制台 v1.0.3 · PC 端"
DIST = Path(__file__).resolve().parent.parent / "dist"
ZIP = DIST / "AstrBotPC-1.0.3-win64.zip"
OFFLINE = DIST / "AstrBotPC-1.0.3-win64-offline.zip"
SINGLE = DIST / "AstrBotPC-1.0.3-win64-single.exe"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "AstrBotPC-release",
    "Accept": "application/vnd.github+json",
}

BODY = """## {name}

把手机上那套「QQ 机器人一键包」搬到 Windows：一个自绘界面的桌面客户端，负责装 NapCat 与 AstrBot、看着每一组进程、扫码登录、翻日志、备份与恢复。

### 该下哪个

| 文件 | 大小 | 适合谁 | 装的时候 |
|---|---|---|---|
| **AstrBotPC-1.0.3-win64-offline.zip**（懒人版） | 约 280 MB | **推荐，什么都不用准备** | 解压即用，不联网、不用装 Python |
| AstrBotPC-1.0.3-win64.zip（目录版） | 约 23 MB | 有 Python、网络好、在意下载体积 | 联网下载 NapCat / AstrBot，pip 装依赖 |
| AstrBotPC-1.0.3-win64-single.exe（单文件版） | 约 23 MB | 就想拷一个文件到处跑 | 联网下载，且仍需本机有 Python |

**懒人版**里带着 NapCat、AstrBot 源码、151 个依赖 wheel，还有一份便携 Python 3.12。下载一个包，解压，双击 `AstrBotPC.exe`，点「开始部署」，全程不用打开浏览器、不用装任何东西、不用连网。

**单文件版**是「连目录都省了」的形态：一个 23 MB 的 exe 拷到哪都能跑（冷启动约 2 秒）。代价是它不带离线资源，部署时要联网，而且你自己机器上得有一个 Python 3.10+（打包版会依次找 `py -3`、PATH 里的 `python`、常见安装目录）。

三个包是同一份程序，界面和功能完全一样，区别只在「部署安装那几分钟怎么过」。

- Windows 10/11 自带 WebView2，更老的系统补一个 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
- 绿色版：删目录即卸载，配置与日志写在 `%LOCALAPPDATA%\\AstrBotPC`
- 懒人版体积大是因为资源摆在 `AstrBotPC.exe` 旁边的 `resources\\` 里，删掉它就是目录版

### 1.0.3：出厂口令直接可用

- **AstrBot 控制台**：账号 `astrbot`、密码 `Astrbot123`。部署时直接写进配置，不再是随机串、不用去日志里翻。
- **NapCat / SnowLuma 的 OneBot 令牌**：默认 `zhuxin`，AstrBot 与协议端两边写同一个值；老实例里留空的令牌会自动补上。
- **NapCat WebUI 令牌**：默认 `zhuxin`，装完就能登 WebUI 看账号状态。
- **都还能改**：服务页「重设密码」、实例页「访问令牌」照旧，改完点一键接线 / 重启生效。

### 1.0.2：SnowLuma 与 NapCat 并存

- **协议端可选**：每个实例在「实例」页选 NapCat 或 SnowLuma，二选一。SnowLuma 直接挂在已登录的 QQ 上做 OneBot 转换，不用另装 QQ；NapCat 照旧。
- **实例级隔离**：SnowLuma 的配置、日志、WebUI 端口都跟着实例走（独立工作目录 + 独立端口），两个实例同时开也不会抢 `onebot11.json`。
- **一键安装**：「扩展」页新增「协议端」卡片，显示 NapCat / SnowLuma 的安装状态与版本，SnowLuma 点一下就后台下载安装（约 41 MB，带进度）。
- **登录页知轻重**：选 SnowLuma 时不再傻等二维码，改成「拉起 QQ」按钮 + 在 QQ 窗口里扫码的三步提示；帮助卡也换成 QQ 侧的排查项。
- **部署向导跟着变**：当前实例用哪个协议端，另一步就标成「已跳过」并说明原因，启动步骤也改名成「启动 SnowLuma」。
- **修**：切换协议端后，部署页仍显示切换前的步骤名与说明。

### 1.0.1：任务栏与窗口手感

- **任务栏图标能最小化了**：无边框窗口缺 `WS_MINIMIZEBOX`，以前只有标题栏那个小按钮能最小化，点任务栏图标没反应；现在两个都能用。
- **最小化 / 还原有过渡动画**：无边框窗口不参与 Windows 自带的窗口动画，客户端自己补了一段淡入淡出（约 170 ms；系统关掉「显示动画」时自动不做）。
- **最大化不再盖住任务栏**：以前最大化铺满整屏，任务栏被压在最下面点不到；现在按显示器工作区最大化。
- **修掉「还原后白板」**：最小化改走 pywebview / WinForms 的正常路径，WebView2 的内容不会在还原时变成一整块白。

### 1.0.0：版本重新起算，补上六件硬功能

之前发布的 PC 版本与 tag 已全部撤下。这一版从 1.0.0 重新开始，以后按 1.0.x / 1.1.x 的小版本节奏更新。

- **真正多实例并行**：一个 QQ 号一套独立的 AstrBot 数据目录、NapCat 工作目录、三个端口和进程组。两个号可以同时在线，互不抢配置；实例页能分别启动、停止、重启，也能一键把端口和令牌接给 AstrBot。
- **模型线路故障转移**：配置主线路与任意条备用线路，保存时写入 AstrBot 的 `fallback_provider_ids`。线路卡显示密钥打码、优先级、健康状态与延迟；不健康时自动落到下一条。
- **试聊与端到端自检**：模型页按当前人格直接聊一句，显示模型、耗时和 token；排障页六段自检（实例 / NapCat / AstrBot / 模型 / 控制台 / 网页会话）逐段说明通不通、卡在哪里、下一步做什么。
- **插件管理器**：「扩展」页列插件、启停、从 GitHub 或本地 zip 安装、更新、卸载、看配置与日志。启停写入 AstrBot 的 `shared_preferences.json`，并明确提示重启后生效。
- **组件更新中心**：集中显示 PC、AstrBot、NapCat 与插件版本；查最新版、升级前自动快照、从快照回滚。升级给官方发布页，不在客户端里贸然替换源码树。
- **资源看板与报错解释**：「资源」页用 6h / 24h / 7d 趋势展示 CPU、内存、磁盘、进程数与错误率；最近错误点「解释」会给出原因与处理步骤，采样可清空。
- **排障页升级**：内置命令行自动识别 GBK / UTF-8（跑 `ver` 不再乱码），超时连子进程一起收；体检、崩溃记录、诊断包导出 / 下载 / 删除都在这一页。
- **十二个页面**：概览 / 资源 / 部署 / 模型 / 服务 / 日志 / 登录 / 排障 / 扩展 / 实例 / 备份 / 设置；`Ctrl+1…9` 跳常用页，深色与 390px 窄屏都过冒烟。
- **旧数据自动迁移**：首次启动把旧 stack 配置迁进 `instances/<id>/`，旧实例补端口与 NapCat 密钥，不删已经装好的文件。

### 功能一览

- 十二个页面，部署向导八步，演练模式默认开启
- 每个实例独立 AstrBot data、NapCat config、WebUI / Dashboard / OneBot 端口与进程组
- 模型页：中转站、密钥、人格、多线路、试聊、测连通
- 排障页：体检、六段自检、命令行、崩溃记录、诊断包、重置部署
- 扩展页：组件版本 / 快照 / 回滚，插件启停 / 安装 / 配置 / 日志
- 资源页：CPU / 内存 / 磁盘 / 进程趋势，报错解释
- 备份后台打包、取消、从文件恢复、每日自动备份；日志单文件清空 / 删除 / 下载
- 托盘常驻、开机自启、掉线自愈、深浅主题、Ctrl+K 命令面板
- SSE 推送（status / log / deploy / notice），断线自动回落轮询

### 已知问题

- NapCat 首次登录需要人工扫码，向导只负责把二维码页面准备好
- 更新只提示、不自动覆盖安装（本机程序自替换风险太高）
- 同一份 QQ 安装能否稳定双开受腾讯客户端限制，多实例建议每个号用独立的 QQ 运行时；界面会提示这一点
- 目录版和单文件版没有内置 wheel，懒人版没有这个限制

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
        "body": BODY.format(name=NAME),
        "draft": False,
        "prerelease": False,
    })
    print(f"release created: {rel['id']} -> {rel['html_url']}")
    return rel


def upload(release_id: int, path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"找不到发布包：{path}，先跑 tools/build_exe.ps1")

    payload = path.read_bytes()
    name = path.name
    for host in ("https://uploads.github.com", "https://api.github.com"):
        url = f"{host}/repos/{REPO}/releases/{release_id}/assets?name={name}"
        print(f"uploading {name} ({len(payload) / 1024 / 1024:.1f} MB) -> {host}")
        try:
            res = call("POST", url, raw=payload, ctype="application/octet-stream", timeout=1800)
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
    raise SystemExit(f"资产上传失败：{name}")


def main() -> int:
    if not TOKEN:
        print("GITHUB_TOKEN 没有设置", file=sys.stderr)
        return 2
    rel = ensure_release()
    rid = int(rel["id"])
    # 顺序有讲究：小包先传，离线包（几百 MB）最后传，中途断了也不影响别人下载。
    # 单文件版继续用 tools/upload_asset.py 补，避免这里一次跑太久。
    for path in (ZIP, OFFLINE):
        if path.is_file():
            upload(rid, path)
        else:
            print(f"跳过（没有这个文件）：{path.name}")
    print("RELEASE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
