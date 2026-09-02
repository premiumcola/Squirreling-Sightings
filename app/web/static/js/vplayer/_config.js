// ─── vplayer/_config.js ────────────────────────────────────────────────────
// PURE. Caller config in, normalised player config out. No DOM, no
// fetch, no module state — which is what lets every per-mode decision
// in the package be a unit test instead of a browser smoke.
//
// The one structural idea here: LIVE IS SIMULATION WITH THINGS HIDDEN.
// Both ride the same rolling-window controller over the same live
// transport; live simply hides the detection panel and the overlays.
// Expressing that as two flags rather than two controllers is the whole
// reason this file exists — the previous architecture grew a second
// implementation for exactly this difference and then had to fix every
// bug twice.
//
// Recorded differs structurally instead: a known duration, so a
// drag-to-seek scrubber rather than a right-anchored rolling window,
// and an item that can be navigated, relabelled, confirmed and deleted.

/** The three surfaces this player serves. */
export const VPLAYER_MODES = ['recorded', 'live', 'sim'];

// Per-mode flags. Read by the shell, the timeline and the panels; no
// consumer branches on `mode` itself, they branch on these — so adding
// a fourth surface later is a row in this table, not a new code path.
const MODE_FLAGS = {
  recorded: {
    timeline: 'scrub', // full known duration, drag-to-seek
    panel: 'recorded', // object list + provenance fold
    // Overlay-toggle persistence scope. These are the EXISTING keys
    // mediaview/overlay-toggles.js already stores under, deliberately
    // reused: an operator who turned trails off in the Mediathek must
    // find them off here too, and a new key would silently reset that.
    contextKey: 'mediathek',
    showPanel: true,
    showOverlays: true,
    overlayToggles: ['bboxes', 'trails', 'zones', 'masks'],
    canNavigate: true, // prev/next chevrons, when handlers are supplied
    canDelete: true,
    canConfirm: true,
    canRecordNow: false,
    canPickRevision: false,
    live: false,
  },
  sim: {
    timeline: 'rolling', // right-anchored last-60s window
    panel: 'live', // active tracks, raw detections, debug log
    contextKey: 'live',
    showPanel: true,
    showOverlays: true,
    overlayToggles: ['bboxes', 'trails', 'zones', 'masks'],
    canNavigate: false,
    canDelete: false,
    canConfirm: false,
    canRecordNow: true,
    // Only the simulation may be pointed at another profile revision.
    // This is the flag that keeps the live view honest: it is the same
    // controller and the same panel code, and without a per-mode flag
    // "the live view always shows the running profile" would rest on
    // nobody happening to render the chip.
    canPickRevision: true,
    live: true,
  },
  live: {
    // Same controller as sim. The operator watching a camera wants the
    // picture, not the pipeline: panel and overlays off.
    timeline: 'rolling',
    panel: 'live',
    contextKey: 'live',
    showPanel: false,
    showOverlays: false,
    overlayToggles: [],
    canNavigate: false,
    canDelete: false,
    canConfirm: false,
    canRecordNow: true,
    canPickRevision: false,
    live: true,
  },
};

/** Rolling live window, in ms. One number, used by every live surface. */
export const LIVE_WINDOW_MS = 60000;

/** Overlay layers, in paint order. */
const OVERLAY_KEYS = ['bboxes', 'trails', 'zones', 'masks'];

/** Action handlers the shell may wire up; anything absent stays null. */
const ACTION_KEYS = ['onClose', 'onPrev', 'onNext', 'onConfirm', 'onDelete', 'onDownload'];

/**
 * Normalise the overlay block: only the four known layers, always all
 * four present as booleans, defaulting to the mode's own answer. A
 * missing key must never read as `undefined` downstream — an overlay
 * that is neither on nor off is how a layer ends up painting when the
 * operator turned it off.
 */
function _normalizeOverlays(raw, flags) {
  const out = {};
  for (const key of OVERLAY_KEYS) {
    const wanted = flags.overlayToggles.includes(key);
    out[key] = raw && key in raw ? raw[key] === true : wanted && flags.showOverlays;
  }
  return out;
}

/** Keep only callable handlers; everything else becomes an explicit null. */
function _normalizeActions(raw) {
  const out = {};
  for (const key of ACTION_KEYS) {
    const fn = raw ? raw[key] : null;
    out[key] = typeof fn === 'function' ? fn : null;
  }
  return out;
}

/**
 * Pull the camera identity out of whichever shape the caller used. The
 * live surfaces pass camId/cameraName flat; recorded passes a mediathek
 * item. Both end up as one item so nothing downstream has to ask which
 * call site it came from.
 */
function _normalizeItem(raw) {
  const item = raw.item && typeof raw.item === 'object' ? { ...raw.item } : {};
  if (raw.camId && !item.camera_id) item.camera_id = raw.camId;
  if (raw.cameraName && !item.camera_name) item.camera_name = raw.cameraName;
  return item;
}

/**
 * Build the normalised player config.
 *
 * @param {object} raw  caller config: { mode, source?, item?, camId?,
 *   cameraName?, overlays?, actions? }
 * @returns {{mode:string, source:object|null, item:object,
 *   overlays:object, actions:object, flags:object, windowMs:number}}
 * @throws {Error} on a missing or unknown mode — loudly, at the call
 *   site, rather than rendering an empty shell.
 */
export function buildPlayerConfig(raw) {
  if (!raw || typeof raw !== 'object') {
    throw new Error('openVideoPlayer: config object required');
  }
  const mode = raw.mode;
  const flags = MODE_FLAGS[mode];
  if (!flags) {
    throw new Error(`openVideoPlayer: unknown mode '${mode}'`);
  }
  return {
    mode,
    source: raw.source && typeof raw.source === 'object' ? { ...raw.source } : null,
    item: _normalizeItem(raw),
    overlays: _normalizeOverlays(raw.overlays, flags),
    actions: _normalizeActions(raw.actions),
    // Opaque callback bag for the panels (the shared api helper, the
    // re-index trigger, the correction save). Passed through verbatim:
    // unlike `actions`, whose keys the shell itself wires to chrome,
    // these belong to whichever panel the mode selects.
    deps: raw.deps && typeof raw.deps === 'object' ? { ...raw.deps } : {},
    flags: { ...flags, overlayToggles: [...flags.overlayToggles] },
    windowMs: flags.live ? LIVE_WINDOW_MS : 0,
  };
}
