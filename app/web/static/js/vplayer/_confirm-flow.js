// ─── vplayer/_confirm-flow.js ──────────────────────────────────────────────
// "Behalten" — the operator says the detector got this one right.
//
// Like the delete flow, the ledger write is SERVER-side: the confirm
// endpoint books correct=True, source="web" on its 200 path, with no
// `tl_` guard — so a timelapse CAN book a positive verdict here, unlike
// on delete, where the backend skips `tl_*` ids. That asymmetry is in
// the source as written and is preserved rather than tidied.
//
// One tap, no arming: confirming is not destructive, and a second tap
// on a positive judgement would only slow down the review loop this
// button exists to speed up.

/**
 * PURE: the confirm request for an item.
 *
 * @returns {{url: string, method: string}|null}
 */
export function confirmRequestFor(item) {
  if (!item || !item.camera_id || !item.event_id) return null;
  return {
    url:
      `/api/camera/${encodeURIComponent(item.camera_id)}` +
      `/events/${encodeURIComponent(item.event_id)}/confirm`,
    // POST with no body and no Content-Type — the event id in the path
    // is the whole request.
    method: 'POST',
  };
}

/**
 * Run the confirm.
 *
 * @param {object} item
 * @param {object} deps
 * @param {(url, opts) => Promise} deps.request  throws on non-2xx
 * @param {(item) => void} [deps.onConfirmed]  marks the item and its
 *   grid card, then advances — that fan-out belongs to whoever owns
 *   the grid state, not to this module
 * @param {(msg) => void} [deps.onError]
 * @returns {Promise<{confirmed: boolean}>}
 */
export async function runConfirm(item, deps) {
  const req = confirmRequestFor(item);
  if (!req) {
    deps.onError?.('Bestätigen nicht möglich — Aufnahme unvollständig');
    return { confirmed: false };
  }
  try {
    await deps.request(req.url, { method: req.method });
  } catch (e) {
    deps.onError?.('Bestätigen fehlgeschlagen: ' + (e?.message || e));
    return { confirmed: false };
  }
  deps.onConfirmed?.(item);
  return { confirmed: true };
}
