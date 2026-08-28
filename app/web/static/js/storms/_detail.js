// ─── storms/_detail.js ─────────────────────────────────────────────────────
// Detail — Kopf (Name / Klasse / Notiz), Verlaufs-Chart mit Onset- und
// Peak-Markern, Aufnahmen, Kennzahlen.
//
// Desktop (≥ 900px) puts the chart and the Aufnahmen side by side —
// "das Gewitter mit dem Video daneben". Phone and tablet stack them,
// chart first: "daneben" is not achievable at 327 px, and faking it with
// a 150 px-wide video is worse than stacking. With no footage at all the
// two-column layout collapses to one so no large empty box sits beside
// the chart.

import { esc } from '../core/dom.js';
import { renderStatsChartInto, STATS_CHART_PAD } from '../weather/stats-chart/index.js';
import { WEATHER_FIELD_LABEL_DE, WEATHER_FIELD_UNIT_DE } from '../weather/stats.js';
import {
  stormsState,
  STORM_METRICS,
  STORM_METRIC_SHORT,
  slotsClear,
  slotAssign,
} from './_state.js';
import {
  effectiveClass,
  classMeta,
  episodeThresholds,
  firstMetricWithData,
  fmtDateFull,
  fmtDuration,
  fmtIntensity,
  fmtMetric,
  fmtTime,
  leadPeak,
  metricHasData,
} from './_helpers.js';
import { detailHeadHtml, bindDetailHead } from './_detail_edit.js';
import { renderFootage, highlightFootageAt } from './_footage.js';
import { fetchFootage } from './_api.js';

// Which metric the detail chart isolates. Own state, not the Wetter
// panel's — that one belongs to the section above.
//
// The sticky metric only survives if THIS episode has data for it, the
// same guard compare applies. Without it, picking Schnee on a snow
// episode and then opening a thunderstorm renders a blank chart with
// the Schnee pill both selected and disabled — a state the operator
// cannot click out of.
export function detailMetric(ep) {
  const sticky = stormsState.metric;
  if (sticky && STORM_METRICS.includes(sticky) && metricHasData([ep], sticky)) return sticky;
  const lead = leadPeak(ep);
  return lead ? lead.key : firstMetricWithData([ep]);
}

function _metricPills(ep, active) {
  const peaks = ep.peaks || {};
  return `<div class="st-mpills" role="tablist" aria-label="Messgröße">${STORM_METRICS.map((k) => {
    const has = Number.isFinite(Number(peaks[k]));
    const full = WEATHER_FIELD_LABEL_DE[k] || k;
    return `<button type="button" class="st-mpill${k === active ? ' is-on' : ''}" data-metric="${esc(k)}"${has ? '' : ' disabled'} title="${esc(full)}" aria-label="${esc(full)}">${esc(STORM_METRIC_SHORT[k] || k)}</button>`;
  }).join('')}</div>`;
}

function _statsHtml(ep) {
  const rows = STORM_METRICS.filter((k) => Number.isFinite(Number((ep.peaks || {})[k]))).map(
    (k) =>
      `<div class="st-kv"><span class="st-kv-k">${esc(WEATHER_FIELD_LABEL_DE[k] || k)}</span><span class="st-kv-v">${esc(fmtMetric(k, ep.peaks[k]))}</span></div>`,
  );
  const rain = Number(ep.totals?.precipitation_mm);
  if (Number.isFinite(rain)) {
    rows.push(
      `<div class="st-kv"><span class="st-kv-k">Regenmenge</span><span class="st-kv-v">${esc(fmtMetric('precipitation', rain).replace('mm/h', 'mm'))}</span></div>`,
    );
  }
  rows.push(
    `<div class="st-kv"><span class="st-kv-k">Dauer</span><span class="st-kv-v">${esc(fmtDuration(ep.duration_min))}</span></div>`,
    `<div class="st-kv"><span class="st-kv-k">Intensität</span><span class="st-kv-v">${esc(fmtIntensity(ep.intensity))}</span></div>`,
  );
  return `<div class="st-kvs">${rows.join('')}</div>`;
}

function _shellHtml(ep, metric) {
  const m = classMeta(effectiveClass(ep));
  const when = `${fmtDateFull(ep.started_at)} · ${fmtTime(ep.started_at)}–${fmtTime(ep.ended_at)}`;
  return `<div class="st-detail" style="--cc:${m.color}">
      <div class="st-dtop">
        <a class="st-back" href="#storms" aria-label="Zurück zur Liste">‹ Archiv</a>
        <span class="st-dwhen">${esc(when)}</span>
      </div>
      ${detailHeadHtml(ep)}
      <div class="st-dcols" data-cols="2">
        <div class="st-dchart">
          ${_metricPills(ep, metric)}
          <div class="ws-stats-chart-wrap st-chart-wrap" id="stormsDetailChart"></div>
          <div class="st-axis-hint">Beginn, Höhepunkt und Ende sind im Verlauf markiert · Messpunkt alle 5 min</div>
          ${_statsHtml(ep)}
          <button type="button" class="btn btn-action st-cmp-from-detail" data-act="compare-with">Mit anderem Gewitter vergleichen</button>
        </div>
        <div class="st-dfootage" id="stormsFootage"><div class="st-fstrip">Aufnahmen werden geladen …</div></div>
      </div>
    </div>`;
}

// Chart payload in the shape renderStatsChartInto already speaks. Units
// and labels come from the existing German mirrors of HISTORY_UNITS /
// HISTORY_LABELS_DE — the backend does not need to echo them.
function _chartData(ep) {
  return {
    samples: ep.samples || [],
    units: WEATHER_FIELD_UNIT_DE,
    labels_de: WEATHER_FIELD_LABEL_DE,
    thresholds: episodeThresholds(ep),
  };
}

function _mountChart(ep, metric) {
  const wrap = document.querySelector('#stormsDetailChart');
  const foot = document.querySelector('#stormsFootage');
  if (!wrap) return;
  renderStatsChartInto(wrap, _chartData(ep), {
    isolated: metric,
    markers: [
      { ts: ep.started_at, label: 'Beginn' },
      { ts: ep.peak_at, label: 'Höhepunkt', colour: 'rgba(255,255,255,.7)' },
      { ts: ep.ended_at, label: 'Ende' },
    ],
    // Chart → tiles cross-highlight. Both directions are pure timestamp
    // arithmetic; no new state, no new data.
    hover: {
      onGuide: (sample) => {
        if (!foot) return;
        highlightFootageAt(foot, sample ? Date.parse(sample.ts) : NaN);
      },
    },
  });
}

async function _mountFootage(ep) {
  const host = document.querySelector('#stormsFootage');
  if (!host) return;
  let payload = stormsState.footage[ep.id];
  if (!payload) {
    payload = await fetchFootage(ep.id);
    stormsState.footage[ep.id] = payload;
  }
  if (!document.body.contains(host)) return;
  const any = renderFootage(host, payload);
  // No footage at all → collapse to a single full-width column.
  const cols = host.closest('.st-dcols');
  if (cols) cols.dataset.cols = any ? '2' : '1';
  if (!any) host.classList.add('st-dfootage--slim');
  _bindTileCross(host, ep);
}

// Tiles → chart: paint a translucent accent band over the chart across
// the hovered clip's span. The converse direction (chart guide → tile
// ring) is highlightFootageAt. Both are pure timestamp arithmetic
// against domains that already exist — no new state, no new data.
function _paintChartBand(ep, startIso, endIso) {
  const wrap = document.querySelector('#stormsDetailChart');
  const svg = wrap?.querySelector('svg');
  if (!svg) return;
  svg.querySelector('.st-band')?.remove();
  const samples = ep.samples || [];
  const t0 = Date.parse(samples[0]?.ts);
  const t1 = Date.parse(samples[samples.length - 1]?.ts);
  const a = Date.parse(startIso);
  const b = Date.parse(endIso);
  if (![t0, t1, a, b].every((n) => Number.isFinite(n)) || t1 <= t0) return;
  const vb = svg.viewBox?.baseVal;
  const vbW = vb?.width || wrap.clientWidth;
  const vbH = vb?.height || wrap.clientHeight;
  const cw = vbW - STATS_CHART_PAD.l - STATS_CHART_PAD.r;
  const ch = vbH - STATS_CHART_PAD.t - STATS_CHART_PAD.b;
  const clamp = (t) => Math.max(t0, Math.min(t1, t));
  const x1 = STATS_CHART_PAD.l + ((clamp(a) - t0) / (t1 - t0)) * cw;
  const x2 = STATS_CHART_PAD.l + ((clamp(b) - t0) / (t1 - t0)) * cw;
  const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
  rect.setAttribute('class', 'st-band');
  rect.setAttribute('x', x1.toFixed(1));
  rect.setAttribute('y', String(STATS_CHART_PAD.t));
  rect.setAttribute('width', Math.max(2, x2 - x1).toFixed(1));
  rect.setAttribute('height', String(ch));
  rect.setAttribute('fill', 'rgba(127,174,201,.18)');
  rect.setAttribute('pointer-events', 'none');
  svg.insertBefore(rect, svg.firstChild);
}

function _bindTileCross(host, ep) {
  host.querySelectorAll('.st-tile').forEach((tile) => {
    const on = () => _paintChartBand(ep, tile.dataset.spanStart, tile.dataset.spanEnd);
    const off = () => _paintChartBand(ep, null, null);
    tile.addEventListener('pointerenter', on);
    tile.addEventListener('pointerleave', off);
  });
}

/**
 * Re-draw ONLY the chart, leaving the DOM around it in place.
 *
 * The resize path calls this instead of re-rendering the view: the
 * detail header holds two live text editors that autosave on blur, and
 * replacing `host.innerHTML` removes them without firing blur, so a
 * half-typed name or note is lost to a window drag or a rotation.
 */
export function remountDetailChart(ep) {
  if (!ep || !document.querySelector('#stormsDetailChart')) return;
  _mountChart(ep, detailMetric(ep));
}

export function renderDetail(host, ep, onNavigate) {
  const metric = detailMetric(ep);
  const rerender = () => renderDetail(host, ep, onNavigate);
  host.innerHTML = _shellHtml(ep, metric);
  bindDetailHead(host, ep, rerender);
  host.querySelectorAll('[data-metric]').forEach((b) =>
    b.addEventListener('click', () => {
      stormsState.metric = b.dataset.metric;
      rerender();
    }),
  );
  host.querySelector('[data-act="compare-with"]')?.addEventListener('click', () => {
    // Enter Auswahl-Modus with this episode pre-loaded into slot 1.
    slotsClear();
    slotAssign(ep.id);
    stormsState.selecting = true;
    onNavigate('#storms');
  });
  _mountChart(ep, metric);
  _mountFootage(ep);
}
