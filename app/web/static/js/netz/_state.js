// ─── netz/_state.js ────────────────────────────────────────────────────────
// Module state for the Netz page. One object, no getters — the sub-modules
// read it directly, matching storms/_state.js next door.

export const netzState = {
  // ── Netz-Tab ──
  camId: null,
  state: null, // last /api/netz/state payload
  loading: false,
  // Staged, uncommitted drags: {label: E}. Pointerup STAGES a value; it
  // is not saved until "Übernehmen". The snapshot is what "Verwerfen"
  // restores to.
  staged: {},
  snapshot: {},
  // Per (label, E) preview cache — the drag pill's third line, so a
  // slow round-trip never re-fires for a radius the pointer already
  // visited on its way out.
  previews: {},

  // Fangnetz PRIMARY axes (camera-wide settings) — see _settings_axes.js.
  // Rebuilt from state.tuning on every render; tuneStaged holds raw
  // values a drag has moved but not yet committed via patchTuning.
  tuneAxes: [],
  tuneStaged: {},

  // ── Verlauf-Tab ──
  tab: 'netz',
  archive: null,
  archiveFilter: { cam: null, label: null, open: false },
  archiveView: 'list', // list | detail
  detailId: null,
  detail: null,
};

export function stagedCount() {
  return Object.keys(netzState.staged).length;
}

export function clearStaged() {
  netzState.staged = {};
  netzState.snapshot = {};
}

/** E currently shown for an axis: the staged value if the operator is
 *  mid-edit, otherwise the committed one. */
export function shownE(axis) {
  const st = netzState.staged[axis.label];
  return st === undefined ? axis.E : st;
}

export function axisByLabel(label) {
  return (netzState.state?.axes || []).find((a) => a.label === label) || null;
}

export function previewKey(label, e) {
  return `${label}:${e}`;
}
