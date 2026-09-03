// ─── weather/stats-chart/_hover_tip.js ─────────────────────────────────────
// The plain hover half of the chart pointer stack: pointer → sample
// lookup, the vertical guide line, and the floating tooltip that lists
// every active line's value at the hovered timestamp.
//
// Split out of _hover.js (404 lines, over the 400 ceiling). The cut is
// the one the file already documented in its own section banner: this
// module is what a chart with NO drag-to-zoom and NO markMode needs, and
// _hover_drag.js is the additive rest. The layering is one-directional —
// _hover_drag.js imports from here, never the other way round — so the
// two never form the import cycle that a naive "move the drag block out"
// would have produced (_onDown calls _onMove, _onUp calls _paintAt).
//
// The default tooltip CONTENT builders (_defaultRows / _defaultHead)
// live here rather than in _hover.js because _paintDragTooltip needs
// _defaultHead too: the timestamps the operator reads while dragging are
// formatted by the exact same function as the ones the plain tooltip
// shows, so the two can never round differently.

import { WEATHER_STATS_PALETTE, _wsFmtVal } from '../stats.js';

// Default tooltip body: one row per active metric at this sample.
//
// `units` comes from the payload the chart was rendered with, the same
// place `labels` already came from. It used to be missing here and
// _wsFmtVal fell through to the Wetterdaten panel's module-global
// state — so the Gewitter-Archiv's detail chart, which ships its own
// units map on purpose, printed every hovered value without a unit
// whenever that panel had not been opened yet.
export function _defaultRows(sample, fields, labels, units) {
  const sampleVals = sample.values || {};
  return fields
    .map((key) => {
      const v = sampleVals[key];
      if (v == null || !Number.isFinite(Number(v))) return '';
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      const lbl = labels[key] || key;
      const valFmt = _wsFmtVal(key, Number(v), units);
      return `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${colour}"></span><span class="ws-tt-lbl">${lbl}</span><span class="ws-tt-val">${valFmt}</span></div>`;
    })
    .filter(Boolean)
    .join('');
}

// Default tooltip header: HH:MM, with "· dd.MM" appended when the window
// spans more than one day so the same time-of-day isn't ambiguous.
export function _defaultHead(sampleTs, spansMultiDay) {
  const p2 = (n) => (n < 10 ? '0' : '') + n;
  const dt = new Date(sampleTs);
  const headTime = `${p2(dt.getHours())}:${p2(dt.getMinutes())}`;
  if (!spansMultiDay) return headTime;
  return `${headTime} · ${p2(dt.getDate())}.${p2(dt.getMonth() + 1)}`;
}

// Position the tip 12 right / 6 above the cursor, clamped to the wrapper.
export function _placeTip(tip, wrap, ev) {
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
export function _nearestIdx(samples, t) {
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

export function _hide(c) {
  c.tip.hidden = true;
  c.guide.style.display = 'none';
  if (c.hideTimer.id) {
    clearTimeout(c.hideTimer.id);
    c.hideTimer.id = 0;
  }
}

// Map the pointer's local x onto a sample, then paint guide + tooltip.
export function _paintAt(c, localX, ev) {
  const t = c.tFirst + ((localX - c.pad.l) / c.cw) * c.tSpan;
  const idx = _nearestIdx(c.samples, t);
  const sample = c.samples[idx];
  const sampleTs = new Date(sample.ts).getTime();
  const guideX = c.pad.l + ((sampleTs - c.tFirst) / c.tSpan) * c.cw;
  c.guide.setAttribute('x1', guideX.toFixed(1));
  c.guide.setAttribute('x2', guideX.toFixed(1));
  c.guide.style.display = '';
  const head = c.opts.head ? c.opts.head(sample, idx) : _defaultHead(sampleTs, c.spansMultiDay);
  const rows = c.opts.rows
    ? c.opts.rows(sample, idx)
    : _defaultRows(sample, c.fields, c.labels, c.units);
  c.tip.innerHTML = `<div class="ws-tt-time">${head}</div>${rows}`;
  c.tip.hidden = false;
  _placeTip(c.tip, c.wrap, ev);
  if (typeof c.opts.onGuide === 'function') c.opts.onGuide(sample, idx);
}

// The pointer's local x in viewBox units. Shared by hover and brush so
// the "CSS transform on an ancestor / resize race" correction exists
// exactly once. `null` when the SVG isn't laid out yet.
export function _localXOf(c, ev) {
  const rect = c.svg.getBoundingClientRect();
  if (rect.width === 0) return null;
  // The viewBox is authored at the wrapper's own CSS-pixel size, so this
  // ratio is normally 1. It stays a ratio rather than a plain
  // subtraction because a CSS transform on an ancestor (or a resize
  // landing between render and pointer event) would otherwise silently
  // offset every lookup.
  return (ev.clientX - rect.left) * (c.vbW / rect.width);
}

// Same correction as _localXOf, vertical axis — only used by the
// markMode tap handler (nothing else in this file needs a y position),
// so it silently returns null when `c.ch` was never supplied.
export function _localYOf(c, ev) {
  if (c.ch === null) return null;
  const rect = c.svg.getBoundingClientRect();
  if (rect.height === 0) return null;
  const vbH = c.pad.t + c.ch + c.pad.b;
  return (ev.clientY - rect.top) * (vbH / rect.height);
}

export function _onMove(c, ev) {
  if (!Number.isFinite(c.tFirst) || !Number.isFinite(c.tLast) || c.tSpan <= 0) {
    _hide(c);
    return;
  }
  const localX = _localXOf(c, ev);
  if (localX === null) return;
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
