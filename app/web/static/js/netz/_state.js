// ─── netz/_state.js ────────────────────────────────────────────────────────
// Module state for the Erkennungsprofil panels. One object, no getters —
// the sub-modules read it directly, matching storms/_state.js next door.
//
// MULTI-CAMERA BY CONSTRUCTION. Every camera gets its own panel beside its
// own Live-Feed tile, so anything that describes a net is keyed by camera
// id. The old single-camera scalars (`camId` + one `state`) were the shape
// that made a drag on camera B stage onto camera A and PATCH the wrong
// camera — there is deliberately no "current camera" left for a write path
// to read. Writes take their camera id from the DOM node the operator
// touched, the same DOM-walk rule CLAUDE.md mandates for the cam-edit
// collectors.
//
// `focusCam` and the page-level `view`/`archive*` scalars from the
// single-section design are gone: there is no shared camera-chip switcher
// to highlight and no one view to route between any more — each panel owns
// its own Netz/Verlauf toggle, so that state is per camera too
// (`viewByCam` etc.).

export const netzState = {
  cameras: [], // [{id, name, role}] — every camera with a panel
  states: {}, // camId -> /api/netz/state payload
  loading: false,
  // camId -> [{key, E, raw, …}] — what the pointer layer resolves a
  // dragged vertex against. Rebuilt on every render of that camera's panel.
  tuneAxes: {},
  // camId -> {field: rawValue} — dragged but not yet committed.
  tuneStaged: {},

  // ── per-panel Netz / Verlauf toggle ──
  viewByCam: {}, // camId -> 'netz' | 'verlauf'
  archiveByCam: {}, // camId -> last /api/netz/archive response for this cam
  archiveFilterByCam: {}, // camId -> {label, open}
  archiveViewByCam: {}, // camId -> 'list' | 'detail'
  detailIdByCam: {},
  detailByCam: {},
};

export function camState(camId) {
  return netzState.states[camId] || null;
}

export function stagedFor(camId) {
  return netzState.tuneStaged[camId] || {};
}

export function stagedCountFor(camId) {
  return Object.keys(stagedFor(camId)).length;
}

export function stageValue(camId, key, raw) {
  if (!netzState.tuneStaged[camId]) netzState.tuneStaged[camId] = {};
  netzState.tuneStaged[camId][key] = raw;
}

export function clearStagedFor(camId) {
  delete netzState.tuneStaged[camId];
}

export function unstage(camId, key) {
  if (netzState.tuneStaged[camId]) delete netzState.tuneStaged[camId][key];
}

/** The tuning a camera's panel should RENDER: what the server holds, with
 *  any uncommitted drags laid over it. */
export function effectiveTuning(camId) {
  const st = camState(camId);
  return { ...((st && st.tuning) || {}), ...stagedFor(camId) };
}

export function axisFor(camId, key) {
  return (netzState.tuneAxes[camId] || []).find((a) => a.key === key) || null;
}

/** Replace one camera's whole net payload with a fresh server response.
 *
 *  `PATCH /api/netz/<cam>/axes` and `POST /api/netz/<cam>/reset` both
 *  return `H.net_state(cam_id)` — the ladder re-resolved after the write.
 *  Taking it wholesale is the only way the panel can show what actually
 *  landed: a per-class write moves `push`, `spawn`, `source` and
 *  `provenance` together, and patching one of them by hand is how a
 *  display drifts from the pipeline. Staged tuning drags are unaffected —
 *  `effectiveTuning` layers them on top of whatever is stored. */
export function applyNetState(camId, state) {
  if (camId && state) netzState.states[camId] = state;
}

/** Fold a saved response back into the stored state so the next render
 *  shows what the server actually accepted (it clamps and range-checks),
 *  not what was optimistically dragged. */
export function applySaved(camId, fields) {
  const st = camState(camId);
  if (!st) return;
  st.tuning = { ...(st.tuning || {}), ...fields };
}

// ── per-panel Netz / Verlauf toggle ─────────────────────────────────────

export function viewFor(camId) {
  return netzState.viewByCam[camId] || 'netz';
}

export function setView(camId, view) {
  netzState.viewByCam[camId] = view === 'verlauf' ? 'verlauf' : 'netz';
}

export function archiveViewFor(camId) {
  return netzState.archiveViewByCam[camId] || 'list';
}

export function setArchiveView(camId, view) {
  netzState.archiveViewByCam[camId] = view === 'detail' ? 'detail' : 'list';
}

export function archiveFilterFor(camId) {
  if (!netzState.archiveFilterByCam[camId]) {
    netzState.archiveFilterByCam[camId] = { label: null, open: false };
  }
  return netzState.archiveFilterByCam[camId];
}
