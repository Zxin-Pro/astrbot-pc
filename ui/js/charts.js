/** 手写图表：只依赖 SVG，跟着主题色走，尊重 reduced-motion。 */

const NS = 'http://www.w3.org/2000/svg';

function el(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== undefined && v !== null) node.setAttribute(k, String(v));
  }
  return node;
}

/** 面积折线：values 为数字数组 */
export function sparkline(values, { w = 240, h = 44, color = 'var(--brand-500)', fill = true, smooth = true } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: 'none', class: 'spark' });
  const data = (values || []).map((v) => Number(v) || 0);
  if (!data.length) return svg;
  const max = Math.max(1, ...data);
  const min = Math.min(...data, 0);
  const span = max - min || 1;
  const stepX = w / Math.max(1, data.length - 1);
  const y = (v) => h - 3 - ((v - min) / span) * (h - 6);
  const pts = data.map((v, i) => [i * stepX, y(v)]);

  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i += 1) {
    if (!smooth) {
      d += ` L ${pts[i][0]} ${pts[i][1]}`;
      continue;
    }
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const cx = (x0 + x1) / 2;
    d += ` C ${cx} ${y0} ${cx} ${y1} ${x1} ${y1}`;
  }

  if (fill) {
    const gid = `spark-${Math.random().toString(36).slice(2, 8)}`;
    const defs = el('defs');
    const grad = el('linearGradient', { id: gid, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(el('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': '0.26' }));
    grad.appendChild(el('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': '0' }));
    defs.appendChild(grad);
    svg.appendChild(defs);
    svg.appendChild(el('path', {
      d: `${d} L ${w} ${h} L 0 ${h} Z`,
      fill: `url(#${gid})`,
      stroke: 'none',
    }));
  }

  svg.appendChild(el('path', {
    d,
    fill: 'none',
    stroke: color,
    'stroke-width': '1.6',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  }));
  return svg;
}

/** 柱状图（带悬停提示） */
export function bars(values, { w = 320, h = 96, color = 'var(--brand-500)', labels = [] } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${w} ${h}`, preserveAspectRatio: 'none', class: 'bars' });
  const data = (values || []).map((v) => Math.max(0, Number(v) || 0));
  if (!data.length) return svg;
  const max = Math.max(1, ...data);
  const gap = 3;
  const bw = (w - gap * (data.length - 1)) / data.length;
  data.forEach((v, i) => {
    const bh = Math.max(v ? 3 : 1.5, (v / max) * (h - 8));
    const rect = el('rect', {
      x: i * (bw + gap),
      y: h - bh,
      width: bw,
      height: bh,
      rx: Math.min(3, bw / 2),
      fill: color,
      opacity: v ? 0.85 : 0.22,
    });
    if (labels[i] !== undefined) {
      const t = el('title');
      t.textContent = `${labels[i]}：${v}`;
      rect.appendChild(t);
    }
    svg.appendChild(rect);
  });
  return svg;
}

/** 进度环 */
export function ring(percent, { size = 88, stroke = 8, color = 'var(--brand-600)', label = '', suffix = '' } = {}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const p = Math.max(0, Math.min(100, Number(percent) || 0));
  const svg = el('svg', { width: size, height: size, viewBox: `0 0 ${size} ${size}`, class: 'ring' });
  svg.appendChild(el('circle', {
    cx: size / 2, cy: size / 2, r,
    fill: 'none', stroke: 'var(--line)', 'stroke-width': stroke,
  }));
  const arc = el('circle', {
    cx: size / 2, cy: size / 2, r,
    fill: 'none', stroke: color, 'stroke-width': stroke,
    'stroke-linecap': 'round',
    'stroke-dasharray': `${(c * p) / 100} ${c}`,
    transform: `rotate(-90 ${size / 2} ${size / 2})`,
  });
  svg.appendChild(arc);

  const value = suffix ? `${Math.round(p)}${suffix}` : label;
  const caption = suffix ? label : '';
  if (value) {
    const t = el('text', {
      x: '50%', y: caption ? '46%' : '50%',
      'text-anchor': 'middle', 'dominant-baseline': 'central',
      fill: 'var(--ink)', 'font-size': size > 72 ? '16' : '14', 'font-weight': '600',
    });
    t.textContent = value;
    svg.appendChild(t);
  }
  if (caption) {
    const t2 = el('text', {
      x: '50%', y: '62%',
      'text-anchor': 'middle', 'dominant-baseline': 'central',
      fill: 'var(--ink-4)', 'font-size': '10',
    });
    t2.textContent = caption;
    svg.appendChild(t2);
  }
  return svg;
}
