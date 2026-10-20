/** 登录：扫码上线。二维码是从 NapCat 落盘的文件里读的，不碰手机。 */

import { api } from '../api.js';
import { notify } from '../components.js';
import { icon } from '../icons.js';
import { esc, timeAgo, sleep } from '../util.js';
import { pageHead } from './common.js';

const TIPS = [
  { t: '用手机 QQ 扫上面这个码', d: '扫完在手机上点确认登录，电脑这边会自己接上。' },
  { t: '等十秒左右', d: 'NapCat 登录成功后，「服务」里的两个进程都会变成运行中。' },
  { t: '去控制台配模型', d: '第一次用需要填一个模型 API Key，之后就能聊天了。' },
];

export function mount(root, ctx) {
  const state = { dataUrl: '', mtime: 0, stale: false, path: '', polling: false, timer: 0, ticker: 0 };

  root.innerHTML = `
    <div class="page">
      ${pageHead({
        title: '登录',
        desc: '每次换电脑或掉线之后，扫一下就好。',
        actions: `<button class="btn" data-act="refresh">${icon('refresh', 15)}重新获取</button>`,
      })}

      <div class="grid grid--split">
        <div class="card card--qr">
          <div class="qr-stage" id="qr-stage">
            <div class="qr-skeleton skeleton" id="qr-skel" hidden></div>
            <div class="qr-placeholder" id="qr-ph">
              ${icon('qrcode', 44)}
              <strong>还没有二维码</strong>
              <p>先在「服务」里启动 NapCat，二维码生成后会自动出现在这里。</p>
            </div>
            <img id="qr-img" alt="QQ 登录二维码" hidden />
            <div class="qr-stale" id="qr-stale" hidden>
              ${icon('alert', 22)}
              <strong>这个码可能过期了</strong>
              <p>刷新一下拿新的，旧码一分钟左右就会失效。</p>
            </div>
          </div>
          <div class="qr-actions">
            <button class="btn btn--primary btn--lg" data-act="refresh" id="qr-refresh">${icon('refresh', 16)}换一张</button>
            <button class="btn btn--lg" data-act="save" id="qr-save" disabled>${icon('download', 16)}保存图片</button>
          </div>
          <div class="qr-meta">
            <span class="inline">
              <span class="live-dot" id="qr-live" aria-hidden="true"></span>
              <span id="qr-live-text">每 3 秒自动检查</span>
            </span>
            <span class="muted" id="qr-time">—</span>
          </div>
        </div>

        <div class="stack">
          <div class="card">
            <div class="card-head"><h3>三步上线</h3></div>
            <div class="stack" style="gap:14px">
              ${TIPS.map((s, i) => `
                <div class="tip-row">
                  <span class="step__idx" style="width:24px;height:24px">${i + 1}</span>
                  <div>
                    <strong>${esc(s.t)}</strong>
                    <p class="muted" style="font-size:12.5px;margin-top:2px">${esc(s.d)}</p>
                  </div>
                </div>`).join('')}
            </div>
          </div>

          <div class="card">
            <div class="card-head">
              <h3>扫码登录不上？</h3>
              <button class="btn btn--sm btn--ghost" data-act="to-logs">看日志${icon('chevron', 13)}</button>
            </div>
            <ul class="check-list">
              <li><span class="check-list__i">${icon('check', 12)}</span>NapCat 是否在「服务」里显示运行中</li>
              <li><span class="check-list__i">${icon('check', 12)}</span>换一个手机 QQ 号试试，风控的号扫不出来</li>
              <li><span class="check-list__i">${icon('check', 12)}</span>电脑时间是否准确，偏差大会导致签名失败</li>
              <li><span class="check-list__i">${icon('check', 12)}</span>改用「文件传码」：把码导到手机相册再扫</li>
            </ul>
            <div class="inline" style="margin-top:14px">
              <button class="btn btn--block" data-act="restart-napcat">${icon('refresh', 15)}重启 NapCat 再试</button>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  const stage = root.querySelector('#qr-stage');
  const img = root.querySelector('#qr-img');
  const ph = root.querySelector('#qr-ph');
  const skel = root.querySelector('#qr-skel');
  const stale = root.querySelector('#qr-stale');
  const timeEl = root.querySelector('#qr-time');
  const saveBtn = root.querySelector('#qr-save');
  const liveText = root.querySelector('#qr-live-text');
  const liveDot = root.querySelector('#qr-live');

  function paint(res, quiet) {
    if (res && res.ok === false) {
      if (!quiet) notify.error(res.err || '获取二维码失败');
      showPlaceholder();
      return;
    }
    if (!res || !res.exists) {
      showPlaceholder();
      return;
    }
    skel.hidden = true;
    ph.hidden = true;
    stale.hidden = !res.stale;
    if (res.dataUrl !== state.dataUrl) {
      img.src = res.dataUrl;
      img.hidden = false;
    }
    state.dataUrl = res.dataUrl;
    state.mtime = res.mtime || 0;
    state.path = res.path || '';
    state.stale = !!res.stale;
    stage.classList.toggle('is-stale', state.stale);
    timeEl.textContent = res.mtime ? `生成于 ${timeAgo(res.mtime)}` : '';
    saveBtn.disabled = false;
    if (res.stale) {
      skel.hidden = true;
      img.hidden = true;
      ph.hidden = true;
      stale.hidden = false;
    }
  }

  function showPlaceholder() {
    img.hidden = true;
    stale.hidden = true;
    skel.hidden = true;
    ph.hidden = false;
    state.dataUrl = '';
    timeEl.textContent = '';
    saveBtn.disabled = true;
  }

  async function fetchQr(quiet) {
    const res = await api.qr();
    paint(res, quiet);
    return res;
  }

  async function loop() {
    if (state.polling) return;
    state.polling = true;
    while (state.polling) {
      await fetchQr(true);
      await sleep(3000);
    }
  }

  function stopLoop() {
    state.polling = false;
    liveDot.classList.remove('is-live');
    liveText.textContent = '已暂停检查';
  }

  fetchQr().then((res) => {
    if (res && res.exists) {
      liveDot.classList.add('is-live');
      loop();
    } else {
      liveText.textContent = '启动 NapCat 后自动出现';
      loop();
    }
  });

  state.ticker = setInterval(() => {
    if (state.mtime) timeEl.textContent = `生成于 ${timeAgo(state.mtime)}`;
  }, 5000);

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const act = btn.dataset.act;
    if (act === 'refresh') {
      btn.disabled = true;
      skel.hidden = false;
      ph.hidden = true;
      const res = await fetchQr();
      skel.hidden = true;
      btn.disabled = false;
      if (res && res.exists) notify.ok('已取到最新的二维码');
      else notify.warn('暂时还没有新码，确认 NapCat 在运行');
    } else if (act === 'save') {
      if (!state.dataUrl) return notify.warn('还没有二维码可保存');
      const a = document.createElement('a');
      a.href = state.dataUrl;
      a.download = 'qq-login-qr.png';
      a.click();
      notify.ok('已保存到下载目录');
    } else if (act === 'to-logs') {
      ctx.go('logs');
    } else if (act === 'restart-napcat') {
      btn.disabled = true;
      const res = await api.service('napcat', 'restart');
      btn.disabled = false;
      if (res.ok) notify.ok('NapCat 正在重启，稍等片刻');
      else notify.error(res.err || '重启失败');
    }
  });

  return {
    update(store, reason) {
      if (reason === 'log') {
        const msg = store.lastLog;
        if (msg && /\.png$/i.test(msg.path || '') && state.dataUrl === '') fetchQr(true);
      }
    },
    destroy() {
      stopLoop();
      clearInterval(state.ticker);
    },
  };
}
