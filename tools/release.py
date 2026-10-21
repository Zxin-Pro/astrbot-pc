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
TAG = "pc-v1.4.0"
NAME = "烛之控制台 v1.4.0 · PC 端"
DIST = Path(__file__).resolve().parent.parent / "dist"
ZIP = DIST / "AstrBotPC-1.4.0-win64.zip"
OFFLINE = DIST / "AstrBotPC-1.4.0-win64-offline.zip"
SINGLE = DIST / "AstrBotPC-1.4.0-win64-single.exe"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "User-Agent": "AstrBotPC-release",
    "Accept": "application/vnd.github+json",
}

BODY = """## {name}

把手机上那套「QQ 机器人一键包」搬到 Windows：一个自绘界面的桌面客户端，负责装 NapCat 与 AstrBot、看着两个进程、扫码登录、翻日志、备份与恢复。

### 该下哪个

| 文件 | 大小 | 适合谁 | 装的时候 |
|---|---|---|---|
| **AstrBotPC-1.4.0-win64-offline.zip**（懒人版） | 约 275 MB | **推荐，什么都不用准备** | 解压即用，不联网、不用装 Python |
| AstrBotPC-1.4.0-win64.zip（目录版） | 约 18 MB | 有 Python、网络好、在意下载体积 | 联网下载 NapCat / AstrBot，pip 装依赖 |
| AstrBotPC-1.4.0-win64-single.exe（单文件版） | 约 18 MB | 就想拷一个文件到处跑 | 联网下载，且仍需本机有 Python |

**懒人版**里带着 NapCat、AstrBot 源码、151 个依赖 wheel，还有一份便携 Python 3.12。下载一个包，解压，双击 `AstrBotPC.exe`，点「开始部署」，全程不用打开浏览器、不用装任何东西、不用连网。

**单文件版**是「节目录都省了」的形态：一个 18 MB 的 exe 拷到哪都能跑（冷启动约 2 秒）。代价是它不带离线资源，部署时要联网，而且你自己机器上得有一个 Python 3.10+（打包版会依次找 `py -3`、PATH 里的 `python`、常见安装目录）。

三个包是同一份程序，界面和功能完全一样，区别只在「部署安装那几分钟怎么过」。

- Windows 10/11 自带 WebView2，更老的系统补一个 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
- 绿色版：删目录即卸载，配置与日志写在 `%LOCALAPPDATA%\\AstrBotPC`
- 懒人版体积大是因为资源摆在 `AstrBotPC.exe` 旁边的 `resources\\` 里，删掉它就是目录版

### 1.4.0：多了一个「模型」页

装好之后最麻烦的一步其实是配模型：要进 AstrBot 的 WebUI、找 provider 模板、填 base_url、贴密钥、再挑模型名。现在这些都在客户端里做完。

- 新增「模型」页：中转站卡片显示站点名、延迟和**站点版本号**，一键跳注册（邀请码 `CZLT` 已带在链接里，文案标着「烛心推荐用这家」）
- 贴一个密钥就行：接口地址默认 `https://worldcodes.online/v1`，模型名默认 `gpt-4o-mini`，点「拉模型」能直接从接口列出来的模型里选
- 保存并启用：把 provider 写进 AstrBot 的 `data/cmd_config.json`，同时设成默认模型
- 人格预设两套（烛心 / 助手），也可以自己写；写进 `data/data_v4.db` 的 `personas` 表并设为默认人格
- 修：AstrBot v4 会把 provider 拆成 `provider_sources` + `provider` 两层并在启动时迁移重写；现在直接按最终结构读写，不再每次启动都被迁一遍，界面也不会「保存了却显示没配」
- 修：中转站检测回来时会整页重画，把刚贴进去的密钥冲掉；现在只重画中转站那一格
- 保存后需要重启 AstrBot，页面上有按钮，也写清了为什么

### 1.3.1：装好之后右侧不再显示「没装」

- 修：部署一跑完，右侧体检自己重新查一遍。原先它只认进页面时那份旧快照，于是左边八步全绿、右边还写着「NapCat 缺失」「AstrBot 源码不完整」，看着像装坏了其实已经好了
- 修：「离线资源：未内置」那条红色标签改成中性的「联网安装」——普通安装包本来就不带资源，不该长得像故障
- 要是还看到旧的「缺失」，点一下「重新体检」也会立刻纠正；这个版本之后不用再点

### 1.3.0：懒人版，连 Python 都不用装

- `resources\\python\\` 里放一份便携 Python 3.12.10（NuGet 的完整发行版，含 `Lib\\venv` 与 `ensurepip`）
- 建虚拟环境时优先用内置解释器，其次才是 `py -3`、PATH 和常见安装目录
- 环境体检里那条会写「内置便携版，不用另装 Python」，一眼看出用的是哪个
- 顺带解决一个隐患：wheel 是按 3.12 打的，以前系统里是 3.13 就装不上、要退回联网；现在内置解释器固定 3.12，永远配得上
- 修：`_stage_env` 判「有没有 Python」时按名字匹配（`"Python" in names`），而实际名字是「Python 运行时」，这个判断从来没生效过；改成按 key 判
- `tools/build_offline.py --lazy` 一键备齐四样资源；顺手把源码包（`.tar.gz`）就地编译成 wheel，纯离线装依赖才不会因为「没有 setuptools」失败
- 部署页「离线资源」那行会显示成 `懒人版` 徽标，并写明不用联网也不用装 Python

### 1.2.0：离线包，装的时候一步网都不用联

- 新增离线版安装包：`resources\\` 里预置 NapCat、AstrBot 源码和全部依赖 wheel
- 部署向导先看 `resources\\`：有就直接解压，没有才联网下载。两种包是同一份程序，不用改设置
- 「部署」页的环境体检多一行「离线资源」，一眼看出这次会不会联网
- 依赖改成 `pip install --no-index --find-links`，从内置 wheel 装
- 离线资源摆在 `AstrBotPC.exe` 旁边的 `resources\\`，用户看得见也换得掉，不塞进 exe 内部
- 修：打包后 `sys.executable` 是 `AstrBotPC.exe`，按它建虚拟环境必然失败；改成先找系统里的真 Python

### 1.1.1：图标换成手机版那张

- 程序图标、任务栏、托盘、网页标签页统一用手机版同一张插画
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

- 九个页面：概览 / 部署 / 模型 / 服务 / 日志 / 登录 / 实例 / 备份 / 设置
- 部署向导八步，演练模式默认开启；真实模式断点续传拉 NapCat、建虚拟环境装 AstrBot
- 进程管理：启停、崩溃自愈（2s→5s→10s 退避）、CPU / 内存采样
- 托盘常驻：关窗不退出，右键菜单启停服务、检查更新、退出
- 检查更新只认 PC 端发布，不会拿手机版 APK 冒充
- SSE 推送（status / log / deploy / notice），断线自动回落轮询
- 深浅两套主题、Ctrl+K 命令面板、键盘可达

### 已知问题

- NapCat 首次登录需要人工扫码，向导只负责把二维码页面准备好
- 更新只提示不自动覆盖安装（本机程序自替换风险太高）
- 目录版和单文件版没有内置 wheel，wheel 按打包时的 Python 版本挑；懒人版没这个问题

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
