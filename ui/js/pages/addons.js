/** 扩展：组件更新、快照回滚与 AstrBot 插件管理。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify } from '../components.js';
import { icon } from '../icons.js';
import { bytes, esc, fdate } from '../util.js';
import { emptyState, pageHead } from './common.js';

/** 异步按钮统一：执行期间禁用，结束恢复，出错给一条中文提示。 */
async function withBusy(btn, fn) {
  if (btn) btn.disabled = true;
  try {
    await fn();
  } catch (err) {
    console.error('[addons]', err);
    notify.error(`操作失败：${err?.message || err}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function mount(root, ctx) {
  const state = {
    tab: 'components',
    inventory: null,
    invErr: '',
    check: null,
    snapshots: null,
    snapErr: '',
    plugins: null,
    plugErr: '',
  };

  // 插件接口按实例分区；没显式指定时后端会退回当前实例（再不行是 bot1）
  const instanceOf = () => (ctx.store.instances || []).find((it) => it.active) || (ctx.store.instances || [])[0] || null;
  const activeIid = () => instanceOf()?.id || '';

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '扩展',
        desc: '组件版本、快照回滚和插件都在这一页；装完插件或切换开关后，重启 AstrBot 才生效。',
      })}

      <div class="segmented" id="ext-tabs" role="tablist" aria-label="扩展分类" style="margin-bottom:18px">
        <button class="is-active" type="button" role="tab" aria-selected="true" data-tab="components">${icon('layers', 14)}组件更新</button>
        <button type="button" role="tab" aria-selected="false" data-tab="plugins">${icon('bolt', 14)}插件</button>
      </div>

      <div data-panel="components" role="tabpanel" aria-label="组件更新">
        <div class="section">
          <div class="section-head">
            <h2>组件清单 <span class="muted">当前版本与上游发布</span></h2>
            <div class="inline">
              <button class="btn btn--sm" type="button" data-act="check">${icon('refresh', 14)}检查更新</button>
              <button class="btn btn--sm btn--primary" type="button" data-act="snapshot-open">${icon('archive', 14)}立即快照</button>
            </div>
          </div>
          <div class="card card--flush" id="components-card"><p class="hint" style="padding:16px">正在读取组件清单…</p></div>
        </div>

        <div class="section">
          <div class="section-head">
            <h2>快照与回滚</h2>
            <span class="hint" id="snap-meta"></span>
          </div>
          <div class="card card--flush" id="snapshots-card"><p class="hint" style="padding:16px">正在读取快照…</p></div>
        </div>
      </div>

      <div data-panel="plugins" role="tabpanel" aria-label="插件" hidden>
        <div class="section" id="plugin-install-section">
          <div class="section-head"><h2>安装插件</h2></div>
          <div class="card">
            <div class="form-grid">
              <label class="field field--full">
                <span class="field__label">GitHub 仓库</span>
                <input class="input mono" id="pl-url" placeholder="https://github.com/owner/astrbot_plugin_xxx" spellcheck="false">
                <span class="field__help">填仓库主页地址，安装时会取最新发布或默认分支。</span>
              </label>
              <label class="field field--full">
                <span class="field__label">本地 zip 包</span>
                <input class="input mono" id="pl-path" placeholder="D:\plugins\astrbot_plugin_xxx.zip" spellcheck="false">
                <span class="field__help">窗口版点「从文件安装」会弹系统选择框；网页版请把绝对路径贴进这里。</span>
              </label>
            </div>
            <div class="row-actions">
              <button class="btn btn--primary" type="button" data-act="install-github">${icon('download', 15)}从 GitHub 安装</button>
              <button class="btn" type="button" data-act="install-file">${icon('folder', 15)}从文件安装</button>
              <span class="hint">装好后在表格里打开开关，再重启 AstrBot。</span>
            </div>
          </div>
        </div>

        <div class="section">
          <div class="section-head">
            <h2>已装插件 <span class="muted" id="plugin-meta"></span></h2>
            <button class="btn btn--sm btn--ghost" type="button" data-act="plugins-refresh">${icon('refresh', 14)}刷新</button>
          </div>
          <div class="card card--flush" id="plugins-card"><p class="hint" style="padding:16px">正在读取插件…</p></div>
        </div>
      </div>
    </div>`;

  /* ------------------------------ 标签页 ------------------------------ */

  function setTab(tab) {
    state.tab = tab === 'plugins' ? 'plugins' : 'components';
    root.querySelectorAll('[data-tab]').forEach((btn) => {
      const on = btn.dataset.tab === state.tab;
      btn.classList.toggle('is-active', on);
      btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    root.querySelectorAll('[data-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.panel !== state.tab;
    });
  }

  /* ------------------------------ 组件更新 ------------------------------ */

  function checkOf(key) {
    return (state.check?.items || []).find((it) => it.key === key) || null;
  }

  function statusCell(item) {
    if (item.kind === 'plugin') return '<span class="muted" style="font-size:12px">插件市场更新</span>';
    if (!item.installed) return '<span class="pill pill--warn">未安装</span>';
    const hit = checkOf(item.key);
    if (!hit) return '<span class="muted" style="font-size:12px">未检查</span>';
    if (hit.err) {
      return `<span class="pill pill--bad">检查失败</span>
        <p class="muted" style="font-size:11.5px;margin:4px 0 0;max-width:260px;line-height:1.5">${esc(hit.err)}</p>`;
    }
    if (hit.newer) return '<span class="pill pill--warm">有新版</span>';
    if (hit.latest) return '<span class="pill pill--ok">已最新</span>';
    if (hit.noRelease) return '<span class="pill">还没有发布版</span>';
    return '<span class="pill">无版本信息</span>';
  }

  function renderComponents() {
    const el = root.querySelector('#components-card');
    if (!el) return;
    if (state.invErr) {
      el.innerHTML = `<p class="hint" style="padding:16px">读不到组件清单：${esc(state.invErr)}</p>`;
      return;
    }
    if (!state.inventory) {
      el.innerHTML = '<p class="hint" style="padding:16px">正在读取组件清单…</p>';
      return;
    }

    const rows = (state.inventory.items || []).map((item) => {
      const hit = checkOf(item.key);
      const current = hit?.current || item.version || '';
      const latest = hit?.latest ? `v${esc(hit.latest)}` : '<span class="muted">—</span>';
      const source = item.source ? `<div class="muted" style="font-size:11.5px">${esc(item.source)}</div>` : '';
      const badge = item.kind === 'plugin'
        ? '<span class="pill">插件</span>'
        : (item.installed ? '' : '<span class="pill pill--warn">未安装</span>');

      let action = '<span class="muted" style="font-size:12px">—</span>';
      if (item.key === 'pc') {
        action = `<button class="btn btn--sm" type="button" data-act="release">${icon('external', 13)}去 Release 页</button>`;
      } else if (item.kind === 'service') {
        action = `<button class="btn btn--sm btn--primary" type="button" data-act="upgrade" data-key="${esc(item.key)}" ${item.installed ? '' : 'disabled title="先完成部署再升级"'}>${icon('download', 13)}立即升级</button>`;
      }

      return `<tr>
        <td><strong>${esc(item.label || item.key)}</strong> ${badge}${source}</td>
        <td class="mono">${current ? `v${esc(current)}` : '<span class="muted">—</span>'}</td>
        <td class="mono">${latest}</td>
        <td>${statusCell(item)}</td>
        <td class="right"><div class="inline" style="justify-content:flex-end">${action}</div></td>
      </tr>`;
    }).join('');

    const meta = state.check
      ? `上次检查 ${state.check.ts ? fdate(state.check.ts, true) : '—'}${state.check.cached ? '（缓存）' : ''}${state.check.err ? ` · ${state.check.err}` : ''}`
      : '还没检查过更新。点右上「检查更新」问一次 GitHub，结果会缓存 30 分钟。';

    el.innerHTML = `
      <div style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>组件</th><th>当前版本</th><th>最新版本</th><th>检查</th><th class="right">操作</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5"><p class="hint" style="padding:10px">组件清单是空的，先完成部署再来。</p></td></tr>'}</tbody>
        </table>
      </div>
      <p class="field__help" style="padding:10px 14px;margin:0;border-top:1px solid var(--line-2)">${esc(meta)}</p>`;
  }

  function renderSnapshots() {
    const el = root.querySelector('#snapshots-card');
    if (!el) return;
    if (state.snapErr) {
      el.innerHTML = `<p class="hint" style="padding:16px">读不到快照列表：${esc(state.snapErr)}</p>`;
      return;
    }
    if (!state.snapshots) {
      el.innerHTML = '<p class="hint" style="padding:16px">正在读取快照…</p>';
      return;
    }

    const items = state.snapshots.items || [];
    const meta = root.querySelector('#snap-meta');
    if (meta) meta.textContent = items.length ? `共 ${items.length} 份` : '';
    if (!items.length) {
      el.innerHTML = '<p class="hint" style="padding:16px">还没有组件快照。升级或回滚前点一次「立即快照」，出问题能滚回来。</p>';
      return;
    }

    el.innerHTML = `
      <div style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>时间</th><th>标签</th><th>大小</th><th class="right">操作</th></tr></thead>
          <tbody>${items.map((snap) => `<tr>
            <td class="mono">${esc(fdate(snap.createdAt, true))}</td>
            <td>
              ${snap.label ? esc(snap.label) : '<span class="muted">手动快照</span>'}
              ${snap.version ? `<span class="muted" style="font-size:11.5px;margin-left:6px">v${esc(snap.version)}</span>` : ''}
              ${snap.valid ? '' : '<span class="pill pill--bad" style="margin-left:6px">已损坏</span>'}
            </td>
            <td class="mono">${bytes(snap.bytes)}</td>
            <td class="right">
              <button class="btn btn--sm" type="button" data-act="rollback" data-name="${esc(snap.name)}" ${snap.valid ? '' : 'disabled title="快照里的 manifest.json 缺失或损坏，不能回滚"'}>${icon('refresh', 13)}回滚</button>
            </td>
          </tr>`).join('')}</tbody>
        </table>
      </div>`;
  }

  async function loadInventory() {
    try {
      const res = await api.components();
      if (!res.ok) {
        state.invErr = res.err || '原因未知';
        state.inventory = null;
        renderComponents();
        return;
      }
      state.invErr = '';
      state.inventory = res;
      renderComponents();
    } catch (err) {
      state.invErr = err?.message || String(err);
      state.inventory = null;
      renderComponents();
    }
  }

  async function loadSnapshots() {
    try {
      const res = await api.componentSnapshots();
      if (!res.ok) {
        state.snapErr = res.err || '原因未知';
        state.snapshots = null;
        renderSnapshots();
        return;
      }
      state.snapErr = '';
      state.snapshots = res;
      renderSnapshots();
    } catch (err) {
      state.snapErr = err?.message || String(err);
      state.snapshots = null;
      renderSnapshots();
    }
  }

  // 首屏静默读一次缓存，不强制联网；失败只体现在表格上，不弹 toast
  async function loadCheckSilent() {
    try {
      const res = await api.componentsCheck(false);
      state.check = res;
      renderComponents();
    } catch {
      /* 保持「未检查」，用户手动点按钮 */
    }
  }

  function doCheck(btn) {
    return withBusy(btn, async () => {
      const res = await api.componentsCheck(true);
      state.check = res;
      renderComponents();
      if (!res.ok) return notify.error(res.err || '检查更新失败');
      const newer = (res.items || []).filter((it) => it.newer).length;
      notify.ok(newer ? `检查完成：${newer} 个组件有新版` : '检查完成：都是最新版');
    });
  }

  function openSnapshotModal() {
    modal({
      title: '生成组件快照',
      desc: '把 AstrBot 源码树和当前实例的配置打成一个 zip，放在 backups/components 下。升级前打一份，出问题能回滚。',
      body: `<label class="field">
        <span class="field__label">标签（可选）</span>
        <input class="input" id="snapshot-label" maxlength="40" placeholder="例如：升级 AstrBot 前">
        <span class="field__help">留空就用「手动快照」。</span>
      </label>`,
      actions: [
        { label: '取消' },
        {
          label: '开始快照',
          primary: true,
          run: async (close, el) => {
            const input = el.querySelector('#snapshot-label');
            const label = input?.value.trim() || '手动快照';
            const res = await api.componentSnapshot(label);
            if (!res.ok) {
              notify.error(res.err || '快照失败');
              return false;
            }
            notify.ok(`快照已生成：${res.name}（${bytes(res.bytes)}）`);
            await loadSnapshots();
            return true;
          },
        },
      ],
      onMount: ({ root: el }) => {
        el.querySelector('#snapshot-label')?.addEventListener('keydown', (e) => {
          if (e.key !== 'Enter') return;
          e.preventDefault();
          el.querySelector('.modal__foot .btn--primary')?.click();
        });
      },
    });
  }

  function upgrade(btn) {
    const key = btn.dataset.key || '';
    return withBusy(btn, async () => {
      const res = await api.componentUpgrade(key);
      if (!res.ok) return notify.error(res.err || '升级准备失败');
      notify.ok(res.note || '已生成升级前快照');
      await loadSnapshots();
    });
  }

  function openRelease(btn) {
    return withBusy(btn, async () => {
      let url = checkOf('pc')?.url || '';
      if (!url) {
        const prepared = await api.componentUpgrade('pc');
        if (prepared.ok) url = prepared.url || '';
      }
      if (!url) return notify.error('还没拿到 PC 端发布页地址，先点「检查更新」');
      const opened = await api.openUrl(url);
      if (!opened.ok) notify.error(opened.err || '打不开浏览器');
      else notify.info('已用浏览器打开 Release 页');
    });
  }

  async function rollback(btn) {
    const name = btn.dataset.name || '';
    const snap = (state.snapshots?.items || []).find((it) => it.name === name);
    const ok = await confirmDialog({
      title: '回滚到这个快照？',
      desc: `会用「${snap?.label || name}」覆盖 AstrBot 源码树，实例数据不动；回滚前会自动再打一份快照。回滚完成后需要重启 AstrBot。`,
      confirm: '回滚',
      danger: true,
    });
    if (!ok) return;
    await withBusy(btn, async () => {
      const res = await api.componentRollback(name);
      if (!res.ok) return notify.error(res.err || '回滚失败');
      notify.ok(`已回滚 ${res.count || 0} 个文件，重启 AstrBot 后生效`);
      await loadSnapshots();
    });
  }

  /* ------------------------------ 插件 ------------------------------ */

  function findPlugin(id) {
    return (state.plugins?.items || []).find((it) => it.id === id) || null;
  }

  function renderPlugins() {
    const el = root.querySelector('#plugins-card');
    if (!el) return;
    const inst = instanceOf();
    const list = state.plugins?.items || [];
    const install = root.querySelector('#plugin-install-section');
    if (install) install.hidden = !(ctx.store.instances || []).length && !list.length;

    const meta = root.querySelector('#plugin-meta');
    if (meta) meta.textContent = inst ? `实例「${inst.name || inst.id}」` : '';

    if (!state.plugins && state.plugErr) {
      el.innerHTML = `<div style="padding:16px">
        <p class="hint" style="margin:0">读不到插件列表：${esc(state.plugErr)}</p>
        <button class="btn btn--sm" type="button" data-act="plugins-refresh" style="margin-top:10px">${icon('refresh', 13)}重新读取</button>
      </div>`;
      return;
    }
    if (!state.plugins) {
      el.innerHTML = '<p class="hint" style="padding:16px">正在读取插件…</p>';
      return;
    }
    if (!list.length) {
      el.innerHTML = emptyState({
        iconName: 'bolt',
        title: inst ? '这个实例还没装插件' : '还没有可用的实例',
        desc: inst
          ? `插件目录是空的：把插件装到「${inst.name || inst.id}」上，再回来启用。`
          : '插件跟着实例走。先到「实例」页建一个号并完成部署，插件目录才会生成。',
        action: inst ? '' : '<button class="btn btn--sm btn--primary" type="button" data-act="go-instances">去实例页</button>',
      });
      return;
    }

    el.innerHTML = `
      <div style="overflow-x:auto">
        <table class="table">
          <thead><tr><th>插件</th><th>版本</th><th>作者</th><th>状态</th><th class="right">操作</th></tr></thead>
          <tbody>${list.map((plugin) => `<tr>
            <td>
              <strong>${esc(plugin.name || plugin.id)}</strong>
              ${plugin.invalid ? '<span class="pill pill--warn">结构不完整</span>' : ''}
              <div class="muted mono" style="font-size:11.5px">${esc(plugin.id)}</div>
              ${plugin.desc ? `<p class="muted" style="font-size:12px;margin:3px 0 0;max-width:380px;line-height:1.55">${esc(plugin.desc)}</p>` : ''}
            </td>
            <td class="mono">${plugin.version ? `v${esc(plugin.version)}` : '<span class="muted">—</span>'}</td>
            <td>${plugin.author ? esc(plugin.author) : '<span class="muted">—</span>'}</td>
            <td>
              <div class="inline">
                <span class="switch">
                  <input type="checkbox" data-toggle="${esc(plugin.id)}" ${plugin.enabled ? 'checked' : ''} ${plugin.invalid ? 'disabled' : ''} aria-label="${plugin.enabled ? '停用' : '启用'} ${esc(plugin.name || plugin.id)}">
                  <span class="switch__track"></span>
                </span>
                <span class="muted" style="font-size:12px">${plugin.enabled ? '已启用' : '已停用'}</span>
              </div>
            </td>
            <td class="right">
              <div class="inline" style="justify-content:flex-end">
                <button class="btn btn--sm" type="button" data-act="plugin-config" data-id="${esc(plugin.id)}">${icon('settings', 13)}配置</button>
                <button class="btn btn--sm btn--ghost" type="button" data-act="plugin-logs" data-id="${esc(plugin.id)}">${icon('file', 13)}日志</button>
                <button class="btn btn--sm btn--ghost" type="button" data-act="plugin-remove" data-id="${esc(plugin.id)}">${icon('trash', 13)}卸载</button>
              </div>
            </td>
          </tr>`).join('')}</tbody>
        </table>
      </div>
      ${state.plugins.warn ? `<p class="field__help" style="padding:10px 14px;margin:0;border-top:1px solid var(--line-2)">${esc(state.plugins.warn)}</p>` : ''}`;
  }

  async function loadPlugins() {
    try {
      const res = await api.plugins(activeIid() || undefined);
      if (!res.ok) {
        state.plugErr = res.err || '原因未知';
        state.plugins = null;
        renderPlugins();
        return;
      }
      state.plugErr = '';
      state.plugins = res;
      renderPlugins();
    } catch (err) {
      state.plugErr = err?.message || String(err);
      state.plugins = null;
      renderPlugins();
    }
  }

  function installGithub(btn) {
    const input = root.querySelector('#pl-url');
    const url = input?.value.trim() || '';
    if (!url) {
      input?.focus();
      return notify.warn('先粘贴 GitHub 仓库地址');
    }
    return withBusy(btn, async () => {
      const res = await api.pluginInstall({ url, iid: activeIid() });
      if (!res.ok) return notify.error(res.err || '安装失败');
      notify.ok(`已安装 ${res.name || res.id || '插件'}，重启 AstrBot 后生效`);
      input.value = '';
      await loadPlugins();
    });
  }

  async function installFile(btn) {
    const input = root.querySelector('#pl-path');
    const picker = window.pywebview?.api?.pick;
    if (picker) {
      let picked;
      try {
        picked = await picker('zip');
      } catch (err) {
        return notify.error(`选择文件失败：${err?.message || err}`);
      }
      if (!picked?.ok) return notify.error(picked?.err || '没有选到文件');
      if (!picked.path) return notify.warn('没有选择 zip 文件');
      input.value = picked.path;
    }
    const path = input.value.trim();
    if (!path) {
      if (!picker) {
        input.focus();
        notify.info('网页版没有文件选择框，请把 zip 的绝对路径填进上面的输入框，再点「从文件安装」。');
      } else {
        notify.warn('还没有选到 zip 文件');
      }
      return;
    }
    await withBusy(btn, async () => {
      const res = await api.pluginInstall({ path, iid: activeIid() });
      if (!res.ok) return notify.error(res.err || '安装失败');
      notify.ok(`已安装 ${res.name || res.id || '插件'}，重启 AstrBot 后生效`);
      input.value = '';
      await loadPlugins();
    });
  }

  async function openConfig(btn, plugin) {
    await withBusy(btn, async () => {
      const res = await api.pluginConfig(plugin.id, activeIid());
      if (!res.ok) return notify.error(res.err || '读不到插件配置');
      const text = JSON.stringify(res.data ?? {}, null, 2);
      modal({
        title: `配置 · ${plugin.name || plugin.id}`,
        desc: '保存前会做一次 JSON 校验；改完重启 AstrBot 才会生效。',
        wide: true,
        body: `<label class="field">
          <span class="field__label">配置 JSON</span>
          <textarea class="textarea mono" id="plugin-config-text" spellcheck="false" style="min-height:340px">${esc(text)}</textarea>
          <span class="field__hint" id="plugin-config-err"></span>
        </label>`,
        actions: [
          { label: '取消' },
          {
            label: '保存',
            primary: true,
            run: async (close, el) => {
              const area = el.querySelector('#plugin-config-text');
              const errEl = el.querySelector('#plugin-config-err');
              let data;
              try {
                data = JSON.parse(area.value);
              } catch (parseErr) {
                errEl.textContent = `JSON 格式不对：${parseErr.message}`;
                area.focus();
                return false;
              }
              if (!data || typeof data !== 'object' || Array.isArray(data)) {
                errEl.textContent = '配置必须是一个 JSON 对象（不能是数组或空值）';
                area.focus();
                return false;
              }
              const saved = await api.pluginConfigSave(plugin.id, data, activeIid());
              if (!saved.ok) {
                errEl.textContent = saved.err || '保存失败';
                notify.error(saved.err || '保存失败');
                return false;
              }
              notify.ok('配置已保存，重启 AstrBot 后生效');
              return true;
            },
          },
        ],
      });
    });
  }

  async function openLogs(btn, plugin) {
    await withBusy(btn, async () => {
      const res = await api.pluginLogs(plugin.id, activeIid(), 300);
      if (!res.ok) return notify.error(res.err || '读不到插件日志');
      const text = (res.lines || []).join('\n');
      modal({
        title: `日志 · ${plugin.name || plugin.id}`,
        desc: res.path ? `来源：${res.path}` : '最近 300 行',
        wide: true,
        body: text
          ? `<pre class="term-out mono" style="max-height:56vh;overflow:auto;white-space:pre-wrap;margin:0">${esc(text)}</pre>`
          : '<p class="hint">这个插件最近没有日志输出；AstrBot 跑起来后才会写。</p>',
      });
    });
  }

  async function removePlugin(btn, plugin) {
    const ok = await confirmDialog({
      title: `卸载插件「${plugin.name || plugin.id}」？`,
      desc: '插件目录会移到 backups/plugins-trash 回收站，需要时能手动找回。卸载后重启 AstrBot 生效。',
      confirm: '卸载',
      danger: true,
    });
    if (!ok) return;
    await withBusy(btn, async () => {
      const res = await api.pluginRemove(plugin.id, activeIid());
      if (!res.ok) return notify.error(res.err || '卸载失败');
      notify.ok(`已卸载「${plugin.name || plugin.id}」，重启 AstrBot 后生效`);
      await loadPlugins();
    });
  }

  /* ------------------------------ 事件 ------------------------------ */

  root.addEventListener('click', (e) => {
    const tabBtn = e.target.closest('[data-tab]');
    if (tabBtn) {
      setTab(tabBtn.dataset.tab);
      return;
    }
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    const id = btn.dataset.id;

    if (act === 'check') return doCheck(btn);
    if (act === 'snapshot-open') return openSnapshotModal();
    if (act === 'upgrade') return upgrade(btn);
    if (act === 'release') return openRelease(btn);
    if (act === 'rollback') return rollback(btn);
    if (act === 'plugins-refresh') {
      state.plugErr = '';
      state.plugins = null;
      renderPlugins();
      return withBusy(btn, loadPlugins);
    }
    if (act === 'install-github') return installGithub(btn);
    if (act === 'install-file') return installFile(btn);
    if (act === 'plugin-config') {
      const plugin = findPlugin(id);
      if (plugin) return openConfig(btn, plugin);
      return undefined;
    }
    if (act === 'plugin-logs') {
      const plugin = findPlugin(id);
      if (plugin) return openLogs(btn, plugin);
      return undefined;
    }
    if (act === 'plugin-remove') {
      const plugin = findPlugin(id);
      if (plugin) return removePlugin(btn, plugin);
      return undefined;
    }
    if (act === 'go-instances') return ctx.go('instances');
    return undefined;
  });

  root.addEventListener('change', async (e) => {
    const input = e.target.closest('input[data-toggle]');
    if (!input) return;
    const id = input.dataset.toggle;
    const want = input.checked;
    const plugin = findPlugin(id);
    const label = input.closest('.inline')?.querySelector('.muted');
    input.disabled = true;
    try {
      const res = await api.pluginToggle(id, want, activeIid());
      if (!res.ok) {
        input.checked = !want;
        notify.error(res.err || '切换失败');
        return;
      }
      if (plugin) plugin.enabled = want;
      if (label) label.textContent = want ? '已启用' : '已停用';
      notify.ok(`${want ? '已启用' : '已停用'}${plugin ? `「${plugin.name || plugin.id}」` : ''}，重启 AstrBot 后生效`);
    } catch (err) {
      input.checked = !want;
      notify.error(`切换失败：${err?.message || err}`);
    } finally {
      input.disabled = false;
    }
  });

  root.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    if (e.target.id === 'pl-url') {
      e.preventDefault();
      root.querySelector('[data-act="install-github"]')?.click();
    } else if (e.target.id === 'pl-path') {
      e.preventDefault();
      root.querySelector('[data-act="install-file"]')?.click();
    }
  });

  /* ------------------------------ 首屏 ------------------------------ */

  renderComponents();
  renderSnapshots();
  renderPlugins();
  loadInventory();
  loadSnapshots();
  loadPlugins();
  loadCheckSilent();

  return {
    update(store, reason) {
      if (reason === 'instances') {
        loadInventory();
        loadPlugins();
      }
    },
  };
}
