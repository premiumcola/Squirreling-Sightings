// ─── netz/_state.js ────────────────────────────────────────────────────────
// Module state for the Erkennungsprofil page. One object, no getters —
// the sub-modules read it directly, matching storms/_state.js next door.
//
// MULTI-CAMERA BY CONSTRUCTION. The page shows every camera's net side by
// side, so anything that describes a net is keyed by camera id. The old
// single-camera scalars (`camId` + one `state`) were the shape that made
// a drag on camera B stage onto camera A and PATCH the wrong camera —
// there is deliberately no "current camera" left for a write path to read.
// Writes take their camera id from the DOM node the operator touched,
// the same DOM-walk rule CLAUDE.md mandates for the cam-edit collectors.

export const netzState = {
  // ── Netz view ──
  cameras: [], // [{id, name, role}] — the chip row
  states: {}, // camId -> /api/netz/state payload
  loading: false,
  // camId -> [{key, E, raw, …}] — what the pointer layer resolves a
  // dragged vertex against. Rebuilt on every render of that camera's card.
  tuneAxes: {},
  // camId -> {field: rawValue} — dragged but not yet committed.
  tuneStaged: {},
  // Which camera's card is highlighted by the chip row. Purely visual —
  // never read by a write path.
  focusCam: null,

  // ── Verlauf view ──
  view: 'netz', // netz | verlauf
  archive: null,
  archiveFilter: { cam: null, label: null, open: false },
  archiveView: 'list', // list | detail
  detailId: null,
  detail: null,
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

/** The tuning a camera's card should RENDER: what the server holds, with
 *  any uncommitted drags laid over it. */
export function effectiveTuning(camId) {
  const st = camState(camId);
  return { ...((st && st.tuning) || {}), ...stagedFor(camId) };
}

export function axisFor(camId, key) {
  return (netzState.tuneAxes[camId] || []).find((a) => a.key === key) || null;
}

/** Fold a saved response back into the stored state so the next render
 *  shows what the server actually accepted (it clamps and range-checks),
 *  not what was optimistically dragged. */
export function applySaved(camId, fields) {
  const st = camState(camId);
  if (!st) return;
  st.tuning = { ...(st.tuning || {}), ...fields };
}
