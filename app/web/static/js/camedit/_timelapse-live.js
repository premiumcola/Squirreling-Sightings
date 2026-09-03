// ─── camedit/_timelapse-live.js ────────────────────────────────────────────
// Pure shaping for the "was läuft gerade" half of the timelapse tile.
//
// The tile used to show only the periodic per-camera profiles, so a sun
// or event timelapse could be capturing for 75 minutes with nothing on
// screen saying so. These helpers turn the `weather` block of
// /api/timelapse/status into rows — and they deliberately keep ONE rule:
// a row exists only while a capture is actually in flight.
//
// The backend distinguishes running / scheduled / skipped / unknown and
// says why it skipped. None of that belongs here: the tile answers "what
// is happening right now", and the scheduled-and-why view lives with the
// configuration under the weather charts. Two places, two questions, no
// duplicated sentence.
//
// No DOM, no fetch, no clock reads — every input is passed in, so this
// file is testable and the render stays a template.

// German labels arrive from the backend (`phase_text` / `trigger_text`,
// both sourced from `weather_episodes._footage.KIND_LABEL_DE`). We do
// not re-derive them here; a fourth copy of "Sonnenuntergang" in the
// codebase is exactly how these strings drift apart.
const _FALLBACK_SUN = 'Sonnen-Timelapse';
const _FALLBACK_EVENT = 'Wetter-Timelapse';

/** Round seconds to a short German remaining-time phrase, or '' when unknown.
 *
 * The null check is explicit and comes first: `Number(null)` is 0, not
 * NaN, so a missing remaining time would otherwise render as "noch 1 s"
 * — a confident countdown for a number we do not have.
 */
function fmtRemaining(seconds) {
  if (seconds === null || seconds === undefined || seconds === '') return '';
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) return '';
  if (n < 1) return 'endet gleich';
  if (n < 90) return `noch ${Math.round(n)} s`;
  const min = Math.round(n / 60);
  if (min < 90) return `noch ${min} min`;
  const h = Math.floor(min / 60);
  const rest = min % 60;
  return rest ? `noch ${h} h ${rest} min` : `noch ${h} h`;
}

/**
 * Rows for every weather timelapse capturing RIGHT NOW.
 *
 * Filtering on `state === 'running'` rather than on the window times is
 * the point: the backend sets that state from an in-flight registry a
 * capture thread writes, so a window that looks open on the clock but
 * whose capture never started produces no row.
 */
function weatherLiveRows(weather) {
  if (!weather || weather.available === false) return [];
  const rows = [];
  for (const s of weather.sun || []) {
    if (s.state !== 'running') continue;
    rows.push({
      kind: 'sun',
      camId: s.camera_id,
      camName: s.camera_name || s.camera_id || '',
      what: s.phase_text || _FALLBACK_SUN,
      remaining: fmtRemaining(s.remaining_s),
    });
  }
  for (const e of weather.event || []) {
    if (e.state !== 'running') continue;
    rows.push({
      kind: 'event',
      camId: e.camera_id,
      camName: e.camera_name || e.camera_id || '',
      what: e.trigger_text || _FALLBACK_EVENT,
      remaining: fmtRemaining(e.remaining_s),
    });
  }
  return rows;
}

/**
 * Should the tile be on screen at all?
 *
 * Two independent reasons: a camera records a periodic profile, or a
 * weather capture is in flight. Either one alone is enough; neither
 * means the tile stays empty and the `:empty` CSS rule hides it, exactly
 * as before this file existed.
 */
function tlTileVisible(status, liveRows) {
  if (!status) return false;
  return (Number(status.active_count) || 0) > 0 || (liveRows || []).length > 0;
}

export { fmtRemaining, weatherLiveRows, tlTileVisible };
