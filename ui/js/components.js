/** 通用交互组件：toast、modal、确认框、命令面板。 */

import { icon } from './icons.js';
import { esc, h, qs } from './util.js';

/* ------------------------------ toast ------------------------------ */

const ICONS = { ok: 'check', warn: 'alert', error: 'xcircle', info: 'info' };

export function toast(text, kind = 'info', ms = 3200) {
  const host = qs('#toasts');
  if (!host) return;
  const el = h(`
    <div class="toast toast--${esc(kind)}" role="status">
      <span class="toast__icon">${icon(ICONS[kind] || 'info', 16)}</span>
      <div class="toast__text">${esc(text)}</div>
      <button class="toast__close" aria-label="关闭">${icon('x', 14)}</button>
    </div>`);
  const close = () => {
    el.classList.add('is-out');
    setTimeout(() => el.remove(), 200);
  };
  el.querySelector('.toast__close').addEventListener('click', close);
  host.appendChild(el);
  if (ms > 0) setTimeout(close, ms);
  while (host.children.length > 4) host.firstElementChild.remove();
}

export const notify = {
  ok: (t, ms) => toast(t, 'ok', ms),
  warn: (t, ms) => toast(t, 'warn', ms),
  error: (t, ms) => toast(t, 'error', ms ?? 4600),
  info: (t, ms) => toast(t, 'info', ms),
};

/* ------------------------------ modal ------------------------------ */

let openModals = 0;

export function modal({ title, desc = '', body = '', actions = [], wide = false, onMount }) {
  const root = qs('#modal-root');
  const backdrop = h(`
    <div class="modal-backdrop">
      <div class="modal ${wide ? 'modal--wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">
        <div class="modal__head">
          <h3>${esc(title)}</h3>
          ${desc ? `<p>${esc(desc)}</p>` : ''}
        </div>
        <div class="modal__body">${body}</div>
        <div class="modal__foot"></div>
      </div>
    </div>`);
  const foot = backdrop.querySelector('.modal__foot');
  const close = () => {
    backdrop.remove();
    openModals -= 1;
    document.removeEventListener('keydown', onKey);
  };
  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  };

  actions.forEach((a) => {
    const btn = h(`<button class="btn ${a.primary ? 'btn--primary' : ''} ${a.danger ? 'btn--danger' : ''}">${esc(a.label)}</button>`);
    btn.addEventListener('click', async () => {
      // a.run 是后加的写法：返回 false 表示「别关」，方便表单校验失败时留在弹层里。
      const run = a.run || a.onClick;
      if (!run) {
        close();
        return;
      }
      btn.disabled = true;
      try {
        // 老页面写的是 run(close, rootEl)，新页面可以写 run({root,close})。
        const keep = a.run ? await a.run(close, backdrop) : await a.onClick({ root: backdrop, close });
        if (keep !== false) close();
      } catch (err) {
        console.error('[modal] action failed', err);
      } finally {
        btn.disabled = false;
      }
    });
    foot.appendChild(btn);
  });

  if (!actions.length) {
    const btn = h('<button class="btn btn--primary">关闭</button>');
    btn.addEventListener('click', close);
    foot.appendChild(btn);
  }

  backdrop.addEventListener('mousedown', (e) => {
    if (e.target === backdrop) close();
  });
  document.addEventListener('keydown', onKey);
  root.appendChild(backdrop);
  openModals += 1;

  const focusable = backdrop.querySelector('input, textarea, select, button.btn--primary') || foot.lastElementChild;
  setTimeout(() => focusable?.focus?.(), 40);

  if (onMount) onMount({ root: backdrop, close });
  return { close, root: backdrop };
}

export function confirmDialog({ title, desc, confirm = '确定', cancel = '取消', danger = false }) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({
      title,
      desc,
      body: '',
      actions: [
        { label: cancel },
        {
          label: confirm,
          primary: !danger,
          danger,
          onClick: () => {
            done = true;
            resolve(true);
          },
        },
      ],
    });
    const obs = new MutationObserver(() => {
      if (!document.body.contains(m.root) && !done) {
        obs.disconnect();
        resolve(false);
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  });
}

/* ------------------------------ 更新说明 ------------------------------ */

/** 更新说明弹层：标题栏的版本 chip 和设置页「看更新内容」共用。 */
export function updateNotesModal(u) {
  if (!u || !u.newer) return;
  const body = `
    <div class="update-notes">
      <div class="update-notes__meta">
        <span class="pill pill--ok">v${esc(u.current)}</span>
        ${icon('arrowRight', 14)}
        <span class="pill pill--brand">v${esc(u.latest)}</span>
        ${u.publishedAt ? `<span class="muted" style="font-size:12px">发布于 ${esc(String(u.publishedAt).slice(0, 10))}</span>` : ''}
      </div>
      <pre class="update-notes__body">${esc(u.notes || '这次没有写更新说明，去发布页看看。')}</pre>
    </div>`;
  modal({
    title: `新版本 v${u.latest}`,
    desc: '更新包在 GitHub 发布页，下载后覆盖安装即可，数据目录不受影响。',
    body,
    wide: true,
    actions: [
      { label: '稍后' },
      {
        label: '去下载',
        primary: true,
        onClick: () => {
          if (u.url) window.open(u.url, '_blank');
        },
      },
    ],
  });
}

/* ------------------------------ 命令面板 ------------------------------ */

export function palette(items) {
  const root = qs('#palette-root');
  let active = 0;
  let filtered = items.slice();

  const wrap = h(`
    <div class="palette-backdrop">
      <div class="palette" role="dialog" aria-modal="true" aria-label="快速跳转">
        <input class="palette__input" placeholder="跳到某一页，或输入动作…" aria-label="搜索">
        <div class="palette__list" role="listbox"></div>
        <div class="palette__foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>↵</kbd> 进入</span>
          <span><kbd>Esc</kbd> 关闭</span>
        </div>
      </div>
    </div>`);
  const input = wrap.querySelector('.palette__input');
  const list = wrap.querySelector('.palette__list');

  const close = () => {
    wrap.remove();
    document.removeEventListener('keydown', onKey, true);
  };

  const draw = () => {
    if (!filtered.length) {
      list.innerHTML = '<div class="palette__empty">没有匹配的条目</div>';
      return;
    }
    let lastGroup = '';
    list.innerHTML = filtered.map((it, i) => {
      const head = it.group && it.group !== lastGroup
        ? `<div class="palette__group">${esc(it.group)}</div>`
        : '';
      lastGroup = it.group || lastGroup;
      return `${head}
          <button class="palette__item ${i === active ? 'is-active' : ''}" role="option" aria-selected="${i === active}" data-i="${i}">
            ${icon(it.icon || 'chevron', 16)}
            <span>${esc(it.label)}</span>
            ${it.hint ? `<small>${esc(it.hint)}</small>` : ''}
          </button>`;
    }).join('');
  };

  const run = (i) => {
    const it = filtered[i];
    if (!it) return;
    close();
    it.run();
  };

  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      close();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      active = Math.min(filtered.length - 1, active + 1);
      draw();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      active = Math.max(0, active - 1);
      draw();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      run(active);
    }
  };

  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    filtered = q
      ? items.filter((it) => (it.label + ' ' + (it.hint || '')).toLowerCase().includes(q))
      : items.slice();
    active = 0;
    draw();
  });

  list.addEventListener('click', (e) => {
    const el = e.target.closest('.palette__item');
    if (el) run(Number(el.dataset.i));
  });

  wrap.addEventListener('mousedown', (e) => {
    if (e.target === wrap) close();
  });

  document.addEventListener('keydown', onKey, true);
  root.innerHTML = '';
  root.appendChild(wrap);
  draw();
  setTimeout(() => input.focus(), 30);
}

export function modalOpen() {
  return openModals > 0;
}
