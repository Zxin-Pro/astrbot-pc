/** 接口封装：统一错误处理，永远返回后端那一套 {ok, ...} 结构。 */

const BASE = '';

async function request(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(BASE + path, opt);
  } catch (e) {
    return { ok: false, err: `连接不上本地服务：${e.message}` };
  }
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    return { ok: false, err: `返回内容不是 JSON（HTTP ${res.status}）` };
  }
  if (!res.ok && data.ok !== false) {
    data.ok = false;
    data.err = data.err || `HTTP ${res.status}`;
  }
  return data;
}

export const api = {
  bootstrap: () => request('GET', '/api/bootstrap'),
  health: () => request('GET', '/api/health'),
  state: () => request('GET', '/api/state'),
  env: () => request('GET', '/api/env'),
  envCheck: () => request('GET', '/api/env/check'),

  service: (key, action) => request('POST', `/api/services/${key}/${action}`),

  deployStatus: () => request('GET', '/api/deploy/status'),
  deployStart: (dryRun) => request('POST', '/api/deploy/start', { dryRun }),
  deployCancel: () => request('POST', '/api/deploy/cancel'),

  logs: () => request('GET', '/api/logs'),
  logTail: (path, lines = 400, compact = true) =>
    request('GET', `/api/logs/tail?path=${encodeURIComponent(path)}&lines=${lines}&compact=${compact ? 1 : 0}`),
  logFollow: (path) => request('POST', '/api/logs/follow', { path }),
  logUnfollow: () => request('POST', '/api/logs/unfollow'),

  instances: () => request('GET', '/api/instances'),
  instanceCreate: (payload) => request('POST', '/api/instances', payload),
  instanceUpdate: (id, payload) => request('PATCH', `/api/instances/${encodeURIComponent(id)}`, payload),
  instanceDelete: (id) => request('DELETE', `/api/instances/${encodeURIComponent(id)}`),

  qr: () => request('GET', '/api/qr'),

  stats: (full = false) => request('GET', `/api/stats${full ? '?full=1' : ''}`),

  backups: () => request('GET', '/api/backups'),
  backupCreate: (note) => request('POST', '/api/backups', { note }),
  backupCancel: () => request('POST', '/api/backups/cancel'),
  backupImport: (payload) => request('POST', '/api/backups/import', payload),
  backupRestore: (name) => request('POST', `/api/backups/${encodeURIComponent(name)}/restore`),
  backupDelete: (name) => request('DELETE', `/api/backups/${encodeURIComponent(name)}`),
  backupOpen: () => request('POST', '/api/backups/open'),

  doctor: (force = false) => request('GET', `/api/doctor${force ? '?force=1' : ''}`),
  diagList: () => request('GET', '/api/diag'),
  diagExport: () => request('POST', '/api/diag/export'),
  diagDelete: (name) => request('DELETE', `/api/diag/${encodeURIComponent(name)}`),
  deployReset: () => request('POST', '/api/deploy/reset'),
  terminal: (payload) => request('POST', '/api/terminal/run', payload),
  storage: (force = false) => request('GET', `/api/storage${force ? '?force=1' : ''}`),
  storageClean: (what) => request('POST', '/api/storage/clean', { what }),
  crashes: () => request('GET', '/api/crashes'),
  crashesClear: () => request('DELETE', '/api/crashes'),
  logClear: (path) => request('POST', '/api/logs/clear', { path }),
  logDelete: (path) => request('DELETE', `/api/logs?path=${encodeURIComponent(path)}`),
  instanceApply: (id) => request('POST', `/api/instances/${encodeURIComponent(id)}/apply`),
  instanceActive: (id) => request('POST', `/api/instances/${encodeURIComponent(id)}/active`),
  instanceSuggest: () => request('POST', '/api/instances/suggest'),
  conflicts: () => request('GET', '/api/instances/conflicts'),
  consoleCreds: () => request('GET', '/api/console/creds'),
  consoleCredsReset: (username, password) => request('POST', '/api/console/creds', { username, password }),
  llmTest: () => request('POST', '/api/llm/test'),
  appearance: () => request('GET', '/api/appearance'),
  setBackground: (dataUrl) => request('POST', '/api/appearance/background', { dataUrl }),
  clearBackground: () => request('DELETE', '/api/appearance/background'),
  setGlassLevel: (level) => request('POST', '/api/appearance/level', { level }),
  lan: () => request('GET', '/api/lan'),

  saveSettings: (patch) => request('POST', '/api/settings', { patch }),
  resetSettings: () => request('POST', '/api/reset'),

  llm: () => request('GET', '/api/llm'),
  llmModel: (payload) => request('POST', '/api/llm/model', payload),
  llmPersona: (payload) => request('POST', '/api/llm/persona', payload),
  llmModels: (payload) => request('POST', '/api/llm/models', payload),
  relay: () => request('GET', '/api/relay'),

  openUrl: (url) => request('POST', '/api/open', { url }),

  open: (target) => request('POST', '/api/open', { target }),
  checkUpdate: () => request('GET', '/api/update/check'),
  update: () => request('GET', '/api/update'),

  poll: (seq) => request('GET', `/api/events/poll?seq=${seq}`),
};

/** 事件流：优先 SSE，断了自动降级为轮询，恢复后再切回来。 */
export class LiveLink {
  constructor(onEvent) {
    this.onEvent = onEvent;
    this.es = null;
    this.seq = 0;
    this.timer = 0;
    this.closed = false;
    this.state = 'idle';
  }

  start() {
    this.closed = false;
    this._sse();
    this._startPoll();
  }

  _sse() {
    try {
      this.es = new EventSource(`/events?since=${this.seq}`);
      this.es.onopen = () => { this.state = 'live'; };
      this.es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          this.seq = Math.max(this.seq, msg.seq || 0);
          this.onEvent(msg);
        } catch { /* 忽略坏帧 */ }
      };
      this.es.onerror = () => {
        this.state = 'degraded';
        if (this.es) {
          this.es.close();
          this.es = null;
        }
        if (!this.closed) setTimeout(() => this._sse(), 4000);
      };
    } catch {
      this.state = 'degraded';
    }
  }

  _startPoll() {
    const tick = async () => {
      if (this.closed) return;
      if (this.state !== 'live') {
        const res = await api.poll(this.seq);
        if (res.ok && Array.isArray(res.items)) {
          for (const m of res.items) {
            this.seq = Math.max(this.seq, m.seq || 0);
            this.onEvent(m);
          }
        }
      }
      this.timer = setTimeout(tick, this.state === 'live' ? 5000 : 2000);
    };
    tick();
  }

  stop() {
    this.closed = true;
    clearTimeout(this.timer);
    if (this.es) {
      this.es.close();
      this.es = null;
    }
  }
}
