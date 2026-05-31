// ─── mediaview/live-detect-diag.js ─────────────────────────────────────────
// Legacy in-modal debug-strip — a NO-OP surface (_debugDiagOn() returns false /
// _ensureDiagStrip() returns null, SIMU-FIX-01a), kept as gated stubs so the
// render-path callsites stay clean. Live Debug data now lives in the Debug tab
// (live-detect-debug/). Reads shared state via S.
import { byId, esc } from '../core/dom.js';
import { fittedRect } from '../core/video-fit.js';
import { S } from './live-detect-state.js';

const _DEBUG_LS_KEY = 'tam.livedetect.debug';

// B7 · raw tick-loop state. Owned by the tick lifecycle, read by the
// debug strip. Reset on every openLiveDetect call.

// SIMU-FIX-01a · the legacy mvSimDiagStrip is gone. _debugDiagOn
// returns false so every gated function in this file (the strip
// renderer, _refreshXRow, _updateDiagStrip) becomes a no-op
// without needing to delete every callsite. The Debug tab inside
// zone-detail (SIMU-05a-f) now surfaces the same information in
// a properly-scrolled scrollable panel. localStorage cleanup
// happens once on first call so the legacy key doesn't linger.
export function _debugDiagOn() {
  if (!S.legacyDebugKeysCleaned) {
    S.legacyDebugKeysCleaned = true;
    try {
      localStorage.removeItem(_DEBUG_LS_KEY);
      localStorage.removeItem(_DEBUG_COLLAPSE_KEY);
    } catch {
      /* private-mode / quota — silent */
    }
  }
  return false;
}

export function _setDebugDiag(_on) {
  /* SIMU-FIX-01a · no-op; Debug pill removed. */
}

// SIMU-FIX-01a · legacy collapse-state constant retained only so the
// _debugDiagOn one-shot cleanup can remove the localStorage key by
// name. No reader path remains.
const _DEBUG_COLLAPSE_KEY = 'tam.livedetect.debug.collapsed';

// SIMU-FIX-01a · the legacy strip is gone; this stub stays so the
// surrounding gated callsites (_renderDiagStrip, _updateDiagStrip)
// short-circuit cleanly. Always returns null → no DOM creation.
export function _ensureDiagStrip() {
  return null;
}

// One row per kind. Block layout (NOT flex/inline) so on iPhone
// width each k=v pair sits on its own line; CSS handles font sizes
// (key 10 px, value 11 px) and wrap-free overflow. Mismatch flag
// surfaces an amber border so the user spots it at a glance.
export function _renderDiagStripLine(kind, fields, opts = {}) {
  if (!fields) return '';
  const pairs = Object.entries(fields)
    .map(
      ([k, v]) =>
        `<div class="mv-sim-diag-pair"><span class="mv-sim-diag-k">${esc(k)}</span><span class="mv-sim-diag-eq">=</span><span class="mv-sim-diag-v">${esc(String(v))}</span></div>`,
    )
    .join('');
  const trailing = opts.trailing ? `<div class="mv-sim-diag-tag">${esc(opts.trailing)}</div>` : '';
  const flagAttr = opts.flag ? ` data-flag="${esc(opts.flag)}"` : '';
  return `<div class="mv-sim-diag-row" data-kind="${esc(kind)}"${flagAttr}><div class="mv-sim-diag-kind">${esc(kind)}</div>${pairs}${trailing}</div>`;
}

export function _renderDiagStrip() {
  const strip = _ensureDiagStrip();
  if (!strip) return;
  // B7 · refresh the tick row on every paint so the deltas stay
  // truthful even when the rest of the strip is updating for other
  // reasons. Cheap (date math + computed status flag).
  _refreshTickRow();
  _refreshCadenceRow();
  // B12' · MOUNT row split out from the inline fields so the row can
  // appear at the TOP of the strip even on the success path (muted)
  // — drawing the eye first to "did the mount succeed" before
  // anything else. The _err flag picked from the record promotes
  // the row to red without using the trailing-tag mechanism.
  let mountRow = '';
  if (S.diagState.mount) {
    const m = S.diagState.mount;
    const fields = {
      started_at: m.started_at,
      started_with_camId: m.started_with_camId,
      torn_down_prev: m.torn_down_prev,
      chrome_mounted: m.chrome_mounted,
      first_tick_scheduled: m.first_tick_scheduled,
    };
    if (m.error) fields.error = m.error;
    const opts = m._err ? { flag: 'mount-fail' } : {};
    mountRow = _renderDiagStripLine('mount', fields, opts);
  }
  const rows = [
    mountRow,
    _renderDiagStripLine('tick', S.diagState.tick?.fields, S.diagState.tick?.opts || {}),
    _renderDiagStripLine('cadence', S.diagState.cadence?.fields, S.diagState.cadence?.opts || {}),
    _renderDiagStripLine('bbox', S.diagState.bbox?.fields, S.diagState.bbox?.opts || {}),
    _renderDiagStripLine('trails', S.diagState.trails?.fields, S.diagState.trails?.opts || {}),
    _renderDiagStripLine('zonemask', S.diagState.zonemask?.fields, S.diagState.zonemask?.opts || {}),
    _renderDiagStripLine('media', S.diagState.media?.fields, S.diagState.media?.opts || {}),
  ].filter(Boolean);
  if (S.diagState.posFail) {
    rows.push(_renderDiagStripLine('position-fail', S.diagState.posFail));
  }
  if (S.diagState.paintFail) {
    rows.push(_renderDiagStripLine('paint-fail', S.diagState.paintFail));
  }
  // C56 · the body holds the full multi-row dump; the summary line
  // at the top is the one-glance "TICK <status> · BBOX dets=<n> ·
  // MEDIA <branch> · MOUNT <ok|err>" the user sees when the strip is
  // collapsed. Both are written here so they stay synced on every
  // tick refresh.
  const body = strip.querySelector('.mv-sim-diag-body') || strip;
  body.innerHTML = rows.join('');
  const summaryEl = strip.querySelector('.mv-sim-diag-summary');
  if (summaryEl) summaryEl.textContent = _buildDebugSummary();
}

// C56 · compact summary string for the collapsed header. Order is
// fixed (TICK · BBOX · MEDIA · MOUNT) so a screenshot reader knows
// where to look for the primary signal. Truncation handled by CSS
// (text-overflow: ellipsis).
export function _buildDebugSummary() {
  const parts = [];
  const tickFields = S.diagState.tick?.fields || {};
  const tickFlag = S.diagState.tick?.opts?.flag;
  const tickStatus = tickFlag === 'tick-stuck' ? 'STUCK' : tickFlag === 'tick-warn' ? 'WARN' : 'ok';
  parts.push(`TICK ${tickStatus}`);
  const bboxFields = S.diagState.bbox?.fields || {};
  if ('dets' in bboxFields) parts.push(`BBOX dets=${bboxFields.dets}`);
  const mediaFields = S.diagState.media?.fields || {};
  if ('branch' in mediaFields) parts.push(`MEDIA ${mediaFields.branch}`);
  if (S.diagState.mount) parts.push(`MOUNT ${S.diagState.mount._err ? 'err' : 'ok'}`);
  return parts.join(' · ');
}

export function _updateDiagStrip(kind, fields, opts = {}) {
  if (!_debugDiagOn()) return;
  if (kind === 'position-fail') {
    S.diagState.posFail = fields;
  } else if (kind === 'paint-fail') {
    S.diagState.paintFail = fields;
  } else if (kind in S.diagState) {
    S.diagState[kind] = { fields, opts };
  }
  _renderDiagStrip();
}

// A1 · gather the rich bbox-row fields used by the debug strip.
// Reads SVG geometry + computed style + the mediaEl
// _positionSvgOverImage would pick + fittedRect(). A3 extends this
// with bbox_space / source / snap and the space-mismatch flag.
export function _collectBboxDiagFields(svg, fs) {
  const wrap = byId('lightboxMediaWrap');
  const videoEl = byId('lightboxVideo');
  const imgEl = byId('lightboxImg');
  const usingVideo = videoEl && videoEl.style.display !== 'none' && videoEl.videoWidth > 0;
  const mediaEl = usingVideo ? videoEl : imgEl && imgEl.style.display !== 'none' ? imgEl : null;
  const mediaTag = mediaEl ? (mediaEl === videoEl ? 'video' : 'img') : 'null';
  const wrapBox = wrap?.getBoundingClientRect();
  const svgRect = svg.getBoundingClientRect();
  const cs = window.getComputedStyle(svg);
  let mediaDims = 'n/a';
  let fitDims = 'n/a';
  if (mediaEl) {
    const nW = mediaEl.naturalWidth || 0;
    const nH = mediaEl.naturalHeight || 0;
    const vW = mediaEl.videoWidth || 0;
    const vH = mediaEl.videoHeight || 0;
    const cW = mediaEl.clientWidth || 0;
    const cH = mediaEl.clientHeight || 0;
    mediaDims = `nat=${nW}×${nH} vid=${vW}×${vH} cli=${cW}×${cH}`;
    try {
      const fit = fittedRect(mediaEl);
      fitDims = `${Math.round(fit.w)}×${Math.round(fit.h)}@${Math.round(fit.x)},${Math.round(fit.y)}`;
    } catch {
      fitDims = 'err';
    }
  }
  const source = S.session?.lastSourceFrameSize;
  const snap = S.session?.lastSnapshotFrameSize;
  const bboxSpace = S.session?.lastBboxSpace || '?';
  // A3 · viewBox is set from S.session.lastFrameSize, which equals
  // the top-level data.frame_size — the backend's stated bbox-space
  // size. bbox_space says which space the bbox tuples actually use.
  // The two should match: "source" ↔ source == frame_size,
  // "snapshot" ↔ snap == frame_size. If they don't, the response is
  // internally inconsistent — flag SPACE MISMATCH so the user sees
  // it instead of staring at invisible boxes.
  let mismatch = false;
  if (bboxSpace === 'source' && source && (source.w !== fs.w || source.h !== fs.h)) {
    mismatch = true;
  } else if (bboxSpace === 'snapshot' && snap && (snap.w !== fs.w || snap.h !== fs.h)) {
    mismatch = true;
  }
  const fields = {
    dets: (S.session.lastDetections || []).length,
    raw: S.session.lastRawCount ?? '?',
    bbox_space: bboxSpace,
    source: source ? `${source.w}×${source.h}` : 'n/a',
    snap: snap ? `${snap.w}×${snap.h}` : 'n/a',
    viewBox: `${fs.w}×${fs.h}`,
    svgRect: `${Math.round(svgRect.width)}×${Math.round(svgRect.height)}@${Math.round(svgRect.left - (wrapBox?.left || 0))},${Math.round(svgRect.top - (wrapBox?.top || 0))}`,
    zIndex: cs.zIndex,
    display: cs.display,
    bboxesOn: S.overlays.bboxes ? 'true' : 'false',
    media: mediaTag,
    mediaDims,
    fit: fitDims,
  };
  const opts = mismatch ? { flag: 'space-mismatch', trailing: 'SPACE MISMATCH' } : {};
  return { fields, opts };
}

// B7 · paint the tick lifecycle row from the raw S.tickState numbers.
// Always runs (no-ops when debug strip is OFF). The row carries the
// single primary signal: STUCK in red means the loop is wedged. The
// values themselves let the user tell apart "never started" (Infinity
// since last tick) from "started but request hangs" (lastTickAt
// recent but no lastRespAt) from "ticking but each tick errors"
// (lastTickAt+lastRespAt both recent, lastStatus 503/neterr).
export function _refreshTickRow() {
  if (!_debugDiagOn()) return;
  const now = Date.now();
  const sessionOn = !!S.session;
  // B7' · field names match the new spec exactly so the iPhone
  // screenshot can be diffed against the prompt without translating:
  //   sinceTick  → last_tick_started_ms_ago
  //   sinceResp  → last_resp_ok_ms_ago (only set on ok=true responses)
  //   mountedAt  → mounted_ms_ago      (drives the "never-resp + age"
  //                                     STUCK trigger below)
  const sinceTick = S.tickState.lastTickAt ? now - S.tickState.lastTickAt : Infinity;
  const sinceResp = S.tickState.lastRespAt ? now - S.tickState.lastRespAt : Infinity;
  const sinceMount = S.tickState.startedAt ? now - S.tickState.startedAt : Infinity;
  const nextIn = S.tickState.nextTickAt ? Math.max(0, S.tickState.nextTickAt - now) : null;
  const abortPending = !!(
    S.session &&
    S.session.abort &&
    S.session.abort.signal &&
    !S.session.abort.signal.aborted
  );
  // STUCK rules (B7'):
  //   red  · session=="mounted" AND (
  //             last_tick_started_ms_ago > 15000
  //           OR last_resp_ok_ms_ago === Infinity AND mounted_ms_ago > 8000
  //         )
  //   amber· session=="mounted" AND last_tick_started_ms_ago > 5000
  // The "Infinity + 8 s mount age" rule catches Session 1's pattern:
  // chrome mounted, tick fires repeatedly, but no ok response ever
  // — by 8 s after openLiveDetect we know that's the real fail mode.
  let flag = null;
  let trailing = '';
  if (sessionOn) {
    const neverResp = !Number.isFinite(sinceResp);
    if (sinceTick > 15_000 || (neverResp && sinceMount > 8_000)) {
      flag = 'tick-stuck';
      trailing = 'STUCK';
    } else if (sinceTick > 5_000) {
      flag = 'tick-warn';
    }
  }
  const fmtMs = (v) => (Number.isFinite(v) ? String(Math.round(v)) : '∞');
  const fields = {
    session: sessionOn ? 'mounted' : 'idle',
    camId: S.tickState.startedWithCamId || '—',
    last_tick_started_ms_ago: fmtMs(sinceTick),
    last_resp_ok_ms_ago: fmtMs(sinceResp),
    last_status: String(S.tickState.lastStatus ?? '—'),
    next_in_ms: nextIn == null ? '—' : String(nextIn),
    camId_match: sessionOn && S.session.camId === S.tickState.startedWithCamId ? 'true' : 'false',
    abort_pending: abortPending ? 'true' : 'false',
    mounted_ms_ago: fmtMs(sinceMount),
  };
  // B31' · counter + reason for the most recent silent drop. Both
  // hidden when N=0 so the healthy case stays clean.
  if ((S.tickState.ticksDroppedLate || 0) > 0) {
    fields.dropped = String(S.tickState.ticksDroppedLate);
    if (S.tickState.lastDropReason) fields.drop_reason = S.tickState.lastDropReason;
  }
  const opts = flag ? { flag, trailing } : {};
  S.diagState.tick = { fields, opts };
}

// C73 · paint the CADENCE row from S.tickState's last-scheduled
// snapshot + the running EMA. Compact one-row dump (floor / cycle /
// next / mode / hold) — keeps the strip readable on iPhone width.
// Called from _scheduleNext and from _renderDiagStrip so the row
// stays current even when the loop is wedged.
export function _refreshCadenceRow() {
  if (!_debugDiagOn()) return;
  const src = S.session?.lastFrameSrc || 'unknown';
  const mode = src === 'sub' ? 'sub-fast' : src === 'main_fallback' ? 'main-slow' : 'unknown';
  const floor = S.tickState.lastFloorMs;
  const cycle = S.tickState.lastCycleMs;
  const delay = S.tickState.lastDelayMs;
  const fields = {
    mode,
    floor_ms: Number.isFinite(floor) ? String(Math.round(floor)) : '—',
    last_cycle_ms: Number.isFinite(cycle) ? String(Math.round(cycle)) : '—',
    next_in_ms: Number.isFinite(delay) ? String(Math.round(delay)) : '—',
    hold_ms: Number.isFinite(S.holdMsActive) ? String(Math.round(S.holdMsActive)) : '—',
    avg_cycle_ms: Number.isFinite(S.cycleEmaMs) ? String(Math.round(S.cycleEmaMs)) : '—',
  };
  S.diagState.cadence = { fields, opts: {} };
}

// Pull current wrap/img/video geometry into the "media" row. Called
// from each overlay render path so the row stays in sync with the
// other three. Cheap (three getBoundingClientRect calls).
export function _refreshMediaRow() {
  if (!_debugDiagOn()) return;
  const wrap = byId('lightboxMediaWrap');
  const imgEl = byId('lightboxImg');
  const videoEl = byId('lightboxVideo');
  const _box = (el) => {
    if (!el) return 'n/a';
    const r = el.getBoundingClientRect();
    return `${Math.round(r.width)}×${Math.round(r.height)}@${Math.round(r.left)},${Math.round(r.top)}`;
  };
  // B19 · include the branch _positionSvgOverImage last took so a
  // screenshot tells us instantly whether the SVG was sized off the
  // img-rect, video-rect, or one of the wrap fallbacks. videoReady
  // surfaces the readyState gate the new validity check uses; B19'
  // adds video_rejected / img_rejected as the explicit "why" string
  // for the screenshot reader.
  const videoReady = videoEl
    ? `rs=${videoEl.readyState || 0} vW=${videoEl.videoWidth || 0}`
    : 'n/a';
  const fields = {
    wrap: _box(wrap),
    img: imgEl ? `${_box(imgEl)} disp=${window.getComputedStyle(imgEl).display}` : 'n/a',
    video: videoEl ? `${_box(videoEl)} disp=${window.getComputedStyle(videoEl).display}` : 'n/a',
    videoReady,
    branch: S.lastMediaBranch || '—',
  };
  if (S.lastVideoRejected) fields.video_rejected = S.lastVideoRejected;
  if (S.lastImgRejected) fields.img_rejected = S.lastImgRejected;
  S.diagState.media = { fields, opts: {} };
}
