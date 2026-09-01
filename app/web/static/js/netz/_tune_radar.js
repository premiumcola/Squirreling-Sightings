// ─── netz/_tune_radar.js ───────────────────────────────────────────────────
// The Erkennungsprofil's settings radar. Split out of _radar.js (339/400
// lines) rather than grown inside it, and it needs its own geometry
// anyway — three differences from the confidence radar next door:
//
//   * ELLIPSE, not circle. The German setting names
//     ("Wildtier-Empfindlichkeit", "Bewegungs-Vortrigger") do not fit the
//     68/76 px label boxes a circular layout leaves room for, which is
//     the whole reason the labels were unreadable. Where those labels GO
//     is _tune_labels.js's problem, not this file's.
//   * GROUP COLOUR on vertices, spokes and labels (see TUNE_GROUPS). The
//     polygon itself stays neutral — _radar.js's comment is right that a
//     rainbow polygon is unreadable.
//   * A "Werk" reference outline drawn from each axis's REAL default,
//     not from the 50 % ring. For a confidence axis E 50 IS factory; for
//     `frame_interval_ms` factory is 350 ms, which sits at E 87. Reusing
//     the ring label here would have been a confident lie.
//
// THE MISTAKE NOT TO REPEAT is still in force (_radar.js:13-20): the
// viewBox and the width/height attributes carry the SAME numbers, so the
// mapping stays uniform 1:1 and glyphs cannot distort. Those numbers are
// the chart box's own measured px size now (netz/_panel.js measures,
// _tune_geometry.js turns the size into the ring) — the SVG fills its
// box edge to edge instead of letterboxing a fixed 560 x 300 inside it.
//
// The ellipse math itself (radarGeometry, tunePolar, eFromEllipse) lives
// in _tune_geometry.js, DOM-free, so the drag layer and a node test can
// share it with the renderer.

import { esc } from '../core/dom.js';
import { TUNE_GROUPS } from './_settings_axes.js';
import { radarGeometry, tunePolar } from './_tune_geometry.js';
import { labelsSvg } from './_tune_labels.js';

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

/** The outer end of every spoke, once — the spokes, the leader lines and
 *  the label rail all need it and it is pure trigonometry. */
function _spokeEnds(axes, geo) {
  return axes.map((axis, i) => ({ axis, ...tunePolar(i, axes.length, 1, geo) }));
}

function _spokesSvg(ends, geo) {
  return ends
    .map(
      (p) =>
        `<line x1="${geo.cx}" y1="${geo.cy}" x2="${p.x.toFixed(1)}" y2="${p.y.toFixed(1)}" ` +
        `stroke="${esc(p.axis.color)}" stroke-width="1" ` +
        `opacity="${p.axis.locked ? '.12' : '.22'}"/>`,
    )
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
  // Every dot carries its group colour now, moved or not — "which group"
  // reads at a glance even before the operator has touched anything
  // (used to be legible only on dots that had already moved, since an
  // at-Werk dot was hollow). "Moved from Werk" is a thin white ring
  // instead: an at-Werk dot's ring is just its own colour again, i.e.
  // no visible ring at all.
  const moved = !!axis.provenance && axis.provenance !== 'werk';
  const stroke = moved ? 'rgba(255,255,255,.85)' : axis.color;
  // A locked axis is drawn, never grabbable: no halo, no hit disc. See
  // _class_rows.js — a class whose Meldung is switched off has a stored
  // threshold that nothing consults, and a draggable vertex there would
  // promise an effect the alarm path never delivers. Hiding the spoke
  // instead would hide the far more useful fact that the class is mute.
  const live = interactive && !axis.locked;
  // The halo is what answers "which node am I about to grab?". Opacity,
  // not radius: SVG geometry properties are only animatable via CSS in
  // newer engines, while opacity works everywhere and cannot reflow.
  const halo = live
    ? `<circle class="netz-tune-halo" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" ` +
      `r="13" fill="${esc(axis.color)}" opacity="0"/>`
    : '';
  // The invisible 44 px disc IS the touch target (iOS minimum).
  const hit = live
    ? `<circle class="netz-tune-hit" data-tune-axis="${esc(axis.key)}" ` +
      `cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="22" fill="transparent"/>`
    : '';
  return (
    `<g class="netz-vertex${axis.locked ? ' is-off' : ''}" ` +
    `data-tune-axis="${esc(axis.key)}">${halo}` +
    `<circle class="netz-tune-dot" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5.5" ` +
    `fill="${esc(axis.color)}" stroke="${stroke}" stroke-width="1.8"/>${hit}</g>`
  );
}

/** The geometry an already-rendered radar was drawn with, read back from
 *  its own viewBox — the one place the size survives once the render
 *  call that measured it has returned. */
export function svgGeometry(svg) {
  const vb = svg.viewBox.baseVal;
  return radarGeometry({ width: vb.width, height: vb.height });
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
  const geo = svgGeometry(svg);
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

/**
 * @param {object}  opts
 * @param {Array}   opts.axes         buildTuneAxes() rows plus, appended,
 *                                    buildClassAxes() rows — ONE net per
 *                                    camera carries both concerns.
 * @param {boolean} opts.interactive  false = a static, non-draggable copy
 * @param {object}  [opts.size]       `{width, height}` — the chart box's
 *                                    measured px size, which becomes the
 *                                    viewBox 1:1. Omitted (no box to
 *                                    measure yet) = the 560 x 300 fallback.
 */
export function renderTuneRadar({ axes, interactive = true, size = null }) {
  const geo = radarGeometry(size || {});
  const values = axes.map((a) => a.E);
  const ends = _spokeEnds(axes, geo);
  return (
    `<svg class="netz-svg netz-tune-svg" viewBox="0 0 ${geo.w} ${geo.h}" ` +
    `width="${geo.w}" height="${geo.h}" role="img" aria-label="Erkennungsprofil">` +
    _ringsSvg(geo) +
    _spokesSvg(ends, geo) +
    _defaultSvg(axes, geo) +
    _polygonSvg(_pointsFor(axes, values, geo)) +
    axes.map((a, i) => _vertexSvg(a, i, axes.length, geo, interactive)).join('') +
    // Label + its CURRENT VALUE, on the rail. Showing the value on the
    // chart is what makes the net readable without tapping every spoke —
    // the complaint the redesign started from.
    labelsSvg(ends, geo, interactive) +
    `</svg>`
  );
}

// A short line/dot glyph for each of the three shape meanings on the
// chart — "was ist die gestrichelte Linie, was die feste?" gets answered
// on the chart itself instead of only once in chat.
function _lineSwatch(dashed) {
  const stroke = dashed ? '#ffffff' : 'rgba(120,200,255,.85)';
  const dash = dashed ? ' stroke-dasharray="3 3" stroke-opacity=".65"' : '';
  return (
    `<svg width="18" height="10" viewBox="0 0 18 10" aria-hidden="true">` +
    `<line x1="1" y1="5" x2="17" y2="5" stroke="${stroke}" stroke-width="2"${dash}/></svg>`
  );
}

function _dotSwatch() {
  return (
    `<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">` +
    `<circle cx="7" cy="7" r="4.5" fill="#7ac8ff" stroke="rgba(255,255,255,.85)" ` +
    `stroke-width="1.5"/></svg>`
  );
}

/** The group names as coloured chips, plus the three line/dot meanings on
 *  the chart itself (solid polygon, dashed Werk outline, moved-vertex
 *  ring) — shown ONCE for the whole Live-Feed section (netz/_panel.js's
 *  initGroupLegend) rather than repeated identically on every panel. */
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
    `<span class="netz-tgroup">${_lineSwatch(false)}Aktuelles Profil</span>` +
    `<span class="netz-tgroup">${_lineSwatch(true)}Werkseinstellung</span>` +
    `<span class="netz-tgroup">${_dotSwatch()}Geändert</span>` +
    `</div>`
  );
}
