// SIMU-06b · Copy-Debug-Snapshot button. Sticky inside the Debug
// panel so it stays visible as the user scrolls through clusters.
// Cyan-bordered glass, inline copy-icon + label. The whole bar
// (top-right anchored, transparent left half) lets clicks through
// to the underlying panel; only the button itself accepts input.
export function _renderCopyBar() {
  const iconSvg =
    '<svg class="mv-ld-copy-ico" width="14" height="14" viewBox="0 0 24 24" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="9" y="9" width="12" height="12" rx="2" ry="2"/>' +
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
  // SIMU-FIX-04d · the toast lives at document.body level (via
  // _ensureToastEl) so it escapes any layout containment from
  // zone-detail / the modal. Only the copy-button stays in the bar.
  return `
    <div class="mv-ld-debug-copy-bar">
      <button type="button" class="mv-ld-debug-copy" data-action="copy-snapshot">
        <span class="mv-ld-debug-copy-glyph">${iconSvg}</span>
        <span class="mv-ld-debug-copy-lbl">Alle Debug-Infos kopieren</span>
      </button>
    </div>`;
}

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
let _snapshotCache = null;
let _snapshotCacheTimer = 0;
let _snapshotCacheCamId = null;

export function _prefetchSnapshot(ctx) {
  const camId = (ctx.session || {}).camId || '';
  if (!camId) return;
  _snapshotCacheCamId = camId;
  fetch(`/api/cameras/${encodeURIComponent(camId)}/debug-snapshot`)
    .then((r) => (r.ok ? r.text() : null))
    .then((md) => {
      if (md && _snapshotCacheCamId === camId) _snapshotCache = md;
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
  _snapshotCache = null;
  _snapshotCacheCamId = null;
}

// SIMU-06c · wire the copy button. Reads the cached snapshot, splices
// in the live "Frontend State" block, writes to the iOS clipboard
// SYNCHRONOUSLY (inside the gesture), shows confirmation toast.
export function _wireCopyBar(host, ctx) {
  const btn = host.querySelector('[data-action="copy-snapshot"]');
  if (!btn) return;
  // SIMU-FIX-04d · the toast lives at document.body level, not
  // inside the copy-bar — so it always renders at the true viewport
  // bottom-center with z-index 9999, never clipped by the modal's
  // own stacking context.
  const toast = _ensureToastEl();
  btn.addEventListener('click', () => {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    btn.classList.add('mv-ld-debug-copy-busy');
    let md = _snapshotCache;
    if (!md) {
      _showToast(
        toast,
        'Snapshot lädt … bitte gleich erneut tippen',
        'ok',
        2200,
      );
      _prefetchSnapshot(ctx);
      btn.dataset.busy = '0';
      btn.classList.remove('mv-ld-debug-copy-busy');
      return;
    }
    md = md.replace('<<frontend_state_ua>>', navigator.userAgent || '');
    md = md.replace('<<frontend_state>>', _buildFrontendStateBlock(ctx));
    // SIMU-FIX-05c · invoke clipboard write SYNCHRONOUSLY (no await
    // before writeText). Errors fall through to the textarea +
    // execCommand fallback, also invoked synchronously. Both calls
    // must run inside the original gesture handler for iOS Safari
    // to grant clipboard access.
    let ok = false;
    try {
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(md).then(
          () => {
            _showToast(toast, 'Debug-Snapshot kopiert · paste in den Chat', 'ok', 2000);
          },
          () => {
            _execCopyFallback(md, toast);
          },
        );
        ok = true;
      } else {
        ok = _execCopyFallback(md, toast);
      }
    } catch {
      ok = _execCopyFallback(md, toast);
    }
    if (!ok) {
      _showToast(
        toast,
        'Kopieren fehlgeschlagen — versuche es erneut',
        'error',
        3000,
      );
    }
    btn.dataset.busy = '0';
    btn.classList.remove('mv-ld-debug-copy-busy');
  });
}

export function _execCopyFallback(md, toast) {
  const ta = document.createElement('textarea');
  ta.value = md;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position:fixed;top:-9999px;left:0;opacity:0';
  document.body.appendChild(ta);
  ta.select();
  ta.setSelectionRange(0, md.length);
  let ok = false;
  try {
    ok = document.execCommand('copy');
  } catch {
    ok = false;
  }
  document.body.removeChild(ta);
  if (ok && toast) {
    _showToast(toast, 'Debug-Snapshot kopiert · paste in den Chat', 'ok', 2000);
  }
  return ok;
}

export function _buildFrontendStateBlock(ctx) {
  const session = ctx.session || {};
  const fs = session.lastFrameSize || ctx.fullData?.frame_size || { w: 0, h: 0 };
  const bboxSpace = session.lastBboxSpace || '?';
  const sourceFs = session.lastSourceFrameSize || null;
  const snapFs = session.lastSnapshotFrameSize || null;
  const ovEl = document.getElementById('lightboxLiveOverlay');
  const ovRect = ovEl ? ovEl.getBoundingClientRect() : null;
  const ovStyle = ovEl ? window.getComputedStyle(ovEl) : null;
  const overlaysState = window._mvLdOverlaysSnapshot
    ? window._mvLdOverlaysSnapshot()
    : 'unknown';
  const activeTab = (() => {
    try {
      return localStorage.getItem('tam.ld.activetab') || 'detections';
    } catch {
      return '?';
    }
  })();
  // POLISH-01f · title_collapsed dropped from the snapshot — the
  // title is permanently compact (SIMU-FIX-04c), there's no collapse
  // state to report. Timeline collapse is still a real toggle.
  const timelineCollapsed = (() => {
    try {
      return localStorage.getItem('tam.ld.timeline.collapsed') === '1';
    } catch {
      return false;
    }
  })();
  const lines = [
    `bbox_space:          ${bboxSpace}`,
    sourceFs ? `source_frame_size:   ${sourceFs.w}×${sourceFs.h}` : null,
    snapFs ? `snapshot_frame_size: ${snapFs.w}×${snapFs.h}` : null,
    `viewBox:             ${fs.w}×${fs.h}`,
    ovRect
      ? `svgRect:             ${Math.round(ovRect.width)}×${Math.round(ovRect.height)} @ ${Math.round(ovRect.left)},${Math.round(ovRect.top)}`
      : null,
    ovStyle ? `svg.zIndex:          ${ovStyle.zIndex} · display=${ovStyle.display}` : null,
    `overlays:            ${overlaysState}`,
    `active_tab:          ${activeTab}`,
    `timeline_collapsed:  ${timelineCollapsed}`,
    `viewport:            ${window.innerWidth}×${window.innerHeight} dpr=${window.devicePixelRatio}`,
    `timestamp_frontend:  ${new Date().toISOString()}`,
  ].filter(Boolean);
  return '```\n' + lines.join('\n') + '\n```';
}

async function _writeClipboard(text) {
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for older Safari / iOS WKWebView: spawn a textarea,
  // select, execCommand('copy'), then yank it. Works back to iOS 10
  // but requires a same-tick user gesture which the button click
  // already provides.
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
  if (!ok) throw new Error('clipboard write blocked');
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
