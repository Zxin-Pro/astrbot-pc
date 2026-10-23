/** 服务：唯一的「开关总闸」。进程、端口、资源、快速入口全在这一页。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify } from '../components.js';
import { ring } from '../charts.js';
import { icon } from '../icons.js';
import { esc, bytes, dur, num, copyText } from '../util.js';
import { pageHead, statusPill } from './common.js';

const META = {
  napcat: {
    icon: 'route',
    title: 'NapCat',
    sub: 'QQ 协议适配层，负责和手机 QQ 保持一条长连接。',
    webui: 'NapCat WebUI',
  },
  astrbot: {
    icon: 'shield',
    title: 'AstrBot',
    sub: '机器人大脑，接消息、调模型、回话。',
    webui: 'AstrBot 控制台',
  },
};

export function mount(root, ctx) {
  let busy = false;

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '服务',
        desc: '两个进程各自独立，任何一个挂了都不影响另一个的数据。',
        actions: `
          <button class="btn" data-act="refresh">${icon('refresh', 15)}刷新状态</button>
          <button class="btn btn--primary" data-act="all-start">${icon('play', 15)}全部启动</button>
          <button class="btn btn--danger" data-act="all-stop">${icon('stop', 15)}全部停止</button>`,
      })}
      <div class="grid grid--2" id="svc-grid"></div>

      <div class="section">
        <div class="section-head"><h2>端口与连通性</h2></div>
        <div class="card card--flush">
          <table class="table">
            <thead><tr><th>用途</th><th>地址</th><th>状态</th><th class="ta-r">操作</th></tr></thead>
            <tbody id="port-body"></tbody>
          </table>
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>AstrBot 控制台账号</h2></div>
        <div class="card card--tight" id="creds-card"></div>
      </div>

      <div class="section">
        <div class="section-head"><h2>常见处理</h2></div>
        <div class="grid grid--3">
          <button class="card card--tight is-interactive tile-btn" data-act="open-data">
            <span class="tile-btn__ico">${icon('folder', 18)}</span>
            <span><strong>打开数据目录</strong><small>配置、日志、备份都在这里</small></span>
          </button>
          <button class="card card--tight is-interactive tile-btn" data-act="open-webui">
            <span class="tile-btn__ico">${icon('external', 18)}</span>
            <span><strong>AstrBot 控制台</strong><small>模型、插件、人格设定</small></span>
          </button>
          <button class="card card--tight is-interactive tile-btn" data-act="open-napcat">
            <span class="tile-btn__ico">${icon('route', 18)}</span>
            <span><strong>NapCat WebUI</strong><small>查看账号与消息统计</small></span>
          </button>
          <button class="card card--tight is-interactive tile-btn" data-act="rewire">
            <span class="tile-btn__ico">${icon('route', 18)}</span>
            <span><strong>手动对接 AstrBot</strong><small>把当前实例的地址与令牌重写进配置</small></span>
          </button>
        </div>
      </div>
    </div>`;

  const grid = root.querySelector('#svc-grid');
  const portBody = root.querySelector('#port-body');
  const credsCard = root.querySelector('#creds-card');
  let creds = null;

  function renderCreds() {
    const c = creds;
    if (!c) {
      credsCard.innerHTML = '<p class="muted" style="font-size:12.5px">读取账号信息…</p>';
      return;
    }
    if (!c.ok) {
      credsCard.innerHTML = `<div class="notice notice--warn"><div class="notice__body"><strong>还没读到控制台账号</strong><p class="muted">${esc(c.err || '先部署并启动一次 AstrBot')}</p></div></div>`;
      return;
    }
    credsCard.innerHTML = `
      <div class="card-head" style="margin-bottom:10px">
        <div>
          <h3 style="font-size:14px">${esc(c.username || 'astrbot')}</h3>
          <p class="muted" style="font-size:12px">${c.password ? '默认密码，建议改掉' : '密码是哈希存的，忘了只能重设'} · 端口 ${esc(String(c.port || 6185))}</p>
        </div>
        <div class="inline">
          <button class="btn btn--sm" data-act="copy-user">${icon('copy', 13)}复制账号</button>
          ${c.password ? `<button class="btn btn--sm" data-act="copy-pass">${icon('copy', 13)}复制密码</button>` : ''}
          <button class="btn btn--sm btn--ghost" data-act="reset-pass">重设密码</button>
          <button class="btn btn--sm btn--primary" data-act="open-console">${icon('external', 13)}打开控制台</button>
        </div>
      </div>
      ${c.password ? `<p class="mono" style="font-size:14px;margin:0">${esc(c.username)} / ${esc(c.password)}</p>` : `<p class="field__help" style="margin:0">${esc(c.hint || '')}</p>`}
      ${c.changeRequired ? '<p class="field__hint" style="color:var(--warn)">AstrBot 要求下次登录后修改密码。</p>' : ''}`;
  }

  async function loadCreds() {
    const res = await api.consoleCreds();
    creds = res;
    renderCreds();
  }

  function render() {
    const svc = ctx.store.services || {};
    grid.innerHTML = Object.keys(META).map((key) => {
      const it = svc[key] || {};
      const m = META[key];
      const res = it.resources || {};
      const running = it.status === 'running';
      const cpu = Number(res.cpu || 0);
      return `
        <div class="card">
          <div class="card-head">
            <div class="svc__head">
              <div class="svc__icon ${key === 'napcat' ? 'is-napcat' : ''}">${icon(m.icon, 20)}</div>
              <div class="svc__title">
                <h3>${m.title}${statusPill(it.status)}</h3>
                <p>${esc(m.sub)}</p>
              </div>
            </div>
          </div>
          <div class="svc__body-grid">
            <div class="svc__gauge">
              <div class="svc__ring" data-gauge="${key}"></div>
              <span class="svc__gauge-cap">CPU 占用</span>
            </div>
            <dl class="svc__facts">
              <div class="fact"><dt>监听端口</dt><dd class="mono">127.0.0.1:${it.port ?? '—'}</dd></div>
              <div class="fact"><dt>进程号</dt><dd class="mono">${it.pid || '—'}</dd></div>
              <div class="fact"><dt>内存</dt><dd>${res.rss ? bytes(res.rss) : '—'}</dd></div>
              <div class="fact"><dt>运行时长</dt><dd>${dur(it.uptime || 0)}</dd></div>
              <div class="fact"><dt>自动重启</dt><dd>${it.autoRestart === false ? '关闭' : '开启'}</dd></div>
              <div class="fact"><dt>重启次数</dt><dd>${num(it.restarts || 0)} 次</dd></div>
            </dl>
          </div>
          ${it.message ? `<p class="svc__note">${icon('info', 14)}<span>${esc(it.message)}</span></p>` : ''}
          <div class="svc__actions">
            ${running
              ? `<button class="btn" data-svc="${key}" data-act="restart">${icon('refresh', 15)}重启</button>
                 <button class="btn btn--danger" data-svc="${key}" data-act="stop">${icon('stop', 15)}停止</button>`
              : `<button class="btn btn--primary" data-svc="${key}" data-act="start">${icon('play', 15)}启动</button>`}
            <button class="btn btn--ghost" data-open="${key === 'napcat' ? 'napcat' : 'webui'}">
              ${icon('external', 15)}${esc(m.webui)}
            </button>
          </div>
        </div>`;
      }).join('');

    Object.keys(META).forEach((key) => {
      const it = svc[key] || {};
      const host = grid.querySelector(`[data-gauge="${key}"]`);
      const cpu = Number(it.resources?.cpu || 0);
      if (host) {
        host.innerHTML = '';
        host.appendChild(ring(cpu, { size: 88, stroke: 7, label: '', suffix: '%' }));
      }
    });

    const ports = [
      { name: 'OneBot 反向 WS', host: '127.0.0.1', port: 6199, key: 'onebot' },
      { name: 'AstrBot 控制台', host: '127.0.0.1', port: svc.astrbot?.port || 6185, key: 'astrbot' },
      { name: 'NapCat WebUI', host: '127.0.0.1', port: svc.napcat?.port || 6099, key: 'napcat' },
      { name: '本界面 API', host: ctx.store.server?.host || '127.0.0.1', port: ctx.store.server?.port || 17650, key: 'api' },
    ];
    const probe = ctx.store.ports || {};
    portBody.innerHTML = ports.map((p) => {
      const alive = probe[p.port];
      const st = alive === undefined || alive === null
        ? `<span class="pill">未知</span>`
        : alive ? `<span class="pill pill--ok">已监听</span>` : `<span class="pill pill--bad">未监听</span>`;
      return `<tr>
        <td><strong>${esc(p.name)}</strong></td>
        <td class="mono muted">${p.host}:${p.port}</td>
        <td>${st}</td>
        <td class="ta-r"><button class="btn btn--sm btn--ghost" data-copy="${p.port}">${icon('copy', 13)}复制</button></td>
      </tr>`;
    }).join('');
  }

  render();
  loadCreds();

  function resetPassModal() {
    const gen = () => {
      const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789';
      let out = '';
      for (let i = 0; i < 16; i++) out += chars[Math.floor(Math.random() * chars.length)];
      return out;
    };
    modal({
      title: '重设控制台密码',
      desc: '密码会同时写成 md5 与 pbkdf2 两种哈希，重启 AstrBot 后生效。至少 8 位，含大小写字母和数字。',
      body: `
        <label class="field"><span class="field__label">用户名</span>
          <input class="input mono" name="user" value="${esc(creds?.username || 'astrbot')}" /></label>
        <label class="field"><span class="field__label">新密码</span>
          <input class="input mono" name="pass" value="${gen()}" /></label>
        <div class="row-actions">
          <button class="btn btn--sm" type="button" data-act="gen">${icon('refresh', 14)}换一个</button>
          <span class="field__help">生成的是 16 位随机密码，复制走再保存。</span>
        </div>`,
      actions: [
        { label: '取消' },
        {
          label: '保存并复制',
          primary: true,
          run: async (close, rootEl) => {
            const user = rootEl.querySelector('[name="user"]').value.trim();
            const pass = rootEl.querySelector('[name="pass"]').value.trim();
            if (pass.length < 8 || !/[A-Z]/.test(pass) || !/[a-z]/.test(pass) || !/\d/.test(pass)) {
              notify.warn('密码至少 8 位，且要同时有大小写字母和数字');
              return false;
            }
            const res = await api.consoleCredsReset(user, pass);
            if (!res.ok) {
              notify.error(res.err || '重设失败');
              return false;
            }
            await copyText(`${user} / ${pass}`);
            notify.ok('已保存，账号密码已复制；重启 AstrBot 后生效');
            creds = { ...(creds || {}), ...res, username: user };
            renderCreds();
            close();
          },
        },
      ],
      onMount: ({ root: el }) => {
        el.querySelector('[data-act="gen"]')?.addEventListener('click', () => {
          el.querySelector('[name="pass"]').value = gen();
        });
      },
    });
  }

  async function act(key, action) {
    if (busy) return;
    busy = true;
    document.body.style.cursor = 'progress';
    const res = await api.service(key, action);
    busy = false;
    document.body.style.cursor = '';
    const label = { start: '启动', stop: '停止', restart: '重启' }[action];
    if (res.ok) notify.ok(`${key === 'all' ? '全部服务' : META[key].title}：${label}指令已执行`);
    else notify.error(res.err || `${label}失败`);
    await ctx.refresh();
  }

  root.addEventListener('click', async (e) => {
    const copyBtn = e.target.closest('[data-copy]');
    if (copyBtn) {
      await copyText(`127.0.0.1:${copyBtn.dataset.copy}`);
      notify.ok('地址已复制');
      return;
    }
    const openBtn = e.target.closest('[data-open]');
    if (openBtn) {
      const res = await api.open(openBtn.dataset.open);
      if (!res.ok) notify.error(res.err || '打不开');
      return;
    }
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const action = btn.dataset.act;
    if (action === 'refresh') {
      await ctx.refresh();
      notify.ok('已刷新');
    } else if (action === 'all-start') {
      await act('all', 'start');
    } else if (action === 'all-stop') {
      const ok = await confirmDialog({
        title: '停止全部服务？',
        desc: '机器人会下线，QQ 消息不再有回复。数据不会丢。',
        confirm: '全部停止',
        danger: true,
      });
      if (ok) await act('all', 'stop');
    } else if (action === 'open-data') {
      const res = await api.open('data');
      if (!res.ok) notify.error(res.err || '打不开');
    } else if (action === 'open-webui' || action === 'open-napcat') {
      const res = await api.open(action === 'open-webui' ? 'webui' : 'napcat');
      if (!res.ok) notify.error(res.err || '打不开');
    } else if (action === 'open-console') {
      const res = await api.open('webui');
      if (!res.ok) notify.error(res.err || '打不开');
    } else if (action === 'copy-user') {
      await copyText(creds?.username || 'astrbot');
      notify.ok('账号已复制');
    } else if (action === 'copy-pass') {
      await copyText(creds?.password || '');
      notify.ok(creds?.password ? '密码已复制' : '默认密码不是 astrbot，只能重设');
    } else if (action === 'reset-pass') {
      resetPassModal();
    } else if (action === 'rewire') {
      const inst = (ctx.store.instances || []).find((x) => x.active) || (ctx.store.instances || [])[0];
      if (!inst) return notify.warn('先去「实例」页建一个实例');
      btn.disabled = true;
      const res = await api.instanceApply(inst.id);
      btn.disabled = false;
      if (!res.ok) return notify.error(res.err || '接线失败');
      notify.ok('已把当前实例写进 AstrBot / NapCat 配置，重启服务后生效');
    } else if (['start', 'stop', 'restart'].includes(action) && btn.dataset.svc) {
      await act(btn.dataset.svc, action);
    }
  });

  return {
    update(store) {
      render();
    },
  };
}
