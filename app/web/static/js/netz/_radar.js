// ─── netz/_radar.js ────────────────────────────────────────────────────────
// Polar geometry + SVG render. Two geometries, one interaction model:
// a radar at >= 4 axes, horizontal bars below that (a three-spoke radar
// is an ugly triangle and a two-spoke one is a line). index.js picks by
// axes.length; both accept the same `interactive` flag, so the archive's
// static mini-radar is this module with interaction off.
//
// weather/stats-chart/ could NOT be reused: it is hard cartesian — a
// PAD={l,r,t,b} box, a time-indexed X, buildLinePath, buildXTicks /
// buildYAxis and a hover band. Nothing survives the coordinate change.
// Exactly ONE thing is copied, as a ~15-line pattern rather than an
// import: the 1:1 viewBox sizing below.
//
// THE MISTAKE NOT TO REPEAT (stats-chart/index.js:38-66): a fixed
// viewBox with preserveAspectRatio="none" on an element of a different
// aspect ratio scales X and Y by different factors. SVG text is vector
// and stays sharp under UNIFORM scaling — the "unscharfe, pixelige"
// labels were pure geometric distortion, not rasterisation. Here the
// element is SQUARE and the viewBox is the same square, so the mapping
// is 1:1 by construction and glyphs cannot distort.

import { esc } from '../core/dom.js';
import { radiusForE } from './_mapping.js';
import {
  DIRECTION_LEGEND,
  NEUTRAL,
  axisColor,
  axisIcon,
  isReady,
  labelDe,
  provenanceStroke,
  spokeOpacity,
  vertexFill,
  vertexRadius,
} from './_helpers.js';

// 46 px outside the outer ring for the axis label and its 44 px touch
// target. At 375 px: side 343, r 125.
const LABEL_BAND = 46;
export const MIN_RADAR_AXES = 4;

export function chartSide(vw) {
  return Math.max(240, Math.min(vw - 32, 340));
}

export function chartRadius(side) {
  return side / 2 - LABEL_BAND;
}

/** Cartesian point for (axis index, radius). Index 0 points straight up
 *  and the rest run clockwise, so the first axis of the fixed global
 *  order is always at twelve o'clock. */
export function polar(i, n, radius, cx, cy) {
  const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
  return { x: cx + Math.cos(a) * radius, y: cy + Math.sin(a) * radius };
}

// ── chrome ────────────────────────────────────────────────────────────

// Rings as alternating FILLED DISCS, never strokes: stroked rings are
// exactly the "thin border lines" the design rules forbid. Depth comes
// from colour contrast.
function ringsSvg(cx, cy, r) {
  const bands = [1, 0.75, 0.5, 0.25];
  return bands
    .map((f, i) => {
      const fill = i % 2 === 0 ? 'rgba(255,255,255,.035)' : 'rgba(255,255,255,.06)';
      return `<circle cx="${cx}" cy="${cy}" r="${(r * f).toFixed(1)}" fill="${fill}"/>`;
    })
    .join('');
}

// Ring labels on the VERTICAL spoke only — not on every spoke, which is
// how a radar turns into a wall of numbers. Ring 50 gets a NAME rather
// than a number: it is the reference the whole chart is read against.
function ringLabelsSvg(cx, cy, r) {
  return [
    { f: 0.25, t: '25', o: 0.45 },
    { f: 0.5, t: 'Werk', o: 0.72 },
    { f: 0.75, t: '75', o: 0.45 },
  ]
    .map(
      (m) =>
        `<text x="${cx + 4}" y="${(cy - r * m.f - 3).toFixed(1)}" class="netz-ring-lbl" ` +
        `opacity="${m.o}">${m.t}</text>`,
    )
    .join('');
}

function spokesSvg(axes, cx, cy, r) {
  return axes
    .map((axis, i) => {
      const p = polar(i, axes.length, r, cx, cy);
      return (
        `<line x1="${cx}" y1="${cy}" x2="${p.x.toFixed(1)}" y2="${p.y.toFixed(1)}" ` +
        `stroke="rgba(255,255,255,.10)" stroke-width="1" opacity="${spokeOpacity(axis)}"/>`
      );
    })
    .join('');
}

function pointsFor(axes, values, cx, cy, r) {
  return axes
    .map((axis, i) => {
      const p = polar(i, axes.length, radiusForE(values[i], r), cx, cy);
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    })
    .join(' ');
}

// ONE neutral fill and a 3 px stroke of the same hue. Not per-class
// colour: a rainbow polygon is unreadable. Only the VERTICES carry
// classColor.
function polygonSvg(points) {
  return (
    `<polygon points="${points}" fill="rgba(120,200,255,.16)" ` +
    `stroke="rgba(120,200,255,.85)" stroke-width="3" stroke-linejoin="round"/>`
  );
}

// The learner's Vorschlag, dashed and white. Drawn ONLY across axes
// whose stratum is ready, with the current value used for the rest so
// the shape stays closed. If no axis is ready it is not drawn at all —
// a dashed regular polygon on day one would be a fabricated confidence.
function proposalSvg(axes, values, cx, cy, r) {
  if (!axes.some((a) => isReady(a) && Number.isFinite(Number(a.proposal)))) return '';
  const proposed = axes.map((a, i) =>
    isReady(a) && Number.isFinite(Number(a.proposal)) ? Number(a.proposal) : values[i],
  );
  return (
    `<polygon points="${pointsFor(axes, proposed, cx, cy, r)}" fill="none" ` +
    `stroke="#ffffff" stroke-opacity=".5" stroke-width="2" stroke-dasharray="5 4" ` +
    `stroke-linejoin="round"/>`
  );
}

function vertexSvg(axis, i, value, cx, cy, r, interactive) {
  const p = polar(i, axis._n, radiusForE(value, r), cx, cy);
  const rad = vertexRadius(axis);
  const fill = vertexFill(axis);
  const stroke = provenanceStroke(axis);
  const ready = isReady(axis)
    ? `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${rad / 2 + 4}" ` +
      `fill="none" stroke="#fff" stroke-width="2"/>`
    : '';
  // The invisible 44 px disc IS the touch target — iOS minimum, and at
  // 6 axes on a 125 px radius the arc gap between neighbours at the rim
  // is ~130 px, so they cannot overlap.
  const hit = interactive
    ? `<circle class="netz-hit" data-axis="${esc(axis.label)}" cx="${p.x.toFixed(1)}" ` +
      `cy="${p.y.toFixed(1)}" r="22" fill="transparent"/>`
    : '';
  return (
    `<g class="netz-vertex" data-axis="${esc(axis.label)}">` +
    `<circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="${rad / 2}" ` +
    `fill="${fill}" stroke="${stroke}" stroke-width="1.5"/>${ready}${hit}</g>`
  );
}

function axisLabelsSvg(axes, cx, cy, r, interactive) {
  return axes
    .map((axis, i) => {
      const p = polar(i, axes.length, r + 26, cx, cy);
      const tag = interactive ? 'button' : 'span';
      const attrs = interactive
        ? ` type="button" data-axis-label="${esc(axis.label)}"`
        : '';
      return (
        `<foreignObject x="${(p.x - 34).toFixed(1)}" y="${(p.y - 22).toFixed(1)}" ` +
        `width="68" height="44">` +
        `<${tag} xmlns="http://www.w3.org/1999/xhtml" class="netz-axis-lbl"${attrs}>` +
        `<span class="netz-axis-ic" style="color:${esc(axisColor(axis.label))}">` +
        `${axisIcon(axis.label, 16)}</span>` +
        `<span class="netz-axis-name">${esc(labelDe(axis.label))}</span>` +
        `</${tag}></foreignObject>`
      );
    })
    .join('');
}

// ── public render ─────────────────────────────────────────────────────

/**
 * @param {object} opts
 * @param {Array}  opts.axes         axis rows from /api/netz/state
 * @param {Array}  opts.values       E per axis, in the same order
 * @param {number} opts.side         square side in px
 * @param {boolean} opts.interactive false = the archive's static mini-radar
 */
export function renderRadar({ axes, values, side, interactive = true }) {
  const cx = side / 2;
  const cy = side / 2;
  const r = chartRadius(side);
  const rows = axes.map((a) => ({ ...a, _n: axes.length }));
  return (
    `<svg class="netz-svg" viewBox="0 0 ${side} ${side}" width="${side}" height="${side}" ` +
    `role="img" aria-label="Erkennungsnetz">` +
    ringsSvg(cx, cy, r) +
    spokesSvg(axes, cx, cy, r) +
    ringLabelsSvg(cx, cy, r) +
    proposalSvg(axes, values, cx, cy, r) +
    polygonSvg(pointsFor(axes, values, cx, cy, r)) +
    rows.map((a, i) => vertexSvg(a, i, values[i], cx, cy, r, interactive)).join('') +
    axisLabelsSvg(axes, cx, cy, r, interactive) +
    `</svg>`
  );
}

/** Under 4 axes the radar degenerates, so the same data becomes bars.
 *  Same mapping, same evidence encoding, same drag — only the geometry
 *  changes. */
export function renderBars({ axes, values, side, interactive = true }) {
  const w = side;
  const rows = axes
    .map((axis, i) => {
      const frac = Math.max(0, Math.min(100, values[i])) / 100;
      const c = axisColor(axis.label);
      const hit = interactive
        ? `<span class="netz-bar-hit" data-axis="${esc(axis.label)}"></span>`
        : '';
      const readyRing = isReady(axis) ? ' is-ready' : '';
      const hollow = (axis.evidence?.judged || 0) === 0 ? ' is-empty' : '';
      return (
        `<div class="netz-bar-row${readyRing}${hollow}" data-axis-row="${esc(axis.label)}" ` +
        `style="--cc:${esc(c)};--pv:${esc(provenanceStroke(axis))}">` +
        `<button type="button" class="netz-bar-lbl" data-axis-label="${esc(axis.label)}">` +
        `<span class="netz-axis-ic" style="color:${esc(c)}">${axisIcon(axis.label, 16)}</span>` +
        `<span class="netz-axis-name">${esc(labelDe(axis.label))}</span></button>` +
        `<div class="netz-bar-track" style="opacity:${spokeOpacity(axis)}">` +
        `<i class="netz-bar-fill" style="width:${(frac * 100).toFixed(1)}%"></i>` +
        `<b class="netz-bar-werk"></b>` +
        `<span class="netz-bar-knob" style="left:${(frac * 100).toFixed(1)}%"></span>${hit}` +
        `</div></div>`
      );
    })
    .join('');
  return `<div class="netz-bars" style="max-width:${w}px">${rows}</div>`;
}

/** The always-visible direction legend. Two lines, 11 px, below the
 *  chart — never a tooltip. */
export function legendHtml(axes) {
  const dots = [
    ['manuell', 'var(--netz-prov-manual)'],
    ['automatisch', 'var(--netz-prov-auto)'],
    ['Werk', NEUTRAL],
  ]
    .map(
      ([t, c]) =>
        `<span class="netz-leg-dot"><i style="background:${esc(c)}"></i>${esc(t)}</span>`,
    )
    .join('');
  const empty = axes.every((a) => (a.evidence?.judged || 0) === 0)
    ? '<div class="netz-leg-hint">Hohle Punkte = noch keine Rückmeldungen.</div>'
    : '';
  return (
    `<div class="netz-legend">` +
    `<div class="netz-leg-dir">${esc(DIRECTION_LEGEND[0])}</div>` +
    `<div class="netz-leg-dir">${esc(DIRECTION_LEGEND[1])}</div>` +
    `<div class="netz-leg-prov">${dots}</div>${empty}</div>`
  );
}
