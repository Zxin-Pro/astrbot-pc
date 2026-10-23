/** 备份：一键打包、一键回滚，还能把别处的备份拿回来。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, bytes, fdate, timeAgo } from '../util.js';
import { emptyState, pageHead } from './common.js';

export function mount(root, ctx) {
  let data = { items: [], job: {} };
  let timer = 0;
  let scanning = false;

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '备份',
        desc: '配置、账号、插件数据打成一个压缩包，放在你自己的电脑上；换台电脑也能搬过去。',
        actions: `
          <button class="btn" data-act="open">${icon('folder', 15)}打开目录</button>
          <button class="btn" data-act="import">${icon('download', 15)}从文件恢复</button>
          <button class="btn btn--primary" data-act="create">${icon('archive', 15)}立即备份</button>`,
      })}

      <div id="job-slot"></div>
      <div class="card card--tight" id="usage-card"></div>

      <div class="section">
        <div class="section-head">
          <h2>备份记录 <span class="muted" id="bk-count"></span></h2>
          <button class="btn btn--sm btn--ghost" data-act="refresh">${icon('refresh', 14)}重新统计</button>
        </div>
        <div id="bk-list"></div>
      </div>
    </div>`;

  const listEl = root.querySelector('#bk-list');
  const usageEl = root.querySelector('#usage-card');
  const jobEl = root.querySelector('#job-slot');

  function rows() {
    return Array.isArray(data.items) ? data.items : [];
  }

  function renderUsage() {
    const u = data || {};
    const segs = [
      { label: '配置与数据', value: Number(u.stack || 0), cls: 'brand' },
      { label: '日志', value: Number(u.logs || 0), cls: 'warm' },
      { label: '备份', value: Number(u.backups || 0), cls: 'ok' },
    ];
    const total = Math.max(1, segs.reduce((a, b) => a + b.value, 0));
    const disk = u.disk || {};
    usageEl.innerHTML = `
      <div class="card-head" style="margin-bottom:12px">
        <h3>占用</h3>
        <span class="muted" style="font-size:12px">程序数据合计 ${bytes(u.total || 0)}${disk.free ? ` · 磁盘余 ${bytes(disk.free)}` : ''}</span>
      </div>
      <div class="usage-bar">${segs.map((s) => `<span class="usage-bar__seg usage-bar__seg--${s.cls}" style="width:${Math.max(2, (s.value / total) * 100)}%"></span>`).join('')}</div>
      <div class="usage-legend">${segs.map((s) => `<span><i class="usage-bar__dot usage-bar__dot--${s.cls}"></i>${esc(s.label)} <b>${bytes(s.value)}</b></span>`).join('')}</div>`;
  }

  function renderJob() {
    const job = data.job || {};
    if (!job.running) {
      jobEl.innerHTML = '';
      return;
    }
    jobEl.innerHTML = `
      <div class="card card--tight notice notice--brand">
        <div class="notice__body">
          <strong>正在打包备份…</strong>
          <p class="muted">大目录要几十秒到几分钟，可以先去别的页面，这里会自己更新。</p>
        </div>
        <button class="btn btn--sm" data-act="cancel">取消</button>
      </div>`;
  }

  function renderList() {
    const list = rows();
    root.querySelector('#bk-count').textContent = list.length ? `${list.length} 个` : '';
    if (!list.length) {
      listEl.innerHTML = `<div class="card">${emptyState({
        iconName: 'archive',
        title: '还没有备份',
        desc: '点右上角「立即备份」，几秒钟就能完成一份。',
      })}</div>`;
      return;
    }
    listEl.innerHTML = `
      <div class="card card--flush">
        <table class="table table--hover">
          <thead><tr><th>文件名</th><th>备注</th><th>大小</th><th>创建时间</th><th class="ta-r">操作</th></tr></thead>
          <tbody>${list.map((b) => `
            <tr data-name="${esc(b.name)}">
              <td class="mono truncate" title="${esc(b.name)}">${esc(b.name)}</td>
              <td>${b.note ? esc(b.note) : '<span class="muted">—</span>'}</td>
              <td class="mono">${bytes(b.size || 0)}</td>
              <td><span title="${fdate(b.createdAt)}">${timeAgo(b.createdAt)}</span></td>
              <td class="ta-r">
                <button class="btn btn--sm" data-act="restore" data-name="${esc(b.name)}">恢复</button>
                <button class="btn btn--sm btn--ghost" data-act="download" data-name="${esc(b.name)}" title="下载到浏览器">${icon('download', 13)}</button>
                <button class="icon-btn icon-btn--danger" data-act="del" data-name="${esc(b.name)}" title="删除">${icon('trash', 14)}</button>
              </td>
            </tr>`).join('')}</tbody>
        </table>
      </div>`;
  }

  async function reload(force = false) {
    if (scanning) return;
    scanning = true;
    const res = await api.backups();
    scanning = false;
    if (!res.ok) {
      notify.error(res.err || '读取备份列表失败');
      return;
    }
    data = res;
    renderUsage();
    renderJob();
    renderList();
    if (res.job?.running) startPoll();
  }

  function startPoll() {
    if (timer) return;
    timer = setInterval(async () => {
      const res = await api.backups();
      if (!res.ok) return;
      data = res;
      renderJob();
      if (!res.job?.running) {
        clearInterval(timer);
        timer = 0;
        if (res.job?.result?.ok) notify.ok('备份完成');
        else if (res.job?.result?.err) notify.warn(res.job.result.err);
        renderUsage();
        renderList();
      }
    }, 900);
  }

  async function create(note) {
    const res = await api.backupCreate(note);
    if (!res.ok) {
      notify.error(res.err || '备份没能开始');
      return;
    }
    notify.info('开始打包…');
    await reload();
    startPoll();
  }

  function importModal() {
    modal({
      title: '从文件恢复',
      desc: '选一个以前备份出来的 .zip；会先把它放进备份列表，再让你确认恢复。',
      body: `
        <label class="field"><span class="field__label">备份文件路径</span>
          <input class="input mono" name="path" placeholder="D:\\备份\\astrbot-backup-20261022.zip" />
          <span class="field__help">窗口版可以点下面的「选择文件」；网页版请贴绝对路径。</span>
        </label>
        <div class="row-actions"><button class="btn btn--sm" data-act="pick">${icon('folder', 14)}选择文件</button></div>`,
      actions: [
        { label: '取消' },
        {
          label: '导入',
          primary: true,
          run: async (close, rootEl) => {
            const input = rootEl.querySelector('[name="path"]');
            const path = input.value.trim();
            if (!path) {
              input.focus();
              notify.warn('先选一个备份文件');
              return false;
            }
            close();
            const res = await api.backupImport({ path });
            if (!res.ok) {
              notify.error(res.err || '导入失败');
              return;
            }
            notify.ok('已放进备份列表');
            await reload();
          },
        },
      ],
      onMount: ({ root: el }) => {
        el.querySelector('[data-act="pick"]')?.addEventListener('click', async () => {
          const picker = window.pywebview?.api?.pick;
          if (!picker) return notify.info('网页模式没有文件选择框，直接把路径贴进来');
          const res = await picker('zip');
          if (!res?.ok) return notify.error(res?.err || '选择文件失败');
          if (res.path) el.querySelector('[name="path"]').value = res.path;
        });
      },
    });
  }

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    const name = btn.dataset.name;

    if (act === 'open') {
      const res = await api.backupOpen();
      if (!res.ok) notify.error(res.err || '打不开');
    } else if (act === 'refresh') {
      const res = await api.storage(true);
      if (res.ok) notify.ok('已重新统计');
      await reload();
    } else if (act === 'create') {
      modal({
        title: '立即备份',
        desc: '给这次备份写个备注，方便以后挑。',
        body: `<label class="field"><span class="field__label">备注（可选）</span>
          <input class="input" name="note" placeholder="例如：装完新插件之前" maxlength="40" /></label>`,
        actions: [
          { label: '取消' },
          {
            label: '开始备份',
            primary: true,
            run: async (close, rootEl) => {
              const note = rootEl.querySelector('[name="note"]').value.trim();
              close();
              await create(note);
            },
          },
        ],
      });
    } else if (act === 'cancel') {
      const res = await api.backupCancel();
      if (res.ok) notify.info('已请求取消，打包会在下一个文件处停下');
      else notify.warn(res.err || '取消失败');
    } else if (act === 'import') {
      importModal();
    } else if (act === 'download') {
      window.open(`/files?kind=backup&name=${encodeURIComponent(name)}`, '_blank');
      notify.info('已开始下载');
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
        await reload();
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
        await reload();
      } else notify.error(res.err || '删除失败');
    }
  });

  reload();

  return {
    update(store) {
      if (store.backups) reload();
    },
    destroy() {
      if (timer) clearInterval(timer);
      timer = 0;
    },
  };
}
