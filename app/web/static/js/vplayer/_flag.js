// ─── vplayer/_flag.js ──────────────────────────────────────────────────────
// Rollout gate for the unified video player. Three surfaces (recorded
// clips, the live expand arrow, the simulation view) each move onto the
// new player in two commits: first a call site that branches on this
// flag, then a one-line flip of the default here. That way a bad
// rollout is reverted by reverting ONE commit that changes ONE line,
// with the old implementation still on disk the whole time.
//
// Two overrides, in precedence order:
//
//   ?vplayer=sim        — enable one surface for this page load
//   ?vplayer=all        — enable every surface
//   ?vplayer=off        — force every surface OFF, which is the
//                         operator's escape hatch AFTER a default has
//                         been flipped on and something looks wrong
//   localStorage['tamspy.vplayer.v1']  — same vocabulary, but sticky
//                         across reloads for a longer soak
//
// The try/catch shapes copy mediathek/bbox-overlay/_state.js's
// _DEBUG_LB: a browser with storage blocked (Safari private mode, a
// locked-down kiosk profile) throws on plain property access, and a
// player that cannot open because a feature flag threw would be a
// worse failure than any bug this flag is guarding.
//
// This whole file is deleted once all three surfaces have soaked
// default-on — a permanently-true flag is dead code.

/** localStorage key. Versioned so a later rollout can't inherit it. */
const STORE_KEY = 'tamspy.vplayer.v1';

/** Every surface that can be switched independently. */
export const VPLAYER_SURFACES = ['recorded', 'live', 'sim'];

// The defaults. Every surface ships OFF; each gets flipped to true in
// its own one-line commit after the flag-gated call site has proven it.
const DEFAULTS = {
  recorded: false,
  live: false,
  sim: true,
};

/** Read the override token from the URL, or '' when absent/unreadable. */
function _urlToken() {
  try {
    return new URLSearchParams(location.search).get('vplayer') || '';
  } catch {
    return '';
  }
}

/** Read the override token from localStorage, or '' when unreadable. */
function _storedToken() {
  try {
    return localStorage.getItem(STORE_KEY) || '';
  } catch {
    return '';
  }
}

/**
 * Resolve one token against one surface.
 *
 * @returns {boolean|null} the decision, or null when this token says
 *   nothing about this surface and the next source should be consulted.
 */
export function decideFromToken(token, surface) {
  if (!token) return null;
  const t = String(token).trim().toLowerCase();
  if (t === 'off' || t === '0') return false;
  if (t === 'all' || t === '1') return true;
  // A comma list lets one URL enable two surfaces at once during a
  // cross-surface smoke ("?vplayer=sim,live").
  const wanted = t
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (!wanted.length) return null;
  return wanted.includes(surface) ? true : null;
}

/**
 * Is the new player enabled for this surface?
 *
 * Resolved per call rather than once at module load: the SPA never
 * reloads, so a stored override set from the console has to take
 * effect on the next open, not on the next full page load.
 *
 * @param {'recorded'|'live'|'sim'} surface
 * @returns {boolean}
 */
export function vplayerEnabled(surface) {
  const fromUrl = decideFromToken(_urlToken(), surface);
  if (fromUrl !== null) return fromUrl;
  const fromStore = decideFromToken(_storedToken(), surface);
  if (fromStore !== null) return fromStore;
  return DEFAULTS[surface] === true;
}
