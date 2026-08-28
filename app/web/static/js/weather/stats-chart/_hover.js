// ─── weather/stats-chart/_hover.js ─────────────────────────────────────────
// Hover tooltip — vertical guide line + floating box that lists every
// active line's value at the hovered timestamp. Pointer events cover
// mouse + touch + pen. Touch taps auto-hide after 2.5 s. Reduced-motion
// users get instant show/hide (the CSS .ws-chart-tooltip has no
// transition by default; this comment is the contract).
//
// The tooltip CONTENT is injectable (opts.head / opts.rows) so the storm
// compare chart can print "[1] Hagelfront · 2400 J/kg" per episode
// instead of one row per metric. Everything else — the x→sample lookup,
// the guide placement, the clamping, the touch auto-hide — is identical
// in both views and must stay one implementation.

import { WEATHER_STATS_PALETTE, _wsFmtVal } from '../stats.js';

// Default tooltip body: one row per active metric at this sample.
function _defaultRows(sample, fields, labels) {
  const sampleVals = sample.values || {};
  return fields
    .map((key) => {
      const v = sampleVals[key];
      if (v == null || !Number.isFinite(Number(v))) return '';
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      const lbl = labels[key] || key;
      const valFmt = _wsFmtVal(key, Number(v));
      return `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${colour}"></span><span class="ws-tt-lbl">${lbl}</span><span class="ws-tt-val">${valFmt}</span></div>`;
    })
    .filter(Boolean)
    .join('');
}

// Default tooltip header: HH:MM, with "· dd.MM" appended when the window
// spans more than one day so the same time-of-day isn't ambiguous.
function _defaultHead(sampleTs, spansMultiDay) {
  const p2 = (n) => (n < 10 ? '0' : '') + n;
  const dt = new Date(sampleTs);
  const headTime = `${p2(dt.getHours())}:${p2(dt.getMinutes())}`;
  if (!spansMultiDay) return headTime;
  return `${headTime} · ${p2(dt.getDate())}.${p2(dt.getMonth() + 1)}`;
}

// Position the tip 12 right / 6 above the cursor, clamped to the wrapper.
function _placeTip(tip, wrap, ev) {
  const wRect = wrap.getBoundingClientRect();
  const cx = ev.clientX - wRect.left + 12;
  const cy = ev.clientY - wRect.top - 6;
  tip.style.left = '0px';
  tip.style.top = '0px';
  const px = Math.max(4, Math.min(cx, wRect.width - tip.offsetWidth - 4));
  const py = Math.max(4, Math.min(cy, wRect.height - tip.offsetHeight - 4));
  tip.style.left = px + 'px';
  tip.style.top = py + 'px';
}

// Nearest sample index to timestamp `t`.
function _nearestIdx(samples, t) {
  let bestIdx = 0,
    bestDiff = Infinity;
  for (let i = 0; i < samples.length; i++) {
    const d = Math.abs(new Date(samples[i].ts).getTime() - t);
    if (d < bestDiff) {
      bestDiff = d;
      bestIdx = i;
    }
  }
  return bestIdx;
}

// Everything the pointer handlers need, resolved once at bind time.
// Returns null when the chart has no hover chrome to drive.
function _context(wrap, samples, fields, pad, cw, vbW, data, opts) {
  const svg = wrap.querySelector('svg');
  if (!svg) return null;
  const area = svg.querySelector('.ws-chart-hover-area');
  const guide = svg.querySelector('.ws-chart-guide');
  const tip = wrap.querySelector('.ws-chart-tooltip');
  if (!area || !guide || !tip) return null;
  const tFirst = new Date(samples[0]?.ts).getTime();
  const tLast = new Date(samples[samples.length - 1]?.ts).getTime();
  const first = new Date(tFirst);
  const last = new Date(tLast);
  return {
    wrap,
    svg,
    area,
    guide,
    tip,
    samples,
    fields,
    pad,
    cw,
    vbW,
    opts,
    tFirst,
    tLast,
    tSpan: tLast - tFirst,
    labels: data?.labels_de || {},
    hideTimer: { id: 0 },
    spansMultiDay:
      Number.isFinite(first.getTime()) &&
      Number.isFinite(last.getTime()) &&
      first.toDateString() !== last.toDateString(),
  };
}

function _hide(c) {
  c.tip.hidden = true;
  c.guide.style.display = 'none';
  if (c.hideTimer.id) {
    clearTimeout(c.hideTimer.id);
    c.hideTimer.id = 0;
  }
}

// Map the pointer's local x onto a sample, then paint guide + tooltip.
function _paintAt(c, localX, ev) {
  const t = c.tFirst + ((localX - c.pad.l) / c.cw) * c.tSpan;
  const idx = _nearestIdx(c.samples, t);
  const sample = c.samples[idx];
  const sampleTs = new Date(sample.ts).getTime();
  const guideX = c.pad.l + ((sampleTs - c.tFirst) / c.tSpan) * c.cw;
  c.guide.setAttribute('x1', guideX.toFixed(1));
  c.guide.setAttribute('x2', guideX.toFixed(1));
  c.guide.style.display = '';
  const head = c.opts.head ? c.opts.head(sample, idx) : _defaultHead(sampleTs, c.spansMultiDay);
  const rows = c.opts.rows ? c.opts.rows(sample, idx) : _defaultRows(sample, c.fields, c.labels);
  c.tip.innerHTML = `<div class="ws-tt-time">${head}</div>${rows}`;
  c.tip.hidden = false;
  _placeTip(c.tip, c.wrap, ev);
  if (typeof c.opts.onGuide === 'function') c.opts.onGuide(sample, idx);
}

function _onMove(c, ev) {
  if (!Number.isFinite(c.tFirst) || !Number.isFinite(c.tLast) || c.tSpan <= 0) {
    _hide(c);
    return;
  }
  const rect = c.svg.getBoundingClientRect();
  if (rect.width === 0) return;
  // The viewBox is authored at the wrapper's own CSS-pixel size, so this
  // ratio is normally 1. It stays a ratio rather than a plain
  // subtraction because a CSS transform on an ancestor (or a resize
  // landing between render and pointer event) would otherwise silently
  // offset every lookup.
  const localX = (ev.clientX - rect.left) * (c.vbW / rect.width);
  if (localX < c.pad.l || localX > c.pad.l + c.cw) {
    _hide(c);
    return;
  }
  _paintAt(c, localX, ev);
  // Touch: auto-hide after 2.5 s of no further pointer events.
  if (ev.pointerType === 'touch') {
    if (c.hideTimer.id) clearTimeout(c.hideTimer.id);
    c.hideTimer.id = setTimeout(() => _hide(c), 2500);
  }
}

export function bindChartHover(wrap, samples, fields, pad, cw, vbW, data, opts = {}) {
  const c = _context(wrap, samples, fields, pad, cw, vbW, data, opts);
  if (!c) return;
  const move = (ev) => _onMove(c, ev);
  c.area.addEventListener('pointermove', move);
  c.area.addEventListener('pointerdown', move);
  c.area.addEventListener('pointerleave', () => {
    _hide(c);
    if (typeof opts.onGuide === 'function') opts.onGuide(null, -1);
  });
}
