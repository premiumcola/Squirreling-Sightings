// ─── vplayer/panels/_debug-log.js ──────────────────────────────────────────
// The 'Debug-Log' fold: the decision trace, plus the two ways to get a
// run off the device — the clipboard hand-off and the server-side
// bundle.
//
// THE CLIPBOARD WRITE IS NOT REIMPLEMENTED HERE. It delegates to
// live-detect-debug/_copy-bar.js by rendering the button that module
// already wires ([data-action="copy-snapshot"]). Two things make that
// non-negotiable:
//
//   · iOS Safari grants clipboard access ONLY inside the original
//     gesture. The existing implementation calls writeText
//     SYNCHRONOUSLY with no await before it, and falls through to a
//     textarea + execCommand path that is also synchronous. A second
//     implementation that awaited anything first would fail on the
//     exact device this app is built for, and would fail silently.
//   · that path also archives the run and prefetches the snapshot, so
//     the first tap has something to copy.
//
// The bundle is a different thing and a different button: it asks the
// SERVER to collect config, status, telemetry, events, tuning and the
// log tail into one redacted ZIP under storage/debug/. Use it when the
// question is about the box rather than about this one frame.

import { esc } from '../../core/dom.js';
import { renderFold } from '../../core/fold.js';
import { _wireCopyBar } from '../../mediaview/live-detect-debug/_copy-bar.js';
import { S } from '../../mediaview/live-detect-state.js';

/** The copy bar's context, read from the SHARED live-detect state.
 *
 * BOTH BUTTONS USED TO DO NOTHING, and this is why: they were wired only
 * when the caller happened to hand in `deps.ctx` and `deps.post`. The
 * recorded entry point passes `{request, onSaved, onError}`; the live and
 * simulation entry points in dashboard.js pass no `deps` at all — so on
 * the one surface this fold actually appears on, `deps.ctx` was
 * undefined, `_wireCopyBar` never ran, and the bundle listener was never
 * attached. Two buttons rendered, neither reachable.
 *
 * A control whose wiring three separate call sites must each remember to
 * pass is a control that will be dead again after the next one is added.
 * So the fold builds its own context instead. The fields are exactly the
 * ones live-detect-tabs.js assembles for the legacy debug tab — same
 * shape, same source, one implementation.
 */
function _copyCtx(frame) {
  return {
    tickState: S.tickState,
    session: S.session,
    holdMs: S.holdMsActive,
    cycleEmaMs: S.cycleEmaMs,
    // The tick payload as the server sent it — `frame.raw` is the
    // untouched body, `frame` itself is _data/_map.js's mapped view.
    fullData: frame?.raw || frame || null,
  };
}

/** Storage key — its own, so this fold's state is independent. */
const FOLD_KEY = 'tamspy.vplayer.fold.debug';

/** Colour per trace-line kind, matching the existing trace fold. */
const _KINDS = new Set(['pass', 'reject', 'no-detection', 'info']);

function _linesHtml(lines) {
  if (!Array.isArray(lines) || !lines.length) {
    return `<div class="vp-pnl-empty">Warte auf ersten Tick …</div>`;
  }
  return lines
    .map((line) => {
      const kind = line && _KINDS.has(line.kind) ? line.kind : 'info';
      const text = line && typeof line.text === 'string' ? line.text : String(line || '');
      return `<div class="vp-pnl-trace-line" data-kind="${kind}">${esc(text)}</div>`;
    })
    .join('');
}

function _barHtml() {
  return (
    `<div class="vp-pnl-debug-bar">` +
    // The id this button carries is what _copy-bar.js binds to. Keep it.
    `<button type="button" class="vp-pnl-btn" data-action="copy-snapshot">` +
    `Übergabe kopieren</button>` +
    `<button type="button" class="vp-pnl-btn" data-action="vp-bundle">` +
    `Debug-Bundle speichern</button></div>`
  );
}

/**
 * Ask the server to collect a bundle, and say what happened on the
 * button itself.
 *
 * Falls back to its own fetch when no `post` helper was handed in. That
 * fallback is the fix, not a nicety: the surface this fold appears on
 * never passed one, so the button's only path was the one it did not
 * have.
 */
async function _requestBundle(btn, post) {
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = 'Bundle wird erstellt …';
  try {
    const res =
      typeof post === 'function'
        ? await post('/api/debug/bundle')
        : await fetch('/api/debug/bundle', { method: 'POST' }).then((r) =>
            r.ok ? r.json().catch(() => ({})) : { ok: false },
          );
    btn.textContent = res && res.ok === false ? 'Fehlgeschlagen' : 'Bundle gespeichert';
  } catch {
    btn.textContent = 'Fehlgeschlagen';
  }
  window.setTimeout(() => {
    btn.textContent = label;
    btn.disabled = false;
  }, 2500);
}

/**
 * Render the Debug-Log fold.
 *
 * @param {HTMLElement} host
 * @param {object} deps  { ctx, post } — ctx is the copy-bar's live
 *   context; post(url) performs the bundle request
 * @returns {{update: (lines: Array) => void, teardown: () => void}|null}
 */
export function renderDebugLog(host, deps = {}) {
  if (!host) return null;
  const fold = renderFold(host, {
    key: FOLD_KEY,
    title: 'Debug-Log',
    defaultOpen: false,
    tier: deps.tier,
    prefix: 'vp-fold',
  });
  if (!fold) return null;

  const paint = (lines, frame) => {
    fold.body.innerHTML = _barHtml() + `<div class="vp-pnl-trace">${_linesHtml(lines)}</div>`;
    // Re-wire after every repaint: the bar is inside the replaced
    // markup, so its listener goes with it. Unconditional now — see
    // _copyCtx for why a `deps.ctx` guard left both buttons dead.
    _wireCopyBar(fold.body, _copyCtx(frame));
    const bundleBtn = fold.body.querySelector('[data-action="vp-bundle"]');
    if (bundleBtn) bundleBtn.addEventListener('click', () => _requestBundle(bundleBtn, deps.post));
  };

  paint([], null);
  return {
    update: (lines, frame) => paint(lines, frame),
    teardown: () => fold.teardown(),
  };
}
