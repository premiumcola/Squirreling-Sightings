// ─── vplayer/_delete-flow.js ───────────────────────────────────────────────
// Deleting a recording. Three branches, three endpoints, and a set of
// asymmetries that are all deliberate.
//
// THE LEDGER IS NOT HERE. There is no verdict-writing code in the
// frontend at all — the detection-feedback ledger lives entirely in
// app/app/routes/events.py, and these handlers book a verdict
// IMPLICITLY, by which URL they hit:
//
//   · the motion/photo endpoint books correct=False, source="web_delete"
//     (events.py, guarded by `if not event_id.startswith("tl_")`);
//   · the weather endpoint books NOTHING;
//   · the timelapse endpoint books NOTHING.
//
// So the safety of this extraction rests on exactly two things: the
// URLs, and the branch conditions that choose between them. Routing a
// timelapse or a weather sighting through the events URL would file a
// "Fehlalarm" verdict against something no human judged, and because
// the ledger is last-write-wins per event_id it would OVERWRITE an
// honest ✅ the operator had already tapped in Telegram. This project
// has been burned by that class twice.
//
// BRANCH ORDER IS SEMANTIC. `source === 'weather'` is tested BEFORE
// `type === 'timelapse'`, because a weather sighting is synthesised
// timelapse-SHAPED. Swapping them routes weather deletes at the
// timelapse endpoint, which 404s on sighting ids.
//
// ARMING IS ASYMMETRIC, and that is how it shipped: weather and
// timelapse require two taps, motion/photo deletes on the FIRST. The
// only two-step path for a motion event is the ArrowDown key, and only
// once it is already confirmed. There is also NO disarm timeout —
// nothing resets the flag on a timer; it is cleared when the next item
// opens. None of that is tidied up here.

/** The three delete branches. */
export const DELETE_WEATHER = 'weather';
export const DELETE_TIMELAPSE = 'timelapse';
export const DELETE_MOTION = 'motion';

/**
 * PURE: which branch an item belongs to.
 *
 * Order matters — see the header.
 */
export function deleteBranchFor(item) {
  if (!item) return null;
  if (item.source === 'weather') return DELETE_WEATHER;
  if (item.type === 'timelapse') return DELETE_TIMELAPSE;
  return DELETE_MOTION;
}

/** PURE: does this branch require a second tap before it fires? */
export function needsArming(branch) {
  return branch === DELETE_WEATHER || branch === DELETE_TIMELAPSE;
}

/**
 * PURE: the request a branch makes.
 *
 * @returns {{url: string, method: string}|null} null when the item is
 *   missing the fields its branch needs — the caller reports that
 *   rather than firing a request at a malformed URL.
 */
export function deleteRequestFor(item) {
  const branch = deleteBranchFor(item);
  if (!branch) return null;
  if (branch === DELETE_WEATHER) {
    if (!item.event_id) return null;
    return {
      url: `/api/weather/sightings/${encodeURIComponent(item.event_id)}`,
      method: 'DELETE',
    };
  }
  if (branch === DELETE_TIMELAPSE) {
    // The filename, not the event id — the timelapse store is keyed by
    // file. Derived from relpath when the item carries no explicit one.
    const filename = item.filename || (item.relpath || '').split('/').pop();
    if (!filename || !item.camera_id) return null;
    return {
      url:
        `/api/camera/${encodeURIComponent(item.camera_id)}` +
        `/timelapse/${encodeURIComponent(filename)}`,
      method: 'DELETE',
    };
  }
  if (!item.camera_id || !item.event_id) return null;
  return {
    url:
      `/api/camera/${encodeURIComponent(item.camera_id)}` +
      `/events/${encodeURIComponent(item.event_id)}`,
    method: 'DELETE',
  };
}

/**
 * Run the delete.
 *
 * @param {object} item
 * @param {object} deps
 * @param {() => boolean} deps.isArmed   current two-step arming state
 * @param {() => void} deps.arm          set it, and show "nochmal"
 * @param {(url, opts) => Promise} deps.request  the shared api helper,
 *   which throws on any non-2xx — every after-success step below is
 *   therefore genuinely gated on a 2xx
 * @param {(branch, item) => void} [deps.onDeleted]  branch-specific
 *   aftermath: the grids, the re-pagination and the neighbour to open
 *   differ per branch and stay with the caller that owns that state
 * @param {(msg) => void} [deps.onError]
 * @returns {Promise<{armed?: boolean, deleted?: boolean}>}
 */
export async function runDelete(item, deps) {
  const branch = deleteBranchFor(item);
  const req = deleteRequestFor(item);
  if (!branch || !req) {
    deps.onError?.('Löschen nicht möglich — Aufnahme unvollständig');
    return { deleted: false };
  }
  if (needsArming(branch) && !deps.isArmed()) {
    deps.arm();
    return { armed: true };
  }
  try {
    await deps.request(req.url, { method: req.method });
  } catch (e) {
    deps.onError?.('Löschen fehlgeschlagen: ' + (e?.message || e));
    return { deleted: false };
  }
  deps.onDeleted?.(branch, item);
  return { deleted: true };
}
