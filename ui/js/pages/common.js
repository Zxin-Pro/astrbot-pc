/** 页面公共小件：状态胶囊、空状态、骨架、页头。 */

import { icon } from '../icons.js';
import { esc } from '../util.js';

export const STATUS_MAP = {
  running: { label: '运行中', cls: 'pill--ok', dot: true },
  starting: { label: '启动中', cls: 'pill--warn', dot: true },
  stopped: { label: '已停止', cls: '', dot: false },
  crashed: { label: '已掉线', cls: 'pill--bad', dot: true },
  blocked: { label: '已熔断', cls: 'pill--bad', dot: false },
};

export function statusPill(status) {
  const s = STATUS_MAP[status] || { label: status || '未知', cls: '', dot: false };
  return `<span class="pill ${s.cls}">${s.dot ? '<i class="dot live-dot"></i>' : '<i class="dot" style="opacity:.5"></i>'}${esc(s.label)}</span>`;
}

export function pageHead({ title, desc, actions = '', badge = '' }) {
  return `
    <div class="page-head">
      <div class="page-head__text">
        <h1>${esc(title)}${badge}</h1>
        ${desc ? `<p>${esc(desc)}</p>` : ''}
      </div>
      <div class="page-head__actions">${actions}</div>
    </div>`;
}

export function emptyState({ iconName = 'info', title, desc, action = '' }) {
  return `
    <div class="empty">
      ${icon(iconName, 34, 1.4)}
      <strong>${esc(title)}</strong>
      <p>${esc(desc)}</p>
      ${action}
    </div>`;
}

export function skeletonCard(lines = 3) {
  return `<div class="card">
    <div class="skeleton" style="height:14px;width:38%;margin-bottom:14px"></div>
    ${Array.from({ length: lines }).map((_, i) => `<div class="skeleton" style="height:10px;width:${92 - i * 12}%;margin-bottom:9px"></div>`).join('')}
  </div>`;
}

export function kvRow(label, value, mono = false) {
  return `<div class="kv__row"><dt>${esc(label)}</dt><dd class="${mono ? 'mono' : ''}">${value}</dd></div>`;
}
