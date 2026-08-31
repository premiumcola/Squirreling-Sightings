// ─── storms/_helpers.js ────────────────────────────────────────────────────
// Pure German formatters + the two derived facts the whole page reads
// from an episode record: its effective class and its Leitwert (the
// single peak that most exceeds its own configured threshold).
//
// Plus the one shared fragment that is not a formatter: the dead-end
// state. Every "this cannot be shown" branch in the package renders
// through it so none of them can forget the way back out.

import { esc } from '../core/dom.js';
import { _wsStatsState, WEATHER_FIELD_UNIT_DE, wsFieldDigits } from '../weather/stats.js';
import { isMetricInverted } from '../weather/metric-direction.js';
import { STORM_CHARACTERS, STORM_CLASSES, STORM_METRICS } from './_state.js';

export { esc };

export function fmtNumberDe(v, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  return Number(v).toLocaleString('de-DE', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** Value + unit in the metric's own unit, German decimal comma.
 *
 * The decimal banding comes from the Wetter panel's own formatter
 * (wsFieldDigits) so one number cannot read two different ways in two
 * sections of the same page. */
export function fmtMetric(key, v) {
  if (v == null || !Number.isFinite(Number(v))) return '—';
  const unit = WEATHER_FIELD_UNIT_DE[key] || '';
  const s = fmtNumberDe(v, wsFieldDigits(key));
  return unit ? `${s} ${unit}` : s;
}

export function metricUnit(key) {
  return WEATHER_FIELD_UNIT_DE[key] || '';
}

const _p2 = (n) => (n < 10 ? '0' : '') + n;

function _date(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "28.08." — the list row's date. */
export function fmtDayMonth(iso) {
  const d = _date(iso);
  return d ? `${_p2(d.getDate())}.${_p2(d.getMonth() + 1)}.` : '—';
}

/** "28.08.2026" — the auto title's date. */
export function fmtDateFull(iso) {
  const d = _date(iso);
  return d ? `${_p2(d.getDate())}.${_p2(d.getMonth() + 1)}.${d.getFullYear()}` : '—';
}

/** "14:12" */
export function fmtTime(iso) {
  const d = _date(iso);
  return d ? `${_p2(d.getHours())}:${_p2(d.getMinutes())}` : '—';
}

export function fmtDuration(min) {
  const n = Number(min);
  return Number.isFinite(n) ? `${Math.round(n)} min` : '—';
}

/** "0,82" — German decimal comma, always two places. */
export function fmtIntensity(v) {
  return fmtNumberDe(v, 2);
}

export function episodeYear(ep) {
  const d = _date(ep?.started_at);
  return d ? d.getFullYear() : null;
}

/** user_class wins over the detector's auto_class. */
export function effectiveClass(ep) {
  return ep?.user_class || ep?.auto_class || null;
}

export function classMeta(cls) {
  return STORM_CLASSES[cls] || { de: cls || 'unbekannt', color: '#94a3b8', icon: '' };
}

/**
 * The episode's CHARACTER — composition + sequence of its own curve,
 * distinct from `classMeta`'s alarm-class lookup above (see
 * STORM_CHARACTERS' own comment in storms/_state.js). A record from
 * before this feature existed, or a bare test fixture, has no
 * `character` field at all — that renders as no badge, not "unbekannt"
 * (the fallback here only guards a truly UNKNOWN, non-empty slug).
 */
export function characterMeta(character) {
  return STORM_CHARACTERS[character] || { de: character || 'unbekannt', icon: '' };
}

/**
 * The row title. A named episode gets no extra "renamed" marker — the
 * name being non-generic IS the marker.
 */
export function episodeTitle(ep) {
  if (ep?.user_name) return ep.user_name;
  return `${classMeta(effectiveClass(ep)).de} · ${fmtDateFull(ep?.started_at)}`;
}

/**
 * Thresholds to measure this episode against. The snapshot the record
 * carries (stamped by build_record at archive time) is the honest
 * source — the archive outlives the settings that produced it. The live
 * values the Wetter panel above has almost always already fetched are
 * the fallback. When neither exists we simply have no threshold —
 * callers draw no line and no hint rather than inventing one.
 */
export function episodeThresholds(ep) {
  return ep?.thresholds || _wsStatsState.data?.thresholds || {};
}

/**
 * One metric's trigger level, or NaN when it has none.
 *
 * The guard is `> 0`, not `Number.isFinite`: the live history payload
 * emits `null` for every field without an event (wind gusts) and for
 * fog, whose trigger is configured as `vis_max_m` rather than
 * `threshold` — and `Number(null)` is 0, which is finite. Treating that
 * 0 as a threshold draws a "Schwelle" line along the axis floor and
 * makes every ratio infinite.
 */
export function thresholdFor(thresholds, key) {
  const t = Number((thresholds || {})[key]);
  return Number.isFinite(t) && t > 0 ? t : NaN;
}

/**
 * How far past its own trigger line a reading sits, as a ratio. Mirrors
 * the backend's sample_strength: for an inverted metric (low visibility
 * is the alarm) the ratio is threshold ÷ value. 0 when the metric has
 * no usable threshold — comparable only against other unthresholded
 * metrics, which is the honest answer.
 */
export function severityRatio(key, value, threshold) {
  const v = Number(value);
  const t = Number(threshold);
  if (!Number.isFinite(v) || !Number.isFinite(t) || t <= 0) return 0;
  if (isMetricInverted(key)) return v > 0 ? t / v : 0;
  return v / t;
}

/**
 * Leitwert — the single strongest peak, chosen as the peak with the
 * highest ratio to its OWN configured threshold. That is what makes
 * "2400 J/kg" and "12,4 mm/h" comparable at all. With no thresholds
 * configured anywhere we fall back to the first metric that has a peak,
 * in STORM_METRICS order, so the row still shows a number.
 */
export function leadPeak(ep) {
  const peaks = ep?.peaks || {};
  const thr = episodeThresholds(ep);
  let best = null;
  for (const key of STORM_METRICS) {
    const v = Number(peaks[key]);
    if (!Number.isFinite(v)) continue;
    const ratio = severityRatio(key, v, thresholdFor(thr, key));
    if (!best || ratio > best.ratio) best = { key, value: v, ratio };
  }
  return best;
}

/**
 * Compare's default metric: the one whose peak most exceeds its own
 * threshold across the WHOLE selection. Deterministic, one expression,
 * and it opens on the thing that actually made these episodes storms.
 */
export function dominantMetric(episodes) {
  let best = null;
  for (const ep of episodes) {
    const lead = leadPeak(ep);
    if (!lead) continue;
    if (!best || lead.ratio > best.ratio) best = lead;
  }
  return best ? best.key : firstMetricWithData(episodes);
}

/** Metrics that are all-null across the selection → pill renders disabled. */
export function metricHasData(episodes, key) {
  return episodes.some((ep) => Number.isFinite(Number((ep?.peaks || {})[key])));
}

/**
 * First metric in STORM_METRICS order that any of these episodes has a
 * peak for, or `null` when NOTHING has data.
 *
 * `null`, not STORM_METRICS[0]: falling back to the first metric named
 * an entry whose pill renders disabled (it has no data) AND selected
 * (it is the active metric) at the same time — the exact contradiction
 * this fallback exists to prevent. With no metric selected, no pill is
 * selected, and the chart says so in words.
 */
export function firstMetricWithData(episodes) {
  return STORM_METRICS.find((k) => metricHasData(episodes, k)) || null;
}

/**
 * A state the operator cannot act on — a deleted episode, a compare
 * link with too few ids — rendered WITH the way back.
 *
 * Two things make it a dead end otherwise: no control returns to the
 * list, and the bad hash stays in the address bar, so scrolling back
 * into the section re-renders the same message forever. The hash is
 * rewritten to `#storms` without a navigation (replaceState fires no
 * hashchange), so the message stays up, a reload lands on the list, and
 * the button below re-routes explicitly.
 */
export function renderDeadEnd(host, message, onNavigate) {
  host.innerHTML = `<div class="ws-empty st-deadend">
      <div class="st-deadend-txt">${esc(message)}</div>
      <button type="button" class="btn btn-action st-deadend-back">‹ Archiv</button>
    </div>`;
  try {
    history.replaceState(null, '', '#storms');
  } catch {
    /* a blocked history write must not swallow the message */
  }
  host
    .querySelector('.st-deadend-back')
    ?.addEventListener('click', () => onNavigate && onNavigate('#storms'));
}
