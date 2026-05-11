// ─── mediaview/live-detect.js ──────────────────────────────────────────────
// Live-detect mount for the MediaView shell — reuses the recorded
// lightboxModal chrome (lb-fs-video class, top bar, action buttons)
// but swaps the data path: an <img> shows test-detection snapshots
// at ≥1 Hz, an SVG overlay paints bboxes scaled into the snapshot's
// coord space, the Detections panel lists the per-class verdicts,
// and the fine-analysis fold ticks each response's decision trace
// (open by default in live mode so the user sees inference happen).
//
// Polling pattern + adaptive cadence mirror camedit/erk-sim/live.js
// per the cm-52 follow-up prompt; this module does NOT call into the
// erk-sim machinery (the prompt's "keep mediaview self-contained"
// rule). The escape-valve in that prompt also permits shipping
// bbox + detail-pill + fine-analysis-fold without the scrolling
// swimlane — those rows are a focused follow-up and stay out of
// scope here.
//
// Lifecycle:
//   openLiveDetect({camId, cameraName})  — mount + start polling.
//   closeLiveDetect()                    — abort in-flight + stop.
// closeLightbox() in lightbox.js fires closeLiveDetect via the
// window bridge below so any modal-close path tears the session
// down without leaks.
import { byId, esc } from '../core/dom.js';
import { OBJ_LABEL, colors } from '../core/icons.js';
import { renderFineAnalysisFold } from './fine-analysis-fold.js';
import { renderPanelTabs } from './panel-tabs.js';

// Adaptive cadence — fast healthy ticks stay at 1 Hz; a backend
// taking ~3 s to deliver a validated frame backs us off to 0.25 Hz
// so requests don't pile up.
const _TICK_MIN_MS = 1000;
const _TICK_MAX_MS = 4000;
const _TICK_FACTOR = 1.2;
// Hard cap on trace lines kept in memory — older lines scroll off
// the top of the fold body. 80 lines × ~8-12 lines per tick gives
// ~7-10 seconds of context at 1 Hz, plenty for a debug pass.
const _TRACE_CAP = 80;

let _session = null;
let _traceLines = [];

export function openLiveDetect({ camId, cameraName }){
  if (!camId) return;
  // Defensive: tear down any prior session before opening a new one
  // (user clicked SIM twice rapidly, or jumped between tiles).
  closeLiveDetect();
  _setupLiveChrome(camId, cameraName);
  _session = {
    camId,
    abort: null,
    tickHandle: null,
    fold: null,
  };
  _traceLines = [];
  _mountPanels();
  _tick();
  document.body.style.overflow = 'hidden';
}

export function closeLiveDetect(){
  const session = _session;
  _session = null;
  _traceLines = [];
  if (!session) return;
  try { session.abort?.abort(); } catch { /* ignore */ }
  if (session.tickHandle) clearTimeout(session.tickHandle);
  // Remove the live-detect chrome markers and the SVG overlay so the
  // next lightbox open starts from a clean state. Modal hide is the
  // job of closeLightbox / the close button — don't fight with it.
  const modal = byId('lightboxModal');
  if (modal) modal.classList.remove('lb-live-detect');
  const overlay = byId('lightboxLiveOverlay');
  if (overlay) overlay.remove();
}

function _setupLiveChrome(camId, cameraName){
  const modal = byId('lightboxModal');
  if (!modal) return;
  modal.classList.add('lb-fs-video');
  modal.classList.add('lb-live-detect');
  // Top bar — cam name + a "● Live" marker in place of the recorded
  // timestamp slot. The same #lightboxTopBar element the recorded
  // path uses, so the modal's existing layout applies.
  const camEl = byId('lightboxTopCam');
  const tsEl = byId('lightboxTopTime');
  if (camEl) camEl.textContent = cameraName || camId;
  if (tsEl) tsEl.textContent = '● Live';
  const topBar = byId('lightboxTopBar');
  if (topBar) topBar.hidden = false;
  // Show the <img>, hide the <video>. The polling tick writes the
  // first snapshot data-URL into src on the first response.
  const imgEl = byId('lightboxImg');
  const videoEl = byId('lightboxVideo');
  if (videoEl){
    videoEl.pause();
    videoEl.src = '';
    videoEl.style.display = 'none';
  }
  if (imgEl){
    imgEl.style.display = 'block';
    imgEl.src = '';
  }
  // Confirm / Delete don't make sense for a live snapshot — hide
  // them. closeLightbox restores display when the next recorded
  // event opens via _lbResetToPhoto.
  const confirmBtn = byId('lightboxConfirm');
  if (confirmBtn) confirmBtn.style.display = 'none';
  const delBtn = byId('lightboxDelete');
  if (delBtn) delBtn.style.display = 'none';
  modal.classList.remove('hidden');
  _ensureOverlay();
}

function _ensureOverlay(){
  let svg = byId('lightboxLiveOverlay');
  if (svg) return svg;
  const wrap = byId('lightboxMediaWrap');
  if (!wrap) return null;
  svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'lightboxLiveOverlay';
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:5';
  wrap.appendChild(svg);
  return svg;
}

function _mountPanels(){
  const host = byId('lightboxSettings');
  if (!host) return;
  host.hidden = false;
  host.innerHTML = `
    <div class="mv-recorded-panels">
      <div class="mv-recorded-tabs"></div>
      <div class="mv-recorded-fafold"></div>
    </div>`;
  const tabsHost = host.querySelector('.mv-recorded-tabs');
  const faHost = host.querySelector('.mv-recorded-fafold');
  // Live-detect tab strip — just "Detections" today. Aufnahme-Settings
  // is suppressed (no recording_settings exists for a live frame),
  // Wetter is suppressed (no api_snapshot rides along), Nach-Erkennung
  // is suppressed (the worker indexes archived clips, not live).
  const tabs = [{
    id: 'detections',
    label: 'Detections',
    render: (h) => {
      h.innerHTML = `<div id="mvLdDetections" class="mv-ld-detections"><div class="mv-ld-empty">Noch keine Detektion …</div></div>`;
    },
  }];
  renderPanelTabs(tabsHost, tabs, { initialId: 'detections' });
  // Fine-analysis fold OPEN by default in live mode so the trace
  // ticks visibly. The user can still close it; the choice persists
  // (the new '0' explicit-closed sentinel in fine-analysis-fold.js).
  const fold = renderFineAnalysisFold(faHost, null, { defaultOpen: true });
  if (_session) _session.fold = fold;
}

async function _tick(){
  const session = _session;
  if (!session) return;
  try { session.abort?.abort(); } catch { /* ignore */ }
  session.abort = new AbortController();
  const controller = session.abort;
  const cycleStart = performance.now();
  try {
    const r = await fetch(
      `/api/cameras/${encodeURIComponent(session.camId)}/test-detection`,
      { method: 'POST', signal: controller.signal },
    );
    if (_session !== session) return;
    let data = null;
    try { data = await r.json(); } catch { /* keep null */ }
    if (data?.ok) _renderFrame(data);
  } catch (err) {
    if (err?.name === 'AbortError') return;
    // Transient network errors stay silent — the absence of fresh
    // boxes is the user's signal that something's off.
  }
  _scheduleNext(session, performance.now() - cycleStart);
}

function _scheduleNext(session, lastCycleMs){
  if (_session !== session) return;
  const projected = Math.round(
    (Number.isFinite(lastCycleMs) ? lastCycleMs : _TICK_MIN_MS) * _TICK_FACTOR,
  );
  const delay = Math.min(_TICK_MAX_MS, Math.max(_TICK_MIN_MS, projected));
  session.tickHandle = setTimeout(_tick, delay);
}

function _renderFrame(data){
  // Snapshot — base64 data-URL the backend already downscaled to
  // 960 px wide so iOS Safari paints incrementally without choking.
  const imgEl = byId('lightboxImg');
  if (imgEl && data.snapshot) imgEl.src = data.snapshot;
  // SVG bboxes — viewBox lives in the snapshot's coord space so
  // the overlay scales with the wrap regardless of resolution.
  const svg = _ensureOverlay();
  if (svg && data.frame_size){
    const { w, h } = data.frame_size;
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.innerHTML = (data.detections || []).map(d => {
      const c = colors[d.label] || colors.unknown;
      const op = d.verdict === 'pass' ? 1
               : d.verdict === 'belowthresh' ? 0.55
               : 0.30;
      const [x, y, bw, bh] = d.bbox;
      const txt = `${OBJ_LABEL[d.label] || d.label} · ${Math.round((d.score || 0) * 100)} %`;
      return `<g opacity="${op}">
        <rect x="${x}" y="${y}" width="${bw}" height="${bh}" fill="none" stroke="${c}" stroke-width="3" vector-effect="non-scaling-stroke"/>
        <text x="${x + 4}" y="${y + 20}" fill="${c}" font-size="14" font-family="system-ui, sans-serif" font-weight="700" paint-order="stroke" stroke="rgba(0,0,0,0.7)" stroke-width="3">${esc(txt)}</text>
      </g>`;
    }).join('');
  }
  // Detections panel — current per-class verdicts.
  const detHost = byId('mvLdDetections');
  if (detHost){
    const dets = data.detections || [];
    if (!dets.length){
      detHost.innerHTML = `<div class="mv-ld-empty">Keine Objekte erkannt</div>`;
    } else {
      detHost.innerHTML = dets.map(d => {
        const c = colors[d.label] || colors.unknown;
        const lblText = OBJ_LABEL[d.label] || d.label;
        const tone = d.verdict === 'pass' ? 'ok'
                   : d.verdict === 'belowthresh' ? 'warn'
                   : 'mute';
        const verdictText = d.verdict === 'pass' ? 'PASS'
                          : d.verdict === 'belowthresh' ? 'unter Schwelle'
                          : d.verdict === 'filtered' ? 'gefiltert'
                          : '—';
        return `<div class="mv-ld-row" data-tone="${tone}">
          <span class="mv-ld-row-bar" style="background:${c}"></span>
          <span class="mv-ld-row-label">${esc(lblText)}</span>
          <span class="mv-ld-row-score">${Math.round((d.score || 0) * 100)} %</span>
          <span class="mv-ld-row-verdict">${esc(verdictText)}</span>
        </div>`;
      }).join('');
    }
  }
  // Trace lines — append + cap. Auto-scroll respects user intent:
  // we only auto-scroll when the body was already at the bottom
  // before this tick, so a user scrolled up to read older lines
  // doesn't get yanked back. Classic log-viewer pattern.
  if (Array.isArray(data.decision_trace) && _session?.fold){
    for (const line of data.decision_trace){
      _traceLines.push({ kind: _classifyTrace(line), text: line });
    }
    while (_traceLines.length > _TRACE_CAP) _traceLines.shift();
    const body = document.querySelector('#lightboxSettings .mv-fafold-body');
    const wasAtBottom = body
      ? (body.scrollHeight - body.scrollTop - body.clientHeight) < 24
      : true;
    _session.fold.setLines(_traceLines);
    if (body && wasAtBottom){
      body.scrollTop = body.scrollHeight;
    }
  }
}

function _classifyTrace(line){
  if (!line) return 'info';
  if (line.indexOf(' PASS') !== -1) return 'pass';
  if (line.indexOf(' REJECTED') !== -1 || line.indexOf(' FILTERED') !== -1) return 'reject';
  if (line.indexOf('no detection survived') !== -1) return 'no-detection';
  return 'info';
}

window.closeLiveDetect = closeLiveDetect;
