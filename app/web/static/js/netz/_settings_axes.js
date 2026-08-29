// ─── netz/_settings_axes.js ────────────────────────────────────────────────
// The Fangnetz's PRIMARY axes: camera-wide capture/motion/tracking
// settings, not per-class confidence. Confidence has its own evidence-
// driven E (see _mapping.js) fed by Telegram verdicts; these 8 have no
// such feedback loop — a setting is either at its shipped default
// ("Werk") or the operator moved it ("manuell"). That is the whole of
// their provenance, computed here from the raw value alone rather than
// tracked server-side.
//
// Each spec turns a raw stored value into E (0-100, same radial scale
// the chart geometry already understands) and back. `invert: true`
// means a SMALLER raw value is the more sensitive/thorough end (maps to
// OUTER); false means bigger raw = outer. `steps` (categorical or
// stepped-numeric fields) replaces the linear min/max mapping with a
// position in a fixed list, so E only ever lands on a real value —
// there is no "continue and IoU" reading between "roi" and "2x2".

export const TUNE_AXIS_ORDER = [
  'frame_interval_ms',
  'motion_sensitivity',
  'post_motion_tail_s',
  'track_miss_grace_seconds',
  'track_iou_match_threshold',
  'roi_mode',
  'wildlife_motion_sensitivity',
  'roi_min_net_disp_frac',
];

export const TUNE_LABELS_DE = {
  frame_interval_ms: 'Analyse-Intervall',
  motion_sensitivity: 'Bewegungs-Vortrigger',
  post_motion_tail_s: 'Nachlauf',
  track_miss_grace_seconds: 'Gnadenfrist',
  track_iou_match_threshold: 'IoU-Schwelle',
  roi_mode: 'ROI-Modus',
  wildlife_motion_sensitivity: 'Wildtier-Empfindlichkeit',
  roi_min_net_disp_frac: 'Min.-Strecke',
};

const _ROI_STEPS = ['off', 'roi', '2x2', '3x3'];
const _ROI_STEP_LABELS = { off: 'Aus', roi: 'Motion-ROI', '2x2': '2×2', '3x3': '3×3' };
const _TAIL_STEPS = [0, 3, 5, 8, 10, 15];

export const TUNE_SPECS = {
  frame_interval_ms: {
    key: 'frame_interval_ms',
    label: TUNE_LABELS_DE.frame_interval_ms,
    min: 100,
    max: 2000,
    default: 350,
    invert: true,
    fmt: (v) => `${Math.round(v)} ms`,
    hint: 'Wie schnell gescannt wird · innen = sparsam (seltener), außen = wachsam (öfter, mehr Coral-Last)',
  },
  motion_sensitivity: {
    key: 'motion_sensitivity',
    label: TUNE_LABELS_DE.motion_sensitivity,
    min: 0.1,
    max: 1.0,
    default: 0.5,
    invert: false,
    fmt: (v) => `${Math.round(v * 100)} %`,
    hint: 'Bewegung vor der KI · innen = nur große Bewegung, außen = auch kleine',
  },
  post_motion_tail_s: {
    key: 'post_motion_tail_s',
    label: TUNE_LABELS_DE.post_motion_tail_s,
    steps: _TAIL_STEPS,
    default: 0,
    fmt: (v) => (Number(v) <= 0 ? 'Standard' : `${v} s`),
    hint: 'Nachlauf-Aufnahme nach letzter Bewegung · innen = kein Nachlauf, außen = 15 s',
  },
  track_miss_grace_seconds: {
    key: 'track_miss_grace_seconds',
    label: TUNE_LABELS_DE.track_miss_grace_seconds,
    min: 0,
    max: 30,
    default: 0,
    invert: false,
    fmt: (v) => (Number(v) <= 0 ? 'Standard' : `${Number(v).toFixed(1)} s`),
    hint: 'Wie lange ein Track ohne Treffer überlebt · innen = stirbt schnell, außen = nachsichtig',
  },
  track_iou_match_threshold: {
    key: 'track_iou_match_threshold',
    label: TUNE_LABELS_DE.track_iou_match_threshold,
    min: 0,
    max: 0.95,
    default: 0,
    invert: true,
    fmt: (v) => (Number(v) <= 0 ? 'Standard' : Number(v).toFixed(2)),
    hint: 'Box-Ähnlichkeit für Track-Fortsetzung · innen = muss fast exakt matchen, außen = großzügig',
  },
  roi_mode: {
    key: 'roi_mode',
    label: TUNE_LABELS_DE.roi_mode,
    steps: _ROI_STEPS,
    default: 'off',
    fmt: (v) => _ROI_STEP_LABELS[v] || v,
    hint: 'Kleintier-Nachscan bei erkannter Bewegung · innen = aus, außen = volle 3×3-Kachelung',
  },
  wildlife_motion_sensitivity: {
    key: 'wildlife_motion_sensitivity',
    label: TUNE_LABELS_DE.wildlife_motion_sensitivity,
    min: 0,
    max: 3,
    default: 0,
    invert: false,
    fmt: (v) => (Number(v) <= 0 ? 'auto' : `${Number(v).toFixed(1)}×`),
    hint: 'Bewegungsschwelle für kleine Tiere · innen = auto, außen = empfindlicher',
  },
  roi_min_net_disp_frac: {
    key: 'roi_min_net_disp_frac',
    label: TUNE_LABELS_DE.roi_min_net_disp_frac,
    min: 0,
    max: 0.2,
    default: 0,
    invert: false,
    fmt: (v) => (Number(v) <= 0 ? 'auto (4 %)' : `${Math.round(v * 100)} %`),
    hint: 'Mindest-Wegstrecke gegen Wind-Flackern · innen = auto (4 %), außen = strenger',
  },
};

function _clamp01(x) {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

/** Raw stored value → E (0-100). Stepped/categorical specs place E at
 *  the step's index fraction; linear specs use min/max (+ invert). */
export function tuneE(spec, raw) {
  if (spec.steps) {
    const i = spec.steps.indexOf(spec.steps.includes(raw) ? raw : Number(raw));
    const idx = i >= 0 ? i : spec.steps.indexOf(spec.default);
    return Math.round((idx / (spec.steps.length - 1)) * 100);
  }
  const v = Number(raw);
  const frac = _clamp01((v - spec.min) / (spec.max - spec.min));
  return Math.round((spec.invert ? 1 - frac : frac) * 100);
}

/** E (0-100, from a drag) → the raw value to persist. Snaps to the
 *  nearest step for stepped/categorical specs; for security-relevant
 *  numeric specs (IoU, motion sensitivity) the caller still range-
 *  validates server-side — this is the UI-side inverse only. */
export function tuneRawFromE(spec, e) {
  const frac = _clamp01(e / 100);
  if (spec.steps) {
    const idx = Math.round(frac * (spec.steps.length - 1));
    return spec.steps[Math.max(0, Math.min(spec.steps.length - 1, idx))];
  }
  const f = spec.invert ? 1 - frac : frac;
  const raw = spec.min + f * (spec.max - spec.min);
  return spec.key === 'frame_interval_ms' ? Math.round(raw / 50) * 50 : Math.round(raw * 100) / 100;
}

export function tuneDisplay(spec, raw) {
  return spec.fmt(raw);
}

export function tuneIsDefault(spec, raw) {
  if (spec.steps) return String(raw) === String(spec.default);
  return Number(raw) === Number(spec.default);
}

/** Build the axis row array `_radar.js` and the drag layer both expect:
 *  {key, label, E, provenance, raw}, in the fixed TUNE_AXIS_ORDER. */
export function buildTuneAxes(tuning) {
  return TUNE_AXIS_ORDER.map((key) => {
    const spec = TUNE_SPECS[key];
    const raw = tuning?.[key] ?? spec.default;
    return {
      key,
      label: TUNE_LABELS_DE[key] || key,
      raw,
      E: tuneE(spec, raw),
      provenance: tuneIsDefault(spec, raw) ? 'werk' : 'manuell',
      display: tuneDisplay(spec, raw),
    };
  });
}
