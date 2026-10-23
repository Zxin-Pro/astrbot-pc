/** 模型与人格：给 AstrBot 配好中转站与人格，用户只贴一个密钥。 */

import { api } from '../api.js';
import { notify } from '../components.js';
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
    body.innerHTML = '<div id="relay-slot"></div>' + modelCard() + personaCard() + applyCard();
    paintRelay();
  }

  function paintRelay() {
    const slot = body.querySelector('#relay-slot');
    if (slot) slot.innerHTML = relayCard();
  }

  async function loadAll() {
    state = await api.llm();
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

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act],[data-preset]');
    if (!btn) return;
    const act = btn.dataset.act;
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
