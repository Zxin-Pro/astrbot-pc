/** 概览：一眼看到「在不在线、今天忙不忙、有没有出事」。 */

import { api } from '../api.js';
import { bars, sparkline } from '../charts.js';
import { notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, num, dur, bytes, timeAgo, fdate } from '../util.js';
import { kvRow, pageHead, statusPill } from './common.js';

const TILES = [
  { key: 'online', label: '今日在线', icon: 'clock', hint: '累计运行时长' },
  { key: 'messages', label: '今日消息', icon: 'message', hint: '收到并处理的条数' },
  { key: 'errors', label: '今日异常', icon: 'alert', hint: '日志里的错误行' },
  { key: 'services', label: '在线服务', icon: 'server', hint: 'NapCat / AstrBot' },
];

export function mount(root, ctx) {
  const s = ctx.store;

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '概览',
        desc: '这台电脑上的 QQ 机器人现在怎么样，一眼看完。',
        actions: `
          <button class="btn" data-act="refresh">${icon('refresh', 15)}刷新</button>
          <button class="btn btn--primary" data-act="start-all">${icon('play', 15)}一键启动</button>`,
      })}

      <div class="grid grid--4" id="tiles"></div>

      <div class="section">
        <div class="grid grid--main">
          <div class="stack" id="svc-zone"></div>
          <div class="stack">
            <div class="card">
              <div class="card-head">
                <div>
                  <h3>今日节奏</h3>
                  <p class="sub" id="chart-sub">每小时消息量</p>
                </div>
                <span class="tag" id="chart-total">—</span>
              </div>
              <div id="chart-bars"></div>
              <div class="spread" id="chart-axis" style="margin-top:10px;font-size:11px">
                <span class="muted" id="chart-from">00:00</span>
                <span class="muted" id="chart-to">现在</span>
              </div>
            </div>
            <div class="card">
              <div class="card-head"><h3>环境</h3><span class="tag" id="env-ready">—</span></div>
              <dl class="kv" id="env-kv"></dl>
            </div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-head">
          <h2>最近日志 <span class="muted" id="log-hint">AstrBot 输出</span></h2>
          <button class="btn btn--sm btn--ghost" data-act="to-logs">查看全部${icon('chevron', 14)}</button>
        </div>
        <div class="card card--tight" id="recent-log"></div>
      </div>
    </div>`;

  const tiles = root.querySelector('#tiles');
  const svcZone = root.querySelector('#svc-zone');
  const chartBars = root.querySelector('#chart-bars');
  const envKv = root.querySelector('#env-kv');
  const recent = root.querySelector('#recent-log');

  function renderTiles() {
    const t = s.overview?.today || {};
    const svc = s.services || {};
    const arr = ['napcat', 'astrbot'].map((k) => svc[k]).filter(Boolean);
    const running = arr.filter((x) => x.status === 'running').length;
    const vals = {
      online: dur(t.onlineSec || 0, '0 分钟'),
      messages: num(t.messages || 0),
      errors: num(t.errors || 0),
      services: `${running}<small>/ ${arr.length}</small>`,
    };
    const series = (s.overview?.series || []).map((x) => x.m);
    tiles.innerHTML = TILES.map((tile) => {
      const isNum = tile.key === 'messages' || tile.key === 'errors';
      const value = vals[tile.key];
      return `
        <div class="stat">
          <div class="stat__label">${icon(tile.icon, 14)}${tile.label}</div>
          <div class="stat__value">${isNum ? `<span data-num="${tile.key}">${value}</span>` : value}</div>
          <div class="stat__foot">${esc(tile.hint)}</div>
          ${tile.key === 'messages' && series.length ? '<div class="stat__spark" data-spark></div>' : ''}
        </div>`;
    }).join('');

    const host = tiles.querySelector('[data-spark]');
    if (host) host.appendChild(sparkline(series.slice(-14), { w: 240, h: 40 }));
  }

  function renderServices() {
    const svc = s.services || {};
    const order = ['napcat', 'astrbot'];
    svcZone.innerHTML = order.map((k) => {
      const it = svc[k];
      if (!it) return '';
      const res = it.resources || {};
      return `
        <div class="card is-interactive">
          <div class="card-head">
            <div class="svc__head" style="gap:12px">
              <div class="svc__icon ${k === 'napcat' ? 'is-napcat' : ''}">${icon(k === 'napcat' ? 'route' : 'shield', 19)}</div>
              <div class="svc__title">
                <h3>${esc(it.name)}${statusPill(it.status)}</h3>
                <p>端口 ${it.port} · ${it.pid ? `PID ${it.pid}` : '未运行'}</p>
              </div>
            </div>
            <div class="inline">
              <button class="btn btn--sm" data-svc="${k}" data-act="restart" title="重启">${icon('refresh', 14)}</button>
              <button class="btn btn--sm ${it.status === 'running' ? 'btn--danger' : 'btn--primary'}" data-svc="${k}" data-act="${it.status === 'running' ? 'stop' : 'start'}">
                ${it.status === 'running' ? '停止' : '启动'}
              </button>
            </div>
          </div>
          <dl class="svc__meta">
            <div><dt>运行时长</dt><dd>${dur(it.uptime || 0)}</dd></div>
            <div><dt>内存</dt><dd>${res.rss ? bytes(res.rss) : '—'}</dd></div>
            <div><dt>CPU</dt><dd>${res.cpu != null ? `${res.cpu}%` : '—'}</dd></div>
          </dl>
          ${it.message ? `<p class="muted" style="margin-top:10px;font-size:12px">${esc(it.message)}</p>` : ''}
        </div>`;
    }).join('');

    const ready = s.env?.ready;
    root.querySelector('#env-ready').textContent = ready ? '就绪' : '待补齐';
    const app = s.app || {};
    envKv.innerHTML = [
      kvRow('数据目录', `<span class="mono truncate" title="${esc(app.dataRoot || '')}">${esc(app.dataRoot || '—')}</span>`),
      kvRow('界面版本', `v${esc(s.version || '1.0.0')}`),
      kvRow('Python', esc(app.python || '—')),
      kvRow('启动方式', app.shell ? '桌面窗口' : '浏览器'),
    ].join('');
  }

  function renderChart() {
    const series = s.overview?.series || [];
    const values = series.map((x) => x.m);
    const labels = series.map((x) => x.hour);
    const total = values.reduce((a, b) => a + b, 0);
    chartBars.innerHTML = '';

    if (!total) {
      chartBars.innerHTML = `
        <div class="chart-empty">
          ${icon('activity', 22)}
          <p>还没有消息进来</p>
          <span>机器人上线并收到群聊后，这里会按小时画出节奏</span>
        </div>`;
    } else {
      chartBars.appendChild(bars(values, { w: 320, h: 92, labels, color: 'var(--brand-500)' }));
    }

    root.querySelector('#chart-total').textContent = `${num(total)} 条`;
    root.querySelector('#chart-sub').textContent = total
      ? `最近 24 小时 · 峰值 ${num(Math.max(0, ...values))} 条/时`
      : '最近 24 小时 · 暂无数据';
    const axis = root.querySelector('#chart-axis');
    if (axis) axis.hidden = !total;
    if (series.length) {
      root.querySelector('#chart-from').textContent = series[0].hour;
      root.querySelector('#chart-to').textContent = series[series.length - 1].hour;
    }
  }

  function renderRecent(rows) {
    if (!rows.length) {
      recent.innerHTML = `<p class="muted" style="padding:10px 4px;font-size:12px">还没有日志。启动服务后这里会滚动显示最近几行。</p>`;
      return;
    }
    recent.innerHTML = rows.slice(-7).map(({ text, level }) => `
      <div class="log-line ${level === 'error' ? 'is-error' : level === 'warn' ? 'is-warn' : ''}" style="padding:2px 4px">
        <span class="log-line__txt mono">${esc(text)}</span>
      </div>`).join('');
  }

  let lastRows = [];

  async function loadRecent() {
    const res = await api.logTail('', 12, true);
    if (!res.ok) {
      renderRecent([]);
      return;
    }
    root.querySelector('#log-hint').textContent = res.name || 'AstrBot 输出';
    lastRows = (res.lines || []).map((t, i) => ({ text: t, level: (res.levels || [])[i] }));
    renderRecent(lastRows);
  }

  renderTiles();
  renderServices();
  renderChart();
  loadRecent();

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'refresh') {
      await ctx.refresh();
      notify.ok('已刷新');
    } else if (act === 'start-all') {
      btn.disabled = true;
      const res = await api.service('all', 'start');
      btn.disabled = false;
      if (res.ok) notify.ok('已发出启动指令');
      else notify.error(res.err || '启动失败');
      ctx.refresh();
    } else if (act === 'to-logs') {
      ctx.go('logs');
    } else if (act === 'start' || act === 'stop' || act === 'restart') {
      const key = btn.dataset.svc;
      btn.disabled = true;
      const label = { start: '启动', stop: '停止', restart: '重启' }[act];
      const res = await api.service(key, act);
      btn.disabled = false;
      if (res.ok) notify.ok(`${label}指令已执行`);
      else notify.error(res.err || `${label}失败`);
      ctx.refresh();
    }
  });

  return {
    update(store, reason) {
      if (reason === 'log') {
        const msg = store.lastLog;
        if (msg) {
          root.querySelector('#log-hint').textContent = (msg.path || '').split(/[\\/]/).pop();
          lastRows = lastRows.concat(msg.lines.map((t, i) => ({ text: t, level: (msg.levels || [])[i] }))).slice(-12);
          renderRecent(lastRows);
        }
        return;
      }
      if (reason === 'deploy') return;
      renderTiles();
      renderServices();
      renderChart();
    },
  };
}
