/** 部署：把「从零到能扫码」拆成看得见的八步。 */

import { api } from '../api.js';
import { confirmDialog, notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, dur, fdate } from '../util.js';
import { pageHead } from './common.js';

const STEP_ICONS = {
  env: 'shieldCheck',
  dirs: 'folder',
  napcat: 'route',
  astrbot: 'bolt',
  deps: 'database',
  config: 'settings',
  'napcat-run': 'play',
  'astrbot-run': 'power',
};

export function mount(root, ctx) {
  let lastStatus = '';

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '部署',
        desc: '把 NapCat 和 AstrBot 装到这台电脑上，并接好线。',
        actions: `
          <button class="btn" data-act="env">${icon('refresh', 15)}重新体检</button>
          <button class="btn btn--primary" data-act="start">${icon('rocket', 15)}开始部署</button>`,
      })}

      <div class="banner" id="dry-banner">
        ${icon('info', 17)}
        <div class="grow">
          <strong>演练模式</strong>　走完整流程但不真的下载安装，用来确认每一步都通。
          <span id="dry-banner-note">关掉后才会联网拉取 NapCat 与 AstrBot。</span>
        </div>
        <label class="switch">
          <input type="checkbox" id="dry-toggle">
          <span class="switch__track"></span>
        </label>
      </div>

      <div class="section">
        <div class="grid grid--main">
          <div class="card">
            <div class="card-head">
              <div>
                <h3>部署进度</h3>
                <p class="sub" id="deploy-sub">尚未开始</p>
              </div>
              <div class="inline">
                <span class="tag" id="deploy-timer" hidden>—</span>
                <button class="btn btn--sm btn--danger" data-act="cancel" hidden>取消</button>
              </div>
            </div>
            <div class="deploy-bar" id="deploy-bar" hidden>
              <div class="deploy-bar__head">
                <span id="deploy-bar-text">准备中…</span>
                <span class="deploy-bar__pct" id="deploy-bar-pct"></span>
              </div>
              <div class="deploy-bar__track"><i id="deploy-bar-fill"></i></div>
            </div>
            <div class="steps" id="steps"></div>
            <div class="divider"></div>
            <div class="spread">
              <span class="muted" style="font-size:12px" id="deploy-note">每一步都会写日志，失败时可以展开看原因。</span>
              <button class="btn btn--sm" data-act="to-logs">查看日志${icon('chevron', 13)}</button>
            </div>
          </div>

          <div class="stack">
            <div class="card">
              <div class="card-head">
                <h3>环境体检</h3>
                <span class="tag" id="env-tag">—</span>
              </div>
              <div class="list" id="env-list"></div>
            </div>
            <div class="card">
              <div class="card-head"><h3>装好之后</h3></div>
              <ol class="stack" style="font-size:13px;color:var(--ink-2);padding-left:2px">
                <li class="inline"><span class="step__idx" style="width:20px;height:20px;font-size:11px">1</span> 打开「登录」把手机 QQ 扫上去</li>
                <li class="inline"><span class="step__idx" style="width:20px;height:20px;font-size:11px">2</span> 在「服务」里确认两个进程都是运行中</li>
                <li class="inline"><span class="step__idx" style="width:20px;height:20px;font-size:11px">3</span> 去 AstrBot 控制台填模型 API Key</li>
              </ol>
              <button class="btn btn--block" style="margin-top:14px" data-act="open-webui">
                ${icon('external', 15)}打开 AstrBot 控制台
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  const stepsEl = root.querySelector('#steps');
  const barEl = root.querySelector('#deploy-bar');
  const barText = root.querySelector('#deploy-bar-text');
  const barPct = root.querySelector('#deploy-bar-pct');
  const barFill = root.querySelector('#deploy-bar-fill');
  const subEl = root.querySelector('#deploy-sub');
  const timerEl = root.querySelector('#deploy-timer');
  const cancelBtn = root.querySelector('[data-act="cancel"]');
  const dryToggle = root.querySelector('#dry-toggle');
  const envList = root.querySelector('#env-list');
  const envTag = root.querySelector('#env-tag');

  /** 离线资源那一行：内置了就说明部署不用联网。 */
  function offlineRow() {
    const off = ctx.store.deploy && ctx.store.deploy.offline;
    if (!off) return '';
    const have = [];
    if (off.napcat) have.push('NapCat');
    if (off.astrbot) have.push('AstrBot');
    if (off.wheels) have.push(`${off.wheels} 个依赖包`);
    if (off.python) have.push('便携 Python');
    const missing = [];
    if (!off.napcat) missing.push('NapCat');
    if (!off.astrbot) missing.push('AstrBot 源码');
    if (!off.wheels) missing.push('依赖包');
    const lazy = !!off.lazy;
    const ready = !!off.ready;
    const cls = lazy ? 'pill--ok' : ready ? 'pill--ok' : have.length ? 'pill--warn' : 'pill--bad';
    const label = lazy ? '懒人版' : ready ? '已内置' : have.length ? '不完整' : '未内置';
    const detail = lazy
      ? `懒人版齐全（${have.join(' + ')}），部署时不用联网，也不用另装 Python`
      : ready
        ? `离线包齐全（${have.join(' + ')}），部署时一步都不用联网`
        : have.length
          ? `有 ${have.join(' + ')}，还缺 ${missing.join('、') || '便携 Python'}，这几步会走网络`
          : '没有离线包，部署时要联网下载';
    return `
      <div class="list__row">
        <span class="pill ${cls}">${label}</span>
        <div class="list__main">
          <strong>离线资源</strong>
          <span class="truncate" title="${esc(detail)}">${esc(detail)}</span>
        </div>
      </div>`;
  }

  function renderBannerNote() {
    const note = root.querySelector('#dry-banner-note');
    if (!note) return;
    const off = ctx.store.deploy && ctx.store.deploy.offline;
    if (off && off.lazy) {
      note.textContent = '关掉后从内置的离线包解压安装，不用联网，也不用另装 Python。';
    } else if (off && off.ready) {
      note.textContent = '关掉后从内置的离线包解压安装，不用联网。';
    } else if (off && off.sources) {
      note.textContent = '关掉后源码从离线包解压，只有装依赖那步要联网。';
    } else {
      note.textContent = '关掉后才会联网拉取 NapCat 与 AstrBot。';
    }
  }

  function renderEnv() {
    renderBannerNote();
    const env = ctx.store.env;
    if (!env) {
      envList.innerHTML = offlineRow() + '<p class="muted" style="font-size:12px">读取中…</p>';
      envTag.textContent = '—';
      return;
    }
    envTag.textContent = env.ready ? '就绪' : `${(env.missing || []).length} 项待补`;
    envList.innerHTML = offlineRow() + (env.items || []).map((it) => {
      const cls = it.status === 'ok' ? 'pill--ok' : it.status === 'warn' ? 'pill--warn' : 'pill--bad';
      const label = it.status === 'ok' ? '就绪' : it.status === 'warn' ? '注意' : '缺失';
      return `
        <div class="list__row">
          <span class="pill ${cls}">${label}</span>
          <div class="list__main">
            <strong>${esc(it.name)}</strong>
            <span class="truncate" title="${esc(it.detail)}">${esc(it.detail)}</span>
          </div>
        </div>`;
    }).join('');
  }

  function renderSteps() {
    const d = ctx.store.deploy || {};
    const steps = d.steps && d.steps.length ? d.steps : (ctx.store.stages || []);
    stepsEl.innerHTML = steps.map((st, i) => {
      const status = st.status || 'pending';
      const iconName = STEP_ICONS[st.key] || 'chevron';
      const mutating = status === 'running';
      return `
        <div class="step ${status === 'pending' ? '' : 'is-' + status}" data-key="${esc(st.key)}">
          <span class="step__idx">${mutating ? '<span class="spinner"></span>' : status === 'done' ? icon('check', 13, 2.2) : status === 'failed' ? icon('x', 13, 2.2) : i + 1}</span>
          <div class="step__body">
            <strong>${esc(st.name)}${status === 'skipped' ? ' <span class="tag">已跳过</span>' : ''}</strong>
            <p title="${esc(st.detail || st.desc || '')}">${esc(st.detail || st.desc || '')}</p>
          </div>
          <span class="step__meta">${st.ms ? (st.ms / 1000).toFixed(1) + 's' : ''}</span>
        </div>`;
    }).join('');

    if (d.running) {
      subEl.textContent = d.current ? `正在执行：${nameOf(d.current, steps)}` : '准备中…';
      cancelBtn.hidden = false;
      root.querySelector('[data-act="start"]').disabled = true;
      timerEl.hidden = false;
      timerEl.textContent = d.startedAt ? dur(Math.floor(Date.now() / 1000) - d.startedAt) : '准备中';
    } else {
      cancelBtn.hidden = true;
      root.querySelector('[data-act="start"]').disabled = false;
      if (d.finishedAt) {
        if (!d.ok) {
          subEl.textContent = '有步骤没走通，看红字说明';
        } else if (d.dryRun) {
          subEl.textContent = '演练通过，但什么都没装';
        } else {
          subEl.textContent = '全部完成，可以扫码登录了';
        }
        timerEl.hidden = false;
        timerEl.textContent = `${Math.max(1, Math.round((d.finishedAt - d.startedAt) / 1000))}s 总耗时`;
      } else {
        subEl.textContent = '尚未开始';
        timerEl.hidden = true;
      }
    }
    renderProgress(d);
    if (typeof d.dryRun === 'boolean') {
      dryToggle.checked = d.dryRun;
      root.querySelector('#dry-banner').classList.toggle('banner--warn', d.dryRun === false);
    }
  }

  function renderProgress(d) {
    const p = d.progress || {};
    const active = d.running && p.key && (p.total || p.text);
    barEl.hidden = !active;
    if (!active) return;
    const pct = p.total ? Math.min(100, p.percent || 0) : 0;
    barFill.style.width = (p.total ? pct : 12) + '%';
    barFill.classList.toggle('is-indet', !p.total);
    barText.textContent = p.text || '执行中…';
    const bits = [];
    if (p.total) bits.push(`${pct.toFixed(0)}%`);
    if (p.speed) bits.push(`${p.speed} MB/s`);
    barPct.textContent = bits.join(' · ');
  }

  function nameOf(key, steps) {
    return (steps.find((s) => s.key === key) || {}).name || key;
  }

  renderEnv();
  renderSteps();

  dryToggle.checked = ctx.store.config?.deploy?.dryRun !== false;
  dryToggle.addEventListener('change', async () => {
    const res = await ctx.saveSetting({ deploy: { dryRun: dryToggle.checked } });
    if (res.ok) notify.info(dryToggle.checked ? '已切回演练模式' : '已关闭演练，下次部署会真的下载');
  });

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;

    if (act === 'start') {
      if (!dryToggle.checked) {
        const off = ctx.store.deploy && ctx.store.deploy.offline;
        const ok = await confirmDialog({
          title: '确认开始真实部署？',
          desc: off && off.lazy
            ? '懒人版：NapCat、AstrBot 源码、依赖和便携 Python 都在包里，解压到本机就行，不用联网也不用另装 Python。'
            : off && off.ready
              ? '这次用内置的离线包，NapCat、AstrBot 源码和依赖都是现成的，解压到本机就行，不用联网。'
              : '会联网下载 NapCat、拉取 AstrBot 源码并安装依赖，可能需要几分钟，期间请保持网络畅通。',
          confirm: '开始部署',
        });
        if (!ok) return;
      }
      btn.disabled = true;
      const res = await api.deployStart(dryToggle.checked);
      btn.disabled = false;
      if (res.ok) notify.ok('部署已开始');
      else notify.error(res.err || '没启动起来');
      ctx.refreshDeploy();
    } else if (act === 'cancel') {
      const res = await api.deployCancel();
      if (res.ok) notify.warn('已请求取消，当前步骤结束后会停下');
    } else if (act === 'env') {
      btn.disabled = true;
      const res = await api.envCheck();
      btn.disabled = false;
      if (res.ok && res.env) {
        ctx.store.env = res.env;
        ctx.emit?.('env');
      } else notify.error(res.err || '体检失败');
      notify.ok('体检完成');
      renderEnv();
    } else if (act === 'to-logs') {
      ctx.go('logs');
    } else if (act === 'open-webui') {
      const res = await api.open('webui');
      if (!res.ok) notify.error(res.err || '打不开');
    }
  });

  const ticker = setInterval(() => {
    const d = ctx.store.deploy;
    if (d?.running && d.startedAt) {
      timerEl.textContent = dur(Math.floor(Date.now() / 1000) - d.startedAt);
    }
  }, 1000);

  return {
    update(store, reason) {
      if (reason === 'deploy') renderSteps();
      if (reason === 'bootstrap' || reason === 'state' || reason === 'refresh'
          || reason === 'deploy') renderEnv();
    },
    destroy() {
      clearInterval(ticker);
    },
  };
}
