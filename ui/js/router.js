/** 路由：八个页面，懒加载，切换时保留滚动位置。 */

export const ROUTES = [
  { key: 'dashboard', title: '概览', icon: 'dashboard', group: 'primary', load: () => import('./pages/dashboard.js') },
  { key: 'deploy', title: '部署', icon: 'rocket', group: 'primary', load: () => import('./pages/deploy.js') },
  { key: 'services', title: '服务', icon: 'server', group: 'primary', load: () => import('./pages/services.js') },
  { key: 'logs', title: '日志', icon: 'terminal', group: 'primary', load: () => import('./pages/logs.js') },
  { key: 'login', title: '登录', icon: 'qrcode', group: 'primary', load: () => import('./pages/login.js') },
  { key: 'instances', title: '实例', icon: 'layers', group: 'secondary', load: () => import('./pages/instances.js') },
  { key: 'backups', title: '备份', icon: 'archive', group: 'secondary', load: () => import('./pages/backups.js') },
  { key: 'settings', title: '设置', icon: 'settings', group: 'secondary', load: () => import('./pages/settings.js') },
];

export const ROUTE_MAP = new Map(ROUTES.map((r) => [r.key, r]));

export class Router {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.current = null;
    this.view = null;
    this.scrolls = new Map();
    this.token = 0;
    window.addEventListener('hashchange', () => this.fromHash());
  }

  parse(hash) {
    const raw = (hash || window.location.hash || '').replace(/^#\/?/, '');
    const key = raw.split('?')[0].split('/')[0];
    return ROUTE_MAP.has(key) ? key : 'dashboard';
  }

  async go(key, opts = {}) {
    if (!ROUTE_MAP.has(key)) key = 'dashboard';
    if (key === this.current && !opts.force) return;
    const token = ++this.token;
    const route = ROUTE_MAP.get(key);

    if (this.current) {
      const el = this.host.querySelector('.page');
      if (el) this.scrolls.set(this.current, this.host.scrollTop || el.scrollTop || 0);
    }
    if (this.view?.destroy) {
      try { this.view.destroy(); } catch { /* 页面已经卸载 */ }
    }
    this.view = null;

    if (window.location.hash !== `#/${key}`) {
      history.replaceState(null, '', `#/${key}`);
    }

    this.host.classList.add('is-loading');
    let mod;
    try {
      mod = await route.load();
    } catch (err) {
      this.host.classList.remove('is-loading');
      this.fail(key, err);
      return;
    }
    if (token !== this.token) return;

    this.current = key;
    this.host.innerHTML = '';
    this.host.classList.remove('is-loading');
    const root = document.createElement('div');
    root.className = 'route-root';
    this.host.appendChild(root);

    try {
      this.view = mod.mount(root, this.ctx) || null;
    } catch (err) {
      this.fail(key, err);
      return;
    }

    requestAnimationFrame(() => {
      const saved = this.scrolls.get(key) || 0;
      this.host.scrollTop = saved;
      root.classList.add('is-enter');
      setTimeout(() => root.classList.remove('is-enter'), 420);
    });

    document.documentElement.dataset.route = key;
    this.onChange?.(key, route);
  }

  fromHash() {
    this.go(this.parse(), { force: true });
  }

  push(store, reason) {
    if (!this.view?.update) return;
    try {
      this.view.update(store, reason);
    } catch (err) {
      console.error('[router] update failed', err);
    }
  }

  fail(key, err) {
    console.error(`[router] 加载 ${key} 失败`, err);
    this.host.innerHTML = `
      <div class="page">
        <div class="empty">
          <div class="empty__icon">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.2"/><circle cx="12" cy="16.4" r="1" fill="currentColor" stroke="none"/></svg>
          </div>
          <strong>这个页面没加载出来</strong>
          <p>${String(err?.message || err || '未知错误')}</p>
          <button class="btn btn--primary" onclick="location.reload()">重新载入界面</button>
        </div>
      </div>`;
  }
}
