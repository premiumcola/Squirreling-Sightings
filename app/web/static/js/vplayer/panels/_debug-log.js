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

  const paint = (lines) => {
    fold.body.innerHTML = _barHtml() + `<div class="vp-pnl-trace">${_linesHtml(lines)}</div>`;
    // Re-wire after every repaint: the bar is inside the replaced
    // markup, so its listener goes with it.
    if (deps.ctx) _wireCopyBar(fold.body, deps.ctx);
    const bundleBtn = fold.body.querySelector('[data-action="vp-bundle"]');
    if (bundleBtn && typeof deps.post === 'function') {
      bundleBtn.addEventListener('click', async () => {
        bundleBtn.disabled = true;
        const label = bundleBtn.textContent;
        bundleBtn.textContent = 'Bundle wird erstellt …';
        try {
          const res = await deps.post('/api/debug/bundle');
          bundleBtn.textContent = res && res.ok === false ? 'Fehlgeschlagen' : 'Bundle gespeichert';
        } catch {
          bundleBtn.textContent = 'Fehlgeschlagen';
        }
        window.setTimeout(() => {
          bundleBtn.textContent = label;
          bundleBtn.disabled = false;
        }, 2500);
      });
    }
  };

  paint([]);
  return {
    update: (lines) => paint(lines),
    teardown: () => fold.teardown(),
  };
}
