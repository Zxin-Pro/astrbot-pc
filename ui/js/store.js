/** 全局状态：一份内存对象 + 订阅通知，页面按需取用。 */

import { api } from './api.js';

const listeners = new Set();

export const store = {
  ready: false,
  boot: null,
  services: {},
  overview: null,
  deploy: null,
  stages: [],
  instances: [],
  backups: { items: [], count: 0, bytes: 0 },
  logs: [],
  config: {},
  env: null,
  app: null,
  update: null,
  live: false,
  error: '',
  partial: false,
};

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function emit(reason = 'update') {
  for (const fn of listeners) {
    try {
      fn(store, reason);
    } catch (e) {
      console.error('订阅者出错', e);
    }
  }
}

export function patch(obj, reason = 'update') {
  Object.assign(store, obj);
  emit(reason);
}

/** 首屏：一次拿全，减少瀑布请求 */
export async function bootstrap() {
  const res = await api.bootstrap();
  if (!res.ok) {
    store.error = res.err || '无法读取启动数据';
    store.partial = true;
    emit('error');
    return res;
  }
  Object.assign(store, {
    boot: res,
    app: res.app,
    config: res.config || {},
    env: res.env,
    services: res.services || {},
    overview: res.overview,
    deploy: res.deploy,
    stages: res.stages || [],
    instances: res.instances || [],
    backups: res.backups || { items: [], count: 0, bytes: 0 },
    ready: true,
    error: '',
    partial: false,
    server: res.server,
    version: res.version,
    update: res.update || null,
  });
  emit('bootstrap');

  // 体检在后台预热，首屏不等它；拿回来再补一次
  if (store.env?.pending) {
    api.env().then((r) => {
      if (r.ok && r.env) patch({ env: r.env }, 'env');
    }).catch(() => {});
  }

  // 启动时后台会静默查一次更新，这里慢一步去取结果
  if (!store.update) {
    setTimeout(() => {
      api.update().then((r) => {
        if (r.ok && r.update) patch({ update: r.update }, 'update');
      }).catch(() => {});
    }, 1500);
  }

  return res;
}

export async function refreshState() {
  const res = await api.state();
  if (!res.ok) return res;
  patch({ services: res.services || {}, overview: res.overview || store.overview }, 'state');
  return res;
}

export async function refreshDeploy() {
  const res = await api.deployStatus();
  if (!res.ok) return res;
  patch({ deploy: res, stages: res.steps ? store.stages : store.stages }, 'deploy');
  return res;
}

export async function refreshInstances() {
  const res = await api.instances();
  if (!res.ok) return res;
  patch({ instances: res.items || [] }, 'instances');
  return res;
}

export async function refreshBackups() {
  const res = await api.backups();
  if (!res.ok) return res;
  patch({ backups: res }, 'backups');
  return res;
}

export async function refreshLogs() {
  const res = await api.logs();
  if (!res.ok) return res;
  patch({ logs: res.items || [] }, 'logs');
  return res;
}

export function servicesList() {
  const s = store.services || {};
  return ['napcat', 'astrbot'].map((k) => s[k]).filter(Boolean);
}

export function runningCount() {
  return servicesList().filter((s) => s.status === 'running').length;
}

export function getSetting(path, fallback = undefined) {
  const parts = String(path).split('.');
  let node = store.config;
  for (const p of parts) {
    if (node == null || typeof node !== 'object') return fallback;
    node = node[p];
  }
  return node === undefined ? fallback : node;
}

export async function saveSetting(patchObj) {
  const res = await api.saveSettings(patchObj);
  if (res.ok) patch({ config: res.config || store.config }, 'config');
  return res;
}
