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
// There is no fabricated percentage anywhere. ffmpeg could emit one, but
// only by rewriting the per-camera event JSON at ~1 Hz per clip for a
// job that usually finishes in seconds. Elapsed-in-stage is free and
// true — and since `_encode_queue.py` started admitting only
// `ENCODE_SLOTS` re-encodes at a time, `queued` genuinely IS a FIFO
// position, so `/api/media/queue-status` (the encoder's own in-memory
// state, not a derived guess) can name it and an ETA built from the
// last few REAL encode durations. A clip the live queue still owns gets
// that honest "Platz X von Y" instead of the scarier "hängt" — the two
// mean different things: one is waiting its turn, the other has no
// thread left working on it at all.
import { byId, esc } from '../core/dom.js';

// ── the global encode queue, polled independently of the per-camera list ──
// A clip queued behind another camera's burst never shows up in THIS
// camera's `stage_stalled` reasoning, so this is a separate fetch
// against the one place that knows the real, cross-camera FIFO.
let _globalQueue = null; // last /api/media/queue-status body, or null
let _queuePoll = null;
let _lastPending = []; // what the strip last painted, for the poll's own repaint

function _repaintQueueStrip() {
  const host = byId('mediaProcessingQueue');
  if (host) host.innerHTML = processingQueueHTML(_lastPending);
}

async function _refreshGlobalQueue() {
  try {
    const res = await fetch('/api/media/queue-status');
    if (res.ok) {
      _globalQueue = await res.json();
      _repaintQueueStrip();
    }
  } catch (_) {
    // Stale data beats none — keep whatever the last successful poll had.
  }
}

function _globalQueueInfo(eventId) {
  if (!eventId || !_globalQueue) return null;
  const row = _globalQueue.queued.find((q) => q.event_id === eventId);
  if (!row) return null;
  return { position: row.position, total: _globalQueue.queued.length, etaS: row.eta_s };
}

/** Start polling the global queue while the strip has something to show;
 * stop the moment it empties out, so an idle Mediathek tab costs nothing.
 * Separate from `_ensureProcessingPoll` in `_paging.js`, which only
 * reloads the FULL per-camera item list and stops for a stalled-only
 * page — this one has to keep running exactly then, or the operator
 * never sees a queue drain. */
function _ensureQueueStatusPoll(hasPending) {
  if (hasPending && !_queuePoll) {
    _refreshGlobalQueue();
    _queuePoll = setInterval(_refreshGlobalQueue, 5000);
  } else if (!hasPending && _queuePoll) {
    clearInterval(_queuePoll);
    _queuePoll = null;
    _globalQueue = null;
  }
}

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
 * Is this item worth polling for?
 *
 * A stalled clip is still "pending" — it keeps its tile and its row in
 * the strip — but nothing is going to advance it, so refreshing every
 * three seconds only buys a full event-tree rglob per camera, forever.
 * One abandoned stub used to be enough to keep that running for the
 * lifetime of the tab.
 */
export function isActivelyPending(item) {
  return isPendingItem(item) && !item.stage_stalled;
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
 * `kind` is what the UI branches on: busy | waiting | stalled | failed.
 *
 * `waiting` is `stalled` with an alibi: the live encode queue (fetched
 * separately, see `_globalQueueInfo`) still owns this event_id, so it is
 * not abandoned — it is third in a real line. That distinction is the
 * whole reason `stage_stalled` alone must not drive the icon: it fires
 * the moment `queued` outlasts its 2-minute ceiling, which a busy
 * feeder trips in minutes on a queue that is working exactly as
 * designed.
 */
export function procStateOf(item) {
  const stage = item.stage || item.status || '';
  const failed = item.status === 'error' || stage === 'failed';
  const stalled = !failed && !!item.stage_stalled;
  const age = item.stage_age_s;
  const queueInfo = !failed && stage === 'queued' ? _globalQueueInfo(item.event_id) : null;
  const waiting = stalled && !!queueInfo;
  const kind = failed ? 'failed' : waiting ? 'waiting' : stalled ? 'stalled' : 'busy';
  let label = failed ? 'fehlgeschlagen' : STAGE_LABEL[stage] || 'wird verarbeitet';
  if (waiting) label = `Platz ${queueInfo.position} von ${queueInfo.total}`;
  else if (stalled) label = 'hängt';
  return {
    kind,
    stage,
    step: STAGE_STEP[stage] ?? 1,
    age,
    elapsed: fmtElapsed(age),
    label,
    eta: waiting && queueInfo.etaS != null ? `ca. ${fmtElapsed(queueInfo.etaS)}` : '',
    error: item.encode_error || '',
  };
}

// ── tile ────────────────────────────────────────────────────────────────────
// Static ring, no glyph swap: under prefers-reduced-motion the CSS just
// stops the rotation and the arc stays put, so the tile still reads as
// "in progress" rather than going blank.
const _SPIN = '<span class="mvp-spin" aria-hidden="true"></span>';
const _WARN = `<svg class="mvp-warn" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" aria-hidden="true"><path d="M12 4.5 2.8 20h18.4z"/><path d="M12 10v4.4"/><circle cx="12" cy="17.4" r=".9" fill="currentColor" stroke="none"/></svg>`;
// Clock face — "waiting its honest turn", never the alarming triangle.
const _WAIT = `<svg class="mvp-wait" viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg>`;

function _chainHTML(st) {
  // `waiting` is still moving toward `encoding`, just not there yet — the
  // chain must not read "halted" for a clip a real thread is about to
  // pick up.
  const halted = st.kind === 'stalled' || st.kind === 'failed';
  return CHAIN.map((name, i) => {
    const cls =
      halted && i >= st.step
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
  const mark = st.kind === 'busy' ? _SPIN : st.kind === 'waiting' ? _WAIT : _WARN;
  const note =
    st.kind === 'failed'
      ? st.error
        ? esc(st.error)
        : 'Die Umwandlung ist fehlgeschlagen.'
      : st.kind === 'waiting'
        ? `Ein Umwandlungs-Platz wird frei, sobald die davor fertig sind${st.eta ? ` — ${esc(st.eta)}` : ''}.`
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
  // Remaining time beats elapsed time whenever the queue can honestly
  // say one — "noch 4 min" answers what the operator is actually
  // asking, "seit 4 min" does not.
  const age = st.eta || st.elapsed;
  return `<li class="mvq-row" data-kind="${st.kind}">
    <span class="mvq-dot"></span>
    <span class="mvq-cam">${esc(item.camera_name || item.camera_id || '')}</span>
    <span class="mvq-stage">${esc(st.label)}</span>
    <span class="mvq-age">${esc(age)}</span>
  </li>`;
}

/** `"2 Videos werden verarbeitet"` — the one line the user asked for.
 * `stuck` counts ONLY clips with no live owner at all — a clip the
 * queue confirms it still owns is `waiting`, not `stuck`, no matter how
 * long its wait: it is going to finish, `stuck` is not.
 */
export function queueTitle({ busy = 0, waiting = 0, stuck = 0 } = {}) {
  if (stuck) return stuck === 1 ? '1 Video hängt' : `${stuck} Videos hängen`;
  const active = busy + waiting;
  if (busy && waiting) return `${active} Videos in Arbeit`;
  if (waiting)
    return waiting === 1 ? '1 Video wartet in der Reihe' : `${waiting} Videos warten in der Reihe`;
  return busy === 1 ? '1 Video wird verarbeitet' : `${busy} Videos werden verarbeitet`;
}

export function processingQueueHTML(pending) {
  if (!pending.length) return '';
  const kinds = pending.map((i) => procStateOf(i).kind);
  const counts = {
    busy: kinds.filter((k) => k === 'busy').length,
    waiting: kinds.filter((k) => k === 'waiting').length,
    stuck: kinds.filter((k) => k === 'stalled' || k === 'failed').length,
  };
  const mark = counts.stuck ? _WARN : counts.busy ? _SPIN : _WAIT;
  const open = _queueOpen ? ' is-open' : '';
  return `<div class="mvq${open}">
    <button type="button" class="mvq-head" aria-expanded="${_queueOpen ? 'true' : 'false'}"
        aria-controls="mediaProcessingList" onclick="window._toggleProcQueue()">
      ${mark}
      <span class="mvq-title">${esc(queueTitle(counts))}</span>
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
  _lastPending = pending;
  host.innerHTML = processingQueueHTML(pending);
  _ensureQueueStatusPoll(pending.length > 0);
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
