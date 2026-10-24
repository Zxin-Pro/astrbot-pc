# 烛之控制台 · 设计说明

这份文档记录界面的取舍理由，改版时先看这里再动手。

## 一、为什么长这样

这个程序要解决的不是「展示数据」，而是**让一个不写代码的人把 QQ 机器人跑起来**。所以整个界面围绕一条主线组织：

```
部署（把东西装好） → 登录（扫码上线） → 服务（确认在跑） → 日志（出问题能查）
```

侧栏因此分成两组：上面「工作台」是主线四步，下面「数据与设置」是配套。概览放在第一位，因为它回答的是「现在到底怎么样」——用户每次打开窗口最先想知道的事。

## 二、视觉系统

| 项目 | 取值 | 理由 |
| --- | --- | --- |
| 主色 | `#2563EB` | 蓝，冷但不刺眼，和 QQ 蓝有区分 |
| 暖强调 | `#EA580C` | 只用在「需要注意」的地方，不做装饰 |
| 正文 | `#0F172A` | 近黑，比纯黑柔和，长段落不累 |
| 次级文字 | `#475569` | 说明文字，对比度仍 ≥ 4.5:1 |
| 分隔线 | `#E2E8F0` | 极轻，用来分组而不是画表格 |
| 圆角 | 12px / 卡片 16px / 标签 8px | 12 是基准，卡片更圆显得稳，标签更方显得准 |
| 间距 | 4 / 8 节奏，区块间 64px | 大留白让页面有呼吸感 |
| 字体 | 系统无衬线栈 | 不引外部字体，离线可用 |

深色主题不是把颜色反过来，而是重新取值：背景降到 `#0B1220`，卡片 `#111A2C`，品牌色提亮到能在深底上看清。两套主题共用同一批 CSS 变量，`data-theme` 一换即可。

### 液态玻璃这一层

默认形态是液态玻璃（Apple Liquid Glass）。它是一层**覆盖样式**，不重写 `app.css` 的布局：`ui/css/glass.css` 在 `app.css` 之后加载，只改材质与光影。

成立要三个条件：背后有东西可透（`.backdrop` 四块大模糊色块 + `.grain` 颗粒）、玻璃只给面板用（面板里的面板保持薄实色，玻璃叠玻璃会糊）、文字色阶跟着压深一档（玻璃会提亮背景）。任缺一条就退化成「白卡上放白字」。

关闭、降低透明度、窄屏三条降级路径：

| 触发 | 做法 |
| --- | --- |
| 设置里关掉 | `js/glass.js` 给 `<link id="glass-css">` 加 `disabled`，等于回到 `app.css` 原始界面 |
| 系统「降低透明度」 | 面板退成实色、撤掉底图与颗粒、侧栏回到原始配色 |
| 窗口 ≤900px | 模糊半径降一档（14px / 18px），减少老显卡的重算开销 |

`backdrop-filter` 每帧重算，所以玻璃层**不做任何连续动效**。实测八页滚动 p95 都是 59–60fps。

## 三、页面结构约定

- 每个页面 = 页头（标题 + 一句话说明 + 右侧主操作）+ 若干 `.section`
- 区块标题用 `h2`，卡片内小标题用 `h3`，层级不超过三级
- 主操作永远在右上角，且每页只有一个（启动部署 / 一键启动 / 立即备份）
- 空态必须给出**下一步动作**，不能只说「暂无数据」

## 四、几个关键交互的取舍

**部署向导用「八步固定列表」而不是进度条 + 当前步骤。**
用户在这里最怕的是「卡住了不知道卡在哪」。把八步全列出来，当前步高亮、已完成打勾、失败标红并展开原因，用户随时知道还剩几步。进度条只作为下载 / 装依赖时的补充信息——因为这两步耗时不可预期，需要持续的「还在动」信号。

**「演练模式」默认开着。**
真实部署要下 120 MB 外加几分钟的 pip，第一次就真跑容易让人以为程序卡死。先空跑一遍，八步全绿，用户心里有底了再关掉开关真跑。

**日志页分「级别 + 关键字」两级筛选，不做正则。**
查问题时人手最快的方式是「只看错误 + 搜关键词」，正则表达式的学习成本远大于收益。

**服务卡片用环形图只画 CPU，内存用数字。**
CPU 是瞬时值，环形能表达「现在多忙」；内存是稳态值，画成环反而不如直接读数字。

**设置项改完即存，没有「保存」按钮。**
所有开关是一对一的布尔值，改完就落盘，失败会弹提示并回滚。加保存按钮只会让用户忘记点。

**命令面板（Ctrl+K）分「页面」和「动作」两组。**
人和机器都容易把「跳到某页」和「做某件事」混在一起。分组之后，输入 `启` 只剩动作，输入 `日` 只剩页面，匹配更准。

**检查更新只认 PC 端的发布，认不到就直说。**
同一个仓库里手机版已经发到 1.1.31，桌面版才 1.0.0。要是直接拿最新 Release 比，界面会永远挂着「新版 v1.1.31」，用户点进去发现是 APK——比「没有更新」更糟。所以先按 tag（`pc-*` / `desktop-*`）或资产名（含 `PC` / `Windows`）筛出桌面版发布；筛不到就显示「PC 端还没有发布版本」，把选择权交回用户。

**关窗默认收起而不是退出，但每次都要给出回执。**
机器人是要长期跑的，误点 × 就断线代价太大。所以 × 之后窗口消失、托盘弹一条「还在后台跑」；第一次启动时也提示一次托盘已就绪。用户永远知道进程还在，不会以为程序没关干净又开一个。

## 五、动效原则

- 入场 0.4s，只做位移 + 透明度，不做缩放弹跳
- 悬停 120ms，只改颜色和阴影，不改尺寸（避免布局抖动）
- 环形图数值变化用 240ms 过渡，让数字「走」过去而不是跳过去
- 循环动画（在线呼吸灯、进度条不定态）在 `prefers-reduced-motion: reduce` 下全部停止

## 六、无障碍

- 所有可点元素是 `button` 或带 `role` 的容器，键盘可达
- `focus-visible` 统一 2px 品牌色描边 + 2px 偏移
- 状态同时用颜色和文字（「运行中」绿点 + 文字），不靠颜色单独传意
- 装饰性 SVG 加 `aria-hidden="true"`；图标按钮必须有 `aria-label`
- 表单控件都有可见 label 或 `aria-label`

## 七、改版检查清单

1. 新增颜色是否进了 `tokens.css`（不要在 `app.css` 里写死色值）
2. 新增 class 是否真的定义了（`tools/check_vars.py` 能扫出未定义变量）
3. 深浅两套主题都看一遍
4. 1440×900 和 390×844 两个宽度都不横向溢出
5. 跑 `tools/smoke.py`，确认零控制台报错
6. 动过玻璃层就再跑这四条：
   - `tools/probe_glass.py` —— 玻璃/实色 × 深浅的全页截图，看有没有哪块变透明或变白卡
   - `tools/probe_glass_qa.py` —— 卡片内最低对比度（要 ≥ 4.5）与滚动 p95 帧率（要 ≥ 55）
   - `tools/probe_glass_overlay.py` —— 弹层、吐司、降低透明度、降低动效
   - `tools/probe_glass_narrow.py` —— 390px 下玻璃版有没有溢出

## 八、踩过的坑

**pywebview 的 `js_api` 会递归暴露所有非下划线属性。**
`WinApi` 最初把窗口引用存成 `self.window`。pywebview 注入桥接时会 `dir(obj)` 递归遍历，遇到 `window` 就钻进 `Window.native`（WinForms 控件），再钻进 `AccessibilityObject.Bounds.Empty.Empty…`，直到 `maximum recursion depth exceeded`，表现是桌面窗口一启动就退出。改叫 `_window` 就好了——下划线开头的属性会被跳过。

**托盘菜单回调跑在 pystray 的消息循环线程里。**
在里面直接 `stop_all()`（等子进程收摊，最长十秒）或 `start_all()`（等端口，最长二十秒），右键菜单会跟着纹丝不动。所以所有启停都丢进后台线程，菜单立刻返回，结果用托盘气泡回话。

**「关窗最小化」的开关不能只在设置里说。**
`on_closing` 和自绘标题栏的 `close()` 是两条路径，都要走同一个 `_to_tray()` 判断；否则点 × 和点任务栏关闭会得到两种结果。

**配置写对了内容，写错了位置，一样等于没写。**
部署向导最初把 AstrBot 的配置写到 `data/config/cmd_config.json`，看着很合理，但 AstrBot 只读 `data/cmd_config.json`（见 `astrbot/core/config/astrbot_config.py`），写进去的那份永远没人打开，表现是「八步全绿、装上却连不上 NapCat」。NapCat 同理：它先找 `onebot11_<QQ号>.json`，没有才回退读 `onebot11.json` 并另存一份带号的。所以「顺着自己的直觉命名」这件事在对接别人的程序时必须去打源码确认，不能按目录结构猜。

**演练模式最危险的不是不做事，是让人以为做了事。**
空跑八步全绿、结束还写「全部完成」，用户会直接去扫码登录，然后一头雾水。演练结论必须和真实结论用不同的措辞——现在是「演练通过：没有任何文件被安装，关掉演练模式再点一次才会真的装」。

**「能不能联网」要测真正会走的那条链路。**
原来部署第一步只 `HEAD https://github.com`，它返回 200 就放行；但真下载走的是另一条连接，在同样网络下 20 秒后握手超时。检查与执行必须用同一条路径，否则检查越「通过」，后面的失败越难解释。

**「文件下完了」和「文件是完整的」是两件事。**
`download.py` 最初只看到循环正常结束就返回成功，服务端提前断开时留下半截 zip，解压阶段才炸，且报错指向解压而不是下载。现在比对 `Content-Length`，不够就保留 `.part` 换源续传；同时加「20 秒没有新数据」判定——镜像挂死时 `recv` 会一直阻塞，不设停滞检测就会永远停在 99%。

**测速要测得「同一时刻谁快」，不能测「谁先回应」。**
换源时如果按「第一个连上的」来选，会挑中握手很快但吞吐只有 190 KB/s 的镜像，而旁边那个 9.6 MB/s 的却因为晚了几百毫秒被放弃。做法是并发各读 2 秒样本比字节数，且一旦有非零得分就停止等慢源。

**`background-clip: border-box` 不会把高光关进 1px 边框里。**
液态玻璃的第一版想用「一层 tint + 一层描边渐变」做材质，`border-box` 只决定背景能画到边框外沿，结果是整张卡被高光洗白。正解是三层背景图从下往上排：描边高光在最底层、玻璃本体在中间层并 clip 到 `padding-box`、面反光在最上层。本体那层一裁到内边距盒子，高光就自然只剩边框那一条。

**玻璃调「厚」是最容易走错的方向。**
对比度不够时第一反应是把 tint 调白（`.58` → `.75`），数字立刻好看了，但底色全被压掉，只剩边缘一圈有色，液态玻璃的「透」就没了。正确的做法反着来：把白度降下去，同时把整条文字色阶压深一档。测出来浅色 4.89、深色 4.50，透色也保住了。

**「关掉特效」不要写成「再写一份还原规则」。**
`[data-glass="off"]` 里逐条覆盖回去，漏一条就出一次事故——实际漏的是 `border`，面板边框透明、填充也跟着丢，浅色下白底白卡，卡片整体消失。改成关掉时直接给 `<link id="glass-css">` 加 `disabled`：关掉就等于回到 `app.css` 的原始界面，没有「还原」这回事，也就没有漏的可能。

**变量里放「裸颜色」会让整条 `background-image` 失效。**
降级块里写了 `--glass-rim-gradient: var(--line)`，`background-image` 期待的是图片，收到颜色后整条声明作废，连带中间那层本体填充一起消失。要写成 `linear-gradient(var(--line), var(--line))`。

**玻璃上做输入框，白边白底等于没画。**
`.input` 原来是 `--glass-tint-weak` 底 + `--glass-rim-2` 边，浅色下两个都是半透明白，弹窗里的四个输入框彻底看不见。输入框不该是玻璃而是凹槽：按 `--ink` 做减淡（`color-mix(in srgb, var(--ink) 5%, transparent)`），`--ink` 跟主题翻转，同一套公式深浅通用。

**给 `.btn` 写 `--btn-bg` 会把主按钮变成白块。**
`.btn--primary` 是靠自定义属性 `--btn-bg` 传给 `.btn` 的 `background` 简写的。玻璃层如果给 `.btn` 再写一次 `--btn-bg` 或 `background-image`，简写会被整个替换掉，主按钮就退化成白底。次级按钮要用 `:not()` 把主/暖/危险/幽灵四种排除掉。

**怀疑「渲染接缝」先采样像素，别靠截图目测。**
日志页截图上看着有一条竖着的色阶断层，实际从 x=600 采到 x=700 是平滑过渡（242,246,251 → 241,244,249），`elementFromPoint` 返回的也是透明背景元素。截图的缩放与压缩会伪造出并不存在的接缝。

**别把几百 MB 资源塞进单文件 exe。**
单文件版的启动方式是「整个 exe 先解压到临时目录再跑」，体积直接等于冷启动时间。260 MB 的资源塞进去，每次双击都要等几十秒，而用户其实只在第一次部署时用得上。资源放在 exe 同级的 `resources\`，看得见、换得掉、还能整个删掉退回联网版。

**`_MEIPASS` 不是「用户看得见的那个目录」。**
PyInstaller 6 的 onedir 布局里 `sys._MEIPASS` 指向 `_internal/`。按它找资源，路径能通，但用户打开程序目录根本看不到那个文件夹，想换资源也无从下手。找「跟 exe 摆一起的东西」要用 `sys.executable` 的父目录（onefile 下它也是用户双击的那个真路径）。

**离线的副作用要主动兜住，别让用户卡在最后一步。**
wheel 是按打包时的 Python 版本挑的（cp312 / win_amd64）。用户机器换成 3.13，`pip install --no-index` 会全军覆没——如果只报错，用户会觉得「离线包是坏的」。现在的做法是：离线装失败就自动退回联网装一次，并在结果里写明「离线包版本对不上，这次走了网络」。降级可以，但必须说出来。

**打包之后 `sys.executable` 不是 Python。**
`python -m venv` 建虚拟环境靠的是 `sys.executable`。冻进 exe 之后它指向 `AstrBotPC.exe`——这个文件自己就是 Python 程序，但对外只认自己的命令行参数，`-m venv` 会直接失败。这个 bug 只在打包版里出现，源码跑一万遍也复现不了，所以每次改部署逻辑都要**拿真正的 exe 跑一遍**。修法是回到系统里找解释器（`py -3` → PATH 的 `python` → 常见安装目录），找到的路径同时拿去纠正环境体检里显示的「Python 运行时」——否则界面上会写着 `3.12.10（AstrBotPC.exe）`，一眼假。

**与其到处找解释器，不如自己带一个。**
「让用户装 Python」这件事本身就是个坑：装错版本、没勾 Add to PATH、装在中文路径、安全软件拦一下——每一种都要来回好几轮。懒人版的做法是把一份便携 CPython 放进 `resources\python\`（NuGet 的 `python` 包解出来就是完整发行版），`find_python()` 优先用它。附带好处是 wheel 一定配得上：wheel 按 3.12 打，解释器也固定 3.12，不会出现「系统里是 3.13 装不上」。**别用 embeddable zip**——它没有 `venv` 也没有 `ensurepip`，省下 4 MB 换来一个建不起来的虚拟环境。

**按名字匹配一批东西，等于埋一个静默失效的开关。**
`_stage_env` 里原来写 `if "Python" in missing`，而 `missing` 装的是各项的显示名，那一项叫「Python 运行时」——这个判断从加上那天起就没生效过，永远返回 False，代码还看着挺合理。凡是拿显示文案当条件的地方，都该改成按稳定的 key（`python` / `qq` / `git`）判，显示名只用来给人看。

**对接别人的配置，先照着它自己写出来的样子抄。**
AstrBot v4 收到扁平的 provider 项会当场迁移成 `provider_sources`（存 base_url / key）+ `provider`（存模型名，用 `provider_source_id` 指回去）两层，并且**重写整个 `cmd_config.json`**。我们最初按老格式写，每次启动都被迁一遍；界面读的又是扁平字段，迁移后 `apiBase` / `hasKey` 全空，看着像「保存没生效」。改成直接写最终结构、读的时候顺着 `provider_source_id` 找连接信息，两个问题一起消失。判断依据是它自己迁移后的文件长什么样，不是文档里的字段表。

**模型和人格根本不在同一个文件里。**
`cmd_config.json` 里那个 `persona` 数组在 v4 已标 deprecated，写它等于没写——真正的人格在 `data/data_v4.db` 的 `personas` 表里。只改 JSON 会得到「配置里明明有、AstrBot 却说 Loaded 1 personas」。改数据库要注意它是 WAL 模式，`-wal` / `-shm` 要一起处理。

**同一个色名可能已经被「错误提示」占用了。**
`.field__hint` 是 `--bad-600` 红色，`instances.js` 拿它当校验失败的位置。模型页把三句普通说明也写成这个类，整页看着像处处报错。现在分两个：`.field__hint` 只给错误，`.field__help` 是灰色说明。用现成 class 之前先看它在别处是干什么的。

**异步回来别整页重画。**
中转站检测最长要等十几秒，回来时调一次 `render()` 整页重写，用户刚贴进去的密钥和模型名就没了，还会以为是自己点错了。会变的那一块单独放进一个容器（`#relay-slot`），回来只重画它。判断标准很朴素：用户可能正在输入的区域，不能被异步结果整块替换。

**重建 exe 之前，先确认打包机的 pythonnet 是完整的。**
pythonnet 3.x 靠 `clr_loader` + `cffi` 去找 `Python.Runtime.dll`；这两个包缺了，PyInstaller 一声不响，打出来的 exe 也能启动、能起 HTTP 服务，但一开窗口就抛 `webview.errors.WebViewException: You must have pythonnet installed in order to use pywebview`——冒烟只跑 `--headless` 是照不出来的，必须真的开一次窗口。判据两条：`python -c "import clr, webview"` 能过；`dist\AstrBotPC\_internal` 里能看到 `clr_loader` 与 `_cffi_backend*.pyd`。顺带：PyInstaller 自己还依赖 `altgraph`、`pefile`（连带 `ordlookup`）、`packaging`，少一个连 `--version` 都跑不起来。

**后台任务的返回值，别去读子线程的局部变量。**
备份改成后台打包后，`create_async()` 在返回的 dict 里写了 `name`，而 `name` 是在子线程 `_work()` 里算的——子线程已经启动、备份会照常完成，但主线程返回时抛 `NameError`，接口 500，界面说失败。修法是把名字在拿锁之前就算好、写进 `_job`，`_work()` 只读外层闭包。判断标准：任何会被另一个线程读到的值，都必须在启动线程之前绑定好。

**前端的 request 封装已经包过一层参数，调用处别再包。**
`api.js` 的 `setBackground: (dataUrl) => request(..., { dataUrl })` 已经负责组装 body；设置页又写成 `api.setBackground({ dataUrl })`，服务端收到 `{"dataUrl":{"dataUrl":"data:image/png;..."}}`，报「只支持 PNG / JPEG / WebP / GIF」。凡是「helper 签名是值、不是对象」的地方，调用处传对象就是双重包装。排查时在页面里拦一次 fetch 看 body 最快。

**用户自选的背景图必须再加一层可读性遮罩。**
背景图由用户提供，可能是一张亮到发白的人像或花纹，直接把正文压上去必然掉到 4.5:1 以下。做法是给 `.backdrop` 加 `has-bg` 类，再用 `::after` 铺一层半透明白（浅色 .66/.44、深色 .6/.76）；背景图本身只放在 `background-image` 里，不要和渐变混在 JS 字符串里，否则调透明度时两边互相打架。换图、清图都要同时改 class 与 style，不能只改一处。

**导航快捷键按 route.shortcut 匹配，不要按数组下标。**
模型页插到「部署」和「服务」之间后，`Ctrl+8` 落到了备份页、设置页再也按不到——因为代码写的是 `ROUTES[Number(e.key)-1]`。现在每个路由显式带 `shortcut`，`Ctrl+数字` 按这个字段找；新增页面插在中间不会挪动别人。排障页没有快捷键，按侧栏进。

**设置保存成功不等于界面已经用上新值。**
`saveSetting()` 只写后端并把结果返回，`ctx.store.config` 不会自动刷新。背景图、玻璃三档、精简模式这类「立即看得见」的项，保存后必须在本地同步应用（`paintBackdrop` / `applyGlass` / `applyCompact`）并更新 store，否则用户会以为没生效，再点一次。

**打包脚本别再指望 PATH 里那个 python。** `tools/build_exe.ps1` 现在先 `Get-Command python`，找不到再退到 `%LOCALAPPDATA%\Programs\Python\Python3xx\python.exe`；这台机器上 `python` 在 PATH 里也能被 `Get-Command` 找到之前，脚本一直报「无法将 python 项识别为 cmdlet」。另有一个更迷惑的坑：从别的程序里起 PowerShell 去调 exe 时，子进程环境里必须有 `PATHEXT`，否则 `& 'C:\...\python.exe'` 会被 PowerShell 当成「文档」去激活，报 `无法在管道中激活文档`，看起来像是 python 不存在。


**改 PowerShell 脚本时，BOM 是文件的一部分。**
`tools/build_exe.ps1` 里写着「必须存成 UTF-8 with BOM」不是洁癖：Windows PowerShell 5.1 读无 BOM 的脚本会按 ANSI 解码，中文注释里的引号被吃掉，一启动就报 `The string is missing the terminator: '.`。用编辑工具改完要检查头三个字节是不是 `EF BB BF`，不是就补回去。这个错误发生在解析阶段，日志里不会有更具体的位置。

**`$ErrorActionPreference = 'Stop'` 遇到原生命令的 stderr，会在重定向时直接终止脚本。**
构建脚本里 `& $py -m PyInstaller ...` 只写 WARNING 到 stderr，本身退出码是 0；但外层用 `powershell -File tools\build_exe.ps1 *> build.log` 收集输出时，PowerShell 5.1 会把原生命令的 stderr 包成 ErrorRecord，`Stop` 立刻终止，日志停在 `[3/6] pyinstaller onedir`、后面一个字都没有。改成 `cmd /c "powershell -File ... > build.log 2>&1"`，让 cmd 负责重定向，stderr 就不会变成终止错误。诊断时先手工跑一遍被吞掉的命令，能立刻分清是构建坏了还是日志坏了。

**cmd 输出的是 GBK，不是 UTF-8。**
内置终端用 `raw.decode("utf-8", "replace")` 读 `cmd /c ver`，中文「版本」变成一串乱码。正确顺序是：空输出直接返回；有 UTF-8 BOM 用 `utf-8-sig`；严格 UTF-8 能解就用；失败回退 `gbk`；再失败才 `gbk` + `replace`。不要一上来就用 `replace`，它会把「不是 UTF-8」这件事悄悄吞掉。

**按钮在 DOM 里，不等于点了有反应。**
排障页的「运行」按钮带着 `data-act="term-run"`，样式和位置都对，点下去却毫无反应——根 click 处理器里根本没有 `term-run` 这个分支，只有别的几个动作。这类 bug 用截图看不出来，必须在浏览器里点一次并观察有没有发出请求。新增 `data-act` 时，把「加按钮」和「加分支」当成同一步。

**隐藏的 checkbox 不能当点击热区。**
`.switch` 用 `<span>` 包一个透明 `<input type="checkbox">`，而 `.switch input` 的宽高是 0；用户点轨道时事件落不到 input 上，开关永远点不动，只有键盘能改。把 input 改成 `position:absolute; inset:0; width:100%; height:100%; z-index:2; cursor:pointer`，整块轨道都成为热区。判断方法：鼠标点一次看状态变不变，别只测 `checked = true`。

**「没有安装」和「已是最新」是两种状态。**
组件表里 AstrBot / NapCat 没装时，`latest === current` 这类判断会落到「已最新」的绿色徽标上，用户以为一切正常。状态判断要先把 `!installed` 单独拎出来显示「未安装」，再比较版本。

**旧版的全局端口不是新实例的保留端口。**
多实例迁移时 `migrate_ports()` 一开始把 `services.napcat.port` / `services.astrbot.port` 也放进已占用集合，结果第一个实例被挤到 6100/6186，界面上的端口和用户记忆里的 6099/6185 对不上。这两个键是 1.0.0 之前「全局只有一对进程」时代的遗留配置，迁移时只该保留真正的全局项（UI 端口），实例端口从默认值重新分配。

## 窗口动画（1.0.1）

- **无边框窗口没有系统过渡动画**：Windows 只给带 `WS_CAPTION` 的窗口做最小化 / 还原动画。同一个窗口临时加回 `WS_CAPTION|WS_THICKFRAME` 立刻就有多帧渐变（13/74/105/135/165/202/236 ms），去掉就只剩一帧跳变。所以 frameless 客户端要自己做淡入淡出。
- **任务栏按钮依赖 `WS_MINIMIZEBOX`**：`FormBorderStyle.None` 让 WinForms 的 `CreateParams` 不再带这个样式位，点任务栏图标既不能最小化、也不会触发系统动画。补样式位用 `SetWindowLongW(GWL_STYLE)` + `SetWindowPos(..., SWP_FRAMECHANGED)`，两个毛病一起好。别改托管属性 `ControlBox/MinimizeBox`——在活着的无边框 Form 上改会让进程直接退出，连异常都没有。
- **`WS_EX_LAYERED` 是可以用在运行中的 WebView2 窗口上的**：加 `SetLayeredWindowAttributes` 调 alpha，内容正常渲染，不白屏。淡入前先把 alpha 压到 42 再让窗口显示，淡出后在窗口已经缩下去之后再摘样式，顺序反了会看到一次跳亮。
- **最大化盖住任务栏**：无边框窗口最大化时 rect 是整屏（含任务栏）。子类化 `WM_GETMINMAXINFO`，在**调用默认过程之后**改 `ptMaxPosition/ptMaxSize`（先改会被默认过程覆盖），按 `MonitorFromWindow` + `GetMonitorInfoW` 的工作区算。
- **最小化别直接用 Win32 `ShowWindow`**：绕过 WinForms 的 `WindowState` 逻辑，WebView2 的合成表面不知道窗口被藏起来了，还原时只剩一块白。走 `window.minimize()/maximize()/restore()`，样式位负责让系统动画与任务栏按钮成立。


## SnowLuma 与 NapCat 并存（1.0.2）

- **SnowLuma 的数据目录 = 进程 cwd**，这一点和 NapCat 的 `NAPCAT_WORKDIR` 不一样。给它每个实例一个独立 cwd（`instances/<id>/snowluma`），`config/runtime.json`、`config/onebot.json`、`logs/` 就自然分开了；两个实例同时开也不会抢 `onebot11.json`。
- **`index.mjs` 必须用绝对路径启动**：cwd 切到实例目录后再传相对的 `index.mjs`，Node 会去 `<实例目录>/index.mjs` 找，报 `Cannot find module ...\work\index.mjs`。
- **端口别用默认值**：SnowLuma 默认 WebUI 5099、OneBot HTTP 3000、WS 3001，多开必撞。用 `SNOWLUMA_WEBUI_PORT` 指到实例的「协议端 WebUI」端口，OneBot 的 HTTP/WS 服务全关掉（我们的 AstrBot 只认反向 WS），配置里只留一条 `wsClients` 反连 `ws://127.0.0.1:<onebot>/ws`。
- **它自己会拉 QQ**：`hookAutoLoad` 默认开，进程起来会去找 `QQ.exe` 注入。测试时把 `SNOWLUMA_HOOK_AUTOLOAD=0` 打开，只验「进程能起、WebUI 能听、配置读对」，别去注入用户正在用的 QQ。
- **登录只在 QQ 窗口里**：SnowLuma 不落二维码文件，`/api/QQLogin/GetQQLoginQrcode` 给的是一串链接。所以登录页在 SnowLuma 下要换文案——给「拉起 QQ」按钮，告诉用户扫码在 QQ 里完成；别让用户对着空的二维码区等。
- **协议端切换要刷新部署步骤**：`deploy.status()["steps"]` 是 runner 初始化时从裸 `STAGES` 复制的，不带 `skip`、也不会改名；而 `stages()` 才按当前协议端算「跳过 NapCat」「启动 SnowLuma」。`status()` 每次返回前用 `stages()` 把 pending 步的 name/desc/skip 重算一遍，界面才不会显示切之前的旧步骤。


## 出厂口令（1.0.3）

- **AstrBot 的密码要提前写进配置**。AstrBot 启动时若发现 `dashboard` 既没有 `pbkdf2_password` 也没有 `password`，会自己生成 24 位随机密码打到日志里（`astrbot/core/config/astrbot_config.py` 的 `_reset_generated_dashboard_password`）。想要固定密码，就得在部署写 `cmd_config.json` 时把两套哈希一起写进去——只写 env `ASTRBOT_DASHBOARD_INITIAL_PASSWORD` 也能生效，但它会顺手把 `password_change_required` 设成 `true`，用户登录后会被强制改密码。
- 哈希格式必须和 AstrBot 一致：`pbkdf2_sha256$600000$<salt hex>$<digest hex>`，salt 16 字节，迭代 60 万次；md5 那套是兼容旧登录路径的兜底，两套都写。
- **出厂值集中放 `paths.py`**（`DEFAULT_DASHBOARD_PASSWORD` / `DEFAULT_ONEBOT_TOKEN` / `DEFAULT_NAPCAT_SECRET`），别散在各模块里当字面量；`creds.py` 只引用常量，并保留老密码 `astrbot` 的识别，老配置仍能显示明文。
- 已经有密码的配置绝不覆盖（用户改过的密码不能被一次部署抹掉）。判断依据就是 `dashboard` 里两个哈希是否都为空。
- NapCat 的 WebUI 令牌：`NAPCAT_WEBUI_SECRET_KEY` 传 `zhuxin` 会原样写进 `webui.json`；但传空或 `napcat` 会被 NapCat 随机化，所以 `_child_env` 里必须兜底成出厂值。
- 验证密码别只在自家代码里闭环：把 AstrBot 自己的 `astrbot/core/utils/auth_password.py` 用 `importlib` 直接加载，调 `verify_dashboard_password` 才算数（该文件不 import 第三方包，能被单独加载）。
- 真正落地要起一次 AstrBot：用实例的 `stack/venv/Scripts/python.exe main.py`，env 给 `ASTRBOT_ROOT` 与 `DASHBOARD_PORT`，等 `/api/v1/openapi.json` 起来后打 `POST /api/auth/login`（`{"username":"astrbot","password":"Astrbot123"}`）应返回 200 + token，错密码应 401。改过凭据的老实例要重启 AstrBot / NapCat 才生效（配置是启动时读的）。

## 部署页与协议端（1.0.4）

- **内部状态字段别叫 `ok`**。接口习惯用 `{"ok": True, **payload}` 做信封，payload 里再有一个 `ok`（「上一次部署成不成功」）就会把信封覆盖成 `false`；前端 `if (!res.ok) return` 会安静地跳过更新，表现成「接口明明返回了新数据，页面就是不刷新」。部署结果字段现在叫 `lastOk`。排查这类问题的最快路径是在页面上下文里 `const m = await import('/js/store.js')`，直接打印 `m.store.deploy` 并手动 `await m.refreshDeploy()` 看返回值——比盯 DOM 快得多。
- **新打开的页面不要回放历史事件**。EventBus 的 `since=0` 语义是「我不知道进度」，把 `deque` 里最近 50 条全倒给它，等于用旧的部署快照覆盖 bootstrap 刚给的当下状态（切过协议端就会看到旧步骤名）。只有 `since > 0`（断线重连带上次 seq）才该补增量，SSE 与 `/api/events/poll` 两条路都要按这个约定。
- **页面自己拉一次再画**。路由的 `update(store, reason)` 依赖 store 被 patch；刷新请求可能比页面登记订阅更早返回，光靠事件会漏。挂载时主动 `await ctx.refreshDeploy()` 再 `renderSteps()`，并在 `reason === 'instances'`（刚改过协议端）时同时改文案和重拉。
