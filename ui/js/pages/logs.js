/** 日志：定位问题的地方。跟随、过滤、搜索、导出。 */

import { api } from '../api.js';
import { confirmDialog, notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, bytes, debounce, copyText, timeAgo } from '../util.js';
import { pageHead } from './common.js';

const MAX_ROWS = 3000;

export function mount(root, ctx) {
  const state = {
    files: [],
    path: '',
    lines: [],
    levels: [],
    follow: true,
    autoScroll: true,
    level: 'all',
    query: '',
    size: 0,
    loading: false,
  };

  root.innerHTML = `
    <div class="page page--flush">
      ${pageHead({
        title: '日志',
        desc: '所有输出都落在这台电脑上，随时可以翻回去看。',
        actions: `
          <button class="btn" data-act="download" title="下载当前日志文件">${icon('download', 15)}下载</button>
          <button class="btn" data-act="clearfile" title="清空当前日志的内容，保留文件">${icon('trash', 15)}清空</button>
          <button class="btn" data-act="deletefile" title="删除当前日志文件">${icon('x', 15)}删除</button>
          <button class="btn" data-act="copy">${icon('copy', 15)}复制全部</button>`,
      })}

      <div class="log-toolbar">
        <div class="select-wrap">
          <select class="select select--sm" id="file-pick" aria-label="选择日志文件"></select>
        </div>
        <div class="segmented segmented--sm" id="level-seg" role="tablist" aria-label="过滤级别">
          <button class="segmented__item is-active" data-level="all">全部</button>
          <button class="segmented__item" data-level="warn">警告</button>
          <button class="segmented__item" data-level="error">错误</button>
        </div>
        <label class="search search--sm">
          ${icon('search', 15)}
          <input type="search" id="log-search" placeholder="搜索关键字" autocomplete="off" />
        </label>
        <div class="grow"></div>
        <label class="switch switch--inline" title="新日志自动出现在底部">
          <input type="checkbox" id="follow-toggle" checked>
          <span class="switch__track"></span>
          <span class="switch__label">跟随</span>
        </label>
        <span class="tag" id="meta-size" hidden></span>
      </div>

      <div class="log-shell">
        <div class="log-bar">
          <span class="live-dot" id="live-dot" aria-hidden="true"></span>
          <span id="log-path" class="mono truncate">选择左侧日志文件</span>
          <div class="grow"></div>
          <span class="muted" id="log-count">0 行</span>
          <button class="icon-btn icon-btn--sm" id="btn-bottom" title="跳到最新">${icon('chevronDown', 15)}</button>
        </div>
        <div class="log-body" id="log-body" tabindex="0" aria-live="off"></div>
      </div>
    </div>`;

  const body = root.querySelector('#log-body');
  const pick = root.querySelector('#file-pick');
  const pathEl = root.querySelector('#log-path');
  const countEl = root.querySelector('#log-count');
  const sizeEl = root.querySelector('#meta-size');
  const liveDot = root.querySelector('#live-dot');
  const followToggle = root.querySelector('#follow-toggle');
  const searchInput = root.querySelector('#log-search');

  function rowHtml(text, level) {
    const lv = level || 'info';
    return `<div class="log-line is-${lv}"><span class="log-line__lv">${lv === 'error' ? 'ERR' : lv === 'warn' ? 'WRN' : lv === 'debug' ? 'DBG' : 'INF'}</span><span class="log-line__txt mono">${esc(text)}</span></div>`;
  }

  function visible() {
    const q = state.query.trim().toLowerCase();
    const out = [];
    for (let i = 0; i < state.lines.length; i++) {
      const text = state.lines[i];
      const lv = state.levels[i] || 'info';
      if (state.level === 'error' && lv !== 'error') continue;
      if (state.level === 'warn' && lv !== 'warn' && lv !== 'error') continue;
      if (q && !text.toLowerCase().includes(q)) continue;
      out.push([text, lv]);
    }
    return out;
  }

  function emptyHtml(title, hint) {
    return `<div class="log-empty">
      <span class="log-empty__ico" aria-hidden="true">${icon('file', 22)}</span>
      <p>${title}</p>
      <span>${hint}</span>
    </div>`;
  }

  function paint(forceBottom) {
    const rows = visible();
    if (!state.path) {
      body.innerHTML = state.files.length
        ? emptyHtml('选一个日志文件', '左上角的下拉里有 NapCat 与 AstrBot 的输出')
        : emptyHtml('还没有日志文件', '启动 NapCat 或 AstrBot 之后，输出会自动出现在这里');
      countEl.textContent = '0 行';
      return;
    }
    if (!rows.length) {
      body.innerHTML = emptyHtml(
        state.query ? '没有匹配的行' : state.level !== 'all' ? '当前筛选下没有内容' : '这个文件还是空的',
        state.query ? `换个关键字，或清空搜索框` : state.level !== 'all' ? '把筛选切回「全部」试试' : '等服务写出第一行就会自动刷新',
      );
    } else {
      body.innerHTML = rows.slice(-MAX_ROWS).map(([t, l]) => rowHtml(t, l)).join('');
    }
    countEl.textContent = `${rows.length} 行`;
    if (state.autoScroll || forceBottom) scrollBottom();
  }

  function scrollBottom() {
    body.scrollTop = body.scrollHeight;
  }

  async function loadFiles() {
    const res = await api.logs();
    if (!res.ok) {
      notify.error(res.err || '读取日志列表失败');
      return;
    }
    state.files = res.items || [];
    const keep = state.path;
    pick.innerHTML = state.files.length
      ? state.files.map((f) => {
          const label = `${f.group} · ${f.name}`;
          return `<option value="${esc(f.path)}" ${f.path === keep ? 'selected' : ''}>${esc(label)}</option>`;
        }).join('')
      : '<option value="">暂无日志文件</option>';
    if (!keep && state.files.length) {
      const first = state.files.find((f) => f.group === 'AstrBot') || state.files[0];
      pick.value = first.path;
      await selectFile(first.path);
    } else if (!state.path) {
      paint();
    }
  }

  async function selectFile(path, opts = {}) {
    if (state.path && state.follow) {
      api.logUnfollow();
    }
    state.path = path;
    pathEl.textContent = path || '未选择';
    state.lines = [];
    state.levels = [];
    state.size = 0;
    if (!path) {
      paint();
      return;
    }
    await tail(true);
    if (state.follow && !opts.silent) {
      const res = await api.logFollow(path);
      if (!res.ok) notify.warn('跟随失败，改用刷新查看');
    }
    syncDot();
  }

  async function tail(reset) {
    if (!state.path || state.loading) return;
    state.loading = true;
    const res = await api.logTail(state.path, reset ? 600 : 300, true);
    state.loading = false;
    if (!res.ok) {
      if (reset) body.innerHTML = `<div class="log-empty">读取失败：${esc(res.err || '未知错误')}</div>`;
      return;
    }
    sizeEl.textContent = bytes(res.size || 0);
    sizeEl.hidden = !res.size;
    if (reset) {
      state.lines = res.lines || [];
      state.levels = res.levels || [];
    } else {
      state.lines = state.lines.concat(res.lines || []).slice(-MAX_ROWS);
      state.levels = state.levels.concat(res.levels || []).slice(-MAX_ROWS);
    }
    paint(reset);
  }

  function syncDot() {
    liveDot.classList.toggle('is-live', !!state.follow && !!state.path);
    followToggle.checked = state.follow;
  }

  pick.addEventListener('change', () => selectFile(pick.value));

  followToggle.addEventListener('change', async () => {
    state.follow = followToggle.checked;
    if (!state.path) return;
    if (state.follow) {
      const res = await api.logFollow(state.path);
      if (!res.ok) notify.warn(res.err || '跟随失败');
    } else {
      api.logUnfollow();
    }
    syncDot();
  });

  root.querySelector('#level-seg').addEventListener('click', (e) => {
    const b = e.target.closest('[data-level]');
    if (!b) return;
    state.level = b.dataset.level;
    root.querySelectorAll('#level-seg .segmented__item').forEach((el) => el.classList.toggle('is-active', el === b));
    paint(false);
  });

  searchInput.addEventListener('input', debounce(() => {
    state.query = searchInput.value;
    paint(false);
  }, 180));

  body.addEventListener('scroll', () => {
    const near = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
    state.autoScroll = near;
  });

  root.querySelector('#btn-bottom').addEventListener('click', () => {
    state.autoScroll = true;
    scrollBottom();
  });

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    if (btn.dataset.act === 'copy') {
      const rows = visible();
      if (!rows.length) return notify.warn('没有可复制的内容');
      await copyText(rows.map((r) => r[0]).join('\r\n'));
      notify.ok(`已复制 ${rows.length} 行`);
    } else if (btn.dataset.act === 'download') {
      if (!state.path) return notify.warn('先选一个日志文件');
      window.open(`/files?kind=log&path=${encodeURIComponent(state.path)}`, '_blank');
      notify.info('已开始下载；窗口版里若没反应，点「打开目录」从磁盘拿');
    } else if (btn.dataset.act === 'clearfile') {
      if (!state.path) return notify.warn('先选一个日志文件');
      const ok = await confirmDialog({
        title: '清空这个日志？',
        desc: '只清掉内容，文件本身保留 —— 服务还在写这个文件，删了它只会写进虚空。',
        confirm: '清空',
        danger: true,
      });
      if (!ok) return;
      const res = await api.logClear(state.path);
      if (!res.ok) return notify.error(res.err || '清空失败');
      notify.ok(`已清空，腾出 ${bytes(res.freed || 0)}`);
      await tail(true);
    } else if (btn.dataset.act === 'deletefile') {
      if (!state.path) return notify.warn('先选一个日志文件');
      const ok = await confirmDialog({
        title: '删除这个日志文件？',
        desc: '文件会从磁盘上删掉，删之前先停止正在写它的服务更稳妥。',
        confirm: '删除',
        danger: true,
      });
      if (!ok) return;
      api.logUnfollow();
      const res = await api.logDelete(state.path);
      if (!res.ok) return notify.error(res.err || '删除失败');
      state.path = '';
      state.lines = [];
      state.levels = [];
      pathEl.textContent = '未选择';
      await loadFiles();
      paint();
      notify.ok('已删除');
    }
  });

  (async () => {
    await loadFiles();
    if (ctx.store.config?.logs?.follow === false) {
      state.follow = false;
      syncDot();
    }
  })();

  return {
    update(store, reason) {
      if (reason !== 'log') return;
      const msg = store.lastLog;
      if (!msg) return;
      if (msg.path && msg.path !== state.path) return;
      if (msg.replace) {
        state.lines = msg.lines || [];
        state.levels = msg.levels || [];
      } else {
        state.lines = state.lines.concat(msg.lines || []).slice(-MAX_ROWS);
        state.levels = state.levels.concat(msg.levels || []).slice(-MAX_ROWS);
      }
      if (msg.size) {
        sizeEl.textContent = bytes(msg.size);
        sizeEl.hidden = false;
      }
      paint(false);
    },
    destroy() {
      api.logUnfollow();
    },
  };
}
