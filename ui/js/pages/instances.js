/** 实例：一个 QQ 号 = 一份配置。同时挂多个号时，这里就是名册。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, fdate, num, copyText } from '../util.js';
import { emptyState, pageHead } from './common.js';

export function mount(root, ctx) {
  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '实例',
        desc: '每个实例对应一个 QQ 号和一套独立配置，互不干扰。',
        actions: `<button class="btn btn--primary" data-act="add">${icon('plus', 15)}新建实例</button>`,
      })}
      <div id="inst-list"></div>
    </div>`;

  const list = root.querySelector('#inst-list');
  let conflicts = [];
  let statusAll = [];
  let timer = null;

  async function loadStatuses() {
    const res = await api.serviceStatus().catch(() => null);
    statusAll = res?.instances || [];
    render();
  }

  async function loadConflicts() {
    const res = await api.conflicts();
    conflicts = res.items || [];
    render();
  }

  function conflictOf(it) {
    return conflicts.filter((c) => c.id === it.id || c.instance === it.id || c.name === it.name);
  }

  function render() {
    const rows = ctx.store.instances || [];
    if (!rows.length) {
      list.innerHTML = emptyState({
        iconName: 'layers',
        title: '还没有实例',
        desc: '默认会有一个「主号」，你可以直接改它的 QQ 号，也可以再加一个。',
        action: `<button class="btn btn--primary" data-act="add">${icon('plus', 15)}新建实例</button>`,
      });
      return;
    }
    list.innerHTML = `<div class="grid grid--2">${rows.map(card).join('')}${addCard()}</div>`;
  }

  function addCard() {
    return `
      <button class="card instance-add" data-act="add" type="button">
        <span class="instance-add__ico">${icon('plus', 20)}</span>
        <strong>再加一个号</strong>
        <span>每个号一套独立配置，互不影响</span>
      </button>`;
  }

  function card(it) {
    const row = statusAll.find((x) => x.id === it.id) || {};
    const svc = row.services || {};
    const running = svc.napcat?.status === 'running' || svc.astrbot?.status === 'running';
    const online = Boolean(it.onebotOpen);
    const bad = conflictOf(it);
    const proto = it.protocol === 'snowluma' ? 'snowluma' : 'napcat';
    const protoName = proto === 'snowluma' ? 'SnowLuma' : 'NapCat';
    const protoDesc = proto === 'snowluma' ? '挂在 QQ 上做 OneBot 转换' : '注入 QQ 后接管';
    return `
      <div class="card is-interactive instance" data-id="${esc(it.id)}">
        ${bad.length ? `<div class="notice notice--warn"><div class="notice__body"><strong>端口被占用</strong><p class="muted">${bad.map((c) => esc(c.detail || c.message || `${c.port} 已被 ${c.owner || '其他程序'} 占用`)).join('；')}</p></div></div>` : ''}
        <div class="card-head">
          <div class="svc__head">
            <div class="instance__avatar">${esc((it.name || 'Q').slice(0, 1))}</div>
            <div class="svc__title">
              <h3>${esc(it.name || '未命名')}
                ${it.active ? '<span class="pill pill--brand">当前</span>' : ''}
                ${it.enabled === false ? '<span class="pill">已停用</span>' : running ? '<span class="pill pill--ok">运行中</span>' : '<span class="pill">待机</span>'}
              </h3>
              <p class="mono">${esc(it.qq || '未绑定 QQ')}</p>
            </div>
          </div>
          <div class="inline">
            <button class="icon-btn" data-act="edit" data-id="${esc(it.id)}" title="编辑">${icon('settings', 15)}</button>
            <button class="icon-btn icon-btn--danger" data-act="del" data-id="${esc(it.id)}" title="删除">${icon('trash', 15)}</button>
          </div>
        </div>
        <dl class="kv">
          <div class="kv__row"><dt>OneBot 端口</dt><dd class="mono">${esc(String(it.port || 6199))}${online ? '<i class="dot dot--ok" title="端口已监听"></i>' : ''}</dd></div>
          <div class="kv__row"><dt>协议端</dt><dd><span class="pill ${proto === 'snowluma' ? 'pill--brand' : ''}">${esc(protoName)}</span> <span class="muted" style="font-size:11.5px">${esc(protoDesc)}</span></dd></div>
          <div class="kv__row"><dt>协议端 WebUI</dt><dd class="mono">${esc(String(it.napcatPort || 6099))}</dd></div>
          <div class="kv__row"><dt>AstrBot Dashboard</dt><dd class="mono">${esc(String(it.astrbotPort || 6185))}</dd></div>
          <div class="kv__row"><dt>访问令牌</dt><dd class="mono">${it.token ? '已设置' : '<span class="muted">空</span>'}</dd></div>
          <div class="kv__row"><dt>创建时间</dt><dd>${fdate(it.createdAt)}</dd></div>
        </dl>
        <div class="instance__foot">
          <button class="btn btn--sm btn--ghost" data-act="copy-token" data-id="${esc(it.id)}">${icon('copy', 13)}复制令牌</button>
          <button class="btn btn--sm btn--ghost" data-act="apply" data-id="${esc(it.id)}" title="把这个实例的端口与端口令牌写进 AstrBot / NapCat 配置">${icon('route', 13)}一键接线</button>
          ${running ? `<button class="btn btn--sm" data-act="restart-inst" data-id="${esc(it.id)}">${icon('refresh', 13)}重启</button><button class="btn btn--sm btn--danger" data-act="stop-inst" data-id="${esc(it.id)}">${icon('stop', 13)}停止</button>` : `<button class="btn btn--sm btn--primary" data-act="start-inst" data-id="${esc(it.id)}">${icon('play', 13)}启动</button>`}
          ${it.active ? '' : `<button class="btn btn--sm" data-act="active" data-id="${esc(it.id)}">设为当前</button>`}
          <span class="grow"></span>
          <span class="muted" style="font-size:11.5px">${esc(it.id)}</span>
        </div>
      </div>`;
  }

  function form(it) {
    const v = it || {};
    return `
      <div class="form-grid">
        <label class="field field--full">
          <span class="field__label">名称</span>
          <input class="input" name="name" value="${esc(v.name || '')}" placeholder="主号 / 小号 / 测试号" />
        </label>
        <label class="field">
          <span class="field__label">QQ 号</span>
          <input class="input mono" name="qq" value="${esc(v.qq || '')}" inputmode="numeric" placeholder="5–12 位数字" />
          <span class="field__hint" data-err-for="qq"></span>
        </label>
        <label class="field">
          <span class="field__label">OneBot 端口</span>
          <input class="input mono" name="port" type="number" min="1024" max="65535" value="${v.port || 6199}" />
        </label>
        <label class="field">
          <span class="field__label">NapCat WebUI 端口</span>
          <input class="input mono" name="napcatPort" type="number" min="1024" max="65535" value="${v.napcatPort || 6099}" />
        </label>
        <label class="field">
          <span class="field__label">AstrBot Dashboard 端口</span>
          <input class="input mono" name="astrbotPort" type="number" min="1024" max="65535" value="${v.astrbotPort || 6185}" />
        </label>
        <div class="row-actions field--full">
          <button class="btn btn--sm" type="button" data-act="auto-port">${icon('bolt', 14)}自动挑空闲端口</button>
          <span class="field__help" data-port-note>保存后再点一次「一键接线」，新端口才会写进 AstrBot / NapCat。</span>
        </div>
        <label class="field">
          <span class="field__label">协议端</span>
          <select class="input" name="protocol">
            <option value="napcat"${v.protocol === 'snowluma' ? '' : ' selected'}>NapCat（默认）</option>
            <option value="snowluma"${v.protocol === 'snowluma' ? ' selected' : ''}>SnowLuma</option>
          </select>
          <span class="field__help">两者二选一：NapCat 更成熟，SnowLuma 直接挂在已登录的 QQ 上，扫码在 QQ 窗口里。</span>
        </label>
        <label class="field">
          <span class="field__label">访问令牌</span>
          <input class="input mono" name="token" value="${esc(v.token || '')}" placeholder="出厂 zhuxin；留空则不校验" />
          <span class="field__help">NapCat / SnowLuma 与 AstrBot 两边写同一个值，改完点「一键接线」才生效。</span>
        </label>
        <label class="row-switch field--full">
          <span>
            <strong>启用</strong>
            <small>停用后不参与一键启动</small>
          </span>
          <span class="switch">
            <input type="checkbox" name="enabled" ${v.enabled === false ? '' : 'checked'}>
            <span class="switch__track"></span>
          </span>
        </label>
      </div>`;
  }

  function openForm(it) {
    const editing = !!it;
    const m = modal({
      title: editing ? '编辑实例' : '新建实例',
      desc: editing ? '改完保存即可，正在运行的进程需要重启才生效。' : '同一个 QQ 号只需要建一次。',
      wide: false,
      body: form(it),
      actions: [
        { label: '取消', variant: 'ghost', run: (close) => close() },
        {
          label: editing ? '保存' : '创建',
          variant: 'primary',
          run: async (close, rootEl) => {
            const data = readForm(rootEl);
            const err = validate(data);
            if (err) {
              const el = rootEl.querySelector('[data-err-for="qq"]');
              if (el) el.textContent = err;
              return false;
            }
            const res = editing
              ? await api.instanceUpdate(it.id, data)
              : await api.instanceCreate(data);
            if (!res.ok) {
              notify.error(res.err || '保存失败');
              return false;
            }
            notify.ok(editing ? '已保存；端口有改动就点一下「一键接线」' : '实例已创建');
            await ctx.refreshInstances();
            await loadConflicts();
            render();
            close();
          },
        },
      ],
    });
    m.root.querySelector('[data-act="auto-port"]')?.addEventListener('click', async () => {
      const res = await api.instanceSuggest();
      if (!res.ok) return notify.error(res.err || '找空闲端口失败');
      m.root.querySelector('[name="port"]').value = res.port;
      m.root.querySelector('[name="napcatPort"]').value = res.napcatPort;
      m.root.querySelector('[name="astrbotPort"]').value = res.astrbotPort;
      notify.ok(`挑到 ${res.port} / ${res.napcatPort} / ${res.astrbotPort}`);
    });
    const first = m.root.querySelector('input[name="name"]');
    if (first) setTimeout(() => first.focus(), 60);
  }

  function readForm(rootEl) {
    const get = (n) => rootEl.querySelector(`[name="${n}"]`);
    return {
      name: get('name').value.trim(),
      qq: get('qq').value.trim(),
      port: Number(get('port').value) || 6199,
      napcatPort: Number(get('napcatPort').value) || 6099,
      astrbotPort: Number(get('astrbotPort').value) || 6185,
      token: get('token').value.trim(),
      protocol: get('protocol') ? get('protocol').value : 'napcat',
      enabled: get('enabled').checked,
    };
  }

  function validate(d) {
    if (!d.name) return '给它起个名字';
    if (d.qq && !/^\d{5,12}$/.test(d.qq)) return 'QQ 号应该是 5–12 位数字';
    if (d.port < 1024 || d.port > 65535) return '端口范围 1024–65535';
    return '';
  }

  render();
  loadConflicts();
  loadStatuses();
  timer = setInterval(loadStatuses, 8000);

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    const id = btn.dataset.id;
    const it = (ctx.store.instances || []).find((x) => x.id === id);

    if (act === 'add') {
      openForm(null);
    } else if (act === 'edit' && it) {
      openForm(it);
    } else if (act === 'del' && it) {
      const ok = await confirmDialog({
        title: `删除「${it.name}」？`,
        desc: '只会删掉这份配置记录，不会卸载程序，也不会动聊天数据。',
        confirm: '删除',
        danger: true,
      });
      if (!ok) return;
      const res = await api.instanceDelete(it.id);
      if (res.ok) {
        notify.ok('已删除');
        await ctx.refreshInstances();
        render();
      } else notify.error(res.err || '删除失败');
    } else if (act === 'copy-token' && it) {
      await copyText(it.token || '');
      notify.ok(it.token ? '令牌已复制' : '这个实例没有设置令牌');
    } else if (act === 'active' && it) {
      const res = await api.instanceActive(it.id);
      if (!res.ok) return notify.error(res.err || '切换失败');
      notify.ok(`已切到「${it.name}」`);
      await ctx.refreshInstances();
      render();
    } else if (act === 'start-inst' && it) {
      btn.disabled = true;
      if (it.protocol === 'snowluma') {
        const info = await api.snowluma(it.id).catch(() => null);
        if (info && !info.installed) {
          btn.disabled = false;
          notify.error('SnowLuma 还没装好，先去「扩展 · 组件更新」装一下');
          return;
        }
      }
      const res = await api.service('all', 'start', it.id);
      btn.disabled = false;
      if (!res.ok) notify.error(res.err || '启动失败');
      else notify.ok('已启动，稍等十几秒');
      setTimeout(loadStatuses, 1200);
    } else if (act === 'stop-inst' && it) {
      btn.disabled = true;
      const res = await api.service('all', 'stop', it.id);
      btn.disabled = false;
      if (!res.ok) notify.error(res.err || '停止失败');
      else notify.ok('已停止');
      setTimeout(loadStatuses, 800);
    } else if (act === 'restart-inst' && it) {
      btn.disabled = true;
      const res = await api.service('all', 'restart', it.id);
      btn.disabled = false;
      if (!res.ok) notify.error(res.err || '重启失败');
      else notify.ok('正在重启，稍等十几秒');
      setTimeout(loadStatuses, 1500);
    } else if (act === 'apply' && it) {
      btn.disabled = true;
      const res = await api.instanceApply(it.id);
      btn.disabled = false;
      if (!res.ok) return notify.error(res.err || '接线失败');
      notify.ok(res.needsRestart ? '接线已写入，重启服务后生效' : '接线已写入');
      await ctx.refreshInstances();
      render();
    }
  });

  return {
    update(store) {
      if (store.instances) render();
    },
    destroy() {
      if (timer) clearInterval(timer);
    },
  };
}
