/** 排障：体检、命令行、崩溃记录、诊断包。出了事都在这一个页面里。 */

import { api } from '../api.js';
import { confirmDialog, notify } from '../components.js';
import { icon } from '../icons.js';
import { bytes, esc, timeAgo } from '../util.js';
import { pageHead } from './common.js';

const STATUS = {
  ok: { cls: 'ok', text: '正常' },
  warn: { cls: 'warn', text: '注意' },
  fail: { cls: 'fail', text: '有问题' },
};

export function mount(root, ctx) {
  const state = { doctor: null, crashes: [], diags: [], busy: false, term: null, e2e: null };

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '排障',
        desc: '跑不起来、掉线、装不上，先点一次体检；还不行就把诊断包发出来。',
        actions: `
          <button class="btn btn--sm" data-act="export">${icon('download', 15)}导出诊断包</button>
          <button class="btn btn--sm btn--primary" data-act="doctor">${icon('activity', 15)}重新体检</button>`,
      })}

      <div class="section">
        <div class="section-head"><h2>体检</h2></div>
        <div class="card card--tight" id="doctor-card"><p class="hint">正在体检…</p></div>
      </div>

      <div class="section">
        <div class="section-head">
          <h2>端到端自检</h2>
          <span class="hint">从实例、NapCat、AstrBot 到模型和网页会话，六段各查一次</span>
          <span class="grow"></span>
          <button class="btn btn--sm btn--primary" data-act="e2e">${icon('route', 15)}开始自检</button>
        </div>
        <div class="card card--tight" id="e2e-card"><p class="hint">还没跑。点右上「开始自检」，哪一段不通会写清楚。</p></div>
      </div>

      <div class="section">
        <div class="section-head"><h2>命令行</h2></div>
        <div class="card">
          <div class="form-grid">
            <label class="field field--full">
              <span class="field__label">命令</span>
              <input class="input mono" id="term-cmd" placeholder="例如 dir 或 python --version" spellcheck="false">
              <span class="field__help">在数据目录下用 cmd /c 执行，超时 60 秒。别贴密码，输出会留在界面上。</span>
            </label>
          </div>
          <div class="row-actions">
            <button class="btn btn--primary" data-act="term-run">${icon('play', 15)}运行</button>
            <span class="hint" id="term-meta"></span>
          </div>
          <pre class="term-out mono" id="term-out" hidden></pre>
        </div>
      </div>

      <div class="section">
        <div class="section-head">
          <h2>崩溃记录</h2>
          <div class="inline">
            <button class="btn btn--sm btn--ghost" data-act="crashes-refresh">${icon('refresh', 14)}刷新</button>
            <button class="btn btn--sm btn--ghost" data-act="crashes-clear">${icon('trash', 14)}清空</button>
          </div>
        </div>
        <div class="card card--tight" id="crashes-card"><p class="hint">读取中…</p></div>
      </div>

      <div class="section">
        <div class="section-head"><h2>诊断包</h2></div>
        <div class="card card--tight" id="diag-card"><p class="hint">读取中…</p></div>
      </div>

      <div class="section">
        <div class="section-head"><h2>危险操作</h2></div>
        <div class="card">
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>重置部署进度</strong>
              <small>把向导退回到第一步，已经下载与安装的文件不会删。部署卡在中间某一步时用。</small>
            </div>
            <div class="set-row__ctrl">
              <button class="btn btn--sm btn--danger" data-act="deploy-reset">重置部署</button>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  function paintDoctor() {
    const el = root.querySelector('#doctor-card');
    if (!el) return;
    const d = state.doctor;
    if (!d) {
      el.innerHTML = '<p class="hint">正在体检…</p>';
      return;
    }
    if (!d.ok && !d.items) {
      el.innerHTML = `<p class="hint">${esc(d.err || '体检失败')}</p>`;
      return;
    }
    const s = d.summary || {};
    const rows = (d.items || []).map((it) => {
      const st = STATUS[it.status] || STATUS.warn;
      return `
        <div class="diag-row">
          <span class="diag-dot diag-dot--${st.cls}" aria-hidden="true"></span>
          <div class="diag-row__text">
            <strong>${esc(it.label || it.key)} <span class="diag-tag diag-tag--${st.cls}">${st.text}</span></strong>
            <p class="muted">${esc(it.detail || '')}${it.status !== 'ok' && it.hint ? `<br><span class="field__help">${esc(it.hint)}</span>` : ''}</p>
          </div>
        </div>`;
    }).join('');
    el.innerHTML = `
      <div class="diag-summary">
        <span class="pill pill--ok">${s.ok || 0} 项正常</span>
        <span class="pill ${s.warn ? 'pill--warn' : ''}">${s.warn || 0} 项注意</span>
        <span class="pill ${s.fail ? 'pill--bad' : ''}">${s.fail || 0} 项有问题</span>
        <span class="grow"></span>
        <span class="muted" style="font-size:12px">${d.ts ? timeAgo(d.ts) : ''}</span>
      </div>
      <div class="diag-list">${rows}</div>`;
  }

  function paintE2E() {
    const el = root.querySelector('#e2e-card');
    if (!el) return;
    const d = state.e2e;
    if (!d) {
      el.innerHTML = '<p class="hint">还没跑。点右上「开始自检」，哪一段不通会写清楚。</p>';
      return;
    }
    if (!d.steps) {
      el.innerHTML = `<p class="hint">${esc(d.err || '自检失败')}</p>`;
      return;
    }
    const rows = d.steps.map((s) => {
      const cls = s.skipped ? 'warn' : s.ok ? 'ok' : 'fail';
      const tag = s.skipped ? '跳过' : s.ok ? '通过' : '不通';
      return `<div class="diag-row">
        <span class="diag-dot diag-dot--${cls}" aria-hidden="true"></span>
        <div class="diag-row__text">
          <strong>${esc(s.label || s.key)} <span class="diag-tag diag-tag--${cls}">${tag}</span></strong>
          <p class="muted">${esc(s.detail || '')}${s.hint ? `<br><span class="field__help">${esc(s.hint)}</span>` : ''}</p>
        </div>
      </div>`;
    }).join('');
    el.innerHTML = `<div class="diag-summary">
        <span class="pill ${d.ok ? 'pill--ok' : 'pill--bad'}">${d.ok ? '整体通了' : '有段不通'}</span>
        <span class="pill">${d.ms ? d.ms + ' ms' : ''}</span>
        <span class="grow"></span>
        ${d.reply ? `<span class="muted" style="font-size:12px">模型回复：${esc(String(d.reply).slice(0, 60))}</span>` : ''}
      </div>
      <div class="diag-list">${rows}</div>`;
  }

  function paintCrashes() {
    const el = root.querySelector('#crashes-card');
    if (!el) return;
    if (!state.crashes.length) {
      el.innerHTML = '<p class="hint">最近没有异常记录，挺好。</p>';
      return;
    }
    el.innerHTML = state.crashes.map((c) => `
      <details class="diag-crash">
        <summary>
          <span class="diag-dot diag-dot--warn" aria-hidden="true"></span>
          <span class="grow"><strong>${esc(c.summary || '异常')}</strong>
            <small class="muted">${esc(c.source || '')} · ${timeAgo(c.ts)} ${c.count > 1 ? `· 重复 ${c.count} 次` : ''}</small></span>
        </summary>
        ${c.detail ? `<pre class="term-out mono">${esc(c.detail)}</pre>` : ''}
      </details>`).join('');
  }

  function paintDiags() {
    const el = root.querySelector('#diag-card');
    if (!el) return;
    if (!state.diags.length) {
      el.innerHTML = '<p class="hint">还没有诊断包。点右上「导出诊断包」生成一个，里面配置已脱敏。</p>';
      return;
    }
    el.innerHTML = state.diags.map((f) => `
      <div class="set-row set-row--full">
        <div class="set-row__text">
          <strong class="mono">${esc(f.name)}</strong>
          <small>${bytes(f.size || 0)} · ${timeAgo(f.createdAt)}</small>
        </div>
        <div class="set-row__ctrl inline">
          <a class="btn btn--sm" href="/files?kind=diagnostic&name=${encodeURIComponent(f.name)}">${icon('download', 14)}下载</a>
          <button class="btn btn--sm btn--ghost" data-act="diag-del" data-name="${esc(f.name)}">${icon('trash', 14)}删除</button>
        </div>
      </div>`).join('');
  }

  async function loadDoctor(force) {
    const res = await api.doctor(force);
    state.doctor = res;
    paintDoctor();
  }

  async function loadCrashes() {
    const res = await api.crashes();
    state.crashes = res.items || [];
    paintCrashes();
  }

  async function loadDiags() {
    const res = await api.diagList();
    state.diags = res.items || [];
    paintDiags();
  }

  async function runTerm() {
    const cmd = root.querySelector('#term-cmd').value.trim();
    if (!cmd) return notify.warn('先写一条命令');
    const btn = root.querySelector('[data-act="term-run"]');
    const out = root.querySelector('#term-out');
    const meta = root.querySelector('#term-meta');
    btn.disabled = true;
    meta.textContent = '运行中…';
    try {
      const res = await api.terminal({ cmd, timeout: 60 });
      if (!res.ok) {
        meta.textContent = '';
        notify.error(res.err || '执行失败');
        return;
      }
      out.hidden = false;
      out.textContent = (res.out || '') + (res.truncated ? '\n…（输出太长，已截断）' : '');
      meta.textContent = `退出码 ${res.code} · ${res.ms} ms${res.timedOut ? ' · 已超时' : ''}`;
    } catch (err) {
      meta.textContent = '';
      notify.error(err?.message || '执行失败');
    } finally {
      btn.disabled = false;
    }
  }

  root.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.id === 'term-cmd') {
      e.preventDefault();
      runTerm();
    }
  });

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'doctor') {
      btn.disabled = true;
      await loadDoctor(true);
      btn.disabled = false;
      notify.ok('体检完成');
    } else if (act === 'export') {
      btn.disabled = true;
      const res = await api.diagExport();
      btn.disabled = false;
      if (!res.ok) return notify.error(res.err || '导出失败');
      notify.ok(`诊断包已生成：${res.name}（${bytes(res.size || 0)}）`);
      await loadDiags();
    } else if (act === 'e2e') {
      btn.disabled = true;
      const el = root.querySelector('#e2e-card');
      if (el) el.innerHTML = '<p class="hint">正在跑，模型那一段可能要十几秒…</p>';
      state.e2e = await api.selftestE2E();
      btn.disabled = false;
      paintE2E();
      if (state.e2e?.ok) notify.ok('六段都通了');
      else notify.warn(state.e2e?.err || '有段不通，看下面的说明');
    } else if (act === 'term-run') {
      await runTerm();
    } else if (act === 'crashes-refresh') {
      await loadCrashes();
    } else if (act === 'crashes-clear') {
      if (!state.crashes.length) return notify.info('本来就是空的');
      const ok = await confirmDialog({ title: '清空崩溃记录？', desc: '只删记录，不影响正在运行的服务。', confirm: '清空', danger: true });
      if (!ok) return;
      await api.crashesClear();
      await loadCrashes();
      notify.ok('已清空');
    } else if (act === 'diag-del') {
      const name = btn.dataset.name;
      const ok = await confirmDialog({ title: '删除这个诊断包？', desc: name, confirm: '删除', danger: true });
      if (!ok) return;
      const res = await api.diagDelete(name);
      if (!res.ok) return notify.error(res.err || '删除失败');
      await loadDiags();
    } else if (act === 'deploy-reset') {
      const ok = await confirmDialog({
        title: '重置部署进度？',
        desc: '向导回到第一步，已经装好的文件和配置都保留。正在部署时不能点。',
        confirm: '重置',
        danger: true,
      });
      if (!ok) return;
      const res = await api.deployReset();
      if (!res.ok) return notify.error(res.err || '重置失败');
      notify.ok(res.message || '部署进度已重置');
      ctx.go('deploy', { force: true });
    }
  });

  paintDoctor();
  paintE2E();
  paintCrashes();
  paintDiags();
  loadDoctor(false);
  loadCrashes();
  loadDiags();

  return {
    update(store, reason) {
      if (reason === 'status' && store.services) loadCrashes();
    },
  };
}
