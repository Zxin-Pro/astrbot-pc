/** 资源：CPU / 内存 / 磁盘趋势 + 进程占用 + 报错解释。 */

import { api } from '../api.js';
import { confirmDialog, notify } from '../components.js';
import { icon } from '../icons.js';
import { bytes, debounce, esc, fdate, pad, timeAgo } from '../util.js';
import { pageHead } from './common.js';

const RANGES = [
  { hours: 6, label: '6 小时' },
  { hours: 24, label: '24 小时' },
  { hours: 168, label: '7 天' },
];

const ROLES = { napcat: 'NapCat', astrbot: 'AstrBot' };

const LEVELS = {
  error: { text: '错误', color: 'var(--bad-600)' },
  warn: { text: '警告', color: 'var(--warn-500)' },
  info: { text: '提示', color: 'var(--brand-500)' },
};

/** 字节 → GB 数字；单位交给调用处排成小字。 */
function gb(n) {
  const v = Number(n) || 0;
  if (!v) return '0';
  const g = v / 1073741824;
  return g >= 100 ? g.toFixed(0) : String(Math.round(g * 10) / 10);
}

function stamp(ts) {
  if (!ts) return '—';
  const d = new Date(Number(ts) * 1000);
  const now = new Date();
  const sameDay = d.getFullYear() === now.getFullYear()
    && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate();
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return sameDay
    ? `${hm}:${pad(d.getSeconds())}`
    : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`;
}

function axisLabel(ts, hours) {
  const d = new Date(Number(ts) * 1000);
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return hours > 24
    ? `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`
    : hm;
}

function toneHigh(v, warn, bad) {
  if (v == null) return 'idle';
  if (v >= bad) return 'bad';
  if (v >= warn) return 'warn';
  return 'ok';
}

function toneLow(v, warn, bad) {
  if (v == null) return 'idle';
  if (v <= bad) return 'bad';
  if (v <= warn) return 'warn';
  return 'ok';
}

/** 顶部指标卡：大数字 + 小单位 + 细语义色条，不用大面积渐变。 */
function kpiCard({ iconName, label, value, unit, foot, tone, meter }) {
  const width = meter == null ? null : Math.max(0, Math.min(100, Number(meter) || 0));
  return `
    <div class="stat res-kpi res-kpi--${tone}">
      <div class="stat__label">${icon(iconName, 14)}<span>${esc(label)}</span></div>
      <div class="stat__value"><span>${esc(value)}</span>${unit ? `<small>${esc(unit)}</small>` : ''}</div>
      <div class="stat__foot">${foot}</div>
      ${width == null ? '' : `<div class="res-meter" aria-hidden="true"><i style="width:${width.toFixed(1)}%"></i></div>`}
    </div>`;
}

export function mount(root, ctx) {
  const state = {
    range: 24,
    items: [],
    trendLoaded: false,
    trendError: '',
    summary: null,
    summaryLoaded: false,
    summaryError: '',
    errors: [],
    errorsLoaded: false,
    errorsError: '',
    explain: null,
  };

  let disposed = false;
  let timer = 0;
  let tick = 0;
  let trendSeq = 0;

  root.innerHTML = `
    <div class="page resources-page">
      <style>
        .resources-page .res-kpi { padding: 18px 20px 22px; }
        .resources-page .res-kpi .stat__label { color: var(--ink-3); font-weight: 500; }
        .resources-page .res-kpi .stat__label svg { color: var(--res-tone, var(--ink-4)); }
        .resources-page .res-kpi .stat__value { margin-top: 10px; font-size: 30px; letter-spacing: -1.2px; }
        .resources-page .res-kpi .stat__value small { font-size: 12px; letter-spacing: 0; }
        .resources-page .res-kpi .stat__foot { margin-top: 8px; color: var(--ink-3); line-height: 1.5; }
        .resources-page .res-kpi--ok { --res-tone: var(--ok-600); }
        .resources-page .res-kpi--warn { --res-tone: var(--warn-600); }
        .resources-page .res-kpi--bad { --res-tone: var(--bad-600); }
        .resources-page .res-kpi--idle { --res-tone: var(--ink-4); }
        .resources-page .res-meter { position: absolute; left: 0; right: 0; bottom: 0; height: 3px; background: var(--line-2); }
        .resources-page .res-meter > i { display: block; height: 100%; background: var(--res-tone, var(--brand-600)); transition: width var(--t-slow) var(--ease); }

        .resources-page .res-legend { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 20px; margin-bottom: 12px; font-size: 12px; color: var(--ink-3); }
        .resources-page .res-legend__item { display: inline-flex; align-items: center; gap: 7px; }
        .resources-page .res-legend b { color: var(--ink-2); font-weight: 500; font-variant-numeric: tabular-nums; }
        .resources-page .res-swatch { display: inline-block; width: 16px; height: 3px; border-radius: 2px; }
        .resources-page .res-swatch--cpu { background: var(--brand-600); }
        .resources-page .res-swatch--mem { background: var(--warm-600); }
        .resources-page .res-chart { width: 100%; min-height: 150px; }
        .resources-page .res-chart svg { display: block; max-width: 100%; height: auto; }

        .resources-page .res-err { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px 14px; padding: 14px 18px; border-bottom: 1px solid var(--line-2); }
        .resources-page .res-err:last-child { border-bottom: 0; }
        .resources-page .res-err__meta { grid-column: 1; display: flex; align-items: center; gap: 10px; min-width: 0; }
        .resources-page .res-err__meta .truncate { max-width: 240px; }
        .resources-page .res-err__line { grid-column: 1; margin: 0; color: var(--ink-2); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
        .resources-page .res-err .btn { grid-column: 2; grid-row: 1 / span 2; justify-self: end; }
        .resources-page .res-flag { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-3); white-space: nowrap; }

        .resources-page .res-explain__head { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
        .resources-page .res-explain__head strong { font-size: var(--f-15); }
        .resources-page .res-explain__line { margin: 12px 0 0; padding: 10px 12px; border-radius: var(--r-sm); border: 1px solid var(--line-2); background: var(--surface-2); color: var(--ink-2); font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; }
        .resources-page .res-explain { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 16px; }
        .resources-page .res-explain h3 { margin: 0 0 6px; font-size: 12px; font-weight: 600; color: var(--ink-3); letter-spacing: .4px; }
        .resources-page .res-explain p { margin: 0; font-size: 13px; line-height: 1.7; color: var(--ink-2); }
        .resources-page .res-last { border-bottom: 0; padding-bottom: 0; }

        @media (max-width: 720px) {
          .resources-page .res-explain { grid-template-columns: minmax(0, 1fr); }
          .resources-page .res-err { grid-template-columns: minmax(0, 1fr); }
          .resources-page .res-err .btn { grid-column: 1; grid-row: auto; justify-self: start; }
        }

        @media (prefers-reduced-motion: reduce) {
          .resources-page .res-meter > i { transition: none; }
        }
      </style>

      ${pageHead({
        title: '资源',
        desc: '这台电脑的 CPU、内存、磁盘和进程占用；下面还能把日志里的报错翻译成中文。',
        actions: `<button class="btn btn--sm" data-act="refresh">${icon('refresh', 15)}刷新</button>`,
      })}

      <div class="section">
        <div class="grid grid--4" id="res-kpi"></div>
        <p class="hint" id="kpi-hint" style="margin-top:10px">正在读取采样…</p>
      </div>

      <div class="section">
        <div class="section-head">
          <h2 id="trend-title">24 小时趋势</h2>
          <div class="segmented segmented--sm" id="range-seg" role="tablist" aria-label="趋势时间范围">
            ${RANGES.map((r) => `<button type="button" role="tab" data-range="${r.hours}" class="${r.hours === 24 ? 'is-active' : ''}" aria-selected="${r.hours === 24}">${r.label}</button>`).join('')}
          </div>
        </div>
        <div class="card">
          <div class="res-legend">
            <span class="res-legend__item"><i class="res-swatch res-swatch--cpu" aria-hidden="true"></i>CPU <b id="cpu-range">—</b></span>
            <span class="res-legend__item"><i class="res-swatch res-swatch--mem" aria-hidden="true"></i>内存 <b id="mem-range">—</b></span>
            <span class="grow"></span>
            <span class="muted" id="trend-points" style="font-size:12px"></span>
          </div>
          <div class="res-chart" id="trend-host">
            <div class="chart-empty"><p>正在读取采样…</p></div>
          </div>
          <p class="hint" id="trend-foot" style="margin-top:10px">每 30 秒一帧，页面每 30 秒自动刷新。</p>
        </div>
      </div>

      <div class="section">
        <div class="section-head">
          <h2>进程</h2>
          <span class="muted" id="procs-hint" style="font-size:12px"></span>
        </div>
        <div class="card card--flush" id="procs-card"><p class="hint" style="padding:16px 18px">读取中…</p></div>
      </div>

      <div class="section">
        <div class="section-head">
          <h2>最近的错误</h2>
          <span class="muted" id="errors-hint" style="font-size:12px"></span>
        </div>
        <div class="card card--flush" id="errors-card"><p class="hint" style="padding:16px 18px">读取中…</p></div>
        <div class="card" id="explain-card" aria-live="polite" hidden style="margin-top:12px"></div>
      </div>

      <div class="section">
        <div class="section-head"><h2>危险操作</h2></div>
        <div class="card">
          <div class="set-row set-row--full res-last">
            <div class="set-row__text">
              <strong>清空采样</strong>
              <small>删掉本机保存的 CPU / 内存 / 磁盘历史点，趋势图会回到起点。服务和日志都不受影响，30 秒后会有新的第一帧。</small>
            </div>
            <div class="set-row__ctrl">
              <button class="btn btn--sm btn--danger" data-act="clear">${icon('trash', 14)}清空采样</button>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  const q = (sel) => root.querySelector(sel);

  function renderKpi() {
    const box = q('#res-kpi');
    if (!box) return;
    const d = state.summary;
    const latest = (d && d.latest) || null;
    const sum = (d && d.summary) || {};
    const today = (d && d.today) || {};
    const mem = (latest && latest.mem) || {};
    const disk = (latest && latest.disk) || {};
    const boot = !latest;
    const cpu = latest ? Number(latest.cpu) || 0 : null;
    const memPct = latest ? Number(mem.percent) || 0 : null;
    const freePct = disk.total ? ((Number(disk.free) || 0) / Number(disk.total)) * 100 : null;
    const errors = d ? Number(today.errors) || 0 : null;
    const wait = state.summaryLoaded ? '等待第一帧采样' : '读取中…';

    box.innerHTML = [
      kpiCard({
        iconName: 'cpu',
        label: 'CPU',
        value: boot ? '—' : cpu.toFixed(1),
        unit: boot ? '' : '%',
        foot: boot ? wait : `24 小时均值 ${Number(sum.cpuAvg || 0).toFixed(1)}% · 峰值 ${Number(sum.cpuMax || 0).toFixed(1)}%`,
        tone: boot ? 'idle' : toneHigh(cpu, 65, 85),
        meter: boot ? null : cpu,
      }),
      kpiCard({
        iconName: 'activity',
        label: '内存已用',
        value: boot ? '—' : gb(mem.used),
        unit: boot ? '' : (mem.total ? `GB / ${gb(mem.total)} GB` : 'GB'),
        foot: boot ? wait : `占用 ${Number(memPct).toFixed(1)}% · 24 小时均值 ${Number(sum.memAvg || 0).toFixed(1)}%`,
        tone: boot ? 'idle' : toneHigh(memPct, 75, 90),
        meter: boot ? null : memPct,
      }),
      kpiCard({
        iconName: 'drive',
        label: '磁盘剩余',
        value: boot ? '—' : gb(disk.free),
        unit: boot ? '' : 'GB 可用',
        foot: boot ? wait : (disk.total
          ? `已用 ${Number(disk.percent || 0).toFixed(1)}% · 共 ${gb(disk.total)} GB`
          : '读不到磁盘信息'),
        tone: boot ? 'idle' : toneLow(freePct, 20, 10),
        meter: boot ? null : freePct,
      }),
      kpiCard({
        iconName: 'alert',
        label: '今日错误',
        value: d ? String(errors) : '—',
        unit: d ? '次' : '',
        foot: d
          ? `今日重启 ${Number(today.restarts) || 0} 次 · 警告 ${Number(today.warns) || 0} 条`
          : wait,
        tone: errors == null ? 'idle' : (errors === 0 ? 'ok' : (errors < 5 ? 'warn' : 'bad')),
        meter: null,
      }),
    ].join('');

    const hint = q('#kpi-hint');
    if (!hint) return;
    if (state.summaryError) {
      hint.textContent = `读不到采样汇总：${state.summaryError}`;
    } else if (!d) {
      hint.textContent = '正在读取采样…';
    } else {
      const alive = d.running ? '采样器运行中' : '采样器没在跑，下面可能是旧数据';
      hint.textContent = `${alive} · 每 30 秒一帧 · 更新于 ${timeAgo(d.ts)}`;
    }
  }

  function renderProcs() {
    const box = q('#procs-card');
    const hint = q('#procs-hint');
    if (!box) return;
    if (state.summaryError) {
      box.innerHTML = `<p class="hint" style="padding:16px 18px">读不到进程列表：${esc(state.summaryError)}</p>`;
      if (hint) hint.textContent = '';
      return;
    }
    if (!state.summaryLoaded) {
      box.innerHTML = '<p class="hint" style="padding:16px 18px">读取中…</p>';
      return;
    }
    const latest = state.summary && state.summary.latest;
    const list = ((latest && latest.procs) || []).filter((p) => p && p.role);
    if (hint) {
      const running = list.filter((p) => Number(p.pid) > 0).length;
      hint.textContent = list.length ? `${running} 个在运行` : '';
    }
    if (!list.length) {
      box.innerHTML = `
        <div class="empty">
          ${icon('server', 30)}
          <strong>还没有受管进程</strong>
          <p>NapCat 或 AstrBot 启动后，这里会显示它们的 PID、CPU 和内存。</p>
          <button class="btn btn--sm" data-act="to-services">${icon('play', 14)}去服务页启动</button>
        </div>`;
      return;
    }
    box.innerHTML = `
      <table class="table table--hover">
        <caption class="sr-only">受管进程的 CPU 与内存占用</caption>
        <thead><tr><th>角色</th><th>实例</th><th>PID</th><th class="ta-r">CPU</th><th class="ta-r">内存</th></tr></thead>
        <tbody>
          ${list.map((p) => {
            const pid = Number(p.pid) || 0;
            const role = ROLES[p.role] || p.role || '未知';
            const cpuText = pid ? `${Number(p.cpu || 0).toFixed(1)}%` : '—';
            const rssText = pid && p.rss ? bytes(p.rss) : '—';
            return `
              <tr>
                <td><strong>${esc(role)}</strong></td>
                <td class="mono">${esc(p.iid || '默认')}</td>
                <td class="mono">${pid ? esc(String(pid)) : '<span class="muted">未运行</span>'}</td>
                <td class="ta-r mono">${cpuText}</td>
                <td class="ta-r mono">${rssText}</td>
              </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  }

  function renderErrors() {
    const box = q('#errors-card');
    const hint = q('#errors-hint');
    if (!box) return;
    if (!state.errorsLoaded) return;
    if (state.errorsError) {
      if (hint) hint.textContent = '';
      box.innerHTML = `<p class="hint" style="padding:16px 18px">读不到最近的报错：${esc(state.errorsError)}</p>`;
      return;
    }
    if (hint) hint.textContent = state.errors.length ? `${state.errors.length} 条 · 来自日志尾部` : '';
    if (!state.errors.length) {
      box.innerHTML = `
        <div class="empty">
          ${icon('check', 30)}
          <strong>最近没扫到报错</strong>
          <p>日志里暂时没有 error 和警告。真出了问题，去「日志」页看完整输出。</p>
          <button class="btn btn--sm" data-act="to-logs">${icon('terminal', 14)}去日志页</button>
        </div>`;
      return;
    }
    box.innerHTML = state.errors.map((it, i) => {
      const lv = LEVELS[it.level] || LEVELS.error;
      return `
        <div class="res-err">
          <div class="res-err__meta">
            <span class="mono" title="${esc(fdate(it.ts, true))}">${esc(stamp(it.ts))}</span>
            <span class="res-flag"><i class="dot" style="background:${lv.color}" aria-hidden="true"></i>${lv.text}</span>
            <span class="muted truncate" title="${esc(it.source || '')}">${esc(it.source || '日志')}</span>
          </div>
          <p class="res-err__line mono">${esc(it.line || '')}</p>
          <button class="btn btn--sm btn--ghost" data-act="explain" data-i="${i}" aria-label="解释这条报错">${icon('info', 14)}解释</button>
        </div>`;
    }).join('');
  }

  function renderExplain() {
    const card = q('#explain-card');
    if (!card) return;
    const d = state.explain;
    if (!d) {
      card.hidden = true;
      card.innerHTML = '';
      return;
    }
    card.hidden = false;
    if (d.loading) {
      card.setAttribute('aria-busy', 'true');
      card.innerHTML = `<div class="inline"><span class="spinner"></span><span class="hint">正在对照规则解释…</span></div>`;
      return;
    }
    card.setAttribute('aria-busy', 'false');
    if (d.error) {
      card.innerHTML = `
        <div class="inline">
          <span class="res-flag"><i class="dot" style="background:var(--warn-500)" aria-hidden="true"></i>没解释出来</span>
          <span class="grow"></span>
          <button class="btn btn--sm btn--ghost" data-act="explain-close">关闭</button>
        </div>
        <p class="hint" style="margin-top:8px">${esc(d.error)}</p>`;
      return;
    }
    const lv = LEVELS[d.level] || LEVELS.info;
    card.innerHTML = `
      <div class="res-explain__head">
        <span class="res-flag"><i class="dot" style="background:${lv.color}" aria-hidden="true"></i>${lv.text}</span>
        <strong>${esc(d.title || '这条报错')}</strong>
        <span class="grow"></span>
        ${d.source ? `<span class="muted" style="font-size:12px">${esc(d.source)}${d.ts ? ` · ${esc(stamp(d.ts))}` : ''}</span>` : ''}
        <button class="btn btn--sm btn--ghost" data-act="explain-close" aria-label="关闭解释">${icon('x', 14)}</button>
      </div>
      ${d.line ? `<p class="res-explain__line mono">${esc(d.line)}</p>` : ''}
      <div class="res-explain">
        <div><h3>为什么会这样</h3><p>${esc(d.reason || '规则库没有给出原因。')}</p></div>
        <div><h3>怎么处理</h3><p>${esc(d.fix || '到「日志」页看这条报错前后的几行。')}</p></div>
      </div>
      <p class="hint" style="margin-top:14px">解释来自本地规则库，不联网、不上传日志。</p>`;
  }

  function drawTrend() {
    const host = q('#trend-host');
    if (!host) return;
    const cpuRange = q('#cpu-range');
    const memRange = q('#mem-range');
    const points = q('#trend-points');
    const foot = q('#trend-foot');

    if (state.trendError) {
      host.innerHTML = `
        <div class="chart-empty">
          ${icon('alert', 22)}
          <p>读不到采样数据</p>
          <span>${esc(state.trendError)}</span>
        </div>`;
      if (cpuRange) cpuRange.textContent = '—';
      if (memRange) memRange.textContent = '—';
      if (points) points.textContent = '';
      if (foot) foot.textContent = '稍后会自动再试一次。';
      return;
    }

    const items = state.items || [];
    if (!items.length) {
      const loading = !state.trendLoaded;
      host.innerHTML = `
        <div class="chart-empty">
          ${icon('activity', 22)}
          ${loading
            ? '<p>正在读取采样…</p><span>稍等，正在向本机要这段时间的数据</span>'
            : '<p>采样刚开始，30 秒后出现第一帧</p><span>采样在本机后台进行，不需要联网</span>'}
        </div>`;
      if (cpuRange) cpuRange.textContent = '—';
      if (memRange) memRange.textContent = '—';
      if (points) points.textContent = loading ? '' : '0 点';
      if (foot) foot.textContent = loading ? '正在读取采样…' : '本机采样器每 30 秒采一帧，等一会儿就有线了。';
      return;
    }

    const w = Math.max(320, Math.round(host.clientWidth || 720));
    const h = 240;
    const padL = 40;
    const padR = 14;
    const padT = 16;
    const padB = 30;
    const plotW = Math.max(10, w - padL - padR);
    const plotH = h - padT - padB;

    const vals = items.map((it) => ({
      ts: Number(it.ts) || 0,
      cpu: Math.max(0, Math.min(100, Number(it.cpu) || 0)),
      mem: Math.max(0, Math.min(100, Number((it.mem && it.mem.percent) || 0))),
    }));
    const t0 = vals[0].ts;
    const t1 = vals[vals.length - 1].ts;
    const span = Math.max(1, t1 - t0);
    const x = (ts) => padL + (vals.length === 1 ? plotW / 2 : ((ts - t0) / span) * plotW);
    const y = (v) => padT + (1 - v / 100) * plotH;
    const fx = (v) => v.toFixed(1);

    const cpuPts = vals.map((v) => `${fx(x(v.ts))},${fx(y(v.cpu))}`).join(' ');
    const memPts = vals.map((v) => `${fx(x(v.ts))},${fx(y(v.mem))}`).join(' ');
    const baseY = fx(padT + plotH);
    const lastX = fx(x(t1));
    const areaPts = `${fx(x(t0))},${baseY} ${cpuPts} ${lastX},${baseY}`;

    const grid = [0, 25, 50, 75, 100].map((v) => {
      const yy = fx(y(v));
      const label = v % 50 === 0
        ? `<text x="${fx(padL - 8)}" y="${(Number(yy) + 3.6).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--ink-4)">${v}%</text>`
        : '';
      return `<line x1="${padL}" y1="${yy}" x2="${fx(w - padR)}" y2="${yy}" stroke="var(--line-2)" stroke-width="1"${v === 0 || v === 100 ? '' : ' stroke-dasharray="3 5"'} />${label}`;
    }).join('');

    const midTs = t0 + (t1 - t0) / 2;
    const xLabels = [
      { at: padL, anchor: 'start', text: axisLabel(t0, state.range) },
      { at: x(midTs), anchor: 'middle', text: axisLabel(midTs, state.range) },
      { at: w - padR, anchor: 'end', text: '现在' },
    ].map((l) => `<text x="${fx(l.at)}" y="${h - 8}" text-anchor="${l.anchor}" font-size="10" fill="var(--ink-4)">${esc(l.text)}</text>`).join('');

    const cpuMax = Math.max.apply(null, vals.map((v) => v.cpu));
    const cpuMin = Math.min.apply(null, vals.map((v) => v.cpu));
    const memMax = Math.max.apply(null, vals.map((v) => v.mem));
    const memMin = Math.min.apply(null, vals.map((v) => v.mem));
    if (cpuRange) cpuRange.textContent = `峰值 ${cpuMax.toFixed(1)}% · 最低 ${cpuMin.toFixed(1)}%`;
    if (memRange) memRange.textContent = `峰值 ${memMax.toFixed(1)}% · 最低 ${memMin.toFixed(1)}%`;
    if (points) points.textContent = `${vals.length} 点`;

    const rangeLabel = (RANGES.find((r) => r.hours === state.range) || RANGES[1]).label;
    const aria = `最近 ${rangeLabel}的 CPU 与内存占用折线图，从 ${axisLabel(t0, state.range)} 到现在，共 ${vals.length} 个采样点；CPU 最高 ${cpuMax.toFixed(1)}%，内存最高 ${memMax.toFixed(1)}%。`;

    host.innerHTML = `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(aria)}">
        <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${h - padB}" stroke="var(--line)"/>
        <line x1="${padL}" y1="${h - padB}" x2="${fx(w - padR)}" y2="${h - padB}" stroke="var(--line)"/>
        ${grid}
        <polygon points="${areaPts}" fill="var(--brand-600)" opacity="0.08"/>
        <polyline points="${memPts}" fill="none" stroke="var(--warm-600)" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>
        <polyline points="${cpuPts}" fill="none" stroke="var(--brand-600)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${lastX}" cy="${fx(y(vals[vals.length - 1].cpu))}" r="3" fill="var(--brand-600)"/>
        <circle cx="${lastX}" cy="${fx(y(vals[vals.length - 1].mem))}" r="3" fill="var(--warm-600)"/>
        ${xLabels}
      </svg>`;

    if (foot) {
      foot.textContent = state.range > 24
        ? `每 30 秒一帧 · 最后一帧 ${timeAgo(t1)} · 本机只保留最近 24 小时采样，7 天视图最多也只能看到这一段。`
        : `每 30 秒一帧 · 最后一帧 ${timeAgo(t1)} · 页面每 30 秒自动刷新，点数多时会等距抽稀。`;
    }
  }

  async function loadSummary() {
    const res = await api.metricsSummary();
    if (disposed) return;
    state.summaryLoaded = true;
    if (!res.ok) {
      state.summaryError = res.err || '读取失败';
    } else {
      state.summaryError = '';
      state.summary = res;
    }
    renderKpi();
    renderProcs();
  }

  async function loadTrend() {
    const seq = ++trendSeq;
    const res = await api.metrics(state.range, 720);
    if (disposed || seq !== trendSeq) return;
    state.trendLoaded = true;
    if (!res.ok) {
      state.trendError = res.err || '读取失败';
      state.items = [];
    } else {
      state.trendError = '';
      state.items = Array.isArray(res.items) ? res.items : [];
    }
    drawTrend();
  }

  async function loadErrors() {
    const res = await api.metricsErrors(30);
    if (disposed) return;
    state.errorsLoaded = true;
    if (!res.ok) {
      state.errorsError = res.err || '读取失败';
      state.errors = [];
    } else {
      state.errorsError = '';
      state.errors = Array.isArray(res.items) ? res.items : [];
    }
    renderErrors();
  }

  async function explain(index, btn) {
    const item = state.errors[index];
    if (!item) return;
    state.explain = { loading: true };
    renderExplain();
    if (btn) btn.disabled = true;
    const res = await api.metricsExplain({ text: item.line || '' });
    if (btn) btn.disabled = false;
    if (disposed) return;
    if (!res.ok) {
      state.explain = { error: res.err || '解释失败' };
      renderExplain();
      return;
    }
    state.explain = {
      title: res.title,
      reason: res.reason,
      fix: res.fix,
      level: res.level,
      line: item.line,
      source: item.source,
      ts: item.ts,
    };
    renderExplain();
  }

  function setRange(hours) {
    if (state.range === hours || !RANGES.some((r) => r.hours === hours)) return;
    state.range = hours;
    const item = RANGES.find((r) => r.hours === hours);
    const title = q('#trend-title');
    if (title) title.textContent = `${item.label}趋势`;
    root.querySelectorAll('#range-seg [data-range]').forEach((el) => {
      const on = Number(el.dataset.range) === hours;
      el.classList.toggle('is-active', on);
      el.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    state.items = [];
    state.trendLoaded = false;
    drawTrend();
    loadTrend();
  }

  const onClick = async (e) => {
    const rangeBtn = e.target.closest('[data-range]');
    if (rangeBtn && root.contains(rangeBtn)) {
      setRange(Number(rangeBtn.dataset.range));
      return;
    }
    const btn = e.target.closest('[data-act]');
    if (!btn || !root.contains(btn)) return;
    const act = btn.dataset.act;
    if (act === 'refresh') {
      btn.disabled = true;
      await Promise.all([loadSummary(), loadTrend(), loadErrors()]);
      btn.disabled = false;
      if (state.summaryError || state.trendError || state.errorsError) notify.warn('刷新完成，但有数据没读到');
      else notify.ok('已刷新');
    } else if (act === 'to-services') {
      ctx.go('services');
    } else if (act === 'to-logs') {
      ctx.go('logs');
    } else if (act === 'explain') {
      await explain(Number(btn.dataset.i), btn);
    } else if (act === 'explain-close') {
      state.explain = null;
      renderExplain();
    } else if (act === 'clear') {
      const ok = await confirmDialog({
        title: '清空采样记录？',
        desc: '只删本机保存的 CPU / 内存 / 磁盘历史点，服务和日志都不受影响。清空后趋势图要等下一帧（最多 30 秒）才有数据。',
        confirm: '清空',
        danger: true,
      });
      if (!ok) return;
      const res = await api.metricsClear();
      if (!res.ok) return notify.error(res.err || '清空失败');
      notify.ok(res.removed ? `已清空 ${res.removed} 个采样点` : '本来就没有采样记录');
      state.items = [];
      state.summary = null;
      state.summaryLoaded = false;
      state.explain = null;
      state.trendLoaded = false;
      drawTrend();
      renderKpi();
      renderProcs();
      renderExplain();
      await Promise.all([loadSummary(), loadTrend()]);
    }
  };
  root.addEventListener('click', onClick);

  const onResize = debounce(() => {
    if (!disposed) drawTrend();
  }, 160);
  window.addEventListener('resize', onResize);

  renderKpi();
  renderProcs();
  drawTrend();
  loadSummary();
  loadTrend();
  loadErrors();

  timer = setInterval(() => {
    if (disposed || document.visibilityState === 'hidden') return;
    loadSummary();
    loadTrend();
    tick += 1;
    if (tick % 4 === 0) loadErrors();
  }, 30000);

  return {
    destroy() {
      disposed = true;
      if (timer) clearInterval(timer);
      timer = 0;
      window.removeEventListener('resize', onResize);
      root.removeEventListener('click', onClick);
    },
  };
}
