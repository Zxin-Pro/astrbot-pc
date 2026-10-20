# 烛之控制台 · AstrBot 烛版 PC 端

把手机上那套「QQ 机器人一键包」搬到 Windows：一个自绘界面的桌面客户端，负责装 NapCat 与 AstrBot、看着两个进程、扫码登录、翻日志、备份与恢复。

界面全部是原生 HTML/CSS/ESM，没有前端构建步骤；后端只有 Python 标准库，外加 `psutil`（进程采样）和 `pystray` + `Pillow`（托盘，可选）。

---

## 一、跑起来

### 直接下 exe

去 [Releases](https://github.com/Zxin-Pro/astrbot-pc/releases) 下任意一个：

| 文件 | 用法 |
| --- | --- |
| `AstrBotPC-1.0.1-win64-single.exe` | **单文件版**，拷到哪都能双击，冷启动多等 2–4 秒 |
| `AstrBotPC-1.0.1-win64.zip` | **目录版**，解压后双击 `AstrBotPC.exe`，启动更快 |

不需要装 Python；Windows 10/11 自带 WebView2，更老的系统要补一个 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。程序是绿色版，删目录即卸载（单文件版删 exe），设置与日志都写在 `%LOCALAPPDATA%\AstrBotPC`。

### 从源码跑

```bash
# 1) 装依赖（不装 pywebview 也能跑，会自动退回浏览器模式；不装 pystray 就是关窗即退出）
install.bat
#    等价于：python -m pip install -r requirements.txt

# 2) 打开界面
run.bat            # 桌面窗口，无控制台
run-console.bat    # 带控制台，排错时用这个
```

命令行等价写法：

```bash
python -m astrbot_pc                # 桌面窗口
python -m astrbot_pc --web          # 只起服务 + 自动开浏览器
python -m astrbot_pc --headless --port 17650   # 只起服务，给脚本用
```

默认地址 <http://127.0.0.1:17650>，端口被占会自动顺延。

### 数据目录

| 平台 | 位置 |
| --- | --- |
| 默认 | `%LOCALAPPDATA%\AstrBotPC` |
| 覆盖 | 设环境变量 `ASTRBOT_PC_HOME`（便携版 / 多实例 / 测试都靠它） |

```
AstrBotPC/
├─ config.json     设置、实例、端口
├─ stack/          NapCat、AstrBot、环境依赖的安装位置
├─ logs/           两个进程的输出
├─ backups/        NapCat 配置 / AstrBot 数据 / 全量包
├─ state/          运行态快照
└─ tmp/            部署过程的临时文件
```

---

## 二、界面里有什么

| 页面 | 干什么 |
| --- | --- |
| **概览** | 今日在线、消息数、异常数、服务在线数；两个服务的状态卡；24 小时消息节奏；环境信息；最近日志 |
| **部署** | 八步向导：环境检查 → 准备目录 → 取 NapCat → 取 AstrBot → 装依赖 → 写配置 → 启 NapCat → 启 AstrBot。带「演练模式」，可以先空跑看清每一步；真实模式带下载进度条与实时 pip 输出 |
| **服务** | NapCat / AstrBot 各自的启动、重启、停止，CPU 环形图、内存、运行时长、重启次数；端口连通性表；快捷入口 |
| **日志** | 按文件浏览，级别筛选，关键字搜索，跟随滚动，导出 / 导入 |
| **登录** | 每 3 秒自动抓 NapCat 二维码，支持换一张、存图片；右侧是扫码排障清单 |
| **实例** | 一个 QQ 号一套配置：端口、访问令牌、WebUI 地址，可新建 / 编辑 / 删除 |
| **备份** | 查看占用，建备份（可写备注），恢复与删除既有备份 |
| **设置** | 主题（浅色 / 深色 / 跟随系统）、开机启动、关窗最小化到托盘、退出停服务、自动检查更新、自动重启、首选端口、界面访问范围、pip 镜像、AstrBot 安装方式、清理日志、重置数据 |

全局能力：

- `Ctrl+K` 命令面板（页面与动作分两组，`↑↓` 选择、`↵` 进入），`Ctrl+R` 刷新，`Ctrl+1…8` 直接跳页，`Esc` 关弹层
- 事件用 SSE 推送（`status` / `log` / `deploy` / `notice`），断线自动重连并回落到轮询
- 标题栏的「新版 vX」小胶囊：发现 PC 端有新版本才出现，点开就是更新说明与下载入口
- 所有交互走键盘可达路径，`focus-visible` 有明确描边，遵循 `prefers-reduced-motion`

### 桌面窗口与托盘

无边框窗口，标题栏右侧是最小化 / 最大化 / 关闭，左侧「烛之控制台」可直接拖动。

设置里「关闭窗口时最小化到托盘」默认开着：点 × 只是把窗口收起来，NapCat 和 AstrBot 继续在后台跑，右键托盘图标可以「全部启动 / 全部停止 / 检查更新 / 退出」，双击图标把窗口叫回来。

没装 `pystray` 时会安静地退回「关窗即退出」，设置页那句说明会多一个「仅桌面窗口模式生效」的括号。

不开窗口时（`--headless`）界面依旧是完整可用的网页，方便远程或脚本调试。

---

## 三、端口约定

| 用途 | 端口 | 说明 |
| --- | --- | --- |
| 本界面 API | 17650 | 仅监听 `127.0.0.1` |
| NapCat WebUI | 6099 | 与手机版一致 |
| AstrBot 控制台 | 6185 | 与手机版一致 |
| OneBot 反向 WS | 6199 | NapCat → AstrBot |

端口可以在「实例」页改；改完在「服务」页重启对应进程生效。

---

## 四、工程结构

```
astrbot-pc/
├─ launcher.py      PyInstaller 的入口（源码跑也行）
├─ build.spec       打包配置：目录版（onedir）
├─ build_onefile.spec  打包配置：单文件版（onefile）
├─ launch_gui.pyw   开机自启用：无控制台拉起桌面窗口
├─ astrbot_pc/
│  ├─ app.py        入口与三种启动方式
│  ├─ server.py     HTTP 服务、静态资源、SSE 推送
│  ├─ api.py        接口分发（统一 {ok:true,...} / {ok:false,err} 返回）
│  ├─ config.py     读写 config.json
│  ├─ paths.py      数据目录与产品常量（区分源码模式 / exe 模式）
│  ├─ probe.py      端口探测（带 0.8s 缓存，避免首屏被超时拖住）
│  ├─ services.py   进程管理：启停、自愈、CPU/内存采样
│  ├─ deploy.py     八步部署流程（演练 / 真实）
│  ├─ download.py   断点续传下载、解压、剥顶层目录
│  ├─ envcheck.py   Python / Git / QQ NT / 磁盘 / 网络的体检
│  ├─ logs.py       日志列表、尾部读取、跟随
│  ├─ instances.py  多实例 CRUD
│  ├─ backup.py     备份、恢复、占用统计
│  ├─ stats.py      消息量、在线时长、异常数
│  ├─ startup.py    开机自启（写 HKCU Run 键，免管理员）
│  ├─ events.py     事件总线 → SSE
│  ├─ tray.py       托盘常驻：图标、菜单、通知（缺 pystray 自动降级）
│  ├─ update.py     检查更新：只认 PC 端发布，30 分钟缓存
│  └─ shell.py      pywebview 无边框窗口（窗口引用必须下划线开头，见下方说明）
├─ ui/
│  ├─ index.html    外壳：标题栏、侧栏、路由出口、弹层与命令面板
│  ├─ css/          tokens.css（设计变量）+ app.css
│  └─ js/           main / router / store / api / components / charts / icons / util
│     └─ pages/     dashboard / deploy / services / logs / login / instances / backups / settings
├─ tools/           冒烟截图、打包、图标生成与调试脚本
│  ├─ build_exe.ps1 一条命令出 exe + 发布 zip
│  ├─ release.py    建 GitHub Release 并上传 zip
│  ├─ push_api.py   只放行 api.github.com 时的推送通道
│  ├─ make_icon.py  从 favicon.svg 渲染多尺寸 .ico
│  ├─ smoke.py      八页零报错冒烟
│  └─ probe_update.py 用假数据验证版本 chip
├─ build/           app.ico、version_info.txt（打包时用，别删）
└─ docs/            设计说明
```

打包：

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
# → dist\AstrBotPC\AstrBotPC.exe                 目录版
# → dist\AstrBotPC-1.0.1-win64.zip               目录版压缩包
# → dist\AstrBotPC-1.0.1-win64-single.exe        单文件版
```

---

## 五、发版流程

1. 改版本号：`astrbot_pc/paths.py` 的 `APP_VERSION`、`build/version_info.txt`、`tools/release.py` 里的 `TAG` 与 `ZIP`
2. 打包：`powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1`
3. 发布：

   ```powershell
   set GITHUB_TOKEN=ghp_xxx
   python tools\release.py        # 建 pc-v1.0.1 Release + 上传 zip
   ```

   tag 必须用 `pc-v<版本>` 或资产名带 `PC`——`update.py` 只认这两种，否则客户端不会提示更新。
4. 推送代码（`git push` 被网络挡掉时）：

   ```powershell
   python tools\push_api.py       # blob → tree → commit → ref，走 api.github.com
   ```

发完之后，老版本客户端下次启动就会在标题栏出现「新版 v…」胶囊，点开是这份 Release 的说明。

后端接口统一：

```json
{ "ok": true, "data": ... }        // 成功
{ "ok": false, "err": "中文原因" }  // 业务失败（HTTP 仍是 200）
```

> **改 `shell.py` 时注意**：pywebview 会把 `js_api` 对象的非下划线属性递归当作命名空间暴露出去。
> `WinApi` 里指向窗口的引用必须叫 `_window`；叫 `window` 的话它会顺着 `Window.native`
> 一路递归，Windows 上表现为启动即报 `maximum recursion depth exceeded`。

---

## 六、设计规范

- 主色 `#2563EB`，暖强调 `#EA580C`，正文 `#0F172A`，次级 `#475569`，分隔线 `#E2E8F0`
- 圆角 12px 基准（卡片 16、标签 8），间距按 4/8 节奏，卡片内边距 20–24px
- 系统无衬线字体栈，标题 600、正文 400、行高 1.6
- 图标全部是内联 SVG（`ui/js/icons.js`），不使用 emoji 充当结构图标
- 正文对比度 ≥ 4.5:1；状态同时用颜色与文字表达，不靠颜色单独传意
- 入场 0.4s、悬停 120ms；`prefers-reduced-motion` 下关闭位移与循环动画
- 深浅两套主题同一份变量，`data-theme` 切换即可

---

## 七、部署向导在做什么

八步里前六步是「装」，后两步是「起」。每步都会把结果写进「日志」页，失败时红字会带上原始报错尾巴。

| 步骤 | 实际动作 |
| --- | --- |
| 环境检查 | 读 Python / Git / QQ NT / 磁盘；真实模式额外探一次 `github.com` 通不通 |
| 准备目录 | 建 `stack/` `logs/` `backups/` `tmp/` |
| 获取 NapCat | 从 GitHub Release 拉 `NapCat.Shell.Windows.Node.zip`（约 118 MB，自带 node.exe），解压到 `stack/napcat`，自动剥掉压缩包顶层目录 |
| 获取 AstrBot | 下载 AstrBot master 源码包解压到 `stack/astrbot`（设置里可改成 git clone） |
| 安装依赖 | 建 `stack/venv` 独立虚拟环境，`pip install -r requirements.txt`，实时把 pip 最后一行推给进度条 |
| 写入配置 | 写 `stack/napcat/config/onebot11_<QQ号>.json` 的 `websocketClients`，以及 `stack/astrbot/data/config/cmd_config.json` 的 `dashboard` 与 `platform`（aiocqhttp 反向 WS） |
| 启动 NapCat | 拉起进程并等 WebUI 端口（最多 120s） |
| 启动 AstrBot | 拉起进程并等控制台端口（最多 180s） |

下载走断点续传（`Range`），失败自动退避重试两次；进度按 0.25s 节流推到界面，显示已下多少 / 总共多少 / 当前速度。

依赖安装默认走**清华 PyPI 镜像**，设置页可换成阿里云、腾讯云或官方源。国内网络下装 AstrBot 依赖通常要 5–15 分钟，这段时间进度条会一直滚 pip 的最新一行。

---

## 八、当前进度

已跑通：

- 本地服务、八个页面的完整交互、SSE 推送与断线回落，首屏 0.6s 出内容
- 桌面窗口（pywebview 无边框，自绘最小化 / 最大化 / 关闭）
- 托盘常驻：关窗收起、右键菜单启停服务、检查更新、退出；托盘动作走后台线程，不卡菜单
- 检查更新：只认 PC 端发布（tag `pc-*` 或资产名含 `PC` / `Windows`），标题栏出「新版」胶囊，点开有说明与下载入口；30 分钟缓存，查不到就照实说
- 进程管理（真的启停子进程，采样真实 CPU / 内存）；被强杀后下次启动会按记录的 PID 回收残留子进程
- 日志浏览、筛选、跟随、导入导出
- 实例增删改、备份建立 / 恢复 / 删除
- 开机自启（写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，不需要管理员；关掉就删键）
- 部署向导八步全部实跑通过：真下载 NapCat 与 AstrBot、装依赖、写 OneBot 与 AstrBot 配置；写的是 AstrBot 真正会读的 `data/cmd_config.json` 与 NapCat 回退读的 `onebot11.json`
- 下载链路：实测选源（直连 + 三个加速镜像并发测速后取最快）、断点续传、半截包不算成功、20 秒没新数据就换源
- 界面访问范围：「仅本机」/「允许局域网」真的会改监听地址（重启界面生效）
- exe 已发布：<https://github.com/Zxin-Pro/astrbot-pc/releases>（目录版 zip 约 22 MB，另有单文件 exe）
- Playwright 冒烟：八页零控制台报错、零失败请求，390px 窄屏不溢出；深色主题同样过一遍

还没接：

- 更新只提示不自动下载覆盖（本机程序自己替换正在运行的文件太容易搞坏）
- NapCat 首次登录需要人工扫码，向导只负责把二维码页面准备好

---

## 九、更新日志

### 1.0.1

修的都是「点了部署以为装好了，其实一个文件没落地」这一类：

- **写错了配置文件路径**：AstrBot 只读 `data/cmd_config.json`，原来写进 `data/config/cmd_config.json`，平台等于没配，装完也连不上 NapCat。NapCat 那边同理，原来写 `onebot11_default.json`，而它会先找 `onebot11_<QQ号>.json`、找不到才回退读 `onebot11.json`——只认后者。
- **演练模式不再冒充装好**：演练只做检查不动文件，原来八步全绿、结束写「全部完成」，看着像装完了。现在结束文案是「演练通过：没有任何文件被安装」，界面上也会标出来。
- **联网检查不再假阳性**：原来只 `HEAD github.com`，握手超时也会被 DNS 拖住几十秒再报错，而下载走的是另一条链路。改成用下载源本身测速，选不出源就直接说「连不上下载源」。
- **下载链路重写**：直连 + 三个加速镜像并发测速取最快；20 秒收不到新数据就换源；换源保留 `.part` 续传；半截包按失败处理（原来会当成功）。
- **子进程日志乱码**：给子进程补 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`，否则输出重定向到文件时 Windows 上退回 GBK，中文变乱码、带 emoji 的行直接抛 `UnicodeEncodeError` 丢掉。
- **命令带引号跑不起来**：`shlex.split(posix=False)` 会把引号留在 token 里，`"C:\...\python.exe"` 直接报「系统找不到指定的文件」。
- **没装时报错文不对题**：`Path("")` 等于 `Path(".")`，明明没装却说「目录里找不到 main.py，可能装坏了」。
- **强杀后留孤儿**：应用被强制结束时 NapCat 还连着 QQ、下次启动端口冲突。现在启动时按记录的 PID 回收，且只认数据目录下的进程，不会误杀别的。
- 新增设置项「下载加速镜像」（`deploy.accel`），关掉就只走直连。

### 1.0.0

首个 PC 版：八个页面、桌面窗口与托盘、检查更新、进程管理、日志、实例与备份、开机自启、部署向导。

---

## 十、常见问题

**双击 `run.bat` 没反应？**
用 `run-console.bat` 看报错。多半是 `python` 不在 PATH，或没装 `requirements.txt` 里的依赖。

**窗口一片空白？**
WebView2 运行时缺失时 pywebview 起不来。装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)，或直接用 `--web` 走浏览器。

**端口被占？**
服务会顺延端口并在控制台打印实际地址；也可以在设置里改「首选端口」。

**扫码一直不出码？**
先确认 NapCat 在「服务」页是运行中；再看「登录」页右侧的排障清单，最后去「日志」页翻 NapCat 输出。

**开机自启没生效？**
自启写的是当前用户的 Run 键，指向 `launch_gui.pyw`。移动过文件夹或换过 Python，需要在设置里关一次再打开，让路径重新写入。被安全软件拦过的话，在「启动应用」里手动放行。

**点了 × 窗口没退出？**
这是有意的：设置里「关闭窗口时最小化到托盘」开着时，× 只收起窗口。右键托盘图标点「退出」才真的收摊；想改成点 × 就退出，把这个开关关掉。

**托盘图标不见了？**
Windows 会把不常用的图标折叠进「^」里，点开找一下。如果连折叠区都没有，多半是 `pystray` 没装上——用 `run-console.bat` 看有没有 `pip install -r requirements.txt` 的报错。

**「检查更新」说 PC 端还没有发布版本？**
正常。同一个仓库的最新 Release 目前是手机版 `AstrBot-1.1.31.apk`，桌面版还没发过包。程序只认 `pc-*` 的 tag 或名字带 `PC` 的资产，不会拿手机版冒充桌面版。

---

烛心.xyz · QQ 群 1127997343 · PC 端仓库 <https://github.com/Zxin-Pro/astrbot-pc> · 手机版 <https://github.com/Zxin-Pro/astrbot-candle>
