from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("c:" + m.text) if m.type == "error" else None)
    pg.goto("http://127.0.0.1:17661/#/deploy", wait_until="networkidle")
    pg.wait_for_timeout(900)
    # 注入一个假的部署中状态，验证进度条渲染
    pg.evaluate("""async () => {
      const m = await import('/js/store.js');
      m.patch({ deploy: {
        running: true, finished: false, ok: false, dryRun: false,
        current: 'napcat', message: '下载 NapCat 42.3 MB / 120.0 MB',
        startedAt: Math.floor(Date.now()/1000) - 12, finishedAt: 0,
        progress: { key: 'napcat', received: 44300000, total: 125829120, percent: 35.2, speed: 3.7, text: '下载 NapCat 42.3 MB / 120.0 MB' },
        steps: [
          {key:'env',name:'环境检查',desc:'',status:'done',detail:'数据目录 C:\\\\Users\\\\zjh19\\\\DSH\\\\astrbot-pc\\\\.devdata；网络可达',ms:391},
          {key:'dirs',name:'准备目录',desc:'',status:'done',detail:'已准备 stack',ms:0},
          {key:'napcat',name:'获取 NapCat',desc:'',status:'running',detail:'下载 NapCat 42.3 MB / 120.0 MB',ms:0},
          {key:'astrbot',name:'获取 AstrBot',desc:'',status:'pending',detail:'',ms:0},
          {key:'deps',name:'安装依赖',desc:'',status:'pending',detail:'',ms:0},
          {key:'config',name:'写入配置',desc:'',status:'pending',detail:'',ms:0},
          {key:'napcat-run',name:'启动 NapCat',desc:'',status:'pending',detail:'',ms:0},
          {key:'astrbot-run',name:'启动 AstrBot',desc:'',status:'pending',detail:'',ms:0}
        ]
      }}, 'deploy');
    }""")
    pg.wait_for_timeout(600)
    pg.screenshot(path=r"C:\Users\zjh19\DSH\astrbot-pc\.devdata\shots\deploy_progress.png", clip={"x": 240, "y": 120, "width": 900, "height": 520})
    print("errs:", errs[:5])
    b.close()
