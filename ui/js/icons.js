/**
 * 图标：手写 SVG，统一 24 视野 / 1.7 线宽 / 圆头圆角。
 * 只用线条图标 —— 结构位置绝不出现 emoji。
 */

const P = {
  dashboard: '<rect x="3" y="3" width="7.5" height="8.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="5.5" rx="2"/><rect x="13.5" y="12" width="7.5" height="9" rx="2"/><rect x="3" y="15" width="7.5" height="6" rx="2"/>',
  rocket: '<path d="M4.5 15.5c-1.4 1.4-2 5.5-2 5.5s4.1-.6 5.5-2a3 3 0 0 0-3.5-3.5Z"/><path d="M9 14 5.5 10.5C4.7 9.7 4.8 8.4 5.6 7.6l1.2-1.2c.8-.8 2-1 3-.5L13 7.5"/><path d="M14 10.5 20 4.5c1-1 1-1 1.5-2 .5 1 .5 1 0 2.5L15.5 11"/><circle cx="14.5" cy="9.5" r="1.6"/>',
  server: '<rect x="3" y="3.5" width="18" height="7" rx="2.2"/><rect x="3" y="13.5" width="18" height="7" rx="2.2"/><path d="M7 7h.01M7 17h.01"/>',
  terminal: '<rect x="2.8" y="4" width="18.4" height="16" rx="3"/><path d="m7 9.5 3 2.6-3 2.6M12.5 15h4"/>',
  qrcode: '<rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.6"/><rect x="14" y="3.5" width="6.5" height="6.5" rx="1.6"/><rect x="3.5" y="14" width="6.5" height="6.5" rx="1.6"/><path d="M14 14h2.6v2.6H14zM18 18h2.6v2.6H18zM14 20.4h1.4M20.4 14v1.4"/>',
  layers: '<path d="m12 3 8.5 4.6L12 12.2 3.5 7.6 12 3Z"/><path d="m3.5 12.2 8.5 4.6 8.5-4.6"/><path d="m3.5 16.6 8.5 4.6 8.5-4.6"/>',
  archive: '<rect x="3" y="4" width="18" height="4.5" rx="1.8"/><path d="M4.6 8.5V19a1.5 1.5 0 0 0 1.5 1.5h11.8a1.5 1.5 0 0 0 1.5-1.5V8.5"/><path d="M10 12.5h4"/>',
  settings: '<circle cx="12" cy="12" r="3.1"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09A1.7 1.7 0 0 0 8.9 19.3a1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.54 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.54h.08A1.7 1.7 0 0 0 10.1 3V3a2 2 0 1 1 4 0v.09A1.7 1.7 0 0 0 15.1 4.6a1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9v.08A1.7 1.7 0 0 0 21 10.1h.09a2 2 0 1 1 0 4H21a1.7 1.7 0 0 0-1.56 1.03Z"/>',
  play: '<path d="M8 5.6v12.8a1 1 0 0 0 1.53.85l10.2-6.4a1 1 0 0 0 0-1.7L9.53 4.75A1 1 0 0 0 8 5.6Z"/>',
  stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/>',
  refresh: '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/><path d="M20.5 4v5h-5"/>',
  external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18.5 14.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7.5a2 2 0 0 1 2-2h3.5"/>',
  copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2.4"/><path d="M15.5 5.5A2 2 0 0 0 13.5 3.5h-8a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2"/>',
  check: '<path d="m4.5 12.5 5 5 10-11"/>',
  alert: '<path d="M12 3.8 21 19.2a1.4 1.4 0 0 1-1.2 2.1H4.2A1.4 1.4 0 0 1 3 19.2L12 3.8Z"/><path d="M12 9.5v4.2M12 17h.01"/>',
  xcircle: '<circle cx="12" cy="12" r="8.6"/><path d="m9.4 9.4 5.2 5.2M14.6 9.4l-5.2 5.2"/>',
  info: '<circle cx="12" cy="12" r="8.6"/><path d="M12 11v5.2M12 7.8h.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>',
  sun: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.2 5.2l1.4 1.4M17.4 17.4l1.4 1.4M18.8 5.2l-1.4 1.4M6.6 17.4l-1.4 1.4"/>',
  moon: '<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8Z"/>',
  chevron: '<path d="m9 5.5 6.5 6.5L9 18.5"/>',
  chevronDown: '<path d="m5.5 9 6.5 6.5L18.5 9"/>',
  download: '<path d="M12 3.5v11"/><path d="m7.5 10.5 4.5 4.5 4.5-4.5"/><path d="M4 17.5V18a2.5 2.5 0 0 0 2.5 2.5h11A2.5 2.5 0 0 0 20 18v-.5"/>',
  folder: '<path d="M3.5 7.2A2.2 2.2 0 0 1 5.7 5h3.4l2 2.4h7.2a2.2 2.2 0 0 1 2.2 2.2v7.6a2.2 2.2 0 0 1-2.2 2.2H5.7a2.2 2.2 0 0 1-2.2-2.2V7.2Z"/>',
  trash: '<path d="M4 6.5h16"/><path d="M9.5 6.5V4.8A1.3 1.3 0 0 1 10.8 3.5h2.4a1.3 1.3 0 0 1 1.3 1.3v1.7"/><path d="M6.5 6.5 7.4 19a1.6 1.6 0 0 0 1.6 1.5h6a1.6 1.6 0 0 0 1.6-1.5l.9-12.5"/><path d="M10.5 10.5v5.5M13.5 10.5v5.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  shield: '<path d="M12 3.2 19.5 6v6.2c0 4.2-3 7.2-7.5 8.6-4.5-1.4-7.5-4.4-7.5-8.6V6L12 3.2Z"/><path d="m9.2 12 2 2 3.6-3.8"/>',
  activity: '<path d="M3.5 12h4l2.5-7 4 14 2.5-7h4"/>',
  file: '<path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9l-5.5-5.5Z"/><path d="M13.5 3.5V9H19"/><path d="M9 13.5h6M9 17h4"/>',
  message: '<path d="M20.5 12a8.5 8.5 0 0 1-8.5 8.5 9 9 0 0 1-3.4-.65L3.5 21l1.2-4.6A8.5 8.5 0 1 1 20.5 12Z"/>',
  clock: '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.5V12l3 2"/>',
  cpu: '<rect x="6.5" y="6.5" width="11" height="11" rx="2.2"/><path d="M9.5 2.8v3.7M14.5 2.8v3.7M9.5 17.5v3.7M14.5 17.5v3.7M2.8 9.5h3.7M2.8 14.5h3.7M17.5 9.5h3.7M17.5 14.5h3.7"/>',
  drive: '<rect x="3" y="8" width="18" height="8.5" rx="2.4"/><path d="M6.5 12.2h.01M9.8 12.2h.01"/><path d="M3 12.2h18"/>',
  wifi: '<path d="M4 9.5a13 13 0 0 1 16 0"/><path d="M7 13a8.4 8.4 0 0 1 10 0"/><path d="M10 16.4a4 4 0 0 1 4 0"/><path d="M12 19.6h.01"/>',
  power: '<path d="M12 3.5v8"/><path d="M6.8 6.6a8.5 8.5 0 1 0 10.4 0"/>',
  database: '<ellipse cx="12" cy="6" rx="7.5" ry="3.2"/><path d="M4.5 6v12c0 1.8 3.4 3.2 7.5 3.2s7.5-1.4 7.5-3.2V6"/><path d="M4.5 12c0 1.8 3.4 3.2 7.5 3.2s7.5-1.4 7.5-3.2"/>',
  x: '<path d="M6 6l12 12M18 6 6 18"/>',
  arrowUpRight: '<path d="M7 17 17 7"/><path d="M8 7h9v9"/>',
  bell: '<path d="M18 9a6 6 0 1 0-12 0c0 4-1.5 5.5-1.5 5.5h15S18 13 18 9Z"/><path d="M10.3 18.5a2 2 0 0 0 3.4 0"/>',
  filter: '<path d="M4 5.5h16l-6.2 7.3v5.5l-3.6 2v-7.5L4 5.5Z"/>',
  pin: '<path d="M12 21v-6"/><path d="M8 3h8l-1 6.5 2.5 3.5h-11L9 9.5 8 3Z"/>',
  shieldCheck: '<path d="M12 3.2 19.5 6v6.2c0 4.2-3 7.2-7.5 8.6-4.5-1.4-7.5-4.4-7.5-8.6V6L12 3.2Z"/><path d="m8.8 11.8 2.2 2.2 4.2-4.4"/>',
  bolt: '<path d="M13.4 2.5 4.8 13.2h6.2l-1.4 8.3 8.6-10.7h-6.2l1.4-8.3Z"/>',
  route: '<circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="5.5" r="2.5"/><path d="M8 18.5h6.5a3.5 3.5 0 0 0 0-7H9.5a3.5 3.5 0 0 1 0-7H16"/>',
  logo: '<rect x="2.5" y="2.5" width="19" height="19" rx="6"/>',
  sparkles: '<path d="M11 3.5 12.9 9l5.5 1.9-5.5 1.9L11 18.3l-1.9-5.5L3.6 10.9 9.1 9 11 3.5Z"/><path d="M18.5 15.5l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9.9-2.4Z"/>',
  arrowRight: '<path d="M4.5 12h15"/><path d="m14 6.5 5.5 5.5-5.5 5.5"/>',
  tray: '<path d="M3.5 13.5h4l1.5 3h6l1.5-3h4"/><path d="M4.8 5.2h14.4a1.6 1.6 0 0 1 1.5 1.1l1.3 7.2a2.5 2.5 0 0 1-2.5 2.9H4.5A2.5 2.5 0 0 1 2 13.5l1.3-7.2a1.6 1.6 0 0 1 1.5-1.1Z"/>',
};

export function icon(name, size = 18, stroke = 1.7) {
  const d = P[name] || P.info;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
}

export function filledIcon(name, size = 18) {
  const d = P[name] || P.info;
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">${d}</svg>`;
}

export const ICON_NAMES = Object.keys(P);
