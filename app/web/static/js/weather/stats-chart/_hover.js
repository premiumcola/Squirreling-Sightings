// ─── weather/stats-chart/_hover.js ─────────────────────────────────────────
// Hover tooltip — vertical guide line + floating box that lists every
// active line's value at the hovered timestamp. Pointer events cover
// mouse + touch + pen. Touch taps auto-hide after 2.5 s. Reduced-motion
// users get instant show/hide (the CSS .ws-chart-tooltip has no
// transition by default; this comment is the contract).

import { WEATHER_STATS_PALETTE, _wsFmtVal } from '../stats.js';

export function bindChartHover(wrap, samples, fields, pad, cw, vbW, data) {
  const svg = wrap.querySelector('svg');
  if (!svg) return;
  const area = svg.querySelector('.ws-chart-hover-area');
  const guide = svg.querySelector('.ws-chart-guide');
  const tip = wrap.querySelector('.ws-chart-tooltip');
  if (!area || !guide || !tip) return;
  const tFirst = new Date(samples[0]?.ts).getTime();
  const tLast = new Date(samples[samples.length - 1]?.ts).getTime();
  const tSpan = tLast - tFirst;
  const labels = data?.labels_de || {};
  const hideTimer = { id: 0 };
  // Multi-day data: tooltip head shows "HH:MM · dd.MM" instead of just
  // HH:MM so the same time-of-day on different days isn't ambiguous.
  const firstDate = new Date(tFirst);
  const lastDate = new Date(tLast);
  const spansMultiDay =
    Number.isFinite(firstDate.getTime()) &&
    Number.isFinite(lastDate.getTime()) &&
    firstDate.toDateString() !== lastDate.toDateString();

  function _hide() {
    tip.hidden = true;
    guide.style.display = 'none';
    if (hideTimer.id) {
      clearTimeout(hideTimer.id);
      hideTimer.id = 0;
    }
  }

  function _onMove(ev) {
    if (!Number.isFinite(tFirst) || !Number.isFinite(tLast) || tSpan <= 0) {
      _hide();
      return;
    }
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;
    // The viewBox is authored at the wrapper's own CSS-pixel size, so
    // this ratio is normally 1. It stays a ratio rather than a plain
    // subtraction because a CSS transform on an ancestor (or a resize
    // landing between render and pointer event) would otherwise silently
    // offset every lookup.
    const localX = (ev.clientX - rect.left) * (vbW / rect.width);
    if (localX < pad.l || localX > pad.l + cw) {
      _hide();
      return;
    }
    // Map x → timestamp → nearest sample index.
    const t = tFirst + ((localX - pad.l) / cw) * tSpan;
    let bestIdx = 0,
      bestDiff = Infinity;
    for (let i = 0; i < samples.length; i++) {
      const ts = new Date(samples[i].ts).getTime();
      const d = Math.abs(ts - t);
      if (d < bestDiff) {
        bestDiff = d;
        bestIdx = i;
      }
    }
    const sample = samples[bestIdx];
    const sampleTs = new Date(sample.ts).getTime();
    const guideX = pad.l + ((sampleTs - tFirst) / tSpan) * cw;
    guide.setAttribute('x1', guideX.toFixed(1));
    guide.setAttribute('x2', guideX.toFixed(1));
    guide.style.display = '';
    // Tooltip body. Sample values live on sample.values[key], not on
    // sample[key] directly — the previous version walked the wrong
    // path so every row was filtered out and only the time header
    // rendered. Multi-day windows append "· dd.MM" so the same HH:MM
    // on adjacent days isn't ambiguous.
    const p2 = (n) => (n < 10 ? '0' : '') + n;
    const dt = new Date(sampleTs);
    const headTime = `${p2(dt.getHours())}:${p2(dt.getMinutes())}`;
    const head = spansMultiDay
      ? `${headTime} · ${p2(dt.getDate())}.${p2(dt.getMonth() + 1)}`
      : headTime;
    const sampleVals = sample.values || {};
    const rows = fields
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
    tip.innerHTML = `<div class="ws-tt-time">${head}</div>${rows}`;
    tip.hidden = false;
    // Position: 12 right + -6 top of cursor, clamped to wrap bounds.
    const wRect = wrap.getBoundingClientRect();
    const cx = ev.clientX - wRect.left + 12;
    const cy = ev.clientY - wRect.top - 6;
    tip.style.left = '0px';
    tip.style.top = '0px';
    const tipW = tip.offsetWidth;
    const tipH = tip.offsetHeight;
    const px = Math.max(4, Math.min(cx, wRect.width - tipW - 4));
    const py = Math.max(4, Math.min(cy, wRect.height - tipH - 4));
    tip.style.left = px + 'px';
    tip.style.top = py + 'px';
    // Touch: auto-hide after 2.5 s of no further pointer events.
    if (ev.pointerType === 'touch') {
      if (hideTimer.id) clearTimeout(hideTimer.id);
      hideTimer.id = setTimeout(_hide, 2500);
    }
  }

  area.addEventListener('pointermove', _onMove);
  area.addEventListener('pointerdown', _onMove);
  area.addEventListener('pointerleave', _hide);
}
