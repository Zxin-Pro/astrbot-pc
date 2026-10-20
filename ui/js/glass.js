/** 液态玻璃开关。
 *
 * 四件事：
 *   1. 把状态写到 <html data-glass="on|off">，方便别的脚本/样式判断
 *   2. 关的时候直接停用整张 css/glass.css —— 「关」就等于原始界面，
 *      不需要在 glass.css 里再写一份还原规则（写过，漏还原边框，卡片会消失）
 *   3. 记到 localStorage，下次启动首帧就是对的，不会先玻璃再实色
 *   4. 配置里的 app.glass 是跨设备的真源，localStorage 只是加速
 */

const KEY = 'dsh.glass';

function sheet() {
  return document.getElementById('glass-css');
}

function paint(on) {
  document.documentElement.dataset.glass = on ? 'on' : 'off';
  const link = sheet();
  if (link) link.disabled = !on;
}

/** 现在是不是玻璃态。没存过就按「开」算 —— 这是这一版的主视觉。 */
export function glassOn() {
  const v = localStorage.getItem(KEY);
  return v === null ? true : v === '1';
}

/** 切换，并（默认）记到本地。 */
export function applyGlass(on, { persist = true } = {}) {
  const next = !!on;
  paint(next);
  if (persist) localStorage.setItem(KEY, next ? '1' : '0');
  document.dispatchEvent(new CustomEvent('glasschange', { detail: { on: next } }));
  return next;
}

/** 启动时调用：先按本地记录上色，等配置回来再用 syncGlass 校准。 */
export function bootGlass() {
  const on = glassOn();
  paint(on);
  return on;
}

/** 配置到手后调用。本地没存过才听配置的，否则以用户在当前设备的操作为准。 */
export function syncGlass(configValue) {
  if (localStorage.getItem(KEY) !== null) return glassOn();
  if (configValue === false) {
    paint(false);
    return false;
  }
  paint(true);
  return true;
}
