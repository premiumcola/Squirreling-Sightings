// ─── live-detect-debug/_verdict.js ────────────────────────────────────────
// SIMU-07 · the two things the Debug tab is FOR, pinned to the top:
//
//   1. the verdict — three plain-language lines saying which gate is shut
//   2. the copy button — the whole point of the view
//
// The long snapshot is deliberately NOT rendered. The operator's own
// words: "den Text les ich ja sowieso nicht alles durch". So the wall of
// monospace lives only in the clipboard, and the screen carries the
// conclusion the server already computed (routes/_debug_snapshot builds
// the same findings into the copied document, so screen and paste never
// disagree).
//
// Compact mode is the second half: on a 375 px phone the video stage +
// legend band + swimlane eat the screen the debug content needs. The
// toggle hides them — a real control, not an automatic hijack, so the
// user can always get the picture back. The choice is remembered for the
// session and re-applied whenever the Debug tab comes back into view.
import { esc } from '../../core/dom.js';

// Session-scoped on purpose: a preference this aggressive (the video is
// gone) should not silently outlive the browser tab.
const _COMPACT_KEY = 'tam.ld.debug.compact';

// Three lines is what fits above the fold on an iPhone SE; the rest is
// summarised as a count and travels in full inside the copied text.
const _VERDICT_VISIBLE = 3;

const _ICON_COPY =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<rect x="9" y="9" width="12" height="12" rx="2" ry="2"/>' +
  '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';

const _ICON_COMPACT =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<polyline points="4 9 12 3 20 9"/><polyline points="4 21 12 15 20 21"/></svg>';

export function isCompact() {
  try {
    return sessionStorage.getItem(_COMPACT_KEY) === '1';
  } catch {
    return false;
  }
}

function _storeCompact(on) {
  try {
    sessionStorage.setItem(_COMPACT_KEY, on ? '1' : '0');
  } catch {
    /* private mode / quota — the toggle still works for this view */
  }
}

// The shell owns the stage / controls / legend band / playbar; one
// attribute on its root is all the CSS needs to fold them away.
function _shellRoot() {
  return document.querySelector('.mv-shell');
}

// Re-applied on every entry into the Debug tab so the remembered choice
// survives tab switches, and cleared on the way out so the picture comes
// back by itself when the user returns to Detections.
export function applyCompact(on) {
  const root = _shellRoot();
  if (!root) return;
  if (on) root.dataset.compact = '1';
  else delete root.dataset.compact;
}

export function syncCompactForDebugTab(active) {
  applyCompact(!!active && isCompact());
}

// Only the rows, so a tick refresh can swap the verdict without
// re-creating (and thereby un-wiring) the buttons above it.
export function _verdictRowsHtml(findings) {
  const list = Array.isArray(findings) ? findings : [];
  const shown = list.slice(0, _VERDICT_VISIBLE);
  const rest = list.length - shown.length;
  const rows = shown.length
    ? shown
        .map(
          (f) =>
            `<li class="mv-ld-verdict-row" data-tone="${esc(String(f.tone || 'info'))}">` +
            `${esc(String(f.text || ''))}</li>`,
        )
        .join('')
    : '<li class="mv-ld-verdict-row" data-tone="mute">Befund wird geladen …</li>';
  const more =
    rest > 0 ? `<li class="mv-ld-verdict-more">+${rest} weitere · im Kopieren-Text</li>` : '';
  return rows + more;
}

export function _refreshVerdict(host, findings) {
  const list = host.querySelector('[data-mv-ld-verdict]');
  if (list) list.innerHTML = _verdictRowsHtml(findings);
}

export function _renderVerdictBar(findings) {
  const compact = isCompact();
  return `
    <div class="mv-ld-debug-head">
      <div class="mv-ld-debug-actions">
        <button type="button" class="mv-ld-debug-copy" data-action="copy-snapshot">
          <span class="mv-ld-debug-copy-glyph">${_ICON_COPY}</span>
          <span class="mv-ld-debug-copy-lbl">Debug kopieren</span>
        </button>
        <button type="button" class="mv-ld-debug-compact" data-action="toggle-compact"
                aria-pressed="${compact ? 'true' : 'false'}">
          <span class="mv-ld-debug-copy-glyph">${_ICON_COMPACT}</span>
          <span class="mv-ld-debug-copy-lbl">${compact ? 'Video zeigen' : 'Video ausblenden'}</span>
        </button>
      </div>
      <ul class="mv-ld-verdict" data-mv-ld-verdict="1">${_verdictRowsHtml(findings)}</ul>
    </div>`;
}

export function _wireVerdictBar(host) {
  const btn = host.querySelector('[data-action="toggle-compact"]');
  if (!btn) return;
  btn.addEventListener('click', () => {
    const next = !isCompact();
    _storeCompact(next);
    applyCompact(next);
    btn.setAttribute('aria-pressed', next ? 'true' : 'false');
    const lbl = btn.querySelector('.mv-ld-debug-copy-lbl');
    if (lbl) lbl.textContent = next ? 'Video zeigen' : 'Video ausblenden';
  });
}
