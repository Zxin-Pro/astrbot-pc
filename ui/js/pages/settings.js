/** 设置：所有开关都在这里，改完立刻生效，不用重启。 */

import { api } from '../api.js';
import { confirmDialog, modal, notify, updateNotesModal } from '../components.js';
import { icon } from '../icons.js';
import { applyGlass } from '../glass.js';
import { getSetting } from '../store.js';
import { bytes, copyText, esc } from '../util.js';
import { pageHead } from './common.js';

const THEMES = [
  { key: 'light', name: '浅色', desc: '白天用，白底清爽' },
  { key: 'dark', name: '深色', desc: '夜里用，不刺眼' },
];

function ago(ts) {
  if (!ts) return '';
  const s = Math.max(0, Math.floor(Date.now() / 1000) - Number(ts));
  if (s < 60) return '刚刚查过';
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前查过`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前查过`;
  return `${Math.floor(s / 86400)} 天前查过`;
}

function row(opts) {
  const { title, desc, control, full } = opts;
  return `<div class="set-row ${full ? 'set-row--full' : ''}">
    <div class="set-row__text"><strong>${esc(title)}</strong><small>${esc(desc)}</small></div>
    <div class="set-row__ctrl">${control}</div>
  </div>`;
}

function sw(name, checked) {
  return `<span class="switch"><input type="checkbox" data-key="${name}" ${checked ? 'checked' : ''}><span class="switch__track"></span></span>`;
}

export function mount(root, ctx) {
  const cfg = () => ctx.store.config || {};
  const get = (path, def) => getSetting(path, def);

  function updateRow() {
    const u = ctx.store.update;
    if (!u) {
      return `<span class="update-row__ico">${icon('download', 15)}</span>
        <span class="grow"><strong>还没查过更新</strong><small>点右上「检查更新」问一次 GitHub</small></span>`;
    }
    if (!u.ok) {
      return `<span class="update-row__ico is-warn">${icon('alert', 15)}</span>
        <span class="grow"><strong>上次检查没成功</strong><small>${esc(u.err || '稍后再试')}</small></span>`;
    }
    if (u.noRelease) {
      return `<span class="update-row__ico is-ok">${icon('check', 15)}</span>
        <span class="grow"><strong>PC 端还没有发布版本</strong><small>${esc(u.message || '桌面版会单独出包，手机版更新不影响这里')} · ${esc(ago(u.checkedAt))}</small></span>
        <button class="btn btn--sm btn--ghost" data-act="open-repo">关注仓库</button>`;
    }
    if (u.newer) {
      return `<span class="update-row__ico is-new">${icon('sparkles', 15)}</span>
        <span class="grow"><strong>有新版本 v${esc(u.latest)}</strong><small>当前 v${esc(u.current)} · ${esc(ago(u.checkedAt))}</small></span>
        <button class="btn btn--sm btn--primary" data-act="update-notes">看更新内容</button>`;
    }
    return `<span class="update-row__ico is-ok">${icon('check', 15)}</span>
      <span class="grow"><strong>已经是最新版</strong><small>v${esc(u.current)} · ${esc(ago(u.checkedAt))}</small></span>`;
  }

  function syncUpdate(force) {
    const el = root.querySelector('#update-row');
    if (el) el.innerHTML = updateRow();
    if (force) refreshBadge();
  }

  function showNotes(u) {
    updateNotesModal(u);
  }

  function refreshBadge() {
    const u = ctx.store.update;
    document.dispatchEvent(new CustomEvent('update-state', { detail: { newer: !!u?.newer, latest: u?.latest || '' } }));
  }

  root.innerHTML = `
    <div class="page page--narrow">
      ${pageHead({ title: '设置', desc: '改动即时保存，不需要重启界面。' })}

      <div class="section">
        <div class="section-head"><h2>外观</h2></div>
        <div class="card">
          <div class="theme-pick" id="theme-pick">
            ${THEMES.map((t) => `
              <button class="theme-card" data-theme-pick="${t.key}" type="button">
                <span class="theme-card__preview theme-card__preview--${t.key}" aria-hidden="true">
                  <i></i><i></i><i></i>
                </span>
                <span class="theme-card__text"><strong>${t.name}</strong><small>${t.desc}</small></span>
                <span class="theme-card__check">${icon('check', 13, 2.4)}</span>
              </button>`).join('')}
          </div>
          ${row({
            title: '跟随系统',
            desc: '系统切换深色时界面跟着变',
            control: sw('app.followSystem', get('app.followSystem', true)),
          })}
          ${row({
            title: '玻璃质感',
            desc: '半透明磨砂面板的厚度。关掉就是实色，老显卡更顺',
            control: `<select class="select select--sm" data-sel="app.glassLevel">
              <option value="off" ${get('app.glassLevel', 'soft') === 'off' ? 'selected' : ''}>关闭</option>
              <option value="soft" ${get('app.glassLevel', 'soft') === 'soft' ? 'selected' : ''}>轻薄</option>
              <option value="strong" ${get('app.glassLevel', 'soft') === 'strong' ? 'selected' : ''}>厚重</option>
            </select>`,
          })}
          ${row({ title: '精简模式', desc: '少画装饰、去掉背景光晕，远程桌面和低配机器更跟手', control: sw('app.compact', get('app.compact', false)) })}
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>背景图</strong>
              <small>PNG / JPG / WebP，最大 8 MB。会铺满窗口，配合玻璃质感更好看</small>
            </div>
            <div class="set-row__ctrl inline">
              <img id="bg-thumb" alt="" class="bg-thumb" hidden>
              <input type="file" id="bg-file" accept="image/png,image/jpeg,image/webp" hidden>
              <button class="btn btn--sm" data-act="bg-upload">${icon('file', 14)}选择图片</button>
              <button class="btn btn--sm btn--ghost" data-act="bg-clear">${icon('x', 14)}清除</button>
            </div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>启动与退出</h2></div>
        <div class="card">
          ${row({ title: '开机自动启动', desc: '登录 Windows 后在后台把界面准备好', control: sw('app.autoStart', get('app.autoStart', false)) })}
          ${row({ title: '关闭窗口时最小化到托盘', desc: `点右上角 × 不退出，机器人在后台继续跑${ctx.store.app?.shell ? '' : '（仅桌面窗口模式生效）'}`, control: sw('app.minimizeToTray', get('app.minimizeToTray', true)) })}
          ${row({ title: '退出时停止服务', desc: '关掉界面就断开 QQ 和机器人', control: sw('app.stopOnExit', get('app.stopOnExit', false)) })}
          ${row({ title: '自动检查更新', desc: '启动时静默查一次新版本', control: sw('app.checkUpdate', get('app.checkUpdate', true)) })}
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>服务</h2></div>
        <div class="card">
          ${row({ title: 'NapCat 掉线自动重启', desc: '进程意外退出时按 2s→5s→10s 退避重试，连续失败 5 次会停下等你处理', control: sw('services.napcat.autoRestart', get('services.napcat.autoRestart', true)) })}
          ${row({ title: 'AstrBot 掉线自动重启', desc: '同上，只影响机器人本体', control: sw('services.astrbot.autoRestart', get('services.astrbot.autoRestart', true)) })}
          ${row({
            title: '界面端口',
            desc: '本机访问地址的起始端口，被占用时自动顺延',
            control: `<input class="input input--sm mono" style="width:110px" type="number" min="1024" max="65535" data-num="server.preferredPort" value="${get('server.preferredPort', 17650)}" />`,
          })}
          ${row({
            title: '界面访问范围',
            desc: '「仅本机」只有这台电脑能打开；切成「允许局域网」要重启界面生效，且没有密码保护',
            control: `<select class="select select--sm" data-sel="server.authMode">
              <option value="local" ${get('server.authMode', 'local') === 'local' ? 'selected' : ''}>仅本机</option>
              <option value="lan" ${get('server.authMode', 'local') === 'lan' ? 'selected' : ''}>允许局域网</option>
            </select>`,
          })}
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>局域网访问</h2></div>
        <div class="card" id="lan-card"><p class="hint">读取中…</p></div>
      </div>

      <div class="section">
        <div class="section-head"><h2>部署</h2></div>
        <div class="card">
          ${row({
            title: 'pip 镜像',
            desc: '装 AstrBot 依赖时用哪个源。国内建议走清华，能快十倍',
            control: `<select class="select select--sm" data-sel="deploy.pipIndex">
              <option value="" ${!get('deploy.pipIndex', '') ? 'selected' : ''}>官方源</option>
              <option value="https://pypi.tuna.tsinghua.edu.cn/simple" ${get('deploy.pipIndex', '') === 'https://pypi.tuna.tsinghua.edu.cn/simple' ? 'selected' : ''}>清华 TUNA</option>
              <option value="https://mirrors.aliyun.com/pypi/simple" ${get('deploy.pipIndex', '') === 'https://mirrors.aliyun.com/pypi/simple' ? 'selected' : ''}>阿里云</option>
              <option value="https://mirrors.cloud.tencent.com/pypi/simple" ${get('deploy.pipIndex', '') === 'https://mirrors.cloud.tencent.com/pypi/simple' ? 'selected' : ''}>腾讯云</option>
            </select>`,
          })}
          ${row({
            title: 'AstrBot 安装方式',
            desc: '压缩包更省事；用 git 克隆以后能直接拉更新',
            control: `<select class="select select--sm" data-sel="deploy.astrbotMethod">
              <option value="zip" ${get('deploy.astrbotMethod', 'zip') === 'zip' ? 'selected' : ''}>下载压缩包</option>
              <option value="git" ${get('deploy.astrbotMethod', 'zip') === 'git' ? 'selected' : ''}>git 克隆</option>
            </select>`,
          })}
          ${row({
            title: '默认演练',
            desc: '打开后每次部署先走一遍空流程，确认每一环都能过再真跑',
            control: sw('deploy.dryRun', get('deploy.dryRun', true)),
          })}
          ${row({
            title: '下载加速镜像',
            desc: '国内直连 github.com 经常握手超时；打开后会并发挑一个能用的镜像下载 NapCat 与 AstrBot',
            control: sw('deploy.accel', get('deploy.accel', true)),
          })}
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>数据</h2></div>
        <div class="card">
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>数据目录</strong>
              <small class="mono">${esc(ctx.store.app?.dataRoot || '—')}</small>
            </div>
            <div class="set-row__ctrl inline">
              <button class="btn btn--sm" data-act="open-data">${icon('folder', 14)}打开</button>
            </div>
          </div>
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>日志保留</strong>
              <small>单个日志超过 20MB 会截掉旧的一半，避免越滚越大</small>
            </div>
            <div class="set-row__ctrl">
              <button class="btn btn--sm" data-act="clear-logs">清理日志</button>
            </div>
          </div>
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>存储占用</strong>
              <small id="storage-summary">读取中…</small>
            </div>
            <div class="set-row__ctrl inline">
              <button class="btn btn--sm btn--ghost" data-act="clean-tmp">临时文件</button>
              <button class="btn btn--sm btn--ghost" data-act="clean-diag">诊断包</button>
              <button class="btn btn--sm btn--ghost" data-act="clean-cache">缓存</button>
            </div>
          </div>
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>恢复默认</strong>
              <small>所有设置回到初始状态。不会删数据、不会删备份。</small>
            </div>
            <div class="set-row__ctrl">
              <button class="btn btn--sm btn--danger" data-act="reset">重置设置</button>
            </div>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>隐私</h2></div>
        <div class="card">
          ${row({
            title: '匿名使用统计',
            desc: '只上报版本号、页面打开次数和是否部署成功，不含 QQ 号、密钥和聊天内容。默认关闭',
            control: sw('app.analytics', get('app.analytics', false)),
          })}
          <div class="set-row set-row--full">
            <div class="set-row__text">
              <strong>匿名标识</strong>
              <small class="mono" id="analytics-id">—</small>
            </div>
            <div class="set-row__ctrl">
              <button class="btn btn--sm btn--ghost" data-act="analytics-reset">重置标识</button>
            </div>
          </div>
          <div class="row-actions">
            <button class="btn btn--sm btn--ghost" data-act="policy-privacy">${icon('shieldCheck', 14)}隐私政策</button>
            <button class="btn btn--sm btn--ghost" data-act="policy-terms">${icon('file', 14)}用户协议</button>
            <button class="btn btn--sm btn--ghost" data-act="policy-disclaimer">${icon('alert', 14)}免责声明</button>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="section-head"><h2>关于</h2></div>
        <div class="card">
          <div class="about">
            <div class="about__mark">烛</div>
            <div class="grow">
              <strong>烛之控制台</strong>
              <p class="muted" style="font-size:12.5px;margin-top:2px">AstrBot 烛版 · PC 端 v${esc(ctx.store.version || '1.0.0')}</p>
            </div>
            <button class="btn btn--sm" data-act="check-update">${icon('refresh', 14)}检查更新</button>
          </div>
          <div class="update-row" id="update-row">${updateRow()}</div>
          <div class="divider"></div>
          <div class="inline" style="flex-wrap:wrap;gap:8px">
            <button class="btn btn--sm btn--ghost" data-act="open-repo">${icon('arrowUpRight', 13)}GitHub 仓库</button>
            <button class="btn btn--sm btn--ghost" data-act="open-site">${icon('external', 13)}官网</button>
            <span class="grow"></span>
            <span class="tag">QQ 群 1127997343</span>
          </div>
        </div>
      </div>
    </div>`;

  function syncTheme() {
    const cur = document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
    root.querySelectorAll('[data-theme-pick]').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.themePick === cur);
    });
  }
  syncTheme();
  document.addEventListener('themechange', syncTheme);

  let lan = null;
  let storage = null;

  function renderLan() {
    const el = root.querySelector('#lan-card');
    if (!el) return;
    if (!lan) {
      el.innerHTML = '<p class="hint">读取中…</p>';
      return;
    }
    if (!lan.ok) {
      el.innerHTML = `<p class="hint">${esc(lan.err || '读不到网络信息')}</p>`;
      return;
    }
    el.innerHTML = `
      <div class="set-row set-row--full">
        <div class="set-row__text">
          <strong>本机地址</strong>
          <small class="mono">${esc(lan.localUrl || '—')}</small>
        </div>
        <div class="set-row__ctrl">
          <button class="btn btn--sm" data-act="copy-local">${icon('copy', 14)}复制</button>
        </div>
      </div>
      <div class="set-row set-row--full">
        <div class="set-row__text">
          <strong>同一 Wi-Fi 下的手机 / 平板</strong>
          <small>${lan.mode === 'lan'
            ? `${lan.needRestart ? '改完要重启界面才对外监听。' : ''}用这个地址就能打开：<span class="mono">${esc(lan.lanUrl || '—')}</span>`
            : '现在只允许本机访问。把上面「界面访问范围」改成「允许局域网」，重启界面后就能用。'}</small>
        </div>
        <div class="set-row__ctrl">
          ${lan.mode === 'lan' && !lan.needRestart
            ? '<button class="btn btn--sm" data-act="copy-lan">' + icon('copy', 14) + '复制</button>'
            : '<button class="btn btn--sm btn--ghost" data-act="go-server">去改</button>'}
        </div>
      </div>
      ${lan.note ? `<p class="field__help" style="margin:10px 0 0">${esc(lan.note)}</p>` : ''}`;
  }

  async function loadLan() {
    const res = await api.lan();
    lan = res;
    renderLan();
  }

  function renderStorage() {
    const el = root.querySelector('#storage-summary');
    if (!el) return;
    if (!storage) {
      el.textContent = '读取中…';
      return;
    }
    if (!storage.ok) {
      el.textContent = storage.err || '读不到存储占用';
      return;
    }
    const big = (storage.sections || []).filter((s) => s.bytes > 0).slice(0, 3)
      .map((s) => `${s.label} ${bytes(s.bytes)}`).join(' · ');
    el.textContent = `${bytes(storage.total || 0)}${big ? '（' + big + '）' : ''}${storage.disk ? ` · 磁盘余 ${bytes(storage.disk.free)}` : ''}`;
  }

  async function loadStorage(force) {
    const res = await api.storage(force);
    storage = res;
    renderStorage();
  }

  function applyCompact(on) {
    document.documentElement.dataset.compact = on ? '1' : '0';
  }

  function renderAnalytics() {
    const el = root.querySelector('#analytics-id');
    if (el) el.textContent = get('app.analyticsId', '') || '还没生成，打开统计时自动生成';
  }

  function paintBackdrop(file) {
    const bd = document.querySelector('.backdrop');
    if (!bd) return;
    if (file) {
      // 与 main.js 的 applyAppearance 同一套：图放 .backdrop，遮罩由 .has-bg::after 负责
      bd.classList.add('has-bg');
      bd.style.backgroundImage = 'url("/files?kind=background&t=' + encodeURIComponent(file) + '")';
      bd.style.backgroundSize = 'cover';
      bd.style.backgroundPosition = 'center';
    } else {
      bd.classList.remove('has-bg');
      bd.style.backgroundImage = '';
      bd.style.backgroundSize = '';
      bd.style.backgroundPosition = '';
    }
  }

  function renderBg() {
    const b = get('app.background', {}) || {};
    const thumb = root.querySelector('#bg-thumb');
    if (!thumb) return;
    if (b.enabled && b.file) {
      thumb.src = '/files?kind=background&t=' + encodeURIComponent(b.file);
      thumb.hidden = false;
    } else {
      thumb.removeAttribute('src');
      thumb.hidden = true;
    }
  }

  function policyModal(kind) {
    const map = {
      privacy: {
        title: '隐私政策',
        body: `<p>烛之控制台在你自己的电脑上运行，数据默认不出本机。</p>
          <p>· 不上传聊天记录、QQ 号、模型密钥；配置与人格只写在本地数据目录。<br>
          · 「匿名使用统计」默认关闭。打开后只发送随机标识、版本号、页面名与是否部署成功，不含任何账号或内容。<br>
          · 检查更新会向 GitHub 请求公开的 Release 列表，这是唯一的外网请求（拉模型与下载包除外，由你主动触发）。<br>
          · 想清掉统计标识，点下面的「重置标识」。</p>`,
      },
      terms: {
        title: '用户协议',
        body: `<p>这是一个免费的开源工具，按「现状」提供。</p>
          <p>· 你需要自己准备 QQ 账号与模型 API，并遵守它们各自的服务条款。<br>
          · 不要用它做骚扰、刷屏、诈骗或其他违法的事；后果由使用者承担。<br>
          · 软件可能出错，重要配置请用「备份」页导出留底。</p>`,
      },
      disclaimer: {
        title: '免责声明',
        body: `<p>NapCat、AstrBot 与本项目各自独立。因使用本工具导致的账号风控、封禁、数据丢失或服务中断，作者不承担赔偿责任。</p>
          <p>遇到风控请降低发送频率、不要群发，并先停下用官方客户端确认账号状态。</p>`,
      },
    };
    const p = map[kind];
    if (!p) return;
    modal({ title: p.title, body: p.body, actions: [{ label: '知道了', primary: true }] });
  }

  async function save(patch, okText) {
    const res = await ctx.saveSetting(patch);
    if (res.ok) {
      if (okText) notify.ok(okText);
    } else {
      notify.error(res.err || '保存失败');
    }
    return res;
  }

  root.querySelector('#theme-pick').addEventListener('click', (e) => {
    const b = e.target.closest('[data-theme-pick]');
    if (!b) return;
    const theme = b.dataset.themePick;
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('dsh.theme', theme);
    document.dispatchEvent(new CustomEvent('themechange'));
    save({ app: { theme, followSystem: false } });
  });

  root.addEventListener('change', async (e) => {
    const el = e.target;
    if (el.matches('input[data-key]')) {
      const path = el.dataset.key.split('.');
      const patch = {};
      let cur = patch;
      path.forEach((k, i) => {
        if (i === path.length - 1) cur[k] = el.checked;
        else cur = cur[k] = {};
      });
      // 玻璃开关要当场生效，不能等写完配置再刷新
      if (el.dataset.key === 'app.glass') applyGlass(el.checked);
      if (el.dataset.key === 'app.compact') applyCompact(el.checked);
      await save(patch);
    } else if (el.matches('select[data-sel]')) {
      const path = el.dataset.sel.split('.');
      const patch = {};
      let cur = patch;
      path.forEach((k, i) => {
        if (i === path.length - 1) cur[k] = el.value;
        else cur = cur[k] = {};
      });
      if (el.dataset.sel === 'app.glassLevel') {
        // 三档一次写两个键：glass 布尔给旧逻辑，glassLevel 给新样式厚度
        const on = el.value !== 'off';
        await save({ app: { glassLevel: el.value, glass: on } });
        applyGlass(on);
        document.documentElement.dataset.glassLevel = el.value;
        return;
      }
      await save(patch, el.dataset.sel === 'server.authMode' ? '已保存，重启界面后生效' : '已保存');
      if (el.dataset.sel === 'server.authMode') loadLan();
    } else if (el.matches('input[data-num]')) {
      const path = el.dataset.num.split('.');
      const val = Number(el.value);
      if (!val || val < 1024 || val > 65535) {
        notify.error('端口范围 1024–65535');
        return;
      }
      const patch = {};
      let cur = patch;
      path.forEach((k, i) => {
        if (i === path.length - 1) cur[k] = val;
        else cur = cur[k] = {};
      });
      await save(patch, '端口已保存，重启界面后生效');
    }
  });

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;

    if (act === 'open-data') {
      const res = await api.open('data');
      if (!res.ok) notify.error(res.err || '打不开');
    } else if (act === 'reset') {
      const ok = await confirmDialog({
        title: '恢复默认设置？',
        desc: '所有开关回到初始值，数据目录、实例、备份都保留。',
        confirm: '恢复默认',
        danger: true,
      });
      if (!ok) return;
      const res = await api.resetSettings();
      if (res.ok) {
        notify.ok('已恢复默认');
        await ctx.refresh();
        ctx.go('settings', { force: true });
      } else notify.error(res.err || '重置失败');
    } else if (act === 'check-update') {
      btn.disabled = true;
      const res = await api.checkUpdate();
      btn.disabled = false;
      const fresh = res.ok ? res : (res.update || res);
      ctx.store.update = fresh;
      syncUpdate(true);
      if (!res.ok) return notify.error(res.err || '检查失败');
      if (fresh.noRelease) {
        notify.info(fresh.message || 'PC 端还没有发布版本');
      } else if (fresh.newer) {
        notify.info(`有新版本 v${fresh.latest}，当前 v${fresh.current}`);
        showNotes(fresh);
      } else {
        notify.ok(`已是最新版本 v${fresh.current || ctx.store.version}`);
      }
    } else if (act === 'update-notes') {
      const u = ctx.store.update;
      if (u) showNotes(u);
    } else if (act === 'bg-upload') {
      root.querySelector('#bg-file')?.click();
    } else if (act === 'bg-clear') {
      const res = await api.clearBackground();
      if (!res.ok) return notify.error(res.err || '清除失败');
      notify.ok('背景图已清除');
      if (ctx.store?.config?.app) ctx.store.config.app.background = { enabled: false, file: '' };
      paintBackdrop('');
      renderBg();
    } else if (act === 'copy-local') {
      await copyText(lan?.localUrl || '');
      notify.ok('本机地址已复制');
    } else if (act === 'copy-lan') {
      await copyText(lan?.lanUrl || '');
      notify.ok('局域网地址已复制');
    } else if (act === 'go-server') {
      root.querySelector('[data-sel="server.authMode"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } else if (act === 'clean-tmp' || act === 'clean-diag' || act === 'clean-cache') {
      const what = act === 'clean-tmp' ? 'tmp' : act === 'clean-diag' ? 'diag' : 'cache';
      const label = act === 'clean-tmp' ? '临时文件' : act === 'clean-diag' ? '诊断包' : '缓存';
      const ok = await confirmDialog({ title: `清理${label}？`, desc: '只删可以重新生成的东西，配置、数据与备份不受影响。', confirm: '清理' });
      if (!ok) return;
      btn.disabled = true;
      const res = await api.storageClean(what);
      btn.disabled = false;
      if (!res.ok) return notify.error(res.err || '清理失败');
      storage = res.storage || storage;
      renderStorage();
      notify.ok(`已清理，腾出 ${bytes(res.freed || 0)}`);
    } else if (act === 'analytics-reset') {
      const ok = await confirmDialog({ title: '重置匿名标识？', desc: '下次打开统计会换一个新标识，服务端无法再把新旧数据关联。', confirm: '重置' });
      if (!ok) return;
      const id = 'a-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      const res = await save({ app: { analyticsId: id } }, '已换新标识');
      if (res.ok) renderAnalytics();
    } else if (act === 'policy-privacy' || act === 'policy-terms' || act === 'policy-disclaimer') {
      policyModal(act.replace('policy-', ''));
    } else if (act === 'open-repo') {
      window.open('https://github.com/Zxin-Pro/astrbot-candle', '_blank');
    } else if (act === 'open-site') {
      window.open('https://烛心.xyz', '_blank');
    } else if (act === 'clear-logs') {
      const ok = await confirmDialog({
        title: '清理旧日志？',
        desc: '会删掉除今天以外的历史日志文件，正在写入的日志不受影响。',
        confirm: '清理',
        danger: true,
      });
      if (!ok) return;
      const res = await api.open('logs');
      notify.info('已打开日志目录，可以手动清理，避免误删正在写的文件');
    }
  });

  root.querySelector('#bg-file').addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) return notify.error('图片不能超过 8 MB');
    const dataUrl = await new Promise((resolve) => {
      const fr = new FileReader();
      fr.onload = () => resolve(String(fr.result || ''));
      fr.onerror = () => resolve('');
      fr.readAsDataURL(file);
    });
    if (!dataUrl) return notify.error('读不出这张图');
    const res = await api.setBackground(dataUrl);
    if (!res.ok) return notify.error(res.err || '保存失败');
    notify.ok('背景图已保存');
    if (ctx.store?.config?.app) ctx.store.config.app.background = { enabled: !!res.enabled, file: res.file || '' };
    paintBackdrop(res.enabled ? res.file : '');
    renderBg();
  });

  renderBg();
  renderAnalytics();
  applyCompact(get('app.compact', false));
  loadLan();
  loadStorage(false);

  return {
    update() {
      syncUpdate(false);
    },
  };
}
