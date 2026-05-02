// ─── weather/stats.js ──────────────────────────────────────────────────────
// Stage 24 of the legacy.js → ES modules refactor — Wetterstatistik
// chart + explainer + legend + pill bar + auto-refresh observer.
// Pure code move from legacy.js, no behaviour changes.
//
// Imports stay tiny: only byId is reached out for. WEATHER_TYPES
// colours are inlined into WEATHER_STATS_PALETTE up top so no cross-
// module lookup at render time.
import { byId } from "../core/dom.js";

// ── Wetterdaten & Prognose chart (Phase 4) ──────────────────────────────────
// Single-source palette for the multi-line history chart. Re-uses the
// WEATHER_TYPES colours where the parameter maps cleanly onto an event
// type, picks close siblings for the diagnostic-only fields. Order here
// determines render order (last drawn sits on top).
const WEATHER_STATS_PALETTE = {
  precipitation:       '#5a8aa8',  // matches heavy_rain
  snowfall:            '#a8c0d4',  // matches snow
  lightning_potential: '#facc15',  // matches thunder badge
  visibility:          '#94a3b8',  // matches fog
  wind_gusts_10m:      '#84cc16',  // lime — diagnostic, distinct from the rain blues
  cloud_cover:         '#a78bfa',  // violet — diagnostic
  sun_altitude:        '#fb923c',  // matches sunset
};

const _WS_FIELD_ORDER = [
  'precipitation', 'snowfall', 'lightning_potential', 'visibility',
  'wind_gusts_10m', 'cloud_cover', 'sun_altitude',
];

let _wsStatsTimer_chart = null;
let _wsStatsObserver = null;
let _wsStatsState = {
  hours: 24,
  isolated: null,         // field key in isolated-mode, null = all lines
  data: null,             // last fetched payload
  inFlight: false,
};

async function loadWeatherStats(){
  if (_wsStatsState.inFlight) return;
  _wsStatsState.inFlight = true;
  try {
    const r = await fetch('/api/weather/history?hours=' + _wsStatsState.hours);
    _wsStatsState.data = await r.json();
    renderWeatherStats();
  } catch (e) {
    /* leave the previous render up — single transient error shouldn't blank the chart */
  } finally {
    _wsStatsState.inFlight = false;
  }
}

// Catmull-Rom-to-Bezier converter. Returns an SVG path string for the
// run of points, smoothed via cubic Beziers whose control points come
// from the slope between each point's neighbours (uniform Catmull-Rom,
// scaled by `tension` to dampen overshoots — 0.5 keeps the curve close
// to the data without introducing wild bumps). Endpoints duplicate
// themselves as virtual "p0/p3" so the first and last segments don't
// flatten or kink. The caller is responsible for ensuring points come
// from a contiguous run (no nulls) — gaps must be split into separate
// runs by the caller.
function _wsCatmullRomPath(pts, tension){
  if (!pts || pts.length < 2) return '';
  const k = tension / 6;
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 0; i < pts.length - 1; i++){
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || pts[i + 1];
    const c1x = p1[0] + (p2[0] - p0[0]) * k;
    const c1y = p1[1] + (p2[1] - p0[1]) * k;
    const c2x = p2[0] - (p3[0] - p1[0]) * k;
    const c2y = p2[1] - (p3[1] - p1[1]) * k;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

function _wsBuildLinePath(samples, key, x0, y0, w, h){
  // Per-line normalisation: each parameter gets its own min/max so a 30
  // mm/h precipitation peak doesn't flatten the 0.5 cm/h snow line.
  // Null values split the trace into independent runs — Catmull-Rom is
  // applied per-run so a single missing sample doesn't smear an
  // interpolated curve across the gap. Runs of <6 points fall back to
  // straight L-segments because a 3- or 4-point spline tends to
  // overshoot wildly on sparse data.
  const vals = [];
  for (const s of samples){
    const v = (s.values || {})[key];
    vals.push(typeof v === 'number' && isFinite(v) ? v : null);
  }
  const def = vals.filter(v => v != null);
  if (def.length < 2) return null;
  let lo = Math.min(...def), hi = Math.max(...def);
  if (hi - lo < 1e-9){ lo -= 0.5; hi += 0.5; } // flat line: pin to mid-band
  const N = vals.length;
  // Group into contiguous runs of [x, y] points.
  const runs = [];
  let cur = [];
  for (let i = 0; i < N; i++){
    const v = vals[i];
    if (v == null){
      if (cur.length){ runs.push(cur); cur = []; }
      continue;
    }
    const x = x0 + (N === 1 ? 0 : (i / (N - 1)) * w);
    const norm = (v - lo) / (hi - lo);
    const y = y0 + h - norm * h;
    cur.push([x, y]);
  }
  if (cur.length) runs.push(cur);
  let d = '';
  for (const run of runs){
    if (run.length >= 6){
      d += (d ? ' ' : '') + _wsCatmullRomPath(run, 0.3);
    } else {
      d += (d ? ' M' : 'M') + run[0][0].toFixed(1) + ',' + run[0][1].toFixed(1);
      for (let j = 1; j < run.length; j++){
        d += ' L' + run[j][0].toFixed(1) + ',' + run[j][1].toFixed(1);
      }
    }
  }
  return { path: d, lo, hi };
}

// X-axis tick formatter — adapts to the configured window so the bottom
// of the chart communicates the actual time scale at a glance.
//   hours ≤ 24   → "HH:MM"
//   hours ≤ 168  → "Di. HH:MM"   (German weekday + time)
//   hours > 168  → "DD.MM."      (date only — month-scale window)
const _WS_WEEKDAY_DE = ['So.','Mo.','Di.','Mi.','Do.','Fr.','Sa.'];
function _wsFmtTick(ts, hours){
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts.length >= 16 ? ts.slice(11, 16) : '';
  const p2 = n => (n < 10 ? '0' : '') + n;
  if (hours <= 24){
    return p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  if (hours <= 168){
    return _WS_WEEKDAY_DE[d.getDay()] + ' ' + p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  return p2(d.getDate()) + '.' + p2(d.getMonth() + 1) + '.';
}

function _wsFmtVal(key, v){
  if (v == null || !isFinite(v)) return '—';
  const u = (_wsStatsState.data?.units || {})[key] || '';
  let s;
  if (key === 'sun_altitude') s = v.toFixed(0);
  else if (key === 'cloud_cover' || key === 'wind_gusts_10m') s = v.toFixed(0);
  else if (key === 'visibility') s = v.toFixed(0);
  else if (key === 'lightning_potential') s = v.toFixed(0);
  else s = v.toFixed(2);
  return u ? (s + ' ' + u) : s;
}

function _wsCurrentValue(key){
  // Walk back to the most recent non-null sample for this field. A single
  // failed poll (sun-altitude calc miss, API hiccup) shouldn't blank the
  // chip and strip its unit — the chip is meant to read as "this field's
  // latest known value", not "the last sample's value".
  const samples = _wsStatsState.data?.samples || [];
  for (let i = samples.length - 1; i >= 0; i--){
    const v = (samples[i].values || {})[key];
    if (typeof v === 'number' && isFinite(v)) return v;
  }
  return null;
}

// Field-detail copy shown beneath the chart when a legend chip is isolated.
// Three short German blocks per field: relevance for animal observation
// (TAM-spy's domain), weather correlation, seasonal pattern. Source of truth
// for the explainer card.
const WEATHER_STATS_EXPLAINERS = {
  precipitation: {
    summary: "Niederschlag misst Regen, Schnee und Graupel als Wassersäule pro Stunde — die Standard-Einheit ist mm/h.",
    relevance_for_animals: "Aktivitäts-Indikator: viele Vögel und Eichhörnchen reduzieren die Aktivität bei >2 mm/h, andere (Drosseln, Regenwürmer-Sucher) werden gerade dann sichtbar.",
    weather_correlation: "Korreliert positiv mit Bewölkung und Blitz-Potential, negativ mit Sicht.",
    seasonal_pattern: "In Mitteleuropa Maximum Juni–August (konvektive Schauer) und ein Nebenmaximum im Herbst.",
  },
  snowfall: {
    summary: "Schneefall in cm Neuschnee pro Stunde. 1 cm/h entspricht je nach Dichte etwa 0,7–1,2 mm/h Wasseräquivalent.",
    relevance_for_animals: "Frische Schneedecke macht Spuren und Wärmesignaturen besser erkennbar; viele Wildtiere reduzieren Aktivität auf wenige Spitzen am Tag.",
    weather_correlation: "Tritt nur bei Lufttemperaturen ≤ 1 °C zusammen mit aktivem Niederschlag auf.",
    seasonal_pattern: "In Mitteleuropa typisch von November bis März; vereinzelte Reste in Mittelgebirgen bis April.",
  },
  lightning_potential: {
    summary: "Konvektives Energiepotential (CAPE) in J/kg. Werte > 1000 J/kg gelten als Gewitter-Schwelle, > 2000 J/kg als markant unwetterträchtig.",
    relevance_for_animals: "Hohes Blitz-Potential verschiebt Tier-Aktivität in geschützte Bereiche; nach dem Durchzug oft eine kurze, hohe Aktivitätsspitze.",
    weather_correlation: "Korreliert positiv mit feucht-warmen Luftmassen, starkem vertikalem Temperaturgradient und herannahenden Frontensystemen.",
    seasonal_pattern: "Schwerpunkt Mai–August; gelegentliches Herbstmaximum bei warmen Mittelmeer-Tiefs.",
  },
  visibility: {
    summary: "Atmosphärische Sichtweite in Metern — die Distanz, in der ein Objekt vor dem Himmel noch erkennbar ist. Werte unter 1000 m gelten als Nebel.",
    relevance_for_animals: "Kameras verlieren Tier-Detail unter ~200 m, IR-Erkennung fällt zuerst aus. Manche Arten (Rehe, Füchse) nutzen reduzierte Sicht zur Annäherung an Häuser.",
    weather_correlation: "Sinkt mit hoher Luftfeuchte, Niederschlag und Inversionswetterlagen; steigt nach Frontdurchgängen mit kalter, trockener Luft.",
    seasonal_pattern: "Jahresminimum im Spätherbst und Winter (Strahlungs- und Hochnebel); Maximum im klaren Frühling nach kühlen Polarluft-Vorstößen.",
  },
  wind_gusts_10m: {
    summary: "Maximalwind-Böen in 10 m Höhe in km/h, gemittelt über das letzte 10-min-Intervall. Beaufort 6 ≈ 39 km/h, Sturm Beaufort 9 ≈ 75 km/h.",
    relevance_for_animals: "Vögel und kletternde Säuger reduzieren Aktivität ab ~30 km/h Böen; Greifvögel nutzen den Aufwind. Mikrofone werden ab ~25 km/h unbrauchbar.",
    weather_correlation: "Korreliert mit Druckgradient, Frontaldurchgang und nachmittäglicher thermischer Konvektion.",
    seasonal_pattern: "Winter- und Frühjahrsmaximum bei kräftigen Westwetterlagen; Sommer-Spitzen bei Gewitterböen.",
  },
  cloud_cover: {
    summary: "Bewölkungsgrad in Prozent — 0 % wolkenlos, 100 % bedeckt. Open-Meteo summiert tiefe, mittlere und hohe Wolken.",
    relevance_for_animals: "Diffuses Licht bei 60–90 % Bewölkung verlängert die Dämmerungsphase und erhöht Tier-Aktivität auf Lichtungen.",
    weather_correlation: "Vorlaufindikator für Niederschlag; hohe Bewölkung dämpft den Tagesgang der Temperatur um mehrere Grad.",
    seasonal_pattern: "Mittlere Bedeckung in Mitteleuropa ~60 %, mit November-Maximum (Dauergrau) und Aprilspitzen bei Aprilwetter.",
  },
  sun_altitude: {
    summary: "Sonnenhöhe ist der Winkel der Sonne über dem Horizont, gemessen in Grad. 0° = Horizont, 90° = direkt im Zenit, negative Werte = unter dem Horizont (Nacht).",
    relevance_for_animals: "Tagaktive Tiere folgen dem Sonnenstand: morgendliche und abendliche Aktivitätsspitzen liegen typisch zwischen 5° und 20° Höhe (sog. blue/golden hour für Beobachtung).",
    weather_correlation: "Direkter Treiber von Tagestemperatur, Schattenwurf und IR-Beleuchtungsbedarf der Kameras. Keine Wetter-Schwelle — eine astronomische Größe.",
    seasonal_pattern: "Maximum bei Sommersonnenwende (~63° in Nürnberg), Minimum bei Wintersonnenwende (~16°). Über das Jahr eine glatte Sinuskurve.",
  },
};

function _wsRenderExplainer(key){
  const e = WEATHER_STATS_EXPLAINERS[key];
  if (!e) return '';
  const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
  const label = (_wsStatsState.data?.labels_de || {})[key] || key;
  return `<div class="ws-explainer-card" style="--cb:${colour}">
    <div class="ws-explainer-head">
      <span class="ws-explainer-dot" style="background:${colour}"></span>
      <h4>${label}</h4>
    </div>
    <p class="ws-explainer-summary">${e.summary}</p>
    <dl class="ws-explainer-list">
      <dt>Für Tierbeobachtung</dt><dd>${e.relevance_for_animals}</dd>
      <dt>Wetterzusammenhang</dt><dd>${e.weather_correlation}</dd>
      <dt>Jahresverlauf</dt><dd>${e.seasonal_pattern}</dd>
    </dl>
  </div>`;
}

function renderWeatherStatsExplainer(){
  const el = byId('weatherStatsExplainer'); if (!el) return;
  const k = _wsStatsState.isolated;
  if (!k){ el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerHTML = _wsRenderExplainer(k);
}

function renderWeatherStats(){
  renderWeatherStatsChart();
  renderWeatherStatsLegend();
  renderWeatherStatsExplainer();
}

// Round to a "nice number" — 1 / 2 / 5 × 10^n. round=true picks the
// nearest nice value (good for tick steps); round=false picks the
// next nice value ≥ input (good for axis bounds). Used by the
// Wetterstatistik chart for human-readable Y labels (0/5/10/15
// instead of 0.13/4.97/9.81/14.65).
function _niceNum(value, round){
  if (!Number.isFinite(value) || value <= 0) return 1;
  const exp = Math.floor(Math.log10(value));
  const f = value / Math.pow(10, exp);
  let nf;
  if (round){
    if (f < 1.5)      nf = 1;
    else if (f < 3)   nf = 2;
    else if (f < 7)   nf = 5;
    else              nf = 10;
  } else {
    if (f <= 1)       nf = 1;
    else if (f <= 2)  nf = 2;
    else if (f <= 5)  nf = 5;
    else              nf = 10;
  }
  return nf * Math.pow(10, exp);
}

// Generate ~`target` evenly-spaced "nice" tick values across [lo, hi].
// Returns the tick array plus the snapped lo/hi so the caller can use
// the rounded bounds as the Y-axis baseline.
function _niceAxisTicks(lo, hi, target){
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi - lo < 1e-9){
    return { ticks: [lo], step: 1, niceLo: lo, niceHi: hi };
  }
  const range = _niceNum(hi - lo, false);
  const step  = _niceNum(range / Math.max(1, target - 1), true);
  const niceLo = Math.floor(lo / step) * step;
  const niceHi = Math.ceil(hi / step) * step;
  const ticks = [];
  for (let v = niceLo; v <= niceHi + step / 2; v += step) ticks.push(v);
  return { ticks, step, niceLo, niceHi };
}

// Time-tick step ladder used by the chart's X-axis. Each entry is a
// candidate spacing in milliseconds; the picker snaps to the entry
// that gets the visible tick count closest to `target` for the
// current window. Covers 5 min through 1 year so a 24 h zoom shows
// 6 hourly ticks and a 6 mo zoom shows monthly ticks without a
// fixed if-else ladder.
const _WS_TIME_STEP_LADDER_MS = [
  5*60_000, 10*60_000, 15*60_000, 30*60_000,
  60*60_000, 2*60*60_000, 3*60*60_000, 6*60*60_000, 12*60*60_000,
  24*60*60_000, 2*24*60*60_000, 7*24*60*60_000, 14*24*60*60_000,
  30*24*60*60_000, 90*24*60*60_000, 180*24*60*60_000, 365*24*60*60_000,
];

function _wsPickTimeStep(spanMs, target){
  let best = _WS_TIME_STEP_LADDER_MS[0];
  let bestDiff = Infinity;
  for (const s of _WS_TIME_STEP_LADDER_MS){
    const count = spanMs / s;
    if (count < 2) continue;  // would yield <2 ticks → skip
    const diff = Math.abs(count - target);
    if (diff < bestDiff){ bestDiff = diff; best = s; }
  }
  return best;
}

// Snap a timestamp to the next "nice" boundary AT OR AFTER it,
// matching the step magnitude. Sub-day → round to the next hour;
// 1 d → midnight; ≥ 1 mo → start-of-month.
function _wsAnchorTickStart(tFirst, stepMs){
  const d = new Date(tFirst);
  if (stepMs < 24*60*60_000){
    d.setMinutes(0, 0, 0);
    if (d.getTime() < tFirst) d.setHours(d.getHours() + 1);
    return d.getTime();
  }
  if (stepMs < 30*24*60*60_000){
    d.setHours(0, 0, 0, 0);
    if (d.getTime() < tFirst) d.setDate(d.getDate() + 1);
    return d.getTime();
  }
  // Month-magnitude or larger: anchor at the 1st of the next month.
  d.setHours(0, 0, 0, 0);
  d.setDate(1);
  if (d.getTime() < tFirst) d.setMonth(d.getMonth() + 1);
  return d.getTime();
}

const _WS_MONTHS_DE = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];

function _wsFmtTimeTick(t, stepMs){
  const d = new Date(t);
  const p2 = n => (n < 10 ? '0' : '') + n;
  if (stepMs < 24*60*60_000){
    return p2(d.getHours()) + ':' + p2(d.getMinutes());
  }
  if (stepMs < 60*24*60*60_000){
    return p2(d.getDate()) + '. ' + _WS_MONTHS_DE[d.getMonth()];
  }
  return _WS_MONTHS_DE[d.getMonth()] + ' ' + String(d.getFullYear()).slice(-2);
}

function renderWeatherStatsChart(){
  const wrap = byId('weatherStatsChartWrap'); if (!wrap) return;
  const data = _wsStatsState.data;
  const samples = data?.samples || [];
  if (samples.length < 2){
    wrap.innerHTML = '<div class="ws-stats-empty">Noch zu wenige Messpunkte — der Verlauf füllt sich alle 5 min.</div>';
    return;
  }
  // Layout. Left lane reserved for Y-axis labels of the active line;
  // right padding for per-field threshold ticks in all-lines mode.
  // VB_PAD adds slack around the viewBox so axis labels never clip at
  // the very edge of the wrapper (overflow:hidden) even when their
  // baseline sits on the plot boundary.
  const VB_W = 600, VB_H = 220, VB_PAD = 4;
  const pad = { l: 42, r: 72, t: 12, b: 26 };
  const cw = VB_W - pad.l - pad.r;
  const ch = VB_H - pad.t - pad.b;
  const isolated = _wsStatsState.isolated;
  const fields = isolated ? [isolated] : _WS_FIELD_ORDER;
  const hours = _wsStatsState.hours || 24;

  // X-axis tick generation. Picks a step from a candidate ladder so
  // the visible tick count stays close to 6 regardless of window
  // size; format adapts to step magnitude (HH:MM / dd. MMM / MMM YY).
  // Falls back to the legacy index-based 6-tick scheme if timestamps
  // don't parse.
  const tFirst = new Date(samples[0]?.ts).getTime();
  const tLast = new Date(samples[samples.length - 1]?.ts).getTime();
  const tSpan = tLast - tFirst;
  let tickSvg = '';
  if (Number.isFinite(tFirst) && Number.isFinite(tLast) && tSpan > 0){
    const stepMs = _wsPickTimeStep(tSpan, 6);
    const firstTick = _wsAnchorTickStart(tFirst, stepMs);
    const ticks = [];
    for (let t = firstTick; t <= tLast; t += stepMs) ticks.push(t);
    for (const t of ticks){
      const x = pad.l + ((t - tFirst) / tSpan) * cw;
      const label = _wsFmtTimeTick(t, stepMs);
      tickSvg += `<line x1="${x.toFixed(1)}" y1="${(pad.t + ch).toFixed(1)}" x2="${x.toFixed(1)}" y2="${(pad.t + ch + 5).toFixed(1)}" stroke="rgba(255,255,255,.12)" stroke-width="1" shape-rendering="geometricPrecision"/>`;
      tickSvg += `<text x="${x.toFixed(1)}" y="${(VB_H - 8).toFixed(1)}" text-anchor="middle" font-size="10" fill="rgba(255,255,255,.55)" text-rendering="optimizeLegibility" shape-rendering="geometricPrecision">${label}</text>`;
    }
  } else {
    const last = samples.length - 1;
    const intervals = 5;
    for (let k = 0; k <= intervals; k++){
      const idx = Math.round(last * k / intervals);
      const x = pad.l + (idx / last) * cw;
      const anchor = k === 0 ? 'start' : k === intervals ? 'end' : 'middle';
      tickSvg += `<text x="${x.toFixed(1)}" y="${(VB_H - 8).toFixed(1)}" text-anchor="${anchor}" font-size="10" fill="rgba(255,255,255,.55)" text-rendering="optimizeLegibility">${_wsFmtTick(samples[idx]?.ts, hours)}</text>`;
    }
  }

  // Horizontal gridlines — the Y-axis loop further down emits its own
  // gridline at every nice tick when the chart is in isolated mode
  // (so the lines hit the labelled values exactly). In all-lines mode
  // we draw 4 evenly-spaced lines as a fallback, since each line is
  // independently normalised and there's no shared Y scale.
  let gridSvg = '';
  if (!isolated){
    for (let g = 0; g <= 4; g++){
      const y = pad.t + (g / 4) * ch;
      gridSvg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + cw).toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.07)" stroke-width="1" vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision"/>`;
    }
  }
  // Lines — collect per-field meta so the threshold pass can renormalise
  // each tick against the same {lo, hi} the line was drawn against.
  let linesSvg = '';
  const lineMetas = {};
  for (const key of fields){
    const meta = _wsBuildLinePath(samples, key, pad.l, pad.t, cw, ch);
    if (!meta) continue;
    lineMetas[key] = meta;
    const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
    const opacity = isolated && isolated !== key ? 0.15 : 1;
    linesSvg += `<path d="${meta.path}" fill="none" stroke="${colour}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" opacity="${opacity}" vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision" />`;
  }
  // Threshold overlay.
  //
  //  - Isolated mode: full horizontal dashed red line + right-side label
  //    (existing behaviour — that mode is for direct line-vs-boundary
  //    comparisons).
  //  - All-lines mode: per-field 18 px tick on the right edge in the
  //    line's own colour, with a 9 px label to the right of the tick.
  //    Always rendered when a threshold is configured, regardless of
  //    the event's enabled flag — events_enabled[k]==false dims the
  //    tick/label to 0.4 opacity. Out-of-range thresholds clamp to
  //    the top/bottom edge with ▲/▼ glyphs.
  let thresholdSvg = '';
  let noThresholdHint = '';
  if (isolated){
    const thr = (data?.thresholds || {})[isolated];
    const meta = lineMetas[isolated];
    if (thr == null){
      noThresholdHint = '<div class="ws-stats-no-threshold">keine Schwelle konfiguriert</div>';
    } else if (meta){
      const { lo, hi } = meta;
      const norm = (thr - lo) / (hi - lo);
      if (norm >= -0.05 && norm <= 1.05){
        const y = pad.t + ch - Math.max(0, Math.min(1, norm)) * ch;
        const u = (data?.units || {})[isolated] || '';
        const colour = WEATHER_STATS_PALETTE[isolated] || '#94a3b8';
        // Grafana-style: thin dashed horizontal in the LINE's colour
        // (not red) so the threshold reads as part of the same series,
        // plus a colour-tinted small label outside the right edge of
        // the plot. Keeps paint-order halo for legibility against the
        // chart background.
        const lbl = `${thr}${u ? ' ' + u : ''}`;
        thresholdSvg = `
          <line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${pad.l + cw}" y2="${y.toFixed(1)}"
                stroke="${colour}" stroke-width="1" stroke-dasharray="5 4" opacity="0.55"
                vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision" />
          <text class="ws-chart-threshold-label" x="${(pad.l + cw + 4).toFixed(1)}" y="${(y + 3).toFixed(1)}" font-size="9" fill="${colour}" opacity="0.85" text-rendering="optimizeLegibility">${lbl}</text>
        `;
      } else {
        noThresholdHint = '<div class="ws-stats-no-threshold">Schwelle außerhalb des sichtbaren Bereichs</div>';
      }
    }
  } else {
    const tickX1 = pad.l + cw - 18;
    const tickX2 = pad.l + cw;
    const labelX = pad.l + cw + 4;
    const placedYs = [];  // track placed label baselines to stack collisions
    for (const key of _WS_FIELD_ORDER){
      const meta = lineMetas[key]; if (!meta) continue;
      const thr = (data?.thresholds || {})[key];
      if (thr == null) continue;
      const enabled = (data?.events_enabled || {})[key];
      // events_enabled === null → field has no associated event (cloud,
      // wind, sun) and no threshold either, so the thr==null branch above
      // already handled it. true = armed (full opacity), false = configured
      // but off (dim).
      const opacity = enabled === false ? 0.4 : 1.0;
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      const { lo, hi } = meta;
      const norm = (thr - lo) / (hi - lo);
      let tickY, glyph = '', clampNote = '';
      if (norm > 1){
        tickY = pad.t + 4;
        glyph = '▲ ';
        clampNote = ` · aktuell ≪`;
      } else if (norm < 0){
        tickY = pad.t + ch - 4;
        glyph = '▼ ';
        clampNote = ` · aktuell ≫`;
      } else {
        tickY = pad.t + ch - norm * ch;
      }
      // Avoid label-on-label: shift down by 11 px until clear of any
      // already-placed label baseline (within ±11 px).
      let labelY = tickY + 3.5;
      while (placedYs.some(y => Math.abs(y - labelY) < 11)){
        labelY += 11;
      }
      placedYs.push(labelY);
      const u = (data?.units || {})[key] || '';
      const thrFmt = (typeof thr === 'number' && !Number.isInteger(thr) && Math.abs(thr) < 100)
        ? thr.toFixed(2)
        : Math.round(thr);
      const labelText = `${glyph}${thrFmt}${u ? ' ' + u : ''}`;
      const aria = `Schwelle ${thr}${u ? ' ' + u : ''}${clampNote}`;
      thresholdSvg += `
        <line x1="${tickX1.toFixed(1)}" y1="${tickY.toFixed(1)}" x2="${tickX2.toFixed(1)}" y2="${tickY.toFixed(1)}"
              stroke="${colour}" stroke-width="2" stroke-linecap="round" opacity="${opacity}"
              vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision">
          <title>${aria}</title>
        </line>
        <text x="${labelX.toFixed(1)}" y="${labelY.toFixed(1)}" font-size="9" fill="${colour}" opacity="${opacity}" text-rendering="geometricPrecision">${labelText}</text>
      `;
    }
  }
  // Y-axis labels — isolated mode only. 4 nice-rounded values (top,
  // 2/3, 1/3, bottom) in the line's own colour, plus a horizontal
  // gridline at each label's Y position so the lines reads against
  // the labelled value exactly. niceNum() rounds to 1/2/5 × 10^n so
  // labels read 0 / 5 / 10 / 15 instead of 0.13 / 4.97 / 9.81 / 14.65.
  // All-lines mode: each line is independently normalised, no shared
  // Y scale to label — the fixed 4-line gridSvg above provides the
  // visual anchoring.
  let yAxisSvg = '';
  if (isolated && lineMetas[isolated]){
    const meta = lineMetas[isolated];
    const u = (data?.units || {})[isolated] || '';
    const colour = WEATHER_STATS_PALETTE[isolated] || '#94a3b8';
    const { ticks } = _niceAxisTicks(meta.lo, meta.hi, 4);
    const span = (meta.hi - meta.lo) || 1;
    const fmtNice = v => {
      if (Number.isInteger(v)) return String(v);
      return v.toFixed(Math.abs(v) < 10 ? 1 : 0);
    };
    for (const v of ticks){
      // Skip ticks outside the data range (niceNum can over-shoot).
      if (v < meta.lo - span * 0.05 || v > meta.hi + span * 0.05) continue;
      const norm = (v - meta.lo) / span;
      const y = pad.t + ch - norm * ch;
      const txt = `${fmtNice(v)}${u ? ' ' + u : ''}`;
      // Horizontal gridline at this label's Y — opacity 0.07 so it
      // recedes behind the data line.
      yAxisSvg += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${(pad.l + cw).toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.07)" stroke-width="1" vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision"/>`;
      yAxisSvg += `<text x="${pad.l - 6}" y="${(y + 3).toFixed(1)}" text-anchor="end" font-size="10" fill="${colour}" opacity="0.75" text-rendering="optimizeLegibility" shape-rendering="geometricPrecision">${txt}</text>`;
    }
  }

  // viewBox padded by VB_PAD on every side so a label sitting on the very
  // edge of the plot area still has slack before it hits the wrap's
  // overflow:hidden boundary. preserveAspectRatio="none" stretches the
  // padded box to fill the wrapper, so the visual scale change is sub-
  // pixel and not noticeable.
  wrap.innerHTML = `
    <svg viewBox="${-VB_PAD} ${-VB_PAD} ${VB_W + 2 * VB_PAD} ${VB_H + 2 * VB_PAD}" preserveAspectRatio="none" role="img" aria-label="Wetterverlauf">
      ${gridSvg}
      ${yAxisSvg}
      ${tickSvg}
      ${linesSvg}
      ${thresholdSvg}
      <line class="ws-chart-guide" x1="0" y1="${pad.t}" x2="0" y2="${pad.t + ch}" stroke="rgba(255,255,255,.35)" stroke-width="1" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" shape-rendering="geometricPrecision" style="display:none;pointer-events:none"/>
      <rect class="ws-chart-hover-area" x="${pad.l}" y="${pad.t}" width="${cw}" height="${ch}" fill="transparent" style="pointer-events:all;cursor:crosshair"/>
    </svg>
    ${noThresholdHint}
    <div class="ws-chart-tooltip" hidden></div>
  `;
  _wsBindChartHover(wrap, samples, fields, pad, cw, ch, VB_W, VB_H, VB_PAD, isolated, data);
}

// Hover tooltip — vertical guide line + floating box that lists every
// active line's value at the hovered timestamp. Pointer events cover
// mouse + touch + pen. Touch taps auto-hide after 2.5 s. Reduced-motion
// users get instant show/hide (the CSS .ws-chart-tooltip has no
// transition by default; this comment is the contract).
function _wsBindChartHover(wrap, samples, fields, pad, cw, ch, VB_W, VB_H, VB_PAD, isolated, data){
  const svg = wrap.querySelector('svg'); if (!svg) return;
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
  const spansMultiDay = Number.isFinite(firstDate.getTime()) &&
                       Number.isFinite(lastDate.getTime()) &&
                       firstDate.toDateString() !== lastDate.toDateString();

  function _hide(){
    tip.hidden = true;
    guide.style.display = 'none';
    if (hideTimer.id) { clearTimeout(hideTimer.id); hideTimer.id = 0; }
  }

  function _onMove(ev){
    if (!Number.isFinite(tFirst) || !Number.isFinite(tLast) || tSpan <= 0){
      _hide(); return;
    }
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0) return;
    // SVG uses preserveAspectRatio="none". The viewBox is padded by
    // VB_PAD on each side, so client-X maps to viewBox-X via the padded
    // total width and shifts back by -VB_PAD to get the original
    // coordinate system pad/cw operate in.
    const vbTotalW = VB_W + 2 * VB_PAD;
    const localX = -VB_PAD + (ev.clientX - rect.left) * (vbTotalW / rect.width);
    if (localX < pad.l || localX > pad.l + cw){ _hide(); return; }
    // Map x → timestamp → nearest sample index.
    const t = tFirst + ((localX - pad.l) / cw) * tSpan;
    let bestIdx = 0, bestDiff = Infinity;
    for (let i = 0; i < samples.length; i++){
      const ts = new Date(samples[i].ts).getTime();
      const d = Math.abs(ts - t);
      if (d < bestDiff){ bestDiff = d; bestIdx = i; }
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
    const p2 = n => (n < 10 ? '0' : '') + n;
    const dt = new Date(sampleTs);
    const headTime = `${p2(dt.getHours())}:${p2(dt.getMinutes())}`;
    const head = spansMultiDay
      ? `${headTime} · ${p2(dt.getDate())}.${p2(dt.getMonth() + 1)}`
      : headTime;
    const sampleVals = sample.values || {};
    const rows = fields.map(key => {
      const v = sampleVals[key];
      if (v == null || !Number.isFinite(Number(v))) return '';
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      const lbl = labels[key] || key;
      const valFmt = _wsFmtVal(key, Number(v));
      return `<div class="ws-tt-row"><span class="ws-tt-dot" style="background:${colour}"></span><span class="ws-tt-lbl">${lbl}</span><span class="ws-tt-val">${valFmt}</span></div>`;
    }).filter(Boolean).join('');
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
    if (ev.pointerType === 'touch'){
      if (hideTimer.id) clearTimeout(hideTimer.id);
      hideTimer.id = setTimeout(_hide, 2500);
    }
  }

  area.addEventListener('pointermove', _onMove);
  area.addEventListener('pointerdown', _onMove);
  area.addEventListener('pointerleave', () => {
    // Mouse: hide immediately. Touch: leave the auto-hide timer running.
    _hide();
  });
}

function renderWeatherStatsLegend(){
  const wrap = byId('weatherStatsLegend'); if (!wrap) return;
  const data = _wsStatsState.data;
  if (!data){ wrap.innerHTML = ''; return; }
  const isolated = _wsStatsState.isolated;
  const labels = data.labels_de || {};
  const html = _WS_FIELD_ORDER.map(key => {
    const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
    const label = labels[key] || key;
    const val = _wsFmtVal(key, _wsCurrentValue(key));
    // When one series is isolated, the others render with .is-disabled
    // (opacity .35) so the active chip stands out without needing a
    // background pill to mark it. With no isolation, all chips render
    // at full opacity.
    let cls = 'ws-stats-chip';
    if (isolated){
      cls += isolated === key ? ' is-isolated' : ' is-disabled';
    }
    return `<button type="button" class="${cls}" data-field="${key}" aria-pressed="${isolated === key ? 'true' : 'false'}">
      <span class="ws-stats-chip-dot" style="--cb:${colour};background:${colour}"></span>
      <span class="ws-stats-chip-meta">
        <span class="ws-stats-chip-label">${label}</span>
        <span class="ws-stats-chip-value">${val}</span>
      </span>
    </button>`;
  }).join('');
  wrap.innerHTML = html;
  // Wire chip clicks once per render (innerHTML wipes prior listeners).
  wrap.querySelectorAll('.ws-stats-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.field;
      _wsStatsState.isolated = (_wsStatsState.isolated === key) ? null : key;
      renderWeatherStats();
    });
  });
}

function _bindWeatherStatsPills(){
  const bar = byId('weatherStatsPills'); if (!bar || bar.dataset.wired) return;
  bar.querySelectorAll('.ws-stats-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      const h = parseInt(btn.dataset.hours, 10) || 24;
      if (h === _wsStatsState.hours) return;
      _wsStatsState.hours = h;
      bar.querySelectorAll('.ws-stats-pill').forEach(b => b.classList.toggle('is-active', b === btn));
      loadWeatherStats();
    });
  });
  bar.dataset.wired = '1';
}

function _startWeatherStatsRefresh(){
  if (_wsStatsTimer_chart) return; // already running
  loadWeatherStats();
  _wsStatsTimer_chart = setInterval(loadWeatherStats, 60_000);
}

function _stopWeatherStatsRefresh(){
  if (_wsStatsTimer_chart){ clearInterval(_wsStatsTimer_chart); _wsStatsTimer_chart = null; }
}

function initWeatherStats(){
  const block = byId('weatherStatsBlock'); if (!block) return;
  _bindWeatherStatsPills();
  if (_wsStatsObserver) return;  // already initialised
  // Pause polling while the section is off-screen — the chart is a
  // dashboard for the Wetter section, not a background task.
  _wsStatsObserver = new IntersectionObserver((entries) => {
    if (entries.some(e => e.isIntersecting)) _startWeatherStatsRefresh();
    else _stopWeatherStatsRefresh();
  }, { threshold: 0.05 });
  _wsStatsObserver.observe(block);
}

// Per-type unit hint for the threshold slider in Settings → Ereignistypen.
const WEATHER_THRESHOLD_HINTS = {
  thunder:    { unit: 'J/kg', min: 0,  max: 3000, step: 50, key: 'threshold' },
  heavy_rain: { unit: 'mm/h', min: 0,  max: 30,   step: 0.5, key: 'threshold' },
  snow:       { unit: 'cm/h', min: 0,  max: 5,    step: 0.1, key: 'threshold' },
  fog:        { unit: 'm',    min: 100,max: 5000, step: 100, key: 'vis_max_m' },
  sunset:     { unit: '°',    min: -10,max: 15,   step: 1,    key: 'alt_max' },
};

const WEATHER_FIELD_LABEL_DE = {
  precipitation:       'Niederschlag',
  snowfall:            'Schneefall',
  lightning_potential: 'Blitz-Potential',
  visibility:          'Sicht',
  wind_gusts_10m:      'Wind-Böen',
  cloud_cover:         'Bewölkung',
  weather_code:        'WMO-Code',
};
const WEATHER_FIELD_UNIT_DE = {
  precipitation:       'mm/h',
  snowfall:            'cm/h',
  lightning_potential: 'J/kg',
  visibility:          'm',
  wind_gusts_10m:      'km/h',
  cloud_cover:         '%',
  weather_code:        '',
};

// Public surface is exposed via named exports below; legacy.js bridges

// initWeatherStats on window for loadAll().

export {

  WEATHER_STATS_PALETTE,

  loadWeatherStats,

  renderWeatherStats,

  renderWeatherStatsChart,

  renderWeatherStatsLegend,

  renderWeatherStatsExplainer,

  initWeatherStats,

};
