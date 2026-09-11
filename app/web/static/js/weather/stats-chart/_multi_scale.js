// ─── weather/stats-chart/_multi_scale.js ───────────────────────────────────
// The vertical scale of the episode overlay chart, and the identity
// channel that tells the reader which curve is which METRIC.
//
// ── Why one band PER METRIC, and why the numbers move to the tooltip ──
//
// The compare chart used to carry exactly one metric, so one absolute Y
// axis in that metric's own unit was both possible and right: two
// episodes' curve heights were directly comparable, which is the whole
// point of the view.
//
// „gebe im gewitterarchiv auch die möglichkeit beliebige kurven parallel
// anzuwählen und die dann mit anderen von anderen gewittern zu
// vergleichen!" puts several metrics on that plot at once, and
// 2400 J/kg, 12 mm/h and 95 km/h share no axis that means anything. Two
// dishonest answers were available; both are recorded here so neither
// gets tried again:
//
//   One absolute axis for everything — the lightning-potential curve
//   pins the top of the plot and every other metric collapses onto the
//   floor. The axis would be labelled, the labels would be true, and the
//   chart would still show nothing.
//
//   Per-SERIES normalisation — every curve stretched to its own extent.
//   That destroys the one property this view exists for: a 12 mm/h
//   cloudburst and a 3 mm/h shower would draw as identical curves.
//
// So: one band per metric, SHARED by every episode drawn on that metric.
// Within a metric the comparison stays absolute and honest; across
// metrics the plot claims only shape and timing, the Y axis drops its
// labels, and the real numbers move to the legend and the tooltip. That
// is the decision _axes.js::buildYAxis already recorded for the
// Wetterstatistik chart's all-lines mode — a shared-scale label there
// was "technically accurate and practically noise" („kp was das soll").
// Same problem, same answer.
//
// The X domain is NOT split the same way. It stays a single union of
// every episode's relative minutes, because „bitte achte beim vergleich
// auch auf die zeitliche ausdehnung die muss vergleichbar bleiben also
// kein verzug des zeitrahmens!" — a 40-minute squall must occupy a
// third of the width next to a two-hour front, not be stretched to match
// it.

import { approxTextWidth } from './_pad.js';

/**
 * The relative-minute domain plus one {lo, hi} value band per metric.
 * `null` when nothing finite was found at all.
 *
 * The band floor is pinned to 0 for the non-negative storm metrics so
 * two curves' heights stay directly comparable rather than each being
 * stretched to its own extent. Every threshold line is folded into its
 * OWN metric's band so none of them is ever drawn off-plot — a rain
 * threshold must not inflate the lightning band.
 */
export function valueBands(series, thresholds = []) {
  let minMin = Infinity,
    maxMin = -Infinity;
  const bands = {};
  for (const s of series || []) {
    const band = bands[s.metric] || (bands[s.metric] = { lo: Infinity, hi: -Infinity });
    for (const [m, v] of s.points || []) {
      if (Number.isFinite(m)) {
        if (m < minMin) minMin = m;
        if (m > maxMin) maxMin = m;
      }
      if (Number.isFinite(v)) {
        if (v < band.lo) band.lo = v;
        if (v > band.hi) band.hi = v;
      }
    }
  }
  for (const t of thresholds) {
    const band = bands[t.metric];
    if (band && Number.isFinite(t.value) && t.value > band.hi) band.hi = t.value;
  }
  let any = false;
  for (const [key, band] of Object.entries(bands)) {
    if (!Number.isFinite(band.lo) || !Number.isFinite(band.hi)) {
      delete bands[key];
      continue;
    }
    band.lo = Math.min(0, band.lo);
    if (band.hi - band.lo < 1e-9) band.hi = band.lo + 1;
    any = true;
  }
  if (!any || !Number.isFinite(minMin)) return null;
  return { minMin, maxMin, bands };
}

/** Plot y for `v` on `band`. The one place the band → pixel rule lives. */
export function bandY(band, v, pad, ch) {
  return pad.t + ch - ((v - band.lo) / (band.hi - band.lo)) * ch;
}

/** Plot x for relative minute `m` on the shared union domain. */
export function domainX(dom, m, pad, cw) {
  const span = dom.maxMin - dom.minMin || 1;
  return pad.l + ((m - dom.minMin) / span) * cw;
}

// Direct end labels — the metric identity channel, and deliberately not
// a colour one.
//
// Colour is already spoken for: in this view it means "which episode"
// and nothing else, and one colour must mean one thing per view. Dash
// patterns were rejected once already (see _seriesPaths in _multi.js) —
// a dashed 15-minute storm curve reads as noise rather than as a second
// channel. Stroke width is the neighbouring chart's emphasis channel
// (wsLineEmphasis) and would collide with it.
//
// What is left is the strongest option anyway: labelling the line
// itself. "1 Böen" sitting on the end of a curve survives greyscale,
// colour-blindness and a screenshot, and it needs no legend round-trip —
// it answers both questions at the point the reader's eye already is.
// The slot number rides along so the label alone identifies the curve
// with no colour at all.
const LABEL_FONT = 10;
const LABEL_ROW = 12;

// The last finite reading of a series — where its label goes.
function _terminus(s) {
  let last = null;
  for (const [m, v] of s.points || []) {
    if (Number.isFinite(m) && Number.isFinite(v)) last = [m, v];
  }
  return last;
}

// Labels that would overlap get pushed apart vertically, and only when
// they actually overlap: the episodes' spans end at different minutes,
// so most termini are already far enough apart in X to leave alone. The
// stack is clamped back inside the plot as a whole afterwards, so
// pushing the lowest label down can never post it off the chart.
function _declutter(labels, pad, ch) {
  const placed = [];
  for (const l of [...labels].sort((a, b) => a.y - b.y)) {
    let y = l.y;
    for (const p of placed) {
      if (Math.abs(p.x - l.x) > Math.max(p.w, l.w)) continue;
      if (Math.abs(p.y - y) < LABEL_ROW) y = p.y + LABEL_ROW;
    }
    placed.push({ ...l, y });
  }
  const top = pad.t + LABEL_FONT;
  const bottom = pad.t + ch;
  const over = Math.max(0, Math.max(0, ...placed.map((p) => p.y)) - bottom);
  for (const p of placed) p.y = Math.min(bottom, Math.max(top, p.y - over));
  return placed;
}

// paint-order + a dark stroke give the glyphs a halo, so a label that
// lands on top of a crossing curve stays readable without a plate behind
// it — which would have hidden the very data it sits on.
function _labelSvg(l) {
  return `<text x="${(l.x - 4).toFixed(1)}" y="${l.y.toFixed(1)}" text-anchor="end" font-size="${LABEL_FONT}" font-weight="700" fill="${l.colour}" paint-order="stroke" stroke="#0a0e14" stroke-width="3" stroke-linejoin="round">${l.text}</text>`;
}

/**
 * One label per curve at its own right-hand terminus, as SVG.
 *
 * Only called when more than one metric is on the plot: with a single
 * metric the active pill and the labelled Y axis already name it, and
 * twelve redundant captions would be pure ink.
 */
export function metricEndLabels(series, dom, geo, shortOf) {
  const { pad, cw, ch } = geo;
  const raw = [];
  for (const s of series) {
    const band = dom.bands[s.metric];
    const last = band ? _terminus(s) : null;
    if (!last) continue;
    const text = `${s.slot} ${shortOf(s.metric)}`;
    raw.push({
      text,
      colour: s.colour,
      x: domainX(dom, last[0], pad, cw),
      y: bandY(band, last[1], pad, ch),
      w: approxTextWidth(text, LABEL_FONT),
    });
  }
  return _declutter(raw, pad, ch).map(_labelSvg).join('');
}
