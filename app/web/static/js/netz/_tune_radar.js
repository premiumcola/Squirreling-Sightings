// ─── netz/_tune_radar.js ───────────────────────────────────────────────────
// The Erkennungsprofil's settings radar. Split out of _radar.js (339/400
// lines) rather than grown inside it, and it needs its own geometry
// anyway — three differences from the confidence radar next door:
//
//   * ELLIPSE, not circle. The eight German setting names
//     ("Wildtier-Empfindlichkeit", "Bewegungs-Vortrigger") do not fit the
//     68/76 px label boxes a circular layout leaves room for, which is
//     the whole reason the labels were unreadable.
//   * GROUP COLOUR on vertices, spokes and labels (see TUNE_GROUPS). The
//     polygon itself stays neutral — _radar.js's comment is right that a
//     rainbow polygon is unreadable.
//   * A "Werk" reference outline drawn from each axis's REAL default,
//     not from the 50 % ring. For a confidence axis E 50 IS factory; for
//     `frame_interval_ms` factory is 350 ms, which sits at E 87. Reusing
//     the ring label here would have been a confident lie.
//
// THE MISTAKE NOT TO REPEAT is still in force (_radar.js:13-20): the
// viewBox and the width/height attributes carry the SAME aspect ratio, so
// the mapping stays uniform 1:1 and glyphs cannot distort. An ellipse is
// safe; a square viewBox stretched by CSS is not.
//
// eFromRadius/radiusForE in _mapping.js are a bit-for-bit mirror of
// app/app/thresholds/_apply.py and are pinned by test_netz_mapping_mirror
// — they are deliberately NOT reused or extended here. The ellipse
// inverse below is local to the settings path.

import { esc } from '../core/dom.js';
import { TUNE_GROUPS } from './_settings_axes.js';

// viewBox geometry. Wider than tall so the left/right label boxes have
// horizontal room; PAD is what is reserved OUTSIDE the ring for labels.
export const TUNE_W = 440;
export const TUNE_H = 340;
const PAD_X = 108;
const PAD_Y = 40;
const LABEL_W = 104;
const LABEL_H = 34;
// How far outside the ring the label box sits, per axis.
const LABEL_OFF_X = 16;
const LABEL_OFF_Y = 14;
// Snap window around an axis's own default, so "back to Werk" is
// recoverable by feel — the equivalent of _mapping.js's factory snap.
const SNAP = 2;

export function tuneGeometry(w = TUNE_W, h = TUNE_H) {
  return { cx: w / 2, cy: h / 2, rx: w / 2 - PAD_X, ry: h / 2 - PAD_Y };
}

/** Point on the ellipse for (axis index, radial fraction 0-1). Index 0
 *  points straight up, the rest run clockwise. */
export function tunePolar(i, n, frac, geo, padX = 0, padY = 0) {
  const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
  return {
    x: geo.cx + Math.cos(a) * (geo.rx * frac + padX),
    y: geo.cy + Math.sin(a) * (geo.ry * frac + padY),
  };
}

/** Pointer offset from the centre → E (0-100), normalised PER AXIS so the
 *  same visual distance reads the same E on the long and the short axis.
 *  A plain hypot() would make the vertical axes reach 100 sooner than the
 *  horizontal ones on an ellipse. */
export function eFromEllipse(dx, dy, geo, defaultE = null) {
  if (!(geo.rx > 0) || !(geo.ry > 0)) return 0;
  const frac = Math.hypot(dx / geo.rx, dy / geo.ry);
  const raw = Math.max(0, Math.min(100, Math.round(frac * 100)));
  if (defaultE !== null && Math.abs(raw - defaultE) <= SNAP) return defaultE;
  return raw;
}

function _pointsFor(axes, values, geo) {
  return axes
    .map((_, i) => {
      const p = tunePolar(i, axes.length, Math.max(0, Math.min(100, values[i])) / 100, geo);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    })
    .join(' ');
}

// Concentric ellipses as alternating filled bands — never strokes, which
// are the "thin border lines" the design rules forbid.
function _ringsSvg(geo) {
  return [1, 0.75, 0.5, 0.25]
    .map((f, i) => {
      const fill = i % 2 === 0 ? 'rgba(255,255,255,.035)' : 'rgba(255,255,255,.06)';
      return (
        `<ellipse cx="${geo.cx}" cy="${geo.cy}" rx="${(geo.rx * f).toFixed(1)}" ` +
        `ry="${(geo.ry * f).toFixed(1)}" fill="${fill}"/>`
      );
    })
    .join('');
}

function _spokesSvg(axes, geo) {
  return axes
    .map((axis, i) => {
      const p = tunePolar(i, axes.length, 1, geo);
      return (
        `<line x1="${geo.cx}" y1="${geo.cy}" x2="${p.x.toFixed(1)}" y2="${p.y.toFixed(1)}" ` +
        `stroke="${esc(axis.color)}" stroke-width="1" opacity=".22"/>`
      );
    })
    .join('');
}

// The shipped configuration, dashed. Drawn only when at least one axis
// actually deviates — an outline exactly under the solid polygon is
// visual noise that says nothing.
function _defaultSvg(axes, geo) {
  if (!axes.some((a) => a.E !== a.defaultE)) return '';
  const pts = _pointsFor(
    axes,
    axes.map((a) => a.defaultE),
    geo,
  );
  return (
    `<polygon points="${pts}" fill="none" stroke="#ffffff" stroke-opacity=".38" ` +
    `stroke-width="1.5" stroke-dasharray="4 4" stroke-linejoin="round"/>`
  );
}

function _polygonSvg(points) {
  return (
    `<polygon class="netz-tune-poly" points="${points}" fill="rgba(120,200,255,.14)" ` +
    `stroke="rgba(120,200,255,.75)" stroke-width="2.5" stroke-linejoin="round"/>`
  );
}

function _vertexSvg(axis, i, n, geo, interactive) {
  const p = tunePolar(i, n, Math.max(0, Math.min(100, axis.E)) / 100, geo);
  const manuell = axis.provenance === 'manuell';
  const fill = manuell ? axis.color : 'none';
  const stroke = manuell ? axis.color : 'rgba(255,255,255,.34)';
  // The halo is what answers "which node am I about to grab?". Opacity,
  // not radius: SVG geometry properties are only animatable via CSS in
  // newer engines, while opacity works everywhere and cannot reflow.
  const halo = interactive
    ? `<circle class="netz-tune-halo" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" ` +
      `r="13" fill="${esc(axis.color)}" opacity="0"/>`
    : '';
  // The invisible 44 px disc IS the touch target (iOS minimum).
  const hit = interactive
    ? `<circle class="netz-tune-hit" data-tune-axis="${esc(axis.key)}" ` +
      `cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="22" fill="transparent"/>`
    : '';
  return (
    `<g class="netz-vertex" data-tune-axis="${esc(axis.key)}">${halo}` +
    `<circle class="netz-tune-dot" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5.5" ` +
    `fill="${fill}" stroke="${stroke}" stroke-width="1.8"/>${hit}</g>`
  );
}

/** Move ONE vertex in an already-rendered SVG, in place.
 *
 *  The drag used to re-render the whole chart (rings, spokes, polygon,
 *  eight vertices, eight foreignObject labels) and re-bind every listener
 *  on each pointermove. That is what made dragging feel stepped and
 *  sticky: dozens of nodes rebuilt per frame, with the grabbed node
 *  itself replaced mid-gesture. Here only three attributes and one text
 *  node change, so the browser has nothing to re-layout.
 */
export function moveTuneVertex(svg, axes, key) {
  if (!svg) return;
  const i = axes.findIndex((a) => a.key === key);
  if (i < 0) return;
  const geo = tuneGeometry();
  const axis = axes[i];
  const p = tunePolar(i, axes.length, Math.max(0, Math.min(100, axis.E)) / 100, geo);
  const g = svg.querySelector(`.netz-vertex[data-tune-axis="${CSS.escape(key)}"]`);
  if (g) {
    g.querySelectorAll('circle').forEach((c) => {
      c.setAttribute('cx', p.x.toFixed(1));
      c.setAttribute('cy', p.y.toFixed(1));
    });
  }
  const poly = svg.querySelector('.netz-tune-poly');
  if (poly)
    poly.setAttribute(
      'points',
      _pointsFor(
        axes,
        axes.map((a) => a.E),
        geo,
      ),
    );
  const val = svg.querySelector(`[data-tune-axis-label="${CSS.escape(key)}"] .netz-tlbl-v`);
  if (val) val.textContent = axis.display;
}

// Label + its CURRENT VALUE. Showing the value on the chart is what makes
// the net readable without tapping every spoke — the whole complaint the
// redesign started from.
function _labelsSvg(axes, geo, interactive) {
  return axes
    .map((axis, i) => {
      const p = tunePolar(i, axes.length, 1, geo, LABEL_OFF_X, LABEL_OFF_Y);
      const tag = interactive ? 'button' : 'span';
      const attrs = interactive ? ` type="button" data-tune-axis-label="${esc(axis.key)}"` : '';
      return (
        `<foreignObject x="${(p.x - LABEL_W / 2).toFixed(1)}" ` +
        `y="${(p.y - LABEL_H / 2).toFixed(1)}" width="${LABEL_W}" height="${LABEL_H}">` +
        `<${tag} xmlns="http://www.w3.org/1999/xhtml" class="netz-tlbl"${attrs}>` +
        `<span class="netz-tlbl-n" style="color:${esc(axis.color)}">${esc(axis.label)}</span>` +
        `<span class="netz-tlbl-v">${esc(axis.display)}</span>` +
        `</${tag}></foreignObject>`
      );
    })
    .join('');
}

/**
 * @param {object}  opts
 * @param {Array}   opts.axes         rows from buildTuneAxes()
 * @param {boolean} opts.interactive  false = a static, non-draggable copy
 */
export function renderTuneRadar({ axes, interactive = true }) {
  const geo = tuneGeometry();
  const values = axes.map((a) => a.E);
  return (
    `<svg class="netz-svg netz-tune-svg" viewBox="0 0 ${TUNE_W} ${TUNE_H}" ` +
    `width="${TUNE_W}" height="${TUNE_H}" role="img" aria-label="Erkennungsprofil">` +
    _ringsSvg(geo) +
    _spokesSvg(axes, geo) +
    _defaultSvg(axes, geo) +
    _polygonSvg(_pointsFor(axes, values, geo)) +
    axes.map((a, i) => _vertexSvg(a, i, axes.length, geo, interactive)).join('') +
    _labelsSvg(axes, geo, interactive) +
    `</svg>`
  );
}

/** The four group names as coloured chips — the key to the axis colours. */
export function tuneGroupLegendHtml() {
  return (
    `<div class="netz-tgroups">` +
    Object.values(TUNE_GROUPS)
      .map(
        (g) =>
          `<span class="netz-tgroup"><i style="background:${esc(g.color)}"></i>` +
          `${esc(g.label)}</span>`,
      )
      .join('') +
    `</div>`
  );
}
