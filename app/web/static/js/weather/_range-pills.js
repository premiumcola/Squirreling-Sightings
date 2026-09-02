// ─── weather/_range-pills.js ───────────────────────────────────────────────
// The Wetterdaten range picker, told what the archive can actually fill.
//
// The five steps (1 h / 6 h / 24 h / 7 d / 30 d) are static markup in
// partials/mediathek.html and were offered unconditionally. On a fresh
// install that means "30 d" draws three hours of data stretched across a
// month-wide axis — a picture that looks like a month of flat weather
// rather than an archive that does not go back that far.
//
// The extent comes from the payload (`_history.py::history` reports the
// buffer's own oldest/newest/count) rather than being inferred from the
// samples that came back: asking for 30 d and receiving 3 h is
// indistinguishable, client-side, from a service that only kept 3 h.

import { byId } from '../core/dom.js';

/** Hours the archive spans, or null when it cannot say. */
export function archiveSpanHours(extent) {
  if (!extent || (extent.count ?? 0) < 2) return null;
  const first = Date.parse(extent.oldest ?? '');
  const last = Date.parse(extent.newest ?? '');
  if (!Number.isFinite(first) || !Number.isFinite(last) || last <= first) return null;
  return (last - first) / 3_600_000;
}

/**
 * Which steps to offer, and which one to land on.
 *
 * A step is disabled when a SMALLER step already covers the whole
 * archive — i.e. it would show nothing the smaller one does not. That
 * deliberately keeps one step of headroom: the first step at or above
 * the archive's span stays enabled, because that is the "show me
 * everything I have" view and disabling it would leave the operator
 * unable to see their own full history.
 *
 * The default only moves when it has to. With plenty of history the
 * panel keeps its 24 h; it falls back to the widest step that still has
 * data only when the current one has gone dark.
 */
export function rangePillPlan(spanHours, offered, current) {
  const steps = [...new Set((offered || []).filter((h) => Number.isFinite(h) && h > 0))].sort(
    (a, b) => a - b,
  );
  if (!steps.length) return { pills: [], defaultHours: current };
  // `undefined` when the span is unknown, or longer than every step —
  // in both cases nothing is disabled.
  const covering = Number.isFinite(spanHours) ? steps.find((h) => h >= spanHours) : undefined;
  const pills = steps.map((hours) => ({
    hours,
    disabled: covering !== undefined && hours > covering,
  }));
  const enabled = pills.filter((p) => !p.disabled).map((p) => p.hours);
  return {
    pills,
    defaultHours: enabled.includes(current) ? current : enabled[enabled.length - 1],
  };
}

const OUT_OF_RANGE = 'Der Verlauf reicht noch nicht so weit zurück';

/**
 * Apply the plan to the live pill bar. Returns the range the panel
 * should be on, so the caller can switch to it if the current one went
 * dark. Idempotent — safe to run on every render.
 */
export function applyRangePills(extent, currentHours) {
  const bar = byId('weatherStatsPills');
  if (!bar) return null;
  // forEach rather than a spread: the node test harness (tests/_node_js.py)
  // answers querySelectorAll with a Proxy that has forEach but no
  // Symbol.iterator, and spreading it throws. Same idiom the pill-state
  // renderer next door already uses.
  const btns = [];
  bar.querySelectorAll('.ws-stats-pill[data-hours]').forEach((b) => btns.push(b));
  const plan = rangePillPlan(
    archiveSpanHours(extent),
    btns.map((b) => parseInt(b.dataset.hours, 10)),
    currentHours,
  );
  const state = new Map(plan.pills.map((p) => [p.hours, p.disabled]));
  btns.forEach((b) => {
    const off = !!state.get(parseInt(b.dataset.hours, 10));
    b.disabled = off;
    b.classList.toggle('is-unavailable', off);
    if (off) b.title = OUT_OF_RANGE;
    else b.removeAttribute('title');
  });
  return plan.defaultHours;
}
