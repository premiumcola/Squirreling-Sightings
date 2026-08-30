// ─── push-config.js ────────────────────────────────────────────────────────
// The `settings.telegram.push` subtree as DATA: the schema defaults, the
// deep merge, and the effective read. Split out of push.js when that file
// reached the 400-line ceiling — push.js keeps the DOM and the save path,
// this module keeps the shape both of them talk about.
import { state } from './core/state.js';

// Schema-default block — used by the "Standard"-Preset and as a
// fallback when the backend hasn't shipped the keys yet. Mirror of
// TELEGRAM_PUSH_DEFAULTS in app/settings/_consts.py — keep the two in sync.
export function pushDefaults() {
  return {
    enabled: true,
    rate_limit_seconds: 30,
    quiet_hours: { start: '22:00', end: '07:00' },
    night_alert: {
      enabled: true,
      armed_only: true,
      use_sun: true,
      lat: null,
      lon: null,
      start: '22:00',
      end: '07:00',
    },
    labels: {
      person: { push: true, threshold: 0.85 },
      cat: { push: false, threshold: 0.8 },
      dog: { push: true, threshold: 0.8 },
      bird: { push: false, threshold: 0.9 },
      car: { push: true, threshold: 0.85 },
      squirrel: { push: true, threshold: 0.8 },
      motion: { push: false, threshold: 0.0 },
    },
    daily_report: { enabled: true, time: '22:00' },
    highlight: { enabled: true, time: '19:00' },
    system: { enabled: true },
    timelapse: { enabled: true },
  };
}

// In-place deep merge of `s` onto `t`. Mutating on purpose: the save path
// folds a partial onto the live `state.config.telegram.push` object other
// readers already hold a reference to.
export function mergeDeep(t, s) {
  for (const k of Object.keys(s || {})) {
    if (
      s[k] &&
      typeof s[k] === 'object' &&
      !Array.isArray(s[k]) &&
      t[k] &&
      typeof t[k] === 'object'
    ) {
      mergeDeep(t[k], s[k]);
    } else {
      t[k] = s[k];
    }
  }
  return t;
}

// Pull current push config from loaded state with safe fallbacks.
export function pushCfg() {
  const tg = state.config?.telegram || {};
  // Deep merge defaults under user values so the UI never gets undefined.
  // Non-mutating, unlike mergeDeep — the defaults block must survive the
  // call unchanged for the next reader.
  const def = pushDefaults();
  const cur = tg.push || {};
  const merge = (d, c) => {
    const out = { ...d };
    for (const k of Object.keys(c || {})) {
      if (
        c[k] &&
        typeof c[k] === 'object' &&
        !Array.isArray(c[k]) &&
        d[k] &&
        typeof d[k] === 'object'
      ) {
        out[k] = merge(d[k], c[k]);
      } else {
        out[k] = c[k];
      }
    }
    return out;
  };
  return merge(def, cur);
}
