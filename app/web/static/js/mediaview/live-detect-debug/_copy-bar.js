// SIMU-06b/07 · the copy path. The button itself is rendered by
// _verdict.js (it shares the sticky head with the verdict lines); this
// module owns the snapshot cache, the browser-only fields and the
// iOS-safe clipboard write.
//
// Copying is the primary action of this whole view: the operator
// diagnoses an Unraid box from an iPhone, and pasting a document beats
// typing `docker logs … | grep …` on a phone keyboard every time.
//
// M2 · what gets copied is now the machine-first JSON document
// (routes/_debug_snapshot/_machine.py), not the German prose report.
// The paste has exactly one destination — a code window — so stable keys
// and raw numbers beat sentences, and two runs of the same camera diff
// line by line. The SCREEN is unaffected: the Debug tab renders
// `findings`, which is a separate field of the same response.
//
// The same document is POSTed to the SIMU log so the run survives the
// phone's clipboard. Fire-and-forget, and strictly AFTER the clipboard
// write — the clipboard is the primary path and a failed archive write
// must not cost the operator their paste.

// SIMU-FIX-04d · shared toast element pinned to document.body so it
// renders at the true viewport bottom-center with z-index 9999,
// unaffected by the live-detect modal's containing-block stack.
let _toastEl = null;
export function _ensureToastEl() {
  if (_toastEl) return _toastEl;
  _toastEl = document.createElement('div');
  _toastEl.className = 'mv-ld-toast';
  _toastEl.hidden = true;
  document.body.appendChild(_toastEl);
  return _toastEl;
}

// SIMU-FIX-05c · iOS Safari restricts navigator.clipboard.writeText
// to handlers fired DIRECTLY from a user gesture — `await fetch(...)`
// in between breaks that chain and the write silently fails with
// NotAllowedError. The workaround is to PRE-FETCH the snapshot
// while Debug tab is active and keep a fresh cache; the click
// handler then writes the cached string SYNCHRONOUSLY without any
// async hop between gesture-arrival and clipboard-call. The cache
// is refreshed every 5 s so it can't go stale.
let _docCache = null;
let _findingsCache = null;
let _snapshotCacheTimer = 0;
let _snapshotCacheCamId = null;

// SIMU-07 · the render context captured at wire-time goes stale the
// moment the tick loop advances (holdMs / cycle EMA are plain numbers,
// not live references). The panel re-publishes the current context on
// every tick so the clipboard write reports what is on screen NOW.
let _liveCtx = {};
export function setLiveCtx(ctx) {
  _liveCtx = ctx || {};
}

// The auto-diagnosis, computed server-side and rendered on screen by
// _verdict.js. The SAME list the copied document carries under
// `findings`, so screen and paste can never disagree.
export function currentFindings() {
  return _findingsCache;
}

export function _prefetchSnapshot(ctx) {
  const camId = (ctx.session || {}).camId || '';
  if (!camId) return;
  _snapshotCacheCamId = camId;
  fetch(`/api/cameras/${encodeURIComponent(camId)}/debug-snapshot?format=json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data || _snapshotCacheCamId !== camId) return;
      if (data.doc && typeof data.doc === 'object') _docCache = data.doc;
      if (Array.isArray(data.findings)) _findingsCache = data.findings;
    })
    .catch(() => {
      /* cache stays stale; click-handler falls back to live fetch */
    });
}

export function startSnapshotPrefetch(ctx) {
  _prefetchSnapshot(ctx);
  if (_snapshotCacheTimer) clearInterval(_snapshotCacheTimer);
  _snapshotCacheTimer = setInterval(() => _prefetchSnapshot(ctx), 5000);
}

export function stopSnapshotPrefetch() {
  if (_snapshotCacheTimer) {
    clearInterval(_snapshotCacheTimer);
    _snapshotCacheTimer = 0;
  }
  _docCache = null;
  _findingsCache = null;
  _snapshotCacheCamId = null;
}

// Values only the browser knows. The server emits null for them rather
// than a plausible 0 — the scheduler that owns the next-tick delay and
// the bbox hold time runs here, not there. Returns a NEW document; the
// cached one stays pristine for the next tap.
function _withFrontendState(doc, ctx) {
  const t = ctx.tickState || {};
  const next = Number.isFinite(t.lastDelayMs) ? Math.round(t.lastDelayMs) : null;
  const hold = Number.isFinite(ctx.holdMs) ? Math.round(ctx.holdMs) : null;
  return {
    ...doc,
    tick: { ...(doc.tick || {}), next_ms: next, hold_ms: hold },
    frontend: _buildFrontendState(ctx),
  };
}

// Fire-and-forget archive of the run under storage/logs/simu/. The
// server rebuilds the document from its own state and takes ONLY the
// browser-owned fields from this body, so a stray client can never write
// arbitrary content into the log. Never awaited: the clipboard is the
// primary path and this must not be able to delay or break it.
function _archiveRun(camId, payload) {
  if (!camId) return;
  fetch(`/api/cameras/${encodeURIComponent(camId)}/simu-log`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      frontend: payload.frontend,
      next_ms: payload.tick?.next_ms ?? null,
      hold_ms: payload.tick?.hold_ms ?? null,
    }),
  }).catch((err) => {
    console.warn('[simu-log] Lauf nicht gespeichert:', err && (err.message || err));
  });
}

// SIMU-06c · wire the copy button. Reads the cached snapshot, splices
// in the live frontend-only values, writes to the iOS clipboard
// SYNCHRONOUSLY (inside the gesture), shows confirmation toast.
export function _wireCopyBar(host, ctx) {
  const btn = host.querySelector('[data-action="copy-snapshot"]');
  if (!btn) return;
  setLiveCtx(ctx);
  // SIMU-FIX-04d · the toast lives at document.body level, not
  // inside the copy-bar — so it always renders at the true viewport
  // bottom-center with z-index 9999, never clipped by the modal's
  // own stacking context.
  const toast = _ensureToastEl();
  btn.addEventListener('click', () => {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    btn.classList.add('mv-ld-debug-copy-busy');
    if (!_docCache) {
      _showToast(toast, 'Snapshot lädt … bitte gleich erneut tippen', 'ok', 2200);
      _prefetchSnapshot(_liveCtx);
      btn.dataset.busy = '0';
      btn.classList.remove('mv-ld-debug-copy-busy');
      return;
    }
    const payload = _withFrontendState(_docCache, _liveCtx);
    // Indented so a diff of two runs lines up; JSON.stringify is
    // key-order-stable because the server builds the object literally.
    const text = JSON.stringify(payload, null, 2);
    // SIMU-FIX-05c · invoke clipboard write SYNCHRONOUSLY (no await
    // before writeText). Errors fall through to the textarea +
    // execCommand fallback, also invoked synchronously. Both calls
    // must run inside the original gesture handler for iOS Safari
    // to grant clipboard access.
    let ok = false;
    try {
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(text).then(
          () => {
            _showToast(toast, 'Debug-JSON kopiert · Lauf gespeichert', 'ok', 2000);
          },
          () => {
            _execCopyFallback(text, toast);
          },
        );
        ok = true;
      } else {
        ok = _execCopyFallback(text, toast);
      }
    } catch {
      ok = _execCopyFallback(text, toast);
    }
    if (!ok) {
      _showToast(toast, 'Kopieren fehlgeschlagen — versuche es erneut', 'error', 3000);
    }
    _archiveRun((_liveCtx.session || {}).camId, payload);
    btn.dataset.busy = '0';
    btn.classList.remove('mv-ld-debug-copy-busy');
  });
}

// Fallback for older Safari / iOS WKWebView: spawn a textarea, select,
// execCommand('copy'), then yank it. Works back to iOS 10 but requires a
// same-tick user gesture, which the button click already provides.
export function _execCopyFallback(text, toast) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:fixed;top:-9999px;left:0;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, text.length);
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  if (ok && toast) {
    _showToast(toast, 'Debug-JSON kopiert · Lauf gespeichert', 'ok', 2000);
  }
  return ok;
}

// The bbox pipeline's own coordinate spaces, measured in the DOM. This
// is the block that answers "why is the box in the wrong place" — the
// three frame sizes plus the actual rect the overlay resolved to.
function _overlayGeometry(session, fullData) {
  const fs = session.lastFrameSize || fullData?.frame_size || { w: 0, h: 0 };
  const ovEl = document.getElementById('lightboxLiveOverlay');
  const rect = ovEl ? ovEl.getBoundingClientRect() : null;
  const style = ovEl ? window.getComputedStyle(ovEl) : null;
  const size = (v) => (v ? { w: v.w, h: v.h } : null);
  return {
    bbox_space: session.lastBboxSpace || null,
    source_frame: size(session.lastSourceFrameSize),
    snapshot_frame: size(session.lastSnapshotFrameSize),
    view_box: { w: fs.w || 0, h: fs.h || 0 },
    svg_rect: rect
      ? {
          w: Math.round(rect.width),
          h: Math.round(rect.height),
          x: Math.round(rect.left),
          y: Math.round(rect.top),
        }
      : null,
    svg_z_index: style ? style.zIndex : null,
    svg_display: style ? style.display : null,
  };
}

// Everything a stored preference decides. Each read is guarded: private
// mode throws on the very first getItem and a debug payload must not be
// the thing that breaks.
function _viewState() {
  const read = (store, key, fallback) => {
    try {
      return store.getItem(key);
    } catch {
      return fallback;
    }
  };
  // POLISH-01f · title_collapsed dropped from the snapshot — the
  // title is permanently compact (SIMU-FIX-04c), there's no collapse
  // state to report. Timeline collapse is still a real toggle.
  return {
    active_tab: read(localStorage, 'tam.ld.activetab', null) || 'detections',
    timeline_collapsed: read(localStorage, 'tam.ld.timeline.collapsed', null) === '1',
    debug_compact_mode: read(sessionStorage, 'tam.ld.debug.compact', null) === '1',
  };
}

export function _buildFrontendState(ctx) {
  const session = ctx.session || {};
  return {
    user_agent: navigator.userAgent || null,
    captured_at: new Date().toISOString(),
    viewport: {
      w: window.innerWidth,
      h: window.innerHeight,
      dpr: window.devicePixelRatio,
    },
    overlays: window._mvLdOverlaysSnapshot ? window._mvLdOverlaysSnapshot() : null,
    geometry: _overlayGeometry(session, ctx.fullData),
    view: _viewState(),
  };
}

let _toastTimer = 0;
export function _showToast(el, msg, tone, ms) {
  if (!el) return;
  clearTimeout(_toastTimer);
  el.textContent = msg;
  el.dataset.toastTone = tone || 'ok';
  el.hidden = false;
  // Force reflow so the transition kicks in
  void el.offsetWidth;
  el.classList.add('mv-ld-toast-show');
  _toastTimer = setTimeout(() => {
    el.classList.remove('mv-ld-toast-show');
    setTimeout(() => {
      el.hidden = true;
    }, 200);
  }, ms || 2000);
}
