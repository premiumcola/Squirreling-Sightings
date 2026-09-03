// ─── weather/suntltest/_consts.js ──────────────────────────────────────────
// Capture-pipeline constants + the pure math the configurator runs.
//
// G5 · INVARIANT — _DURATIONS and _TARGET_LENGTHS must stay aligned with
// weather_service/_sun_tl/__init__.py's _SUN_TL_TEST_DURATIONS and
// _SUN_TL_TEST_TARGET_LENGTHS. The backend rejects an out-of-allowlist
// value outright rather than coercing it, so a drift here surfaces as a
// visible start failure instead of a silent /15-vs-/150 mismatch.

// G1 · System-wide capture-pipeline constants. Match
//   weather_service/_sun_tl/__init__.py (target_fps fixed at 15) and
//   settings/migrations.py (interval_s floor 8 s).
export const FPS = 15;
export const INTERVAL_S = 8;

// Window options spanning smoke tests (5/10 min) through the
// production-equivalent 75 min lock. Internal seconds map below.
export const DURATIONS = [
  { s: 300, label: '5 min' },
  { s: 600, label: '10 min' },
  { s: 900, label: '15 min' },
  { s: 1200, label: '20 min' },
  { s: 1800, label: '30 min' },
  { s: 2700, label: '45 min' },
  { s: 3600, label: '1 h' },
  { s: 4500, label: '75 min' },
];

// Final MP4 length picker — chips greyed out when the window doesn't
// produce enough frames for the chosen target × 15 fps.
export const TARGET_LENGTHS = [
  { s: 5, label: '5 s' },
  { s: 10, label: '10 s' },
  { s: 15, label: '15 s' },
  { s: 20, label: '20 s' },
  { s: 30, label: '30 s' },
  { s: 37, label: '37 s' },
];

// Pure helpers — single source of truth for the math the backend will
// run. Keep aligned with _sun_tl/__init__.py · _run_sun_capture_inner.
export function captureBudget(windowS) {
  return Math.floor(windowS / INTERVAL_S);
}
export function maxTargetS(windowS) {
  return Math.floor(captureBudget(windowS) / FPS);
}
export function isTargetValid(windowS, targetS) {
  return targetS <= maxTargetS(windowS);
}

// One-liner German hints under each rejected_by_reason row. Frontend
// strings only — backend stays language-agnostic.
const REJECT_HINT_DE = {
  dead_area: 'Wenig Textur — wahrscheinlich Nachthimmel oder leere Wand',
  grey_midband: 'IR-Cut-Filter-Transition oder gleichmäßig grauer Himmel',
  grey_uniform: 'IR-Cut-Filter-Transition oder gleichmäßig grauer Himmel',
  no_detail: 'Frame fast komplett uniform — Encoder-Hickup oder Kamera-Reset',
  pink_artifact: 'H.265-Decode-Fehler — typisch bei schwacher Verbindung',
  patterned_magenta: 'H.265-Decode-Fehler — typisch bei schwacher Verbindung',
  colorbar: 'Kamera hat ein Test-Pattern gesendet',
  too_dark: 'Belichtung außerhalb des gültigen Bereichs',
  too_bright: 'Belichtung außerhalb des gültigen Bereichs',
  bottom_strip_white:
    'H.265-Decoder hat unteren Bildbereich mit weißem Füllmuster ersetzt — RTSP-Paketverlust oder defekter Slice',
  bottom_strip_bright:
    'Unterer Bildbereich deutlich heller als Szene — wahrscheinlich Macroblock-Korruption',
  horizontal_anomaly_band:
    'Horizontales Korruptions-Band im Bild — H.265-Decoder-Fehler, Slice unvollständig oder Macroblock-Verlust',
  flat_gray_full_frame: 'Vollbild flach-grau — H.265-Decoder-Ausgabe ohne Szeneninhalt',
};

export function rejectHintDe(key) {
  if (!key) return '';
  // Normalise the key:
  //   • strip everything from the first '(' so a parameterised
  //     reason head ("horizontal_anomaly_band(y=55%,h=2%,score=3.6)")
  //     matches the bare "horizontal_anomaly_band" entry
  //   • strip the _yNN_hNN band-location suffix that the test-mode
  //     reject sink appends to the folder name
  //   • collapse split_*_dead → "split" so the four split variants
  //     share one hint
  let bare = key;
  const lp = bare.indexOf('(');
  if (lp >= 0) bare = bare.slice(0, lp);
  bare = bare.replace(/_y\d+_h\d+$/, '');
  if (bare.startsWith('split_')) bare = 'split';
  return REJECT_HINT_DE[bare] || REJECT_HINT_DE[key] || '';
}
