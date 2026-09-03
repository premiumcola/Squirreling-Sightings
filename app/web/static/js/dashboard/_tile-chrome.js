// ─── dashboard/_tile-chrome.js ──────────────────────────────────────────
// The camera tile's chrome vocabulary: the per-class glyph set the
// bottom pill row draws from, the chrome-button SVG aliases, and the
// notification-channel cluster (Telegram / MQTT) with the schedule
// arithmetic behind its state dot and its label.
//
// Split out of dashboard.js (1082 lines against a 400-line ceiling).
// This half is a clean leaf — `esc` and `DASHBOARD_SVG` are its only
// imports and nothing here reads `state`, touches the DOM or starts a
// timer, which is what finally makes the schedule-window logic testable
// on its own. `_isInScheduleWindow` moved WITH its only caller
// (`_channelState`) rather than staying behind in dashboard.js, which
// would have made the two modules import each other.
import { esc } from '../core/dom.js';
import { DASHBOARD_SVG } from '../core/icons.js';

// Separate from core/icons.js OBJ_SVG (which carries hard-coded hexes
// for the lightbox / mediathek bbox legend) so the chrome pills can
// inherit colour from the parent's ``color: var(--class-X)``. Each
// glyph is a 24-vb / 16-render Tabler-ish silhouette so it reads at
// a glance even on a 30 px pill.
const _CHROME_CLASS_SVG = {
  person: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/></svg>`,
  cat: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4l2 5"/><path d="M19 4l-2 5"/><circle cx="12" cy="14" r="7"/><circle cx="9.5" cy="13.2" r=".8" fill="currentColor"/><circle cx="14.5" cy="13.2" r=".8" fill="currentColor"/><path d="M10 17q2 1.5 4 0"/></svg>`,
  dog: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 4l2.5 4"/><path d="M17 4l-2.5 4"/><circle cx="12" cy="14" r="6.5"/><circle cx="12" cy="13.5" r=".9" fill="currentColor"/><path d="M10 17q2 1.5 4 0"/></svg>`,
  bird: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6c-3.5-1-7 1-8 5l-2 7l5-3c3 2 7 0 8-4"/><circle cx="15.5" cy="6" r=".9" fill="currentColor"/></svg>`,
  squirrel: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="17" rx="3.5" ry="2.6"/><circle cx="8" cy="10" r="1.6"/><circle cx="12" cy="8.5" r="1.6"/><circle cx="16" cy="10" r="1.6"/><circle cx="6.4" cy="13" r="1.3"/></svg>`,
  fox: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="17" rx="3.5" ry="2.6"/><circle cx="8" cy="10" r="1.6"/><circle cx="12" cy="8.5" r="1.6"/><circle cx="16" cy="10" r="1.6"/><circle cx="6.4" cy="13" r="1.3"/></svg>`,
  hedgehog: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="17" rx="3.5" ry="2.6"/><circle cx="8" cy="10" r="1.6"/><circle cx="12" cy="8.5" r="1.6"/><circle cx="16" cy="10" r="1.6"/><circle cx="6.4" cy="13" r="1.3"/></svg>`,
  car: `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 16h14v-3l-2-4h-10l-2 4v3z"/><circle cx="8" cy="16" r="1.5"/><circle cx="16" cy="16" r="1.5"/><path d="M5 13h14"/></svg>`,
};

export function _chromeClassSvg(cls) {
  return _CHROME_CLASS_SVG[cls] || _CHROME_CLASS_SVG.person;
}

// P32 · chrome SVGs moved to core/icons.js · DASHBOARD_SVG. The
// `_CHROME_*_SVG` aliases below stay so callsites read the same way
// without a search-replace pass; future PRs can inline them.
export const _CHROME_COG_SVG = DASHBOARD_SVG.cog;
export const _CHROME_SIM_SVG = DASHBOARD_SVG.sim;
export const _CHROME_EXPAND_SVG = DASHBOARD_SVG.expand;
export const _CHROME_MINIMIZE_SVG = DASHBOARD_SVG.minimize;
const _CHROME_TG_SVG = DASHBOARD_SVG.telegram;
const _CHROME_MQTT_SVG = DASHBOARD_SVG.mqtt;

export function _isInScheduleWindow(from, to) {
  if (!from || !to) return false;
  const now = new Date();
  const m = now.getHours() * 60 + now.getMinutes();
  const [fh, fm] = from.split(':').map(Number);
  const [th, tm] = to.split(':').map(Number);
  const f = fh * 60 + fm,
    t = th * 60 + tm;
  return f <= t ? m >= f && m < t : m >= f || m < t;
}

// Derive the state-dot colour for a notification channel pill.
//   "on"    → currently armed AND in schedule window         → green dot
//   "muted" → enabled but camera is NOT armed (user toggled) → amber dot
//   "idle"  → enabled + armed + outside schedule window       → no dot
export function _channelState(c) {
  if (!c.armed) return 'muted';
  const sch =
    c.schedule_notify && c.schedule_notify.enabled
      ? c.schedule_notify
      : c.schedule && c.schedule.enabled
        ? c.schedule
        : null;
  if (sch && sch.from && sch.to) {
    return _isInScheduleWindow(sch.from, sch.to) ? 'on' : 'idle';
  }
  return 'on'; // no schedule defined → always on
}

// B3 · Channel cluster label resolver. Returns the single line shown
// inside the TG/MQTT badge — the two-row "sched · status" composition
// is gone, the schedule window is implied by the wording instead.
//   always-on (no schedule or 00:00↔00:00)        → "aktiv"
//   schedule active, state === 'on'               → "aktiv bis HH:MM"
//   schedule armed but outside window, 'idle'     → "aktiv ab HH:MM"
//   camera disarmed (state === 'muted')           → "Kamera nicht scharf"
// schedule_notify takes precedence over the legacy plain schedule.
export function _channelClusterLabel(c, state) {
  if (state === 'muted') return 'Kamera nicht scharf';
  const sch =
    c.schedule_notify && c.schedule_notify.enabled
      ? c.schedule_notify
      : c.schedule && c.schedule.enabled
        ? c.schedule
        : null;
  // No schedule, or the always-on sentinel: a single word carries
  // the whole meaning. Idle should never reach this branch (no
  // schedule = no idle state) but defaulting to "aktiv" is the
  // benign choice if it does.
  if (!sch || !sch.from || !sch.to || sch.from === sch.to) return 'aktiv';
  if (state === 'on') return `aktiv bis ${sch.to}`;
  if (state === 'idle') return `aktiv ab ${sch.from}`;
  return 'aktiv';
}

// E3 · Channel cluster — horizontal 3-column unit. Column 1: paper-
// plane / antenna icon (currentColor). Column 2: single-line label
// (B3 — was a 2-row "sched · status" stack before; the new wording
// folds schedule + state into one phrase, so the pill height halves).
// Column 3: active-dot SVG with a pulsing ring while state === 'on'.
// The cluster is NOT clickable. State-driven visibility comes from
// the data-state attribute consumed by the CSS in 03-dashboard.css.
export function _channelCluster(c, kind, state) {
  const headerLabel = kind === 'mqtt' ? 'MQTT-Kanal' : 'Telegram-Kanal';
  const icon = kind === 'mqtt' ? _CHROME_MQTT_SVG : _CHROME_TG_SVG;
  const label = _channelClusterLabel(c, state);
  return `<div class="cv-channel-cluster cv-${kind}-cluster" data-state="${state}" aria-label="${esc(headerLabel)}">
    <span class="cv-channel-icon" aria-hidden="true">${icon}</span>
    <span class="cv-channel-label">${esc(label)}</span>
    <span class="cv-channel-dot" aria-hidden="true">
      <span class="cv-channel-dot-fill"></span>
      <span class="cv-channel-dot-ring"></span>
    </span>
  </div>`;
}
