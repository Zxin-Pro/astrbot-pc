/** 小工具：转义、格式化、DOM 助手。 */

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

export function attr(name, value) {
  return value ? ` ${name}="${esc(value)}"` : '';
}

export function h(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function qs(sel, root = document) {
  return root.querySelector(sel);
}

export function qsa(sel, root = document) {
  return [...root.querySelectorAll(sel)];
}

export function on(root, event, selector, handler) {
  root.addEventListener(event, (e) => {
    const el = e.target.closest(selector);
    if (el && root.contains(el)) handler(e, el);
  });
}

export function debounce(fn, wait = 220) {
  let t = 0;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
}

export function throttle(fn, wait = 120) {
  let last = 0;
  let timer = 0;
  return (...args) => {
    const now = Date.now();
    const rest = wait - (now - last);
    if (rest <= 0) {
      last = now;
      fn(...args);
    } else if (!timer) {
      timer = setTimeout(() => {
        timer = 0;
        last = Date.now();
        fn(...args);
      }, rest);
    }
  };
}

export function pad(n, w = 2) {
  return String(n).padStart(w, '0');
}

/** 秒 → 1 天 2 小时 / 3 分 20 秒 */
export function dur(sec, zero = '—') {
  sec = Math.max(0, Math.floor(sec || 0));
  if (!sec) return zero;
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (d) return `${d} 天 ${h} 小时`;
  if (h) return `${h} 小时 ${m} 分`;
  if (m) return `${m} 分 ${s} 秒`;
  return `${s} 秒`;
}

export function durShort(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h) return `${h}h${pad(m)}m`;
  if (m) return `${m}m`;
  return `${sec}s`;
}

export function bytes(n) {
  n = Math.max(0, Number(n) || 0);
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
}

export function num(n) {
  return new Intl.NumberFormat('zh-CN').format(Math.round(Number(n) || 0));
}

export function timeAgo(ts) {
  if (!ts) return '—';
  const s = Math.floor(Date.now() / 1000) - Number(ts);
  if (s < 5) return '刚刚';
  if (s < 60) return `${s} 秒前`;
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} 天前`;
  return fdate(ts, true);
}

export function fdate(ts, withTime = false) {
  if (!ts) return '—';
  const d = new Date(Number(ts) * 1000);
  const base = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  if (!withTime) return base;
  return `${base} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fclock(ts = Date.now() / 1000) {
  const d = new Date(Number(ts) * 1000);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function pct(part, total) {
  if (!total) return 0;
  return Math.round((part / total) * 100);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    ta.remove();
    return ok;
  }
}

export function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** 简易数字滚动，尊重 reduced-motion */
export function animateNumber(el, to, { duration = 520, suffix = '', decimals = 0 } = {}) {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const from = Number(el.dataset.v || 0);
  el.dataset.v = String(to);
  if (reduce || from === to) {
    el.textContent = to.toFixed(decimals) + suffix;
    return;
  }
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / duration);
    const eased = 1 - Math.pow(1 - k, 3);
    const v = from + (to - from) * eased;
    el.textContent = v.toFixed(decimals) + suffix;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
