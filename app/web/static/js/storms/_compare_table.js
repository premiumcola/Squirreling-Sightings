// ─── storms/_compare_table.js ──────────────────────────────────────────────
// Vergleichstabelle — one row per metric with data in at least one
// selection, one column per slot, cell = that episode's peak in its own
// unit. Split out of _compare.js at the pre-declared seam.
//
// The per-row WORST reading is bolded and that is the ONLY emphasis in
// the table: a table where several things are highlighted highlights
// nothing. Worst, not largest — `worstValue` reads the metric's
// direction from weather/metric-direction.js, the same helper the
// chart's peak dot and the severity ratio use, because "Sicht" bolded
// by an argmax marks the episode with the BEST visibility as the worst
// fog. tabular-nums throughout so the columns line up digit by digit at
// 11 px.
//
// Column budget, measured at 375 px: section content is 327 px, the
// label column takes 72, leaving 255 for four 63 px columns. A fifth
// cannot fit on any iPhone — which is one of the two independent
// reasons the compare cap is 4.

import { esc } from '../core/dom.js';
import { WEATHER_FIELD_LABEL_DE } from '../weather/stats.js';
import { worstValue } from '../weather/metric-direction.js';
import { STORM_METRICS } from './_state.js';
import { fmtDuration, fmtIntensity, fmtMetric } from './_helpers.js';

/**
 * One table row. `metric` is the history field the values belong to, or
 * null for the quantities that are not metrics (Dauer, Intensität) —
 * for which higher is worse, which is what `worstValue` does with an
 * unknown key.
 *
 * Ties bold every tied cell: pretending one of two identical peaks is
 * "the" worst would be a lie.
 */
function _row(label, cells, values, metric = null) {
  const worst = worstValue(metric, values);
  const tds = cells
    .map((txt, i) => {
      const isMax = Number.isFinite(values[i]) && Number.isFinite(worst) && values[i] === worst;
      return `<td class="${isMax ? 'is-max' : ''}">${esc(txt)}</td>`;
    })
    .join('');
  return `<tr><th scope="row">${esc(label)}</th>${tds}</tr>`;
}

export function compareTableHtml(episodes, slotsOf) {
  const metricRows = STORM_METRICS.filter((k) =>
    episodes.some((ep) => Number.isFinite(Number((ep.peaks || {})[k]))),
  ).map((k) => {
    const values = episodes.map((ep) => {
      const v = Number((ep.peaks || {})[k]);
      return Number.isFinite(v) ? v : NaN;
    });
    return _row(
      WEATHER_FIELD_LABEL_DE[k] || k,
      values.map((v) => (Number.isFinite(v) ? fmtMetric(k, v) : '—')),
      values,
      k,
    );
  });
  const durs = episodes.map((ep) => Number(ep.duration_min));
  const ints = episodes.map((ep) => Number(ep.intensity));
  const head = episodes
    .map((ep) => `<th scope="col" class="st-th-slot">${slotsOf(ep.id)}</th>`)
    .join('');
  return `<div class="st-table-wrap">
      <table class="st-table">
        <thead><tr><th scope="col"><span class="st-sr">Messgröße</span></th>${head}</tr></thead>
        <tbody>
          ${metricRows.join('')}
          ${_row(
            'Dauer',
            durs.map((v) => (Number.isFinite(v) ? fmtDuration(v) : '—')),
            durs,
          )}
          ${_row(
            'Intensität',
            ints.map((v) => (Number.isFinite(v) ? fmtIntensity(v) : '—')),
            ints,
          )}
        </tbody>
      </table>
    </div>`;
}
