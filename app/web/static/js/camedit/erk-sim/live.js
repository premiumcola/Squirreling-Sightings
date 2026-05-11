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
import { _renderErkSimError, _renderErkSimResult } from './snapshot.js';
import { IoUTracker } from './tracker.js';
import { LiveTimeline } from './timeline.js';

// Floor/ceiling for the adaptive polling cadence. Fast healthy ticks
// stay at 1 Hz (the floor); a backend that takes ~3 s to deliver a
// validated frame backs us off to 0.25 Hz so requests don't pile up.
// The 1.2× multiplier on the previous cycle gives the loop a bit of
// headroom over the measured rate without latching to a slow value.
const _TICK_MIN_MS = 1000;
const _TICK_MAX_MS = 4000;
const _TICK_FACTOR = 1.2;
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
  const timeline = new LiveTimeline();
  const tlHost = byId('erkSimTimeline');
  if (tlHost){
    tlHost.hidden = false;
    timeline.render(tlHost, Date.now(), Date.now());  // empty-state hello
  }
  _session = {
    btn,
    camId,
    tracker: new IoUTracker(),
    timeline,
    startedAt: Date.now(),
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

  // performance.now is monotonic and immune to wall-clock jumps; we
  // only care about elapsed milliseconds, so it's the right basis for
  // the adaptive cadence below.
  const cycleStart = performance.now();

  try {
    const r = await fetch(
      `/api/cameras/${encodeURIComponent(session.camId)}/test-detection`,
      { method: 'POST', signal: controller.signal },
    );
    if (_session !== session) return;  // superseded by a stop click
    let data = null;
    try { data = await r.json(); } catch { /* keep null */ }
    // Structured 503: backend says it can't honour the freshness
    // contract right now. Surface a precise banner so the user knows
    // we're not faking a real-time picture, and skip the bbox/trail
    // painting entirely — there's no valid frame to draw on.
    if (r.status === 503 && data && data.code){
      _renderErkSimError(data);
      if (wrap) wrap.dataset.everShown = '1';
      _scheduleNext(session, performance.now() - cycleStart);
      return;
    }
    if (!r.ok || !data?.ok){
      // Other transient backend failure — keep polling silently. The
      // user gets visual feedback only via the absence of fresh boxes.
      _scheduleNext(session, performance.now() - cycleStart);
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
    const now_ms = Date.now();
    const confirmed = session.tracker.tick(dets, now_ms);
    const dropped = session.tracker.lastDropped();
    _renderTrails(confirmed, data.frame_size);
    session.timeline.observe(confirmed, dropped, now_ms);
    const tlHost = byId('erkSimTimeline');
    if (tlHost) session.timeline.render(tlHost, now_ms, session.startedAt);
  } catch (e) {
    if (e?.name === 'AbortError') return;
    // network error — keep polling, intentionally silent (a toast on
    // every tick would be noise).
  }
  _scheduleNext(session, performance.now() - cycleStart);
}

function _scheduleNext(session, lastCycleMs){
  if (_session !== session) return;
  // Clamp the next delay to [floor, ceiling]. Slow cycles back off
  // automatically; fast cycles stay at the floor so a healthy stream
  // still polls at 1 Hz.
  const projected = Math.round((Number.isFinite(lastCycleMs) ? lastCycleMs : _TICK_MIN_MS) * _TICK_FACTOR);
  const delay = Math.min(_TICK_MAX_MS, Math.max(_TICK_MIN_MS, projected));
  session.tickHandle = setTimeout(_tick, delay);
}

// Per-track palette — 12 distinct hues so two simultaneous subjects
// always paint distinguishable trails regardless of class. Indexed by
// the IoUTracker's monotonically-increasing track id; ids 13+ wrap
// back to the top, which is fine because the visual collision only
// matters within a single concurrent set (the tracker drops stale
// ids well before the next one of the same modulo arrives).
const _TRAIL_PALETTE = [
  '#facc15', '#fb923c', '#38bdf8', '#f87171', '#a78bfa', '#34d399',
  '#f472b6', '#fbbf24', '#22d3ee', '#fb7185', '#c084fc', '#86efac',
];
function _trailColorForTrack(id){
  const n = Math.max(0, (id | 0) - 1);
  return _TRAIL_PALETTE[n % _TRAIL_PALETTE.length];
}

// Paint per-track polyline trails into the same SVG overlay
// _renderErkSimResult just populated. Insert at the top of the SVG
// so trails sit BEHIND the bboxes (SVG paints in document order).
// Stroke is per-TRACK-id so two simultaneous subjects get visibly
// distinct trails; the verdict drives stroke-opacity (pass=1,
// belowthresh=.5, filtered=.25) so the alarm-vs-noise signal stays
// readable. Both attributes are inline so the existing
// .erk-track-trail CSS no longer fights the per-track colour.
function _renderTrails(tracks, frame_size){
  const ovl = byId('erkSimOverlay');
  if (!ovl || tracks.length === 0) return;
  const fs = frame_size || { w: 1920, h: 1080 };
  const strokeW = Math.max(2, Math.round(fs.w / 720));
  const trails = tracks.map(t => {
    const path = t.path.slice(-_PATH_CAP);
    if (path.length < 2) return '';
    const points = path.map(p => `${p.cx},${p.cy}`).join(' ');
    const c = _trailColorForTrack(t.id);
    const op = t.last_verdict === 'pass' ? 1
             : t.last_verdict === 'belowthresh' ? 0.5
             : t.last_verdict === 'filtered' ? 0.25
             : 0.6;
    return `<polyline class="erk-track-trail" points="${points}" fill="none" stroke="${c}" stroke-opacity="${op}" stroke-width="${strokeW}" vector-effect="non-scaling-stroke" stroke-linecap="round" stroke-linejoin="round"/>`;
  }).join('');
  if (trails) ovl.insertAdjacentHTML('afterbegin', trails);
}
