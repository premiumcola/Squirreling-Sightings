// ─── mediathek/_chips.js ───────────────────────────────────────────────────
// The count chips under every Mediathek camera card — active cameras,
// the "Alle Medien" tile and the archived strip.
//
// Extracted from orchestration.js (952 lines against a 400 ceiling) so
// the one place that turns `label_counts` into badges is a file of its
// own instead of a block in the middle of the grid orchestrator.
//
// Two defects this module closes, both of the same shape — a chip row
// that does not add up to the grid beside it:
//
//   1. The chip order was a hardcoded six-label list. A `["fox"]`,
//      `["hedgehog"]` or `["marten"]` event has a colour, a threshold
//      and a tile, but no chip: it matched none of the six and was not
//      "motion" either. `_LABEL_ORDER` mirrors the server's one
//      vocabulary (app/app/labels.py) and `_residualChips` catches
//      anything a newer model starts emitting, so nothing can fall out
//      of the row again.
//   2. Archived cards rendered `event_count` under the "Bewegung" icon.
//      `event_count` means "every visible non-timelapse event" — an
//      archived camera with 7 person events read "Bewegung 7". They
//      build their chips from `label_counts` like every other card.
import { esc, hexToRgba } from '../core/dom.js';
import { OBJ_LABEL, objIconSvg } from '../core/icons.js';
import { CAT_COLORS } from '../timeline.js';

// Mirror of OBJECT_LABELS in app/app/labels.py. Order is display order;
// membership decides whether a chip gets the class colour + object icon.
const _LABEL_ORDER = [
  'person',
  'cat',
  'bird',
  'car',
  'dog',
  'squirrel',
  'fox',
  'hedgehog',
  'marten',
  'deer',
];
const _OBJECT_TYPES = new Set(_LABEL_ORDER);

// Chrome chips: not classes, so they carry their own glyph + tone.
const _CHROME_ICONS = {
  event: `<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><circle cx="5" cy="5" r="3.8" stroke="#4a6477" stroke-width="1.3"/><path d="M5 3v2l1.5 1" stroke="#4a6477" stroke-width="1.1" stroke-linecap="round"/></svg>`,
  snap: `<svg width="10" height="10" viewBox="0 0 10 10" fill="none"><rect x="1" y="2.5" width="8" height="6" rx="1.5" stroke="#4a6477" stroke-width="1.2"/><circle cx="5" cy="5.5" r="1.6" fill="#4a6477"/><path d="M3.5 2.5l.4-1h2.2l.4 1" stroke="#4a6477" stroke-width=".9" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
  tl: `<svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="#c4b5fd" stroke-width="1" stroke-linecap="round"><line x1="2.5" y1="1" x2="7.5" y2="1"/><line x1="2.5" y1="9" x2="7.5" y2="9"/><polygon points="3,1.5 7,1.5 5,5" fill="#c4b5fd" opacity=".8"/><polygon points="5,5 3,8.5 7,8.5" stroke="#a855f7" stroke-width="1" fill="none"/></svg>`,
};

const _CHROME_STYLES = {
  event: { bg: 'rgba(255,255,255,.07)', color: 'var(--muted)', radius: '6px' },
  snap: { bg: 'rgba(255,255,255,.07)', color: 'var(--muted)', radius: '6px' },
  tl: { bg: 'rgba(168,85,247,.18)', color: '#c084fc', radius: '8px' },
  motion: { bg: 'rgba(147,197,253,.15)', color: '#93c5fd', radius: '8px' },
};

export function _mocChip(type, count, title) {
  if (_OBJECT_TYPES.has(type)) {
    const col = CAT_COLORS[type] || '#8888aa';
    return `<span class="moc-count-chip" title="${esc(title)}" style="background:${hexToRgba(col, 0.18)};color:${col};border-radius:8px">${objIconSvg(type, 10)} ${count}</span>`;
  }
  const icon = type === 'motion' ? objIconSvg('motion', 10) : _CHROME_ICONS[type];
  const st = _CHROME_STYLES[type] || _CHROME_STYLES.event;
  return `<span class="moc-count-chip" title="${esc(title)}" style="background:${st.bg};color:${st.color};border-radius:${st.radius}">${icon || _CHROME_ICONS.event} ${count}</span>`;
}

// Labels the server counted that this build has no display order for —
// a class from a model added after this file was written. Rendered
// rather than dropped: a missing chip is how a fox sighting became a
// tile nothing counted.
function _residualChips(lc) {
  return Object.keys(lc)
    .filter((k) => k !== 'motion' && !_OBJECT_TYPES.has(k) && (lc[k] || 0) > 0)
    .sort()
    .map((k) => _mocChip(k, lc[k], OBJ_LABEL[k] || k))
    .join('');
}

// The full chip row for one stats entry: objects → residual → motion →
// timelapse. `label_counts.motion` is authoritative — the server counts
// each event once, under its most specific label. The old derivation
// (event_count − objects) invented events whenever event_count held
// something the object labels did not.
export function _buildMocChips(stats) {
  const lc = stats.label_counts || {};
  let html = '';
  for (const k of _LABEL_ORDER) {
    const n = lc[k] || 0;
    if (n > 0) html += _mocChip(k, n, OBJ_LABEL[k] || k);
  }
  html += _residualChips(lc);
  if ((lc.motion || 0) > 0) html += _mocChip('motion', lc.motion, 'Bewegung');
  if ((stats.timelapse_count || 0) > 0) html += _mocChip('tl', stats.timelapse_count, 'Timelapse');
  return html;
}
