// ─── mediaview/status-legend.js ────────────────────────────────────────────
// F1 · The ONE status legend for every MediaView mode (recorded /
// weather / live-detect). Colour encodes IDENTITY (the per-track
// tracks.json colour / per-class colour); dash style + opacity encode
// STATUS — that's what the legend explains:
//
//     Bestätigt · ↓ Schwach · ≈ Ghost · ⊘ Maskiert · "Farbe = Person-Nr."
//
// Live-detect reports verdicts as pass / unter Schwelle (belowthresh) /
// gefiltert (filtered); those map onto the SAME four-row vocabulary via
// MV_LIVE_VERDICT_CAT below so the dashed-stroke meaning is identical
// everywhere — one legend, not three.
//
// Auto-position: when mounted as a floating overlay on the frame, the
// legend sits on the vertical edge OPPOSITE the camera OSD timestamp
// band (opts.osdBand) so the two never overlap (F1 / J1). Mounted
// inline in a chrome row it inherits the row's flow and the OSD-avoid
// attribute is a no-op.
//
// This is the single owner of the status → {dash, alpha, marker} map
// (MV_STATUS_STYLE). K folds mediathek/bbox-overlay/renderer.js's
// private _STATUS_STYLE into this so the painted strokes and the
// legend swatches keep matching from one table.

import { byId, esc } from '../core/dom.js';

// Canonical status-style table. dash = SVG/canvas dash array (empty =
// solid); alpha = stroke opacity; marker = the glyph the bbox score
// pill prints so a "↓ 24 %" pill links visually to the "↓ Schwach"
// legend row.
// dash + alpha mirror mediathek/bbox-overlay/renderer.js _STATUS_STYLE
// so the legend swatch and the painted bbox stroke read identically.
// ``masked`` has no entry there (it swaps to a neutral grey solid via
// _MASKED_COLOR) — it's spelled out here so the legend can show it.
export const MV_STATUS_STYLE = {
  confirmed: { dash: [], alpha: 1, marker: '' },
  weak: { dash: [6, 4], alpha: 1, marker: '↓' },
  ghost: { dash: [2, 4], alpha: 0.55, marker: '≈' },
  masked: { dash: [], alpha: 1, marker: '⊘' },
};

export const MV_STATUS_ROWS = [
  { key: 'confirmed', label: 'Bestätigt' },
  { key: 'weak', label: 'Schwach' },
  { key: 'ghost', label: 'Ghost' },
  { key: 'masked', label: 'Maskiert' },
];

// Live test-detection verdict → unified status category. The live
// pipeline gates a raw detection to pass / belowthresh / filtered;
// the recorded tracks.json already speaks confirmed / weak / ghost /
// masked. Both render through MV_STATUS_STYLE.
export const MV_LIVE_VERDICT_CAT = {
  pass: 'confirmed',
  belowthresh: 'weak',
  filtered: 'masked',
};

const _MASKED_COLOR = '#64748b';
// I4 · NEUTRAL swatch — colour now encodes the track number (see the
// "Farbe = Person-Nr." tail), so the legend swatch conveys only LINE STYLE
// (solid / dashed / dotted), never a hue meaning. Not green.
const _SWATCH_COLOR = '#e2e8f0';

/**
 * Map any verdict/status token onto a canonical MV_STATUS_STYLE key.
 * Accepts both live verdicts (pass/belowthresh/filtered) and recorded
 * statuses (confirmed/weak/ghost/masked). Unknown → 'confirmed'.
 */
export function mvStatusCategory(verdict) {
  if (!verdict) return 'confirmed';
  if (MV_LIVE_VERDICT_CAT[verdict]) return MV_LIVE_VERDICT_CAT[verdict];
  return MV_STATUS_STYLE[verdict] ? verdict : 'confirmed';
}

// 28×8 swatch painted with the row's dash + opacity. ``masked`` flips
// to neutral grey to match the painted stroke.
export function mvStatusSwatch(key) {
  const style = MV_STATUS_STYLE[key] || MV_STATUS_STYLE.confirmed;
  const stroke = key === 'masked' ? _MASKED_COLOR : _SWATCH_COLOR;
  const dash = style.dash.length ? ` stroke-dasharray="${style.dash.join(' ')}"` : '';
  return (
    `<svg width="28" height="8" viewBox="0 0 28 8" opacity="${style.alpha}" aria-hidden="true">` +
    `<line x1="2" y1="4" x2="26" y2="4" stroke="${stroke}" stroke-width="2" stroke-linecap="round"${dash}/>` +
    `</svg>`
  );
}

function _rowHtml(row) {
  const marker = MV_STATUS_STYLE[row.key]?.marker;
  const text = `${marker ? `${marker} ` : ''}${row.label}`.trim();
  return (
    `<span class="mv-legend-row" data-cat="${row.key}">` +
    `<span class="mv-legend-swatch">${mvStatusSwatch(row.key)}</span>` +
    `<span class="mv-legend-label">${esc(text)}</span></span>`
  );
}

// One shared popover node for the mobile "?" chip — reuses the dark
// .mv-live-toggle-tip surface so it matches the per-pill description
// popovers operators already know.
let _tipEl = null;
function _ensureTip() {
  if (_tipEl) return _tipEl;
  _tipEl = document.createElement('div');
  _tipEl.className = 'mv-live-toggle-tip mv-legend-tip';
  _tipEl.setAttribute('role', 'tooltip');
  _tipEl.hidden = true;
  document.body.appendChild(_tipEl);
  return _tipEl;
}

function _showTip(target) {
  const tip = _ensureTip();
  tip.innerHTML =
    `<div class="mv-legend-tip-body">${MV_STATUS_ROWS.map(_rowHtml).join('')}` +
    `<div class="mv-legend-tip-tail">Farbe = Person-Nr.</div></div>`;
  tip.hidden = false;
  const r = target.getBoundingClientRect();
  const tipR = tip.getBoundingClientRect();
  const above = r.top - tipR.height - 10;
  const top = above >= 8 ? above : r.bottom + 10;
  const vw = window.innerWidth || document.documentElement.clientWidth;
  let left = r.left + r.width / 2 - tipR.width / 2;
  left = Math.max(8, Math.min(vw - tipR.width - 8, left));
  tip.style.top = `${Math.round(top)}px`;
  tip.style.left = `${Math.round(left)}px`;
}

function _hideTip() {
  if (_tipEl) _tipEl.hidden = true;
}

/**
 * Mount the unified status legend.
 *
 * @param {HTMLElement|string} host  Container element or its id.
 * @param {Object} [opts]
 * @param {boolean} [opts.float]   Absolute overlay on the frame (true)
 *   vs inline chrome row (false, default).
 * @param {'top'|'bottom'|null} [opts.osdBand]  Where the camera OSD
 *   timestamp band sits — the floating legend auto-positions on the
 *   opposite edge so it never overlaps it.
 * @returns {{ el: HTMLElement, reposition(band): void, teardown(): void }}
 */
export function renderStatusLegend(host, opts = {}) {
  const row = typeof host === 'string' ? byId(host) : host;
  if (!row) return null;
  const wrap = document.createElement('div');
  wrap.className = 'mv-legend';
  if (opts.float) wrap.dataset.float = '1';
  wrap.innerHTML =
    `<div class="mv-legend-desktop" aria-label="Status-Legende">` +
    `${MV_STATUS_ROWS.map(_rowHtml).join('')}` +
    `<span class="mv-legend-tail">Farbe = Person-Nr.</span></div>` +
    `<button type="button" class="mv-legend-chip" aria-label="Status-Legende anzeigen" title="Status-Legende">?</button>`;
  row.appendChild(wrap);

  const reposition = (band) => {
    // Floating legend sits opposite the OSD band; an unknown/absent
    // band defaults to the bottom edge (OSD is most often top-burned).
    const avoid = band === 'bottom' ? 'top' : 'bottom';
    wrap.dataset.osdAvoid = avoid;
  };
  if (opts.float) reposition(opts.osdBand);

  const chip = wrap.querySelector('.mv-legend-chip');
  let open = false;
  const close = () => {
    open = false;
    _hideTip();
  };
  chip.addEventListener('click', (ev) => {
    ev.stopPropagation();
    open = !open;
    if (open) _showTip(chip);
    else _hideTip();
  });
  let lp = 0;
  chip.addEventListener(
    'touchstart',
    () => {
      clearTimeout(lp);
      lp = setTimeout(() => {
        open = true;
        _showTip(chip);
      }, 500);
    },
    { passive: true },
  );
  chip.addEventListener('touchend', () => clearTimeout(lp));
  chip.addEventListener('touchcancel', () => clearTimeout(lp));
  const outside = (ev) => {
    if (!open) return;
    if (ev.target.closest && ev.target.closest('.mv-legend-chip')) return;
    if (ev.target.closest && ev.target.closest('.mv-legend-tip')) return;
    close();
  };
  document.addEventListener('touchstart', outside, { passive: true });
  document.addEventListener('click', outside);
  return {
    el: wrap,
    reposition,
    teardown: () => {
      document.removeEventListener('touchstart', outside);
      document.removeEventListener('click', outside);
      _hideTip();
      wrap.remove();
    },
  };
}
