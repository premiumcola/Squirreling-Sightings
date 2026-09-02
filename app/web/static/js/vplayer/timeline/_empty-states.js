// ─── vplayer/timeline/_empty-states.js ─────────────────────────────────────
// What the timeline says when it has no tracks to draw. Three different
// answers, because there are three different reasons — and telling them
// apart is the whole point: "nothing was found" and "nothing has looked
// yet" need opposite reactions from the operator.
//
//   timelapse    no sidecar, and the clip is a timelapse. These are
//                built from stills and are not indexed on capture, so
//                the answer is an action: run the detection now.
//   done         a sidecar exists (it carries built_at or schema) and
//                its track list is empty. The indexer ran and confirmed
//                nothing.
//   unindexed    no sidecar at all. Nothing has ever looked.
//
// Only `timelapse` renders anything, and only its button. The other two
// had nothing but a sentence to offer, and this block paints ON the
// picture — see emptyStateHtml.
//
// THE RESCAN. The timelapse button posts to /api/events/<id>/rescan.
// Worth knowing, because it reads as a second endpoint next to
// /api/tracking/reindex/<id>: on the server they are literally the same
// view function under two @bp.post decorators (routes/tracking.py), so
// the HTTP calls are interchangeable. The CLIENT flows are not. This
// one mutates its own box in place and polls the sidecar itself;
// "Neu erkennen" toasts, shows the in-video pending banner and runs an
// exponential retry. Collapsing them would lose one of those two.

import { esc } from '../../core/dom.js';

/** Which empty state applies. PURE — the branch is the tested part. */
export function emptyStateFor(item, tracks) {
  if (item && item.type === 'timelapse') return 'timelapse';
  // built_at or schema means a sidecar was written, even if it holds no
  // tracks. Their absence means nothing has ever indexed this clip.
  const ran = !!(tracks && (tracks.built_at || tracks.schema));
  return ran ? 'done' : 'unindexed';
}

const _RESCAN_SVG =
  '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M21 12a9 9 0 1 1-3-6.7"/><polyline points="21 3 21 9 15 9"/></svg>';

/** The markup for one empty state.
 *
 *  NOTHING here may be prose. This block renders inside the timeline,
 *  which is an overlay ON the picture — two lines of explanation printed
 *  straight across the video ("Indexierung fertig · keine Spuren
 *  bestätigt / kurze Sichtungen unter 50 % werden gefiltert") and the
 *  verdict was "der Text im Video muss raus da". A sentence about why a
 *  lane is missing is worth exactly nothing painted over the thing the
 *  operator opened the player to watch.
 *
 *  So: the two states that only had something to SAY now render nothing
 *  at all — the panel below already lists what was found, which is the
 *  same answer without covering the picture. The timelapse state keeps
 *  its BUTTON, because that is the only route to a re-detection for a
 *  timelapse clip and losing it would take away a capability, not a
 *  sentence. The button's text is its accessible name only.
 */
export function emptyStateHtml(state, { item } = {}) {
  if (state === 'timelapse') {
    return (
      `<div class="vp-tl-empty" data-state-kind="timelapse" ` +
      `data-event-id="${esc(String(item?.event_id || ''))}" ` +
      `data-camera-id="${esc(String(item?.camera_id || ''))}">` +
      `<button type="button" class="vp-tl-rescan" title="Nach-Erkennung starten" ` +
      `aria-label="Nach-Erkennung starten">${_RESCAN_SVG}</button></div>`
    );
  }
  return '';
}

/**
 * Wire the timelapse rescan button.
 *
 * Keeps the in-place state machine: the box itself reports running,
 * error and "found nothing", rather than a toast that is gone before
 * the job finishes. The poll belongs to this flow too — the operator is
 * looking at this box, so this box is what has to update.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { post, reload, onDone }
 */
export function wireRescan(host, deps = {}) {
  const btn = host?.querySelector('.vp-tl-rescan');
  if (!btn || typeof deps.post !== 'function') return null;

  const box = btn.closest('.vp-tl-empty');
  // The button is icon-only (no prose over the picture), so its progress
  // and any error go to the accessible name and the tooltip, with
  // `data-state` on the box for the visual treatment. A span that no
  // longer exists would have swallowed the error message silently.
  const setState = (state, text) => {
    if (box) box.dataset.state = state;
    if (!text) return;
    btn.setAttribute('title', text);
    btn.setAttribute('aria-label', text);
  };

  const onClick = async (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    btn.disabled = true;
    setState('running', 'Erkennung läuft …');
    try {
      const eid = box?.dataset.eventId || '';
      const cid = box?.dataset.cameraId || '';
      const res = await deps.post(eid, cid);
      if (res && res.ok === false) throw new Error(res.error || 'Fehler');
      deps.onDone?.(eid, cid);
    } catch (err) {
      setState('err', `Fehler: ${err?.message || err}`);
      btn.disabled = false;
    }
  };

  btn.addEventListener('click', onClick);
  return { teardown: () => btn.removeEventListener('click', onClick) };
}
