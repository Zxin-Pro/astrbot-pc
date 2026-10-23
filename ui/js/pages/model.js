/** 模型与人格：给 AstrBot 配好中转站与人格，用户只贴一个密钥。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify } from '../components.js';
import { icon } from '../icons.js';
import { getSetting } from '../store.js';
import { esc } from '../util.js';
import { pageHead } from './common.js';

const PRESETS = [
  {
    id: '烛心',
    name: '烛心',
    desc: '默认：说话自然、简短，不端着',
    prompt:
      '你叫烛心，是一个住在电脑里的聊天伙伴。说话自然、简短、有分寸，像熟人聊天，不用敬语、不喊口号、不写小作文。' +
      '对方问技术问题就认真答，答完就停。不确定的事直接说不知道，不要编。' +
      '可以有一点自己的情绪和偏好，但别演。',
  },
  {
    id: '助手',
    name: '助手',
    desc: '中性助手，回答完整、条理清楚',
    prompt:
      '你是一个可靠的助手。回答要准确、完整、条理清楚，先给结论再给理由。' +
      '不确定就直说，不要编造事实或链接。',
  },
];

function pill(text, cls = '', dot = false) {
  return `<span class="pill ${cls}">${dot ? '<i class="dot live-dot"></i>' : ''}${esc(text)}</span>`;
}

export function mount(root, ctx) {
  const get = (path, def) => getSetting(path, def);

  let state = null;
  let relay = null;
  let routes = null;
  let health = null;
  let chatLog = [];
  let busy = {};

  root.innerHTML = `
    <div class="page page--narrow">
      ${pageHead({
        title: '模型',
        desc: '中转站、密钥、人格都在这儿配好；保存后重启 AstrBot 生效。',
        actions: `<button class="btn btn--sm btn--ghost" data-act="reload">${icon('refresh', 15)} 重新读取</button>`,
      })}
      <div id="model-body"></div>
    </div>`;

  const body = root.querySelector('#model-body');

  function relayCard() {
    const r = relay || {};
    const online = !!r.online;
    const ver = r.version ? `v${r.version}` : '';
    return `
      <div class="section">
        <div class="section-head">
          <h2>中转站</h2>
          <span class="hint">烛心推荐用这家</span>
        </div>
        <div class="card">
          <div class="relay-row">
            <span class="relay-row__ico">${icon('bolt', 18)}</span>
            <span class="grow">
              <strong>${esc(r.siteName || 'WorldCodes')}</strong>
              <small>${esc(r.subtitle || 'OpenAI 兼容中转站')}${r.latencyMs ? ` · ${r.latencyMs} ms` : ''}</small>
            </span>
            ${r.loading ? pill('检测中…', 'pill--warn') : online ? pill(ver ? `在线 ${ver}` : '在线', 'pill--ok', true) : pill(r.err ? '连不上' : '未检测', '')}
            <button class="btn btn--sm btn--ghost" data-act="relay-check">${icon('activity', 15)} 检测</button>
            <button class="btn btn--sm btn--primary" data-act="relay-register">${icon('external', 15)} 去注册</button>
          </div>
          <p class="hint" style="margin:12px 0 0">
            注册完在站点里生成一个 API 密钥（一般以 <span class="mono">sk-</span> 开头），粘到下面就行。
            邀请码 <span class="mono">CZLT</span> 已带在链接里。
          </p>
        </div>
      </div>`;
  }

  function modelCard() {
    const p = (state && state.provider) || {};
    const apiBase = p.apiBase || get('llm.apiBase', 'https://worldcodes.online/v1');
    const model = p.model || get('llm.model', '');
    const configured = !!(state && state.configured);
    return `
      <div class="section">
        <div class="section-head">
          <h2>模型</h2>
          ${configured ? pill('已配置', 'pill--ok', true) : pill('还没配', 'pill--warn')}
        </div>
        <div class="card">
          <div class="form-grid">
            <label class="field field--full">
              <span class="field__label">API 地址</span>
              <input class="input mono" id="f-base" value="${esc(apiBase)}" placeholder="https://worldcodes.online/v1" spellcheck="false">
              <span class="field__help">默认就是烛心推荐的中转站；换成别的 OpenAI 兼容网关也行。</span>
            </label>
            <label class="field field--full">
              <span class="field__label">API 密钥</span>
              <span class="field-inline">
                <input class="input mono" id="f-key" type="password" value="" placeholder="${p.hasKey ? `已保存 ${esc(p.key)}，留空则不修改` : 'sk-...'}" spellcheck="false" autocomplete="off">
                <button class="btn btn--sm btn--ghost" data-act="key-eye" type="button">显示</button>
                <button class="btn btn--sm btn--ghost" data-act="models" type="button">${icon('refresh', 15)} 拉模型</button>
              </span>
              <span class="field__help">密钥只写进本机的 AstrBot 配置，不会上传到任何地方。</span>
            </label>
            <label class="field field--full">
              <span class="field__label">模型名</span>
              <input class="input mono" id="f-model" list="model-list" value="${esc(model)}" placeholder="先贴密钥，再点「拉模型」" spellcheck="false">
              <datalist id="model-list"></datalist>
              <span class="field__help" id="model-hint">${model ? `当前用的是 ${esc(model)}` : '拉一次列表就能直接选，不用手打。'}</span>
            </label>
          </div>
          <div class="row-actions">
            <button class="btn btn--primary" data-act="save-model">${icon('check', 16)} 保存并启用</button>
            <span class="hint" id="save-hint">${configured ? '改完记得重启 AstrBot 才会用上新配置' : '保存后会写进 AstrBot 的配置，重启后生效'}</span>
          </div>
        </div>
      </div>`;
  }

  function routeCard() {
    const rs = routes || {};
    const items = rs.items || [];
    const hs = health || {};
    const hmap = new Map((hs.items || []).map((h) => [h.id, h]));
    const rows = items.map((it) => {
      const h = hmap.get(it.id);
      const status = h ? (h.ok ? pill(h.latencyMs + ' ms', 'pill--ok', true) : pill('连不上', 'pill--bad')) : (it.primary ? pill('主线路', 'pill--brand') : pill('备用', ''));
      return `<tr>
        <td><strong>${esc(it.name || it.id)}</strong>${it.primary ? ' <span class="pill pill--brand">主</span>' : ''}</td>
        <td class="mono">${esc(it.apiBase)}</td>
        <td class="mono">${esc(it.model || '—')}</td>
        <td class="mono">${esc(it.maskedKey || '—')}</td>
        <td>${status}</td>
        <td class="row-actions">
          <button class="btn btn--sm btn--ghost" data-route-edit="${esc(it.id)}">编辑</button>
          <button class="btn btn--sm btn--ghost" data-route-del="${esc(it.id)}">删除</button>
        </td>
      </tr>`;
    }).join('');
    return `
      <div class="section">
        <div class="section-head">
          <h2>线路</h2>
          ${hs.degraded ? pill('有线路不通', 'pill--warn') : hs.healthy ? pill('都通', 'pill--ok', true) : pill('未检测', '')}
          <span class="grow"></span>
          <button class="btn btn--sm btn--ghost" data-act="route-health">${icon('activity', 15)} 测速</button>
          <button class="btn btn--sm btn--ghost" data-act="route-add">${icon('plus', 15)} 添加线路</button>
        </div>
        <div class="card">
          ${items.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>名称</th><th>API 地址</th><th>模型</th><th>密钥</th><th>状态</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`
            : '<p class="hint">还没有线路。填一条就能用；再加一条就自动变成主备切换。</p>'}
          <p class="hint" style="margin:12px 0 0">
            按顺序从上往下用：主线路失败（401 / 429 / 超时）时 AstrBot 会自动换下一条。${rs.legacy ? '现在是旧的单线路配置，加第二条会切到多线路。' : ''}
          </p>
        </div>
      </div>`;
  }

  function personaCard() {
    const cur = (state && state.persona) || {};
    const personaId = cur.custom ? cur.id : (get('llm.personaId', '') || PRESETS[0].id);
    const prompt = cur.prompt && cur.custom ? cur.prompt : PRESETS[0].prompt;
    return `
      <div class="section">
        <div class="section-head">
          <h2>人格</h2>
          ${cur.custom ? pill('自定义', 'pill--ok', true) : pill('默认人格', '')}
        </div>
        <div class="card">
          <div class="preset-row">
            ${PRESETS.map((p) => `<button class="btn btn--sm btn--ghost" data-preset="${esc(p.id)}" type="button">${esc(p.name)}<small>${esc(p.desc)}</small></button>`).join('')}
          </div>
          <div class="form-grid">
            <label class="field">
              <span class="field__label">人格名</span>
              <input class="input" id="f-persona-id" value="${esc(personaId)}" placeholder="烛心" spellcheck="false">
              <span class="field__help">在 AstrBot 里显示的名字，也是它的 ID。</span>
            </label>
            <label class="field field--full">
              <span class="field__label">提示词</span>
              <textarea class="input" id="f-prompt" rows="7" placeholder="写它是谁、怎么说话、要注意什么">${esc(prompt)}</textarea>
              <span class="field__help">这段话会作为系统提示词发给模型。</span>
            </label>
          </div>
          <div class="row-actions">
            <button class="btn btn--primary" data-act="save-persona">${icon('check', 16)} 保存人格</button>
            <span class="hint">保存后自动设为 AstrBot 的默认人格</span>
          </div>
        </div>
      </div>`;
  }

  function chatCard() {
    const rows = (chatLog || []).map((m) => `
      <div class="chat-msg chat-msg--${m.role}">
        <span class="chat-msg__who">${m.role === 'user' ? '你' : '模型'}</span>
        <div class="chat-msg__text">${esc(m.text)}</div>
        ${m.meta ? `<small class="muted">${esc(m.meta)}</small>` : ''}
      </div>`).join('');
    return `
      <div class="section" id="chat-card">
        <div class="section-head">
          <h2>试聊</h2>
          <span class="hint">按当前人格走完整链路，不经过 QQ</span>
          <span class="grow"></span>
          ${chatLog.length ? '<button class="btn btn--sm btn--ghost" data-act="chat-clear">清空</button>' : ''}
        </div>
        <div class="card">
          <div class="chat-log" id="chat-log">${rows || '<p class="hint">发一句试试。会带你保存的人格、当前主线路，回复也走真实接口。</p>'}</div>
          <div class="field-inline" style="margin-top:12px">
            <input class="input grow" id="f-chat" placeholder="说点什么…" autocomplete="off">
            <button class="btn btn--primary" data-act="chat-send">${icon('message', 16)} 发送</button>
          </div>
          <span class="field__help">回复慢或报错，多半是线路或密钥的问题；保存模型后不用重启也能试。</span>
        </div>
      </div>`;
  }

  function applyCard() {
    return `
      <div class="section">
        <div class="section-head"><h2>生效</h2></div>
        <div class="card">
          <div class="relay-row">
            <span class="relay-row__ico">${icon('power', 18)}</span>
            <span class="grow">
              <strong>AstrBot 只在启动时读一次配置</strong>
              <small>模型和人格都是这样。保存完点右边重启一下，新配置才用得上。</small>
            </span>
            <button class="btn btn--sm" data-act="test">${icon('activity', 15)} 测连通</button>
            <button class="btn btn--sm btn--primary" data-act="restart">${icon('refresh', 15)} 重启 AstrBot</button>
          </div>
        </div>
      </div>`;
  }

  function render() {
    if (!state) {
      body.innerHTML = `<div class="card"><div class="skeleton" style="height:14px;width:40%"></div></div>`;
      return;
    }
    if (state.ok === false) {
      body.innerHTML = `<div class="card"><p class="hint">${esc(state.err || '读不到 AstrBot 配置')}</p></div>`;
      return;
    }
    if (!state.installed) {
      body.innerHTML = `
        <div class="empty">
          ${icon('cpu', 34, 1.4)}
          <strong>还没装 AstrBot</strong>
          <p>先去「部署」页把它装好，回来这里配模型。</p>
          <a class="btn btn--primary" href="#/deploy">去部署</a>
        </div>`;
      return;
    }
    // 中转站卡片单独放一格：它要异步检测，回来时只重画这一格。
    // 一开始整页重画，用户正在输的密钥会被冲掉（检测最长要等十几秒）。
    body.innerHTML = '<div id="relay-slot"></div>' + modelCard() + routeCard() + '<div id="chat-slot">' + chatCard() + '</div>' + personaCard() + applyCard();
    paintRelay();
  }

  function paintRelay() {
    const slot = body.querySelector('#relay-slot');
    if (slot) slot.innerHTML = relayCard();
  }

  async function loadAll() {
    const [s, r] = await Promise.all([api.llm(), api.llmRoutes().catch(() => null)]);
    state = s;
    routes = r;
    render();
    checkRelay();
  }

  async function checkRelay() {
    relay = { loading: true };
    paintRelay();
    const r = await api.relay();
    relay = r;
    paintRelay();
  }

  async function onSaveModel() {
    const apiBase = root.querySelector('#f-base')?.value.trim() || '';
    const keyInput = root.querySelector('#f-key');
    const typed = keyInput?.value.trim() || '';
    const model = root.querySelector('#f-model')?.value.trim() || '';
    const saved = state?.provider?.hasKey ? true : false;
    if (!typed && !saved) {
      notify.info('先贴一个 API 密钥');
      keyInput?.focus();
      return;
    }
    const btn = root.querySelector('[data-act="save-model"]');
    btn.disabled = true;
    const res = await api.llmModel({ apiBase, apiKey: typed, model });
    btn.disabled = false;
    if (!res.ok) {
      notify.info(res.err || '保存失败');
      return;
    }
    // 留空表示沿用已保存的密钥，界面不去改它
    if (!typed) {
      notify.ok('模型已更新，密钥沿用原来的');
    } else {
      notify.ok('模型已保存，重启 AstrBot 生效');
    }
    await loadAll();
  }

  async function onSavePersona() {
    const personaId = root.querySelector('#f-persona-id')?.value.trim() || '';
    const prompt = root.querySelector('#f-prompt')?.value || '';
    const res = await api.llmPersona({ personaId, prompt });
    if (!res.ok) {
      notify.info(res.err || '保存失败');
      return;
    }
    notify.ok('人格已保存，重启 AstrBot 生效');
    await loadAll();
  }

  async function onFetchModels() {
    const key = root.querySelector('#f-key')?.value.trim() || '';
    const apiBase = root.querySelector('#f-base')?.value.trim() || '';
    const btn = root.querySelector('[data-act="models"]');
    if (!key && !state?.provider?.hasKey) {
      notify.info('先贴密钥，才能拉模型列表');
      return;
    }
    btn.disabled = true;
    const res = await api.llmModels({ apiKey: key, apiBase });
    btn.disabled = false;
    if (!res.ok) {
      notify.info(res.err || '拉不到模型列表');
      return;
    }
    const list = root.querySelector('#model-list');
    if (list) list.innerHTML = res.models.map((m) => `<option value="${esc(m)}"></option>`).join('');
    const hint = root.querySelector('#model-hint');
    if (hint) hint.textContent = `拉到 ${res.count} 个模型，点输入框就能选`;
    const input = root.querySelector('#f-model');
    if (input && !input.value && res.models.length) input.value = res.models[0];
    notify.ok(`拉到 ${res.count} 个模型`);
  }

  async function onTest() {
    const btn = root.querySelector('[data-act="test"]');
    if (btn) {
      btn.disabled = true;
      btn.dataset.busy = '1';
    }
    const res = await api.llmTest();
    if (btn) {
      btn.disabled = false;
      delete btn.dataset.busy;
    }
    if (!res.ok) {
      notify.info(res.err || '连不上');
      return;
    }
    notify.ok(`通了：${res.model} · ${res.latencyMs} ms`);
  }

  async function onRestart() {
    const res = await api.service('astrbot', 'restart');
    if (!res.ok) {
      notify.info(res.err || '重启失败');
      return;
    }
    notify.ok('AstrBot 正在重启，稍等十几秒');
  }

  function paintChat() {
    const slot = root.querySelector('#chat-slot');
    if (slot) slot.innerHTML = chatCard();
    const log = root.querySelector('#chat-log');
    if (log) log.scrollTop = log.scrollHeight;
  }

  function openRouteModal(existing) {
    const it = existing || {};
    const form = `
      <div class="form-grid">
        <label class="field">
          <span class="field__label">名称</span>
          <input class="input" id="r-name" value="${esc(it.name || '')}" placeholder="主线路 / 备用">
        </label>
        <label class="field">
          <span class="field__label">权重</span>
          <input class="input mono" id="r-priority" value="${esc(String(it.priority ?? ((routes?.items || []).length + 1) * 10))}" inputmode="numeric">
          <span class="field__help">数字小的先用</span>
        </label>
        <label class="field field--full">
          <span class="field__label">API 地址</span>
          <input class="input mono" id="r-base" value="${esc(it.apiBase || '')}" placeholder="https://worldcodes.online/v1" spellcheck="false">
        </label>
        <label class="field field--full">
          <span class="field__label">API 密钥</span>
          <input class="input mono" id="r-key" type="password" value="" placeholder="${it.maskedKey ? '已保存 ' + esc(it.maskedKey) + '，留空不改' : 'sk-...'}" autocomplete="off">
        </label>
        <label class="field field--full">
          <span class="field__label">模型名</span>
          <input class="input mono" id="r-model" value="${esc(it.model || '')}" placeholder="gpt-4o-mini" spellcheck="false">
        </label>
      </div>`;
    modal({
      title: existing ? '编辑线路' : '添加线路',
      desc: '保存后会写进 AstrBot 的 agent_runner，重启后按顺序做主备切换。',
      body: form,
      actions: [
        { label: '取消' },
        {
          label: '保存',
          primary: true,
          run: async (close, rootEl) => {
            const name = rootEl.querySelector('#r-name')?.value.trim() || '';
            const apiBase = rootEl.querySelector('#r-base')?.value.trim() || '';
            const apiKey = rootEl.querySelector('#r-key')?.value.trim() || '';
            const model = rootEl.querySelector('#r-model')?.value.trim() || '';
            const priority = Number(rootEl.querySelector('#r-priority')?.value || 0) || ((routes?.items || []).length + 1) * 10;
            if (!apiBase || !model) {
              notify.info('API 地址和模型名都要填');
              return false;
            }
            const items = (routes?.items || []).map((x) => ({
              id: x.id, name: x.name, apiBase: x.apiBase, model: x.model,
              apiKey: '', enabled: x.enabled, priority: x.priority,
            }));
            const row = existing
              ? items.find((x) => x.id === existing.id)
              : null;
            if (row) {
              Object.assign(row, { name, apiBase, model, apiKey, priority });
            } else {
              items.push({ id: '', name, apiBase, apiKey, model, enabled: true, priority });
            }
            const res = await api.llmRoutesSave(items, true);
            if (!res.ok) {
              notify.info(res.err || '保存线路失败');
              return false;
            }
            await loadAll();
            if (res.apply && res.apply.ok === false) notify.warn(res.apply.err || '线路已存，写 AstrBot 失败');
            else notify.ok('线路已保存，重启 AstrBot 生效');
          },
        },
      ],
    });
  }

  async function onRouteHealth() {
    const btn = root.querySelector('[data-act="route-health"]');
    if (btn) btn.disabled = true;
    try {
      health = await api.llmRoutesHealth(true);
      render();
      if (health.ok) notify.ok('线路都通');
      else notify.warn(health.err || '有线路连不通');
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function onChatSend() {
    const input = root.querySelector('#f-chat');
    const text = input?.value.trim() || '';
    if (!text || busy.chat) return;
    busy.chat = true;
    chatLog.push({ role: 'user', text });
    if (input) input.value = '';
    paintChat();
    const res = await api.selftestChat(text);
    busy.chat = false;
    if (!res.ok) {
      chatLog.push({ role: 'model', text: res.err || '没发出去', meta: '失败' });
      notify.info(res.err || '试聊失败');
      paintChat();
      return;
    }
    const usage = res.usage || {};
    const meta = [res.model, res.latencyMs ? res.latencyMs + ' ms' : '', usage.total_tokens ? usage.total_tokens + ' tokens' : '', res.persona ? '人格 ' + res.persona : '']
      .filter(Boolean).join(' · ');
    chatLog.push({ role: 'model', text: res.reply || '', meta });
    if (chatLog.length > 20) chatLog = chatLog.slice(-20);
    paintChat();
  }

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act],[data-preset],[data-route-edit],[data-route-del]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (btn.dataset.routeEdit) {
      const it = (routes?.items || []).find((x) => x.id === btn.dataset.routeEdit);
      if (it) openRouteModal(it);
      return;
    }
    if (btn.dataset.routeDel) {
      const it = (routes?.items || []).find((x) => x.id === btn.dataset.routeDel);
      if (!it) return;
      const yes = await confirmDialog({ title: '删除线路', desc: '删掉「' + (it.name || it.id) + '」？至少得留一条。', confirm: '删除', danger: true });
      if (!yes) return;
      const res = await api.llmRouteDelete(it.id);
      if (!res.ok) notify.info(res.err || '删除失败');
      else { notify.ok('线路已删除'); await loadAll(); }
      return;
    }
    if (btn.dataset.preset) {
      const preset = PRESETS.find((p) => p.id === btn.dataset.preset);
      if (!preset) return;
      const idEl = root.querySelector('#f-persona-id');
      const promptEl = root.querySelector('#f-prompt');
      if (idEl) idEl.value = preset.name;
      if (promptEl) promptEl.value = preset.prompt;
      return;
    }
    if (act === 'reload') return loadAll();
    if (act === 'route-add') return openRouteModal(null);
    if (act === 'route-health') return onRouteHealth();
    if (act === 'chat-send') return onChatSend();
    if (act === 'chat-clear') {
      chatLog = [];
      await api.selftestClear();
      paintChat();
      return;
    }
    if (act === 'test') return onTest();
    if (act === 'relay-check') return checkRelay();
    if (act === 'relay-register') {
      const res = await api.openUrl((state && state.relay && state.relay.register) || 'https://worldcodes.online/register?invite_code=CZLT');
      if (!res.ok) notify.info(res.err || '打不开浏览器');
      return;
    }
    if (act === 'key-eye') {
      const input = root.querySelector('#f-key');
      if (!input) return;
      input.type = input.type === 'password' ? 'text' : 'password';
      btn.textContent = input.type === 'password' ? '显示' : '隐藏';
      return;
    }
    if (act === 'models') return onFetchModels();
    if (act === 'save-model') return onSaveModel();
    if (act === 'save-persona') return onSavePersona();
    if (act === 'restart') return onRestart();
  });

  render();
  loadAll();

  return {
    update(store) {
      // 部署状态变化时（刚装好 AstrBot）重新读一次
      if (store.deploy?.finished) loadAll();
    },
    destroy() {},
  };
}
