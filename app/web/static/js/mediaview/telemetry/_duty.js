// ─── mediaview/telemetry/_duty.js ──────────────────────────────────────────
// Block C (the number) + Block B (where the time goes).
//
// The duty bar's heading names its BASIS, because the two bases are not
// comparable. On the TPU tier one process-wide lock serialises every
// camera onto one stick, so a single percentage of one device is
// meaningful. On the CPU tier the interpreters run in parallel and there
// is no shared denominator — the honest number there is how much of each
// camera's own loop thread sits inside the detector. Printing a "TPU
// utilisation" while no TPU is running would be a confident lie.
import { esc } from '../../core/dom.js';

const _BUCKETS = [
  ['pre', 'Vorbereitung'],
  ['wait', 'Wartezeit'],
  ['invoke', 'Berechnung'],
  ['post', 'Auslesen'],
];

export function renderDutyBlock(data) {
  const p = data.projection || {};
  const cams = data.cameras || [];
  const onTpu = p.basis === 'tpu';
  // The mode the cameras are ACTUALLY running, not a hard-coded one —
  // otherwise the headline number describes a configuration nobody chose.
  const current = (p.modes || []).find((m) => m.mode === (p.measured_mode || 'off')) || {};
  const heading = onTpu ? 'TPU-Auslastung' : 'CPU · Schleifen-Belegung je Kamera';
  const value = onTpu
    ? (current.duty ? current.duty[1] : 0)
    : Math.max(0, ...cams.map((c) => Number(c.loop_occupancy) || 0));
  const pct = Math.min(100, Math.round(value * 100));
  return (
    '<div class="mv-tele-block">' +
    `<div class="mv-ld-subsection-head">${esc(heading)}</div>` +
    `<div class="mv-tele-bar" role="img" aria-label="${pct} Prozent belegt">` +
    `<span class="mv-tele-bar-fill" style="width:${pct}%"></span>` +
    `<span class="mv-tele-bar-lead">${pct} %</span>` +
    `<span class="mv-tele-bar-trail">${100 - pct} % Kopffreiheit</span>` +
    '</div>' +
    _waitLine(p) +
    _breakdown(p, cams) +
    '</div>'
  );
}

// The self-check the panel gets for free: if the projection is right,
// measured lock-wait stays small. Wait climbing while the projection does
// not means a third consumer is on the device, or the model is slower
// than its mean suggests. wait_p95 exists for exactly this and until now
// had no display anywhere.
function _waitLine(p) {
  const w = Number(p.wait_ms) || 0;
  const p95 = Number(p.wait_p95_ms) || 0;
  return (
    '<div class="mv-tele-note">' +
    `Gemessene Wartezeit ⌀ ${esc(w.toFixed(1))} ms · p95 ${esc(p95.toFixed(1))} ms` +
    '</div>'
  );
}

function _breakdown(p, cams) {
  const total = Number(p.invoke_ms || 0) + Number(p.prep_ms || 0);
  if (total <= 0) {
    return '<div class="mv-ld-empty-row">Noch keine Inferenz-Messwerte in diesem Fenster</div>';
  }
  const vals = { pre: Number(p.prep_ms) || 0, wait: Number(p.wait_ms) || 0, invoke: Number(p.invoke_ms) || 0, post: 0 };
  const sum = _BUCKETS.reduce((a, [k]) => a + vals[k], 0) || 1;
  const segs = _BUCKETS.map(
    ([k]) =>
      `<span class="mv-tele-seg" data-bucket="${k}" style="flex:${(vals[k] / sum).toFixed(4)} 1 0"></span>`,
  ).join('');
  const chips = _BUCKETS.map(
    ([k, label]) =>
      `<span class="mv-tele-chip" data-bucket="${k}">${esc(label)} ${vals[k].toFixed(1)} ms</span>`,
  ).join('');
  const fps = cams.map((c) => Number(c.analysed_fps) || 0).reduce((a, b) => a + b, 0);
  const maxFps = cams
    .map((c) => Number(c.configured_fps_max) || 0)
    .reduce((a, b) => a + b, 0);
  return (
    '<div class="mv-ld-subsection-head">Analysetempo</div>' +
    `<div class="mv-tele-stack" aria-hidden="true">${segs}</div>` +
    `<div class="mv-tele-chips">${chips}</div>` +
    '<div class="mv-tele-note">' +
    `${esc(fps.toFixed(1))} / ${esc(maxFps.toFixed(1))} Frames/s analysiert · ` +
    `${esc(String(p.samples || 0))} Messwerte` +
    '</div>'
  );
}
