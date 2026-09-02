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
//                nothing. Says so, with the confidence gate that
//                filtered the short sightings out.
//   unindexed    no sidecar at all. Nothing has ever looked.
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
import { pctLabel } from '../_helpers.js';

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

/** The markup for one empty state. */
export function emptyStateHtml(state, { item, tracks } = {}) {
  if (state === 'timelapse') {
    return (
      `<div class="vp-tl-empty" data-state-kind="timelapse" ` +
      `data-event-id="${esc(String(item?.event_id || ''))}" ` +
      `data-camera-id="${esc(String(item?.camera_id || ''))}">` +
      `<span class="vp-tl-empty-text">Noch keine Track-Daten</span>` +
      `<button type="button" class="vp-tl-rescan">${_RESCAN_SVG}` +
      `<span>Nach-Erkennung starten</span></button></div>`
    );
  }
  if (state === 'done') {
    const min = tracks?.gates?.min_confidence;
    const sub =
      typeof min === 'number'
        ? `<span class="vp-tl-empty-sub">kurze Sichtungen unter ${esc(pctLabel(min))} ` +
          `werden gefiltert</span>`
        : '';
    return (
      `<div class="vp-tl-empty" data-state-kind="done">` +
      `<span class="vp-tl-empty-text">Indexierung fertig · keine Spuren bestätigt</span>` +
      `${sub}</div>`
    );
  }
  return (
    `<div class="vp-tl-empty" data-state-kind="unindexed">` +
    `<span class="vp-tl-empty-text">Noch nicht indexiert</span>` +
    // The pill this points at is labelled "Neu erkennen". The old copy
    // still said "Neu indexieren", which the pill has not been called
    // for some time — an instruction naming a button that is not there.
    `<span class="vp-tl-empty-sub">über »Neu erkennen« erzeugen</span></div>`
  );
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
  const label = btn.querySelector('span:last-child');
  const setState = (state, text) => {
    if (box) box.dataset.state = state;
    if (label && text) label.textContent = text;
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
