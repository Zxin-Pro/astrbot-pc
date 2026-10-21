/** 入口：建路由、连事件流、维护顶栏与侧栏状态。 */

import { api, LiveLink } from './api.js';
import { icon } from './icons.js';
import { palette, notify, updateNotesModal } from './components.js';
import { Router, ROUTES } from './router.js';
import {
  store, subscribe, bootstrap, patch,
  refreshState, refreshDeploy, refreshInstances, refreshBackups, saveSetting, runningCount, servicesList,
} from './store.js';
import { esc, dur, num } from './util.js';
import { bootGlass, syncGlass } from './glass.js';

/* ---------------------------------------------------------------- 玻璃质感 */

// 首帧就定下来，避免「先实色再变玻璃」闪一下。
bootGlass();

/* ---------------------------------------------------------------- 主题 */

const THEME_KEY = 'dsh.theme';

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
  const btn = document.getElementById('btn-theme');
  if (btn) btn.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon', 16);
  document.querySelector('meta[name="color-scheme"]')?.setAttribute('content', theme === 'dark' ? 'dark' : 'light');
  document.dispatchEvent(new CustomEvent('themechange'));
}

function initTheme() {
  const saved = localStorage.getItem(THEME_KEY);
  const follow = saved ? false : window.matchMedia('(prefers-color-scheme: dark)').matches;
  applyTheme(saved || (follow ? 'dark' : 'light'));
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (localStorage.getItem(THEME_KEY)) return;
    applyTheme(e.matches ? 'dark' : 'light');
  });
  document.getElementById('btn-theme').addEventListener('click', () => {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
    saveSetting({ app: { theme: next, followSystem: false } });
  });
}

/* ---------------------------------------------------------------- 侧栏 */

function buildNav() {
  const primary = document.getElementById('nav-primary');
  const secondary = document.getElementById('nav-secondary');
  primary.innerHTML = '';
  secondary.innerHTML = '';
  for (const r of ROUTES) {
    const a = document.createElement('a');
    a.className = 'nav-item';
    a.href = `#/${r.key}`;
    a.dataset.key = r.key;
    a.innerHTML = `${icon(r.icon, 17)}<span>${r.title}</span><i class="nav-badge" data-badge="${r.key}" hidden></i>`;
    a.title = r.title;
    (r.group === 'primary' ? primary : secondary).appendChild(a);
  }
}

function markNav(key) {
  document.querySelectorAll('.nav-item').forEach((el) => {
    el.classList.toggle('is-active', el.dataset.key === key);
  });
  const route = ROUTES.find((r) => r.key === key);
  const crumb = document.getElementById('crumb');
  if (crumb && route) crumb.textContent = route.title;
  document.title = `${route ? route.title : '概览'} · 烛之控制台`;
}

function setBadge(key, text, tone = '') {
  const el = document.querySelector(`[data-badge="${key}"]`);
  if (!el) return;
  if (!text) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = text;
  el.className = `nav-badge ${tone ? `nav-badge--${tone}` : ''}`;
}

/* ---------------------------------------------------------------- 状态卡 */

function renderHealth() {
  const dot = document.getElementById('health-dot');
  const title = document.getElementById('health-title');
  const desc = document.getElementById('health-desc');
  const bar = document.getElementById('health-bar');
  const btn = document.getElementById('btn-quick-start');
  if (!dot) return;

  if (!store.ready) {
    dot.className = 'health-dot';
    title.textContent = '正在连接';
    desc.textContent = store.error || '等待本地服务响应…';
    bar.style.width = '12%';
    if (btn) btn.textContent = '重试';
    return;
  }

  const list = servicesList();
  const run = runningCount();
  const total = list.length || 2;
  const ready = store.env?.ready;

  dot.className = `health-dot ${run === total ? 'is-ok' : run > 0 ? 'is-warn' : 'is-bad'}`;
  if (run === total) {
    title.textContent = '一切正常';
    desc.textContent = `机器人在线，已运行 ${dur(longestUptime())}`;
  } else if (run > 0) {
    title.textContent = '部分运行';
    desc.textContent = `${run}/${total} 个服务在跑，点开看看谁停了`;
  } else {
    title.textContent = ready ? '未启动' : '环境不全';
    desc.textContent = ready ? '点下面按钮把服务拉起来' : '还有组件没装好，去「部署」看看';
  }
  bar.style.width = `${Math.max(6, (run / total) * 100)}%`;
  if (btn) btn.textContent = run === total ? '重新检查' : '一键启动';

  setBadge('logs', store.lastLogCount || '', '');
  const errCount = store.overview?.today?.errors || 0;
  setBadge('logs', errCount ? String(errCount) : '', 'warn');
  setBadge('deploy', store.deploy?.running ? '···' : '', 'brand');
  setBadge('settings', store.update?.newer ? '新' : '', 'brand');
}

/* ---------------------------------------------------------------- 更新提示 */

function renderUpdate() {
  const u = store.update;
  const btn = document.getElementById('btn-update');
  if (!btn) return;
  const has = !!u?.newer;
  btn.hidden = !has;
  if (has) {
    btn.title = `有新版本 v${u.latest}（当前 v${u.current}），点开看更新内容`;
    btn.innerHTML = `${icon('sparkles', 14)}<span>新版 v${esc(u.latest)}</span>`;
    btn.onclick = () => updateNotesModal(u);
  } else {
    btn.onclick = null;
  }
}

function longestUptime() {
  return servicesList().reduce((a, s) => Math.max(a, s.uptime || 0), 0);
}

/* ---------------------------------------------------------------- 刷新 */

function makeCtx(router) {
  return {
    store,
    go: (key, opts) => router.go(key, opts),
    async refresh() {
      await Promise.all([refreshState(), refreshDeploy()]);
      renderHealth();
    },
    async refreshDeploy() {
      await refreshDeploy();
    },
    async refreshInstances() {
      await refreshInstances();
    },
    async refreshBackups() {
      await refreshBackups();
    },
    async saveSetting(patchObj) {
      const res = await saveSetting(patchObj);
      if (res.ok && patchObj.app) {
        const t = res.config?.app?.theme;
        if (t && !localStorage.getItem(THEME_KEY)) applyTheme(t);
      }
      return res;
    },
  };
}

/* ---------------------------------------------------------------- 快捷面板 */

function openPalette(router) {
  const items = [
    ...ROUTES.map((r) => ({
      label: r.title,
      hint: r.group === 'primary' ? '工作台' : '数据与设置',
      group: '页面',
      icon: r.icon,
      run: () => router.go(r.key, { force: true }),
    })),
    {
      label: '全部启动',
      hint: '把两个服务都拉起来',
      group: '动作',
      icon: 'play',
      run: async () => {
        const res = await api.service('all', 'start');
        res.ok ? notify.ok('已发出启动指令') : notify.error(res.err || '启动失败');
        refreshState();
      },
    },
    {
      label: '全部停止',
      hint: '机器人下线',
      group: '动作',
      icon: 'stop',
      run: async () => {
        const res = await api.service('all', 'stop');
        res.ok ? notify.warn('已发出停止指令') : notify.error(res.err || '停止失败');
        refreshState();
      },
    },
    {
      label: '立即备份',
      hint: '打包当前数据',
      group: '动作',
      icon: 'archive',
      run: async () => {
        notify.info('正在打包…');
        const res = await api.backupCreate('快捷备份');
        res.ok ? notify.ok('备份完成') : notify.error(res.err || '备份失败');
        refreshBackups();
      },
    },
    {
      label: '打开数据目录',
      hint: '在资源管理器里打开',
      group: '动作',
      icon: 'folder',
      run: () => api.open('data'),
    },
    {
      label: '打开 AstrBot 控制台',
      hint: '浏览器打开 6185',
      group: '动作',
      icon: 'external',
      run: () => api.open('webui'),
    },
    {
      label: '切换深浅色',
      hint: '切换界面配色',
      group: '动作',
      icon: 'sun',
      run: () => document.getElementById('btn-theme').click(),
    },
  ];
  palette(items);
}

/* ---------------------------------------------------------------- 启动 */

async function main() {
  initTheme();
  buildNav();

  const host = document.getElementById('page-host');
  host.innerHTML = `
    <div class="page">
      <div class="boot">
        <div class="boot__mark">烛</div>
        <div class="boot__text">
          <strong>正在连接本地服务</strong>
          <span>马上就好</span>
        </div>
        <span class="spinner spinner--lg"></span>
      </div>
    </div>`;

  const ctx = makeCtx(null);
  const router = new Router(host, ctx);
  ctx.go = (key, opts) => router.go(key, opts);
  router.onChange = (key) => markNav(key);

  let pendingReason = null;
  let flushTimer = 0;
  subscribe((s, reason) => {
    if (reason === 'log') {
      if (s.lastLog) router.push(s, 'log');
      return;
    }
    if (pendingReason === 'deploy' && reason === 'status') return;
    pendingReason = reason;
    if (flushTimer) return;
    flushTimer = requestAnimationFrame(() => {
      const r = pendingReason;
      pendingReason = null;
      flushTimer = 0;
      router.push(store, r);
      renderHealth();
      renderUpdate();
    });
  });

  await bootstrap();

  syncGlass(store.config?.app?.glass);

  if (!store.ready) {
    notify.error(store.error || '读取启动数据失败');
    host.innerHTML = `
      <div class="page">
        <div class="empty">
          <div class="empty__icon" aria-hidden="true">${icon('alert', 28)}</div>
          <strong>连不上本地服务</strong>
          <p>${esc(store.error || '请确认程序还在运行')}</p>
          <button class="btn btn--primary" onclick="location.reload()">重新连接</button>
        </div>
      </div>`;
    return;
  }

  document.getElementById('app').classList.add('is-ready');
  renderHealth();
  renderUpdate();
  api.health().then((res) => {
    if (res.ok && res.ports) patch({ ports: res.ports }, 'state');
  });
  await router.fromHash();

  const link = new LiveLink((evt) => {
    if (!evt) return;
    switch (evt.kind) {
      case 'status':
        patch({ services: evt.data?.services || store.services }, 'state');
        break;
      case 'log':
        patch(
          {
            lastLog: evt.data,
            lastLogCount: (store.lastLogCount || 0) + (evt.data?.lines?.length || 0),
          },
          'log',
        );
        break;
      case 'deploy':
        patch({ deploy: evt.data }, 'deploy');
        break;
      case 'notice': {
        const d = evt.data || {};
        const kind = d.level === 'error' ? 'error' : d.level === 'warn' ? 'warn' : 'info';
        notify[kind](d.text || '有新的提示');
        break;
      }
      default:
        break;
    }
  });
  link.start();

  // 轮询兜底：事件流安静太久时主动拉一次状态
  let lastActivity = Date.now();
  subscribe(() => { lastActivity = Date.now(); });
  setInterval(() => {
    if (Date.now() - lastActivity > 15000 && document.visibilityState === 'visible') {
      refreshState();
      renderHealth();
    }
  }, 5000);

  document.getElementById('btn-palette').addEventListener('click', () => openPalette(router));
  // 设置页里点完「检查更新」会派发这个事件，标题栏的版本 chip 跟着刷新
  document.addEventListener('update-state', renderUpdate);

  document.getElementById('btn-quick-start').addEventListener('click', async () => {
    const btn = document.getElementById('btn-quick-start');
    if (runningCount() === servicesList().length && store.ready) {
      await refreshState();
      renderHealth();
      notify.ok('状态已刷新');
      return;
    }
    btn.disabled = true;
    btn.textContent = '正在启动…';
    const res = await api.service('all', 'start');
    btn.disabled = false;
    renderHealth();
    if (res.ok) notify.ok('已发出启动指令，稍等几秒');
    else notify.error(res.err || '启动失败');
  });

  document.querySelectorAll('[data-win]').forEach((b) => {
    b.addEventListener('click', () => {
      if (window.pywebview?.api?.win) window.pywebview.api.win(b.dataset.win);
      else if (b.dataset.win === 'close') window.close();
    });
  });

  // 只有跑在 pywebview 窗口里才显示自绘的窗口按钮。
  // pywebviewready 可能比这里先触发，所以先看一次注入结果，再挂监听。
  function markShell() {
    document.body.classList.remove('no-shell');
  }
  if (window.pywebview?.api) {
    markShell();
  } else {
    window.addEventListener('pywebviewready', markShell, { once: true });
  }

  document.addEventListener('keydown', (e) => {
    const meta = e.ctrlKey || e.metaKey;
    if (meta && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openPalette(router);
      return;
    }
    if (meta && e.key.toLowerCase() === 'r' && !e.shiftKey) {
      e.preventDefault();
      refreshState().then(renderHealth);
      return;
    }
    if (meta && /^[1-9]$/.test(e.key)) {
      e.preventDefault();
      const r = ROUTES[Number(e.key) - 1];
      if (r) router.go(r.key);
      return;
    }
    if (e.key === 'Escape') {
      document.querySelector('.modal-backdrop')?.click();
    }
  });

  window.addEventListener('error', (e) => {
    console.error('[未捕获]', e.error || e.message);
  });
  window.addEventListener('unhandledrejection', (e) => {
    console.error('[未处理的 Promise]', e.reason);
  });

  setInterval(() => {
    refreshState();
    api.health().then((res) => {
      if (res.ok && res.ports) patch({ ports: res.ports }, 'state');
    });
    if (router.current === 'deploy') refreshDeploy();
  }, 10000);
}

main().catch((err) => {
  console.error(err);
  document.getElementById('page-host').innerHTML = `
    <div class="page"><div class="empty">
      <strong>界面启动失败</strong>
      <p class="mono">${esc(String(err?.message || err))}</p>
    </div></div>`;
});
