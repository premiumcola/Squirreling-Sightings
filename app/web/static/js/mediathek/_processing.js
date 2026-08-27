// ─── mediathek/_processing.js ──────────────────────────────────────────────
// "What is being made right now" — the in-flight half of the library.
//
// The backend walks a clip through recording → queued → encoding →
// ready|failed and stamps `stage` + `stage_since` on the event as it
// goes (see camera_runtime/_recording/_stages.py). `/api/camera/<id>/
// media` derives `stage_age_s` and `stage_stalled` on read, because a
// container restart mid-encode leaves an event frozen in a stage with
// no process behind it and nothing that would ever write a flag.
//
// Two surfaces, one source of truth, each fact shown once:
//   * the tile   — replaces the thumbnail while the clip is in flight
//   * the strip  — one line above the grid summing up all of them
// The strip counts and names; the tile carries the per-clip detail.
//
// There is no percentage anywhere. ffmpeg could emit one, but only by
// rewriting the per-camera event JSON at ~1 Hz per clip for a job that
// usually finishes in seconds. Elapsed-in-stage is free and true.
//
// `queued` is NOT a position in a line: each clip re-encodes in its own
// thread. Never render "2 von 3" — say how many are running, not where
// any of them sits.
import { byId, esc } from '../core/dom.js';

// ── vocabulary ──────────────────────────────────────────────────────────────
const STAGE_LABEL = {
  recording: 'wird aufgenommen',
  queued: 'wartet auf Umwandlung',
  encoding: 'wird umgewandelt',
  processing: 'wird verarbeitet',
};
// Which of the three chain steps a stage sits on. The chain is the
// detail view's whole job: it answers "how far along" without a bar.
const STAGE_STEP = { recording: 0, queued: 1, encoding: 1, processing: 1 };
const CHAIN = ['Aufnahme', 'Umwandlung', 'Fertig'];
const PENDING = new Set(['recording', 'queued', 'encoding', 'processing']);

/** Tiles the user has tapped open, kept across the 3 s poll re-render. */
const _openTiles = new Set();

export function isPendingItem(item) {
  if (!item) return false;
  const stage = item.stage || item.status;
  return PENDING.has(stage);
}

/**
 * Does this card show a stage tile instead of a thumbnail?
 *
 * Pending clips, plus the terminal failure that has nothing to play: a
 * `status: error` event with no video is a dead card that used to
 * render as a broken <img>. It gets the tile so the reason is on it and
 * the delete button is next to the reason.
 */
export function needsProcessingTile(item) {
  if (!item) return false;
  if (isPendingItem(item)) return true;
  return item.status === 'error' && !(item.video_relpath || item.video_url);
}

export function fmtElapsed(seconds) {
  if (seconds == null || seconds < 0) return '';
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const m = Math.floor(seconds / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

/**
 * One item's in-flight state, normalised for both surfaces.
 * `kind` is what the UI branches on: busy | stalled | failed.
 */
export function procStateOf(item) {
  const stage = item.stage || item.status || '';
  const failed = item.status === 'error' || stage === 'failed';
  const stalled = !failed && !!item.stage_stalled;
  const age = item.stage_age_s;
  return {
    kind: failed ? 'failed' : stalled ? 'stalled' : 'busy',
    stage,
    step: STAGE_STEP[stage] ?? 1,
    age,
    elapsed: fmtElapsed(age),
    label: failed ? 'fehlgeschlagen' : stalled ? 'hängt' : STAGE_LABEL[stage] || 'wird verarbeitet',
    error: item.encode_error || '',
  };
}

// ── tile ────────────────────────────────────────────────────────────────────
// Static ring, no glyph swap: under prefers-reduced-motion the CSS just
// stops the rotation and the arc stays put, so the tile still reads as
// "in progress" rather than going blank.
const _SPIN = '<span class="mvp-spin" aria-hidden="true"></span>';
const _WARN = `<svg class="mvp-warn" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M12 4.5 2.8 20h18.4z"/><path d="M12 10v4.4"/><circle cx="12" cy="17.4" r=".9" fill="currentColor" stroke="none"/></svg>`;

function _chainHTML(st) {
  return CHAIN.map((name, i) => {
    const cls =
      st.kind !== 'busy' && i >= st.step
        ? 'is-halted'
        : i < st.step
          ? 'is-done'
          : i === st.step
            ? 'is-now'
            : '';
    return `<li class="${cls}">${name}</li>`;
  }).join('');
}

/**
 * The inner markup of a media card whose clip is still being produced.
 * Rendered instead of the thumbnail + play button.
 *
 * The detail opens on hover (desktop, guarded by `hover: hover`) AND on
 * tap — a phone has no hover, so the same panel has to be reachable by
 * touch or the detail may as well not exist.
 */
export function processingTileHTML(item, badgeHTML = '') {
  const st = procStateOf(item);
  const id = esc(item.event_id || '');
  const open = _openTiles.has(item.event_id) ? ' is-open' : '';
  const mark = st.kind === 'busy' ? _SPIN : _WARN;
  const note =
    st.kind === 'failed'
      ? st.error
        ? esc(st.error)
        : 'Die Umwandlung ist fehlgeschlagen.'
      : st.kind === 'stalled'
        ? 'Seit dem letzten Schritt ist nichts mehr passiert — vermutlich ein Neustart mitten in der Verarbeitung.'
        : '';
  return `<button type="button" class="mvp-tile${open}" data-kind="${st.kind}" data-event-id="${id}"
      aria-expanded="${open ? 'true' : 'false'}"
      onclick="event.stopPropagation();window._toggleProcTile(this)">
      <span class="mvp-mark">${mark}</span>
      <span class="mvp-label">${esc(st.label)}${st.elapsed ? ` · ${esc(st.elapsed)}` : ''}</span>
      <span class="mvp-detail">
        <ol class="mvp-chain">${_chainHTML(st)}</ol>
        ${note ? `<span class="mvp-note">${note}</span>` : ''}
      </span>
    </button>
    ${badgeHTML}`;
}

/** Tap handler for the tile. Bridged onto window by index/orchestration. */
export function toggleProcTile(el) {
  if (!el) return;
  const id = el.dataset.eventId;
  const nowOpen = !el.classList.contains('is-open');
  el.classList.toggle('is-open', nowOpen);
  el.setAttribute('aria-expanded', nowOpen ? 'true' : 'false');
  if (!id) return;
  if (nowOpen) _openTiles.add(id);
  else _openTiles.delete(id);
}

// ── queue strip ─────────────────────────────────────────────────────────────
let _queueOpen = false;

const _CHEV = `<svg class="mvq-chev" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4,6.5 8,10.5 12,6.5"/></svg>`;

function _rowHTML(item) {
  const st = procStateOf(item);
  return `<li class="mvq-row" data-kind="${st.kind}">
    <span class="mvq-dot"></span>
    <span class="mvq-cam">${esc(item.camera_name || item.camera_id || '')}</span>
    <span class="mvq-stage">${esc(st.label)}</span>
    <span class="mvq-age">${esc(st.elapsed)}</span>
  </li>`;
}

/** `"2 Videos werden verarbeitet"` — the one line the user asked for. */
export function queueTitle(busy, stuck) {
  if (busy && stuck) return `${busy + stuck} Videos in Arbeit`;
  if (stuck) return stuck === 1 ? '1 Video hängt' : `${stuck} Videos hängen`;
  return busy === 1 ? '1 Video wird verarbeitet' : `${busy} Videos werden verarbeitet`;
}

export function processingQueueHTML(pending) {
  if (!pending.length) return '';
  const stuck = pending.filter((i) => procStateOf(i).kind !== 'busy').length;
  const busy = pending.length - stuck;
  const open = _queueOpen ? ' is-open' : '';
  return `<div class="mvq${open}">
    <button type="button" class="mvq-head" aria-expanded="${_queueOpen ? 'true' : 'false'}"
        aria-controls="mediaProcessingList" onclick="window._toggleProcQueue()">
      ${busy ? _SPIN : _WARN}
      <span class="mvq-title">${esc(queueTitle(busy, stuck))}</span>
      ${_CHEV}
    </button>
    <ul class="mvq-list" id="mediaProcessingList">${pending.map(_rowHTML).join('')}</ul>
  </div>`;
}

/**
 * Paint the strip above the grid. The host node is created on demand —
 * the Mediathek partial has no slot for it and the drilldown markup is
 * not this module's to edit.
 */
export function renderProcessingQueue(items) {
  const grid = byId('mediaGrid');
  if (!grid || !grid.parentNode) return;
  let host = byId('mediaProcessingQueue');
  if (!host) {
    host = document.createElement('div');
    host.id = 'mediaProcessingQueue';
    grid.parentNode.insertBefore(host, grid);
  }
  const pending = (items || []).filter(isPendingItem);
  host.innerHTML = processingQueueHTML(pending);
}

export function toggleProcQueue() {
  _queueOpen = !_queueOpen;
  const box = byId('mediaProcessingQueue')?.querySelector('.mvq');
  if (!box) return;
  box.classList.toggle('is-open', _queueOpen);
  box.querySelector('.mvq-head')?.setAttribute('aria-expanded', _queueOpen ? 'true' : 'false');
}

window._toggleProcTile = toggleProcTile;
window._toggleProcQueue = toggleProcQueue;
