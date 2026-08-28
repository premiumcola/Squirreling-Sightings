// ─── camedit/_timelapse-model.js ───────────────────────────────────────────
// The numbers behind the Timelapse settings UI: the profile catalogue,
// the period / custom-preset option lists, and the pure functions that
// turn a (period, target, fps) triple into an interval, a frame count,
// a disk estimate and their German labels.
//
// Extracted from timelapse-settings.js, which was 508 lines against a
// 400-line ceiling — the previous pass moved the dashboard status pill
// out and reported that as compliance while this file stayed 108 lines
// over. Model and view is the seam that actually holds: nothing here
// touches the DOM, so the renderer can be read without it and these
// numbers can be reasoned about without the markup.
//
// _TL_PROFILES_DEF mirrors TL_DEFAULT_PROFILES in app/settings/_consts.py
// and TIMELAPSE_PROFILES in app/timelapse_windows.py — keep all three in
// step. _TL_FIXED_FPS and _TL_MIN_INTERVAL_S mirror FIXED_FPS and
// MIN_INTERVAL_S in that same module.

export const _TL_PROFILES_DEF = [
  {
    key: 'daily',
    label: 'Täglich',
    defaultPeriod: 86400,
    defaultTarget: 60,
    minTarget: 10,
    maxTarget: 180,
    step: 5,
  },
  {
    key: 'weekly',
    label: 'Wöchentlich',
    defaultPeriod: 604800,
    defaultTarget: 120,
    minTarget: 30,
    maxTarget: 360,
    step: 10,
  },
  {
    key: 'monthly',
    label: 'Monatlich',
    defaultPeriod: 2592000,
    defaultTarget: 300,
    minTarget: 60,
    maxTarget: 600,
    step: 15,
  },
  {
    key: 'quarterly',
    label: 'Quartal',
    defaultPeriod: 7776000,
    defaultTarget: 600,
    minTarget: 120,
    maxTarget: 1800,
    step: 30,
  },
  {
    key: 'yearly',
    label: 'Jährlich',
    defaultPeriod: 31536000,
    defaultTarget: 900,
    minTarget: 300,
    maxTarget: 2700,
    step: 60,
  },
  {
    key: 'custom',
    label: 'Benutzerdefiniert',
    defaultPeriod: 3600,
    defaultTarget: 30,
    minTarget: 10,
    maxTarget: 2700,
    step: 10,
  },
];
export const _TL_PERIOD_OPTIONS = [
  { v: 900, l: '15 Min' },
  { v: 3600, l: '1 Stunde' },
  { v: 21600, l: '6 Stunden' },
  { v: 43200, l: '12 Stunden' },
  { v: 86400, l: '1 Tag' },
  { v: 259200, l: '3 Tage' },
  { v: 604800, l: '1 Woche' },
  { v: 1209600, l: '2 Wochen' },
  { v: 2592000, l: '1 Monat' },
  { v: 7776000, l: '1 Quartal' },
  { v: 31536000, l: '1 Jahr' },
];
// Period+target presets for the "Benutzerdefiniert" profile — the user picks
// one tuple rather than two independent controls. Value is "<periodS>,<targetS>".
export const _TL_CUSTOM_PRESETS = [
  { period: 900, target: 60, label: '15 Min → 1 Min Video' },
  { period: 1800, target: 60, label: '30 Min → 1 Min Video' },
  { period: 3600, target: 30, label: '1 Std → 30 Sek Video' },
  { period: 3600, target: 60, label: '1 Std → 1 Min Video' },
  { period: 10800, target: 60, label: '3 Std → 1 Min Video' },
  { period: 21600, target: 60, label: '6 Std → 1 Min Video' },
  { period: 21600, target: 120, label: '6 Std → 2 Min Video' },
  { period: 43200, target: 60, label: '12 Std → 1 Min Video' },
  { period: 43200, target: 120, label: '12 Std → 2 Min Video' },
  { period: 86400, target: 30, label: '24 Std → 30 Sek Video' },
  { period: 86400, target: 60, label: '24 Std → 1 Min Video' },
  { period: 86400, target: 120, label: '24 Std → 2 Min Video' },
];
export function _tlClosestCustomPreset(periodS, targetS) {
  const pN = parseInt(periodS) || 3600,
    tN = parseInt(targetS) || 60;
  let best = _TL_CUSTOM_PRESETS[0],
    bd = Infinity;
  for (const p of _TL_CUSTOM_PRESETS) {
    // rank exact period match above exact target match
    const d = Math.abs(Math.log(p.period / pN)) * 2 + Math.abs(Math.log(p.target / tN));
    if (d < bd) {
      bd = d;
      best = p;
    }
  }
  return `${best.period},${best.target}`;
}
export function _tlClosestPeriod(v) {
  const n = parseInt(v) || 3600;
  return _TL_PERIOD_OPTIONS.reduce((a, b) => (Math.abs(b.v - n) < Math.abs(a.v - n) ? b : a)).v;
}
// E2 · fps is now a system-wide constant (matches the backend's hard
// 15 fps lock from settings/migrations.py · migrate_timelapse_intervals).
// The user-tunable <select> is gone; the field still round-trips via
// a hidden input so the save payload shape is unchanged for any
// downstream consumer.
export const _TL_FIXED_FPS = 15;
// _TL_MIN_INTERVAL_S mirrors the backend's 8 s capture-interval floor.
// _tlCalcInterval rounds up to this floor; the slider max bound on each
// non-custom profile is derived from period / (floor × fps) so the user
// can't choose a target the encoder would have to back-fill below 8 s.
export const _TL_MIN_INTERVAL_S = 8;
// Measured, not guessed: a 2560×1440 capture frame encoded at q=72 has a
// median size of ~338 KB (p25 268 / p75 478); a frame taken off disk
// measured 245 KB. ~300 KB is the honest typical. The previous 40 KB
// constant understated a daily profile's footprint by 7.5× — it claimed
// "900 Frames · ~35 MB" where the real cost is ~264 MB per camera.
// The 8 s floor means q is always 72 now, so there is no second branch.
export const _TL_PER_FRAME_KB = 300;
// Footprint past which the estimate stops being a footnote. One
// gigabyte of un-encoded JPEGs per camera is worth an explicit row.
export const _TL_DISK_WARN_MB = 1024;
/** MB → "512 MB" / "4,0 GB". German decimal comma, matching
 *  _fmtBytes in timelapse-status.js. */
export function _tlDiskLabel(mb) {
  const n = Number(mb) || 0;
  if (n < 1024) return `${Math.round(n)} MB`;
  return `${(n / 1024).toFixed(1).replace('.', ',')} GB`;
}
export function _tlFmtInterval(secs) {
  const s = Number(secs);
  if (!isFinite(s) || s <= 0) return '—';
  if (s < 10) {
    // 0.6 → "0,6s"  ·  5 → "5s"  ·  5.5 → "5,5s"
    const r = Math.round(s * 10) / 10;
    const str = r === Math.floor(r) ? String(Math.floor(r)) : r.toFixed(1).replace('.', ',');
    return `${str}s`;
  }
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}min`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}
export function _tlSpeedupLabel(v) {
  if (v >= 10000) return (Math.round(v / 100) / 10).toFixed(1) + 'k×';
  return v + '×';
}
export function _tlIntervalLabel(interval_s) {
  if (interval_s < 60) return interval_s + 's';
  if (interval_s < 3600) return Math.round(interval_s / 60) + 'min';
  if (interval_s < 86400) return Math.round(interval_s / 3600) + 'h';
  return Math.round(interval_s / 86400) + 'd';
}
export function _tlTargetLabel(secs) {
  const n = parseInt(secs) || 0;
  if (n < 60) return n + 's';
  return Math.round(n / 60) + 'min';
}
export function _tlCalcInterval(periodS, targetS, fps) {
  // E2 · floor lifted 2 → 8 to match the system-wide capture floor.
  // Returns {interval_s, clamped} so the caller (e.g. _tlResultDesc)
  // can surface a "video will be shorter than chosen" hint when the
  // raw arithmetic wants something tighter than 8 s.
  const pN = parseInt(periodS) || 86400;
  const tN = Math.max(1, parseInt(targetS) || 60);
  const fN = Math.max(1, parseInt(fps) || _TL_FIXED_FPS);
  const raw = pN / (tN * fN);
  if (raw < _TL_MIN_INTERVAL_S) return { interval_s: _TL_MIN_INTERVAL_S, clamped: true, raw: raw };
  return { interval_s: Math.round(raw), clamped: false, raw: raw };
}
// E2 · derived max target so the slider can't be dragged into the
// clamp zone for a given period. Non-custom profiles call this when
// rendering + when the period changes.
export function _tlMaxTargetForPeriod(periodS, profileMax) {
  const pN = parseInt(periodS) || 86400;
  const ceiling = Math.floor(pN / (_TL_MIN_INTERVAL_S * _TL_FIXED_FPS));
  return Math.max(1, Math.min(profileMax || ceiling, ceiling));
}
// Renamed from _tlPeriodLabel — the original name collided with the
// item-shaped _tlPeriodLabel below at line ~5966. As a regular
// <script> the duplicate function declaration silently overrode this
// one, leaving "Timelapse" as the period label everywhere this was
// called; in module mode the duplicate is a SyntaxError. Restoring
// the original numeric→German-duration intent fixes a long-latent UI
// bug as a side effect of the rename.
export function _tlDurationLabel(s) {
  const n = parseInt(s) || 0;
  if (n >= 31536000)
    return Math.round(n / 31536000) + ' Jahr' + (Math.round(n / 31536000) !== 1 ? 'e' : '');
  if (n >= 2592000)
    return Math.round(n / 2592000) + ' Monat' + (Math.round(n / 2592000) !== 1 ? 'e' : '');
  if (n >= 604800)
    return Math.round(n / 604800) + ' Woche' + (Math.round(n / 604800) !== 1 ? 'n' : '');
  if (n >= 86400) return Math.round(n / 86400) + ' Tag' + (Math.round(n / 86400) !== 1 ? 'e' : '');
  if (n >= 3600) return Math.round(n / 3600) + ' Stunde' + (Math.round(n / 3600) !== 1 ? 'n' : '');
  return Math.round(n / 60) + ' Min';
}
export function _tlResultDesc(periodS, targetS, fps) {
  const pN = parseInt(periodS) || 86400,
    tN = parseInt(targetS) || 60,
    fN = parseInt(fps) || _TL_FIXED_FPS;
  const ci = _tlCalcInterval(pN, tN, fN);
  // E2 · when the clamp fires, the EFFECTIVE total frame count is
  // capped at period/floor and the realised video is shorter than
  // the user asked for. Surface that explicitly instead of silently
  // padding the encoder. ``effectiveFrames`` is what actually lands
  // on disk; ``realisedDuration`` is what the user will see in the
  // mediathek.
  const intervalS = ci.interval_s;
  const effectiveFrames = Math.max(1, Math.floor(pN / intervalS));
  const realisedDuration = effectiveFrames / fN;
  const requestedFrames = Math.max(1, Math.round(tN * fN));
  const totalFrames = ci.clamped ? effectiveFrames : requestedFrames;
  const periodLabel = _tlDurationLabel(pN);
  const intervalLabel = _tlFmtInterval(intervalS);
  const compression = Math.round(pN / Math.max(1, tN));
  const diskMb = Math.max(1, Math.round((totalFrames * _TL_PER_FRAME_KB) / 1024));
  const targetLine = ci.clamped
    ? `<div class="tl-drow tl-drow-warn"><span class="tl-drow-ico">⚠</span><span class="tl-drow-text">Intervall auf Minimum ${_TL_MIN_INTERVAL_S} s begrenzt — Video wird ${Math.round(realisedDuration)} s statt ${tN} s lang</span></div>`
    : '';
  // The footprint line was the only place the cost showed up, and it
  // printed raw MB with no threshold — so "Jährlich", the single
  // largest profile, read as an unremarkable "3955 MB Speicher" for
  // what is 13 500 frames ≈ 4 GB PER CAMERA held until the year rolls.
  // Anything past a gigabyte now says GB and carries its own ⚠ row.
  const heavyLine =
    diskMb >= _TL_DISK_WARN_MB
      ? `<div class="tl-drow tl-drow-warn"><span class="tl-drow-ico">⚠</span><span class="tl-drow-text">${_tlDiskLabel(diskMb)} Rohbilder pro Kamera, bis das Fenster fertig ist</span></div>`
      : '';
  return `<div class="tl-drow"><span class="tl-drow-ico">⏱</span><span class="tl-drow-text">${periodLabel} → ${tN}s Video</span></div>${targetLine}<div class="tl-drow"><span class="tl-drow-ico">📸</span><span class="tl-drow-text">${totalFrames} Frames · Alle ${intervalLabel} ein Foto</span></div><div class="tl-drow tl-drow-accent"><span class="tl-drow-ico">⚡</span><span class="tl-drow-text">${compression}× Zeitraffer · ~${_tlDiskLabel(diskMb)} Speicher</span></div>${heavyLine}`;
}
