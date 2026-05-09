// ─── camedit/erk-sim/live.js ───────────────────────────────────────────────
// Live-detection toggle. Pressing the simulate button starts a 1 Hz
// polling loop against /api/cameras/<id>/test-detection; pressing
// again stops it and freezes the last-rendered frame in place. A
// client-side IoU tracker (tracker.js) keeps subject identity stable
// across ticks so detected objects get a fading path-trail rather
// than blinking on/off whenever inference timing skews a bbox.
//
// The polling lifecycle self-polices: every tick checks that the
// camera id in the form still matches what the loop was started
// against AND that the result panel is still visible. Either failing
// silently stops the loop — no hard coupling to editCamera() or the
// panel-close handler.
import { byId } from '../../core/dom.js';
import { _renderErkSimResult } from './snapshot.js';
import { IoUTracker } from './tracker.js';

const _TICK_MS  = 1000;   // 1 Hz polling — kept simple, no UI control
const _PATH_CAP = 12;     // points painted per trail; tracker stores up to 60

let _session = null;      // null when idle; one object per active live run

const _IDLE_HTML = `
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <polygon points="5 3 19 12 5 21 5 3"/>
  </svg>
  <span class="erk-test-btn-lbl">Erkennung jetzt simulieren</span>
`;

const _LIVE_HTML = `
  <span class="erk-live-dot" aria-hidden="true"></span>
  <span class="erk-test-btn-lbl">Live-Erkennung läuft · Stop</span>
`;

// Public — wired by erk-sim/index.js as the simulate-button click
// handler. Single function gates start/stop, so the button's text
// + class swap drive a single state machine.
export function _onErkSimulateClick(ev){
  if (_session){
    stopLive();
  } else {
    startLive(ev.currentTarget);
  }
}

// Public — called by the panel-close handler in index.js so dismiss
// stops the loop synchronously, not "next tick".
export function stopLive(){
  if (!_session) return;
  const { btn, abort, tickHandle } = _session;
  try { abort?.abort(); } catch { /* ignore */ }
  if (tickHandle) clearTimeout(tickHandle);
  _session = null;
  if (btn){
    btn.classList.remove('is-live');
    btn.disabled = false;
    btn.innerHTML = _IDLE_HTML;
  }
}

function startLive(btn){
  const camId = byId('cameraForm')?.elements?.['id']?.value;
  if (!camId || !btn) return;
  btn.classList.add('is-live');
  btn.innerHTML = _LIVE_HTML;
  _session = {
    btn,
    camId,
    tracker: new IoUTracker(),
    abort: null,
    tickHandle: null,
  };
  // Kick the first tick immediately so the user sees a frame within
  // a couple hundred ms; subsequent ticks are paced by _scheduleNext.
  _tick();
}

async function _tick(){
  const session = _session;
  if (!session) return;
  // Self-policing invariants — bail when the form swapped to a
  // different camera or the result panel got dismissed.
  const formCamId = byId('cameraForm')?.elements?.['id']?.value;
  const wrap = byId('erkSimResult');
  if (formCamId !== session.camId){ stopLive(); return; }
  if (wrap?.hidden && wrap.dataset.everShown === '1'){ stopLive(); return; }

  try { session.abort?.abort(); } catch { /* ignore */ }
  session.abort = new AbortController();
  const controller = session.abort;

  try {
    const r = await fetch(
      `/api/cameras/${encodeURIComponent(session.camId)}/test-detection`,
      { method: 'POST', signal: controller.signal },
    );
    if (_session !== session) return;  // superseded by a stop click
    let data = null;
    try { data = await r.json(); } catch { /* keep null */ }
    if (!r.ok || !data?.ok){
      // Transient backend failure — keep polling. The user gets visual
      // feedback only via the absence of fresh boxes.
      _scheduleNext(session);
      return;
    }

    _renderErkSimResult(data);
    if (wrap) wrap.dataset.everShown = '1';

    const dets = (data.detections || []).map(d => ({
      label: d.label,
      bbox: d.bbox,
      score: d.score,
      verdict: d.verdict,
    }));
    const confirmed = session.tracker.tick(dets, Date.now());
    _renderTrails(confirmed, data.frame_size);
  } catch (e) {
    if (e?.name === 'AbortError') return;
    // network error — keep polling, intentionally silent (a toast on
    // every tick would be noise).
  }
  _scheduleNext(session);
}

function _scheduleNext(session){
  if (_session !== session) return;
  session.tickHandle = setTimeout(_tick, _TICK_MS);
}

// Paint per-track polyline trails into the same SVG overlay
// _renderErkSimResult just populated. Insert at the top of the SVG
// so trails sit BEHIND the bboxes (SVG paints in document order).
function _renderTrails(tracks, frame_size){
  const ovl = byId('erkSimOverlay');
  if (!ovl || tracks.length === 0) return;
  const fs = frame_size || { w: 1920, h: 1080 };
  const strokeW = Math.max(2, Math.round(fs.w / 720));
  const trails = tracks.map(t => {
    const path = t.path.slice(-_PATH_CAP);
    if (path.length < 2) return '';
    const points = path.map(p => `${p.cx},${p.cy}`).join(' ');
    const cls = `erk-track-trail is-${t.last_verdict || 'pass'}`;
    return `<polyline class="${cls}" points="${points}" fill="none" stroke-width="${strokeW}" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>`;
  }).join('');
  if (trails) ovl.insertAdjacentHTML('afterbegin', trails);
}
