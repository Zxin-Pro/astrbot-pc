/** 设置：所有开关都在这里，改完立刻生效，不用重启。 */

import { api } from '../api.js';
import { confirmDialog, notify, updateNotesModal } from '../components.js';
import { icon } from '../icons.js';
import { getSetting } from '../store.js';
import { esc } from '../util.js';
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
      await save(patch);
    } else if (el.matches('select[data-sel]')) {
      const path = el.dataset.sel.split('.');
      const patch = {};
      let cur = patch;
      path.forEach((k, i) => {
        if (i === path.length - 1) cur[k] = el.value;
        else cur = cur[k] = {};
      });
      await save(patch, el.dataset.sel === 'server.authMode' ? '已保存，重启界面后生效' : '已保存');
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

  return {
    update() {
      syncUpdate(false);
    },
  };
}
