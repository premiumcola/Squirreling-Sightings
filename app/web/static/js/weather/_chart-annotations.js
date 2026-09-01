// ─── weather/_chart-annotations.js ──────────────────────────────────────
// Data-anchored chart markers for the manual-event save flow — the
// operator's own words: "ich sehe dran, dass die Sicht massiv runtergeht,
// die Bewölkung massiv hoch geht, und dann hier die Windböen und auch der
// Niederschlag anfangen … Im Sturmauge kommt dann das Blitzpotenzial
// hoch und der Niederschlag auf Maximum, und danach beruhigt sich's
// wieder." They want to mark WHERE on the chart (which curve, which
// moment) supports WHICH phase of the storm's life cycle, as structured
// data ("Du musst wissen, wo der Pfeil liegt und auf was sich der Fall
// bezieht") — not a freeform arrow, a snap-to-sample flag.
//
// Deliberately its OWN module rather than growing stats-chart/_hover.js
// (already sizeable) or _manual-event-save.js (the save FORM's own
// concern, not the chart's pointer behaviour): this file owns the
// marker STATE (the set being built for the current save-panel session)
// + the geometry to place/hit-test/render one, so both the chart's
// pointer wiring (stats-chart/index.js, which calls into
// handleChartTap) and the save form (_manual-event-save.js, which reads
// annotationsPayload()) share one implementation instead of two.
//
// A marker's position is derived, never stored as raw pixels: it snaps
// to the curve's own real sample (same nearest-sample contract
// stats-chart/_hover.js's tooltip already uses) at the exact (curve,
// timestamp) the operator tapped, via the SAME per-field {lo, hi}
// normalisation buildLinePath draws the line against
// (stats-chart/_paths.js's fieldValueRange) — so a marker always sits
// exactly on the curve it names, in every render, at every chart size.
import { fieldValueRange } from './stats-chart/_paths.js';

// Exactly the operator's own three-stage description. Keep in sync with
// MANUAL_EVENT_PHASES in app/app/weather_service/_manual_events.py.
export const ANNOTATION_PHASES = ['aufbau', 'kern', 'abbau'];
export const ANNOTATION_PHASE_LABEL_DE = {
  aufbau: 'Aufbau',
  kern: 'Kern',
  abbau: 'Abbau',
};
// Arrow glyphs read the life-cycle direction at a glance; kern gets a
// filled dot instead of an arrow — it is the peak, not a direction.
export const ANNOTATION_PHASE_GLYPH = { aufbau: '↗', kern: '●', abbau: '↘' };
export const ANNOTATION_PHASE_COLOR = {
  aufbau: '#facc15', // building — same amber as the thunder badge
  kern: '#fb7185', // the core/peak — alarm red
  abbau: '#7faec9', // calming down — the app's own calm storm-blue
};

// Half the iOS 44 px touch-target floor — every marker's hit test (both
// "is this tap ON an existing marker" and the invisible tap-padding the
// rendered glyph gets) uses this radius, exactly the "small visual glyph
// with a larger invisible tap-padding box" pattern the map pin
// (.ws-map-pin-hit, weather/pin-toggle.js's sibling in 25-mobile.css)
// already uses elsewhere in this codebase.
const _HIT_RADIUS = 22;

// ── State: the marker set for the CURRENT save-panel session ───────────
// Mirrors weather/_zoom.js's own contract: pure module state, redraw is
// always the CALLER's job (renderWeatherStatsChart), never triggered
// from in here.
const _state = { markers: [], active: false };

export function resetChartAnnotations() {
  _state.markers = [];
  _state.active = false;
}

export function isMarkModeActive() {
  return _state.active;
}

export function setMarkModeActive(on) {
  _state.active = !!on;
}

// Defensive copy — callers must go through addAnnotation/removeAnnotation
// to mutate, never splice this array directly.
export function chartAnnotations() {
  return _state.markers.slice();
}

// The exact shape the backend validates (routes/weather_manual_events.py
// ::_validate_annotations) — curve/ts/phase, nothing else per record.
export function annotationsPayload() {
  return _state.markers.map((m) => ({ curve: m.curve, ts: m.ts, phase: m.phase }));
}

function _addMarker(curve, ts, phase) {
  const i = _state.markers.findIndex((m) => m.curve === curve && m.ts === ts);
  if (i >= 0) _state.markers[i] = { curve, ts, phase }; // re-marking replaces the phase
  else _state.markers.push({ curve, ts, phase });
}

export function removeAnnotation(curve, ts) {
  _state.markers = _state.markers.filter((m) => !(m.curve === curve && m.ts === ts));
}

// ── Geometry: where a marker sits on THIS render's chart ────────────────
// `geo` is the small, explicit shape every function below shares:
// { samples, fields, pad, cw, ch, tFirst, tSpan, wrap, svg }.

function _tsToX(ts, geo) {
  const t = new Date(ts).getTime();
  return geo.pad.l + ((t - geo.tFirst) / geo.tSpan) * geo.cw;
}

function _valueToY(field, value, samples, pad, ch) {
  const range = fieldValueRange(samples, field);
  if (!range) return null;
  const norm = (value - range.lo) / (range.hi - range.lo);
  return pad.t + ch - norm * ch;
}

// A marker's current screen position, or null when it can't be placed —
// its curve is hidden (legend toggle), its exact sample fell out of the
// current (zoomed) window, or the sample has no value for that curve.
// Skipping quietly is correct here: the marker's DATA is untouched, it
// just has nothing to draw against right now.
export function annotationScreenPos(marker, geo) {
  if (!geo.fields.includes(marker.curve)) return null;
  const sample = geo.samples.find((s) => s.ts === marker.ts);
  if (!sample) return null;
  const v = sample.values?.[marker.curve];
  if (typeof v !== 'number' || !Number.isFinite(v)) return null;
  const y = _valueToY(marker.curve, v, geo.samples, geo.pad, geo.ch);
  if (y == null) return null;
  return { x: _tsToX(marker.ts, geo), y };
}

// Which visible curve's rendered line sits closest (vertically) to a
// click at sample index `idx` — the "click ON a curve" hit-test the
// operator asked for, reusing the exact per-field normalisation the line
// itself is drawn with (fieldValueRange) rather than inventing separate
// hit-testing math for arbitrary lines.
export function nearestCurveAt(samples, fields, idx, clickY, pad, ch) {
  let bestField = null;
  let bestDist = Infinity;
  for (const field of fields) {
    const v = samples[idx]?.values?.[field];
    if (typeof v !== 'number' || !Number.isFinite(v)) continue;
    const y = _valueToY(field, v, samples, pad, ch);
    if (y == null) continue;
    const dist = Math.abs(y - clickY);
    if (dist < bestDist) {
      bestDist = dist;
      bestField = field;
    }
  }
  return bestField;
}

function _findMarkerNear(geo, x, y) {
  for (const m of _state.markers) {
    const pos = annotationScreenPos(m, geo);
    if (!pos) continue;
    if (Math.hypot(pos.x - x, pos.y - y) <= _HIT_RADIUS) return m;
  }
  return null;
}

// ── The tap handler: stats-chart/_hover.js's markMode branch calls this
// on every tap inside the plot area while marking is active. Either
// removes an existing marker under the tap (misclick recovery — "click
// it again... to remove") or resolves the nearest curve at the snapped
// sample and opens the phase picker to add a new one.
export function handleChartTap(geo, idx, x, y, onChange) {
  const existing = _findMarkerNear(geo, x, y);
  if (existing) {
    removeAnnotation(existing.curve, existing.ts);
    onChange?.();
    return;
  }
  const curve = nearestCurveAt(geo.samples, geo.fields, idx, y, geo.pad, geo.ch);
  const sample = geo.samples[idx];
  if (!curve || !sample) return;
  _openPhasePicker(geo.wrap, x, y, (phase) => {
    _addMarker(curve, sample.ts, phase);
    onChange?.();
  });
}

// ── The inline phase picker — a small HTML overlay (like the tooltip,
// not baked into the SVG string) so it can carry real ≥44 px touch
// targets. Positioned at (x, y) which, thanks to the chart's 1:1
// viewBox-to-CSS-pixel authoring (stats-chart/index.js's own comment on
// _sizeOf), are already CSS pixels relative to `wrap`.
function _closePhasePicker(wrap) {
  wrap?.querySelector?.('.ws-chart-annot-picker')?.remove();
}

function _openPhasePicker(wrap, x, y, onPick) {
  if (!wrap?.appendChild) return; // no real DOM (e.g. a node-test stub) — nothing to show
  _closePhasePicker(wrap);
  const el = document.createElement('div');
  el.className = 'ws-chart-annot-picker';
  el.innerHTML = ANNOTATION_PHASES.map(
    (p) =>
      `<button type="button" class="ws-chart-annot-pick" data-phase="${p}" style="--pc:${ANNOTATION_PHASE_COLOR[p]}">${ANNOTATION_PHASE_GLYPH[p]} ${ANNOTATION_PHASE_LABEL_DE[p]}</button>`,
  ).join('');
  wrap.appendChild(el);
  const wRect = wrap.getBoundingClientRect();
  const px = Math.max(4, Math.min(x, wRect.width - (el.offsetWidth || 0) - 4));
  const py = Math.max(4, Math.min(y, wRect.height - (el.offsetHeight || 0) - 4));
  el.style.left = px + 'px';
  el.style.top = py + 'px';
  const onOutside = (ev) => {
    if (el.contains(ev.target)) return;
    _closePhasePicker(wrap);
    document.removeEventListener('pointerdown', onOutside, true);
  };
  el.addEventListener('click', (ev) => {
    const btn = ev.target.closest?.('.ws-chart-annot-pick');
    if (!btn) return;
    onPick(btn.dataset.phase);
    _closePhasePicker(wrap);
    document.removeEventListener('pointerdown', onOutside, true);
  });
  // Deferred: this same tap's pointerdown is still bubbling when the
  // picker opens — listening synchronously would close it immediately.
  setTimeout(() => document.addEventListener('pointerdown', onOutside, true), 0);
}

// ── Rendering — ONE function for both the live editing chart (in mark
// mode, markers carry a removable "×") and the read-only redraw when
// viewing a saved manual event (opts.interactive left false).
function _markerGlyphSvg(x, y, colour, glyph, interactive) {
  const removeGlyph = interactive
    ? `<text x="${(x + 9).toFixed(1)}" y="${(y - 7).toFixed(1)}" text-anchor="middle" font-size="9" font-weight="700" fill="#fca5b5" paint-order="stroke" stroke="rgba(10,10,14,.9)" stroke-width="2.5">×</text>`
    : '';
  return `<g class="ws-chart-annot${interactive ? ' is-interactive' : ''}">
    <circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="6" fill="${colour}" stroke="#0b0f14" stroke-width="1.5"/>
    <text x="${x.toFixed(1)}" y="${(y - 10).toFixed(1)}" text-anchor="middle" font-size="11" fill="${colour}" paint-order="stroke" stroke="rgba(10,10,14,.9)" stroke-width="3">${glyph}</text>
    ${removeGlyph}
  </g>`;
}

// `geo` needs only { samples, fields, pad, cw (unused but kept for a
// consistent geo shape), ch, tFirst, tSpan }. `opts.palette` is injected
// by the caller (stats-chart/index.js already imports
// WEATHER_STATS_PALETTE for the lines themselves) rather than imported
// here, so this module never needs a weather/stats.js import — that
// would cycle back through stats-chart/index.js, which imports THIS
// module.
export function buildAnnotationMarkersSvg(annotations, geo, opts = {}) {
  if (!annotations || !annotations.length) return '';
  const interactive = !!opts.interactive;
  const palette = opts.palette || {};
  let svg = '<g class="ws-chart-annot-layer">';
  for (const m of annotations) {
    const pos = annotationScreenPos(m, geo);
    if (!pos) continue;
    const colour = palette[m.curve] || '#94a3b8';
    const glyph = ANNOTATION_PHASE_GLYPH[m.phase] || '•';
    svg += _markerGlyphSvg(pos.x, pos.y, colour, glyph, interactive);
  }
  svg += '</g>';
  return svg;
}
