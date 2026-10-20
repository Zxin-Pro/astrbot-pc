/** 备份：一键打包、一键回滚。出事时能救命，平时用来搬到另一台电脑。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, bytes, fdate, timeAgo } from '../util.js';
import { emptyState, pageHead } from './common.js';

export function mount(root, ctx) {
  let usage = null;

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '备份',
        desc: '配置、账号、插件数据打成一个压缩包，放在你自己的电脑上。',
        actions: `
          <button class="btn" data-act="open">${icon('folder', 15)}打开目录</button>
          <button class="btn btn--primary" data-act="create">${icon('archive', 15)}立即备份</button>`,
      })}

      <div class="card card--tight" id="usage-card"></div>

      <div class="section">
        <div class="section-head"><h2>备份记录 <span class="muted" id="bk-count"></span></h2></div>
        <div id="bk-list"></div>
      </div>
    </div>`;

  const listEl = root.querySelector('#bk-list');
  const usageEl = root.querySelector('#usage-card');

  function renderUsage() {
    const u = usage || ctx.store.storage || {};
    const rows = [
      { label: '配置与数据', value: Number(u.stack || 0), cls: 'brand' },
      { label: '日志', value: Number(u.logs || 0), cls: 'warm' },
      { label: '备份', value: Number(u.backups || 0), cls: 'ok' },
    ];
    usageEl.hidden = false;
    const total = rows.reduce((a, b) => a + b.value, 0);
    usageEl.innerHTML = `
      <div class="card-head" style="margin-bottom:12px">
        <h3>占用</h3>
        <span class="muted" style="font-size:12px">合计 ${bytes(total)}</span>
      </div>
      <div class="usage-bar">${total ? rows.map((r) => `<span class="usage-bar__seg usage-bar__seg--${r.cls}" style="width:${Math.max(1.5, (r.value / total) * 100)}%"></span>`).join('') : ''}</div>
      <div class="usage-legend">${rows.map((r) => `<span><i class="usage-bar__dot usage-bar__dot--${r.cls}"></i>${esc(r.label)} <b>${bytes(r.value)}</b></span>`).join('')}</div>`;
  }

  function renderList() {
    const box = ctx.store.backups || {};
    const rows = Array.isArray(box) ? box : (box.items || []);
    root.querySelector('#bk-count').textContent = rows.length ? `${rows.length} 个` : '';
    if (!rows.length) {
      listEl.innerHTML = `<div class="card">${emptyState({
        iconName: 'archive',
        title: '还没有备份',
        desc: '点右上角「立即备份」，几秒钟就能完成。',
      })}</div>`;
      return;
    }
    listEl.innerHTML = `
      <div class="card card--flush">
        <table class="table table--hover">
          <thead><tr><th>文件名</th><th>备注</th><th>大小</th><th>创建时间</th><th class="ta-r">操作</th></tr></thead>
          <tbody>${rows.map((b) => `
            <tr data-name="${esc(b.name)}">
              <td class="mono truncate" title="${esc(b.name)}">${esc(b.name)}</td>
              <td>${b.note ? esc(b.note) : '<span class="muted">—</span>'}</td>
              <td class="mono">${bytes(b.size || 0)}</td>
              <td><span title="${fdate(b.mtime)}">${timeAgo(b.mtime)}</span></td>
              <td class="ta-r">
                <button class="btn btn--sm" data-act="restore" data-name="${esc(b.name)}">恢复</button>
                <button class="icon-btn icon-btn--danger" data-act="del" data-name="${esc(b.name)}" title="删除">${icon('trash', 14)}</button>
              </td>
            </tr>`).join('')}</tbody>
        </table>
      </div>`;
  }

  renderUsage();
  renderList();

  async function create(note) {
    const res = await api.backupCreate(note);
    if (!res.ok) {
      notify.error(res.err || '备份失败');
      return;
    }
    notify.ok('备份完成');
    if (res.usage) usage = res.usage;
    await ctx.refreshBackups();
    renderUsage();
    renderList();
  }

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    const name = btn.dataset.name;

    if (act === 'open') {
      const res = await api.backupOpen();
      if (!res.ok) notify.error(res.err || '打不开');
    } else if (act === 'create') {
      const m = modal({
        title: '立即备份',
        desc: '给这次备份写个备注，方便以后挑。',
        body: `<label class="field"><span class="field__label">备注（可选）</span>
          <input class="input" name="note" placeholder="例如：装完新插件之前" maxlength="40" /></label>`,
        actions: [
          { label: '取消', variant: 'ghost', run: (close) => close() },
          {
            label: '开始备份',
            variant: 'primary',
            run: async (close, rootEl) => {
              const note = rootEl.querySelector('[name="note"]').value.trim();
              close();
              notify.info('正在打包，请稍候…');
              await create(note);
            },
          },
        ],
      });
      setTimeout(() => m.root.querySelector('[name="note"]')?.focus(), 60);
    } else if (act === 'restore') {
      const ok = await confirmDialog({
        title: '恢复这个备份？',
        desc: '会用备份里的内容覆盖当前的配置与账号数据。恢复前会自动再做一份当前状态的备份，所以不会没法回头。恢复后服务需要重启。',
        confirm: '恢复',
        danger: true,
      });
      if (!ok) return;
      btn.disabled = true;
      notify.info('正在恢复…');
      const res = await api.backupRestore(name);
      btn.disabled = false;
      if (res.ok) {
        notify.ok('已恢复，建议重启服务');
        await ctx.refresh();
        await ctx.refreshBackups();
        renderList();
      } else notify.error(res.err || '恢复失败');
    } else if (act === 'del') {
      const ok = await confirmDialog({
        title: '删除这个备份？',
        desc: '删除后无法找回，但当前正在使用的数据不受影响。',
        confirm: '删除',
        danger: true,
      });
      if (!ok) return;
      const res = await api.backupDelete(name);
      if (res.ok) {
        notify.ok('已删除');
        if (res.usage) usage = res.usage;
        await ctx.refreshBackups();
        renderUsage();
        renderList();
      } else notify.error(res.err || '删除失败');
    }
  });

  return {
    update(store) {
      if (store.backups) renderList();
      if (store.storage) {
        usage = store.storage;
        renderUsage();
      }
    },
  };
}
