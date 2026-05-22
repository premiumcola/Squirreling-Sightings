// ─── mediaview/fine-analysis-fold.js ───────────────────────────────────────
// Permanent strip BELOW the panel content. Header: chevron + terminal
// icon + "Fein-Analyse · Trace-Log" + tiny subtitle (capture · coral ·
// verdict · matrix · armed · telegram · schedule · final). Closed by
// default; open state renders the decision-trace lines on a darker
// monospace surface (#050810).
//
// Trace-line classification (caller passes already-classified lines):
//   { kind: 'pass' | 'reject' | 'no-detection' | 'info', text }
//     - pass         → success-green text colour
//     - reject       → warning-amber text colour
//     - no-detection → danger-red text colour
//     - info         → muted text colour
//
// Open/closed state persists under
// localStorage[FINE_FOLD_STORAGE_KEY] so the user's last choice
// survives page reloads.

export const FINE_FOLD_STORAGE_KEY = 'tamspy.mediaview.fineFold';

const _TERM_SVG = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>`;
const _CHEVRON_SVG = `<svg viewBox="0 0 12 12" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4.5l3 3 3-3"/></svg>`;

function _isOpen(defaultOpen) {
  try {
    const raw = localStorage.getItem(FINE_FOLD_STORAGE_KEY);
    // Three-state: '1' = explicitly open, '0' = explicitly closed,
    // null = never touched → fall through to the caller's default
    // (live-detect mode wants it open by default so the trace ticks
    // visibly; recorded mode keeps the historical "closed" default).
    if (raw === '1') return true;
    if (raw === '0') return false;
    return !!defaultOpen;
  } catch {
    return !!defaultOpen;
  }
}

function _saveOpen(open) {
  try {
    // Explicit '0' so a user-closed fold stays closed even when the
    // caller's default would have flipped it open (live-detect mode).
    if (open) localStorage.setItem(FINE_FOLD_STORAGE_KEY, '1');
    else localStorage.setItem(FINE_FOLD_STORAGE_KEY, '0');
  } catch {
    /* quota / private mode — fall through */
  }
}

function _renderLines(lines) {
  if (!Array.isArray(lines) || lines.length === 0) {
    return `<div class="mv-fafold-empty">Kein Server-Trace gespeichert für diese Aufnahme — Trace ist nur im Live-Test verfügbar.</div>`;
  }
  return lines
    .map((line) => {
      const kind = line && line.kind ? line.kind : 'info';
      const text = line && typeof line.text === 'string' ? line.text : String(line || '');
      const esc = text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
      return `<div class="mv-fafold-line" data-kind="${kind}">${esc}</div>`;
    })
    .join('');
}

export function renderFineAnalysisFold(host, lines, opts = {}) {
  if (!host) return null;
  const open0 = _isOpen(opts.defaultOpen);
  host.innerHTML = `
    <div class="mv-fafold-root" data-open="${open0 ? '1' : '0'}">
      <button type="button" class="mv-fafold-header" aria-expanded="${open0 ? 'true' : 'false'}">
        <span class="mv-fafold-chevron" aria-hidden="true">${_CHEVRON_SVG}</span>
        <span class="mv-fafold-icon" aria-hidden="true">${_TERM_SVG}</span>
        <span class="mv-fafold-title">Fein-Analyse · Trace-Log</span>
        <span class="mv-fafold-sub">capture · coral · verdict · matrix · armed · telegram · schedule · final</span>
      </button>
      <div class="mv-fafold-body" ${open0 ? '' : 'hidden'}>${_renderLines(lines)}</div>
    </div>`;
  const root = host.querySelector('.mv-fafold-root');
  const header = host.querySelector('.mv-fafold-header');
  const body = host.querySelector('.mv-fafold-body');
  if (header && body && root) {
    header.addEventListener('click', () => {
      const willOpen = body.hidden;
      body.hidden = !willOpen;
      header.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      root.dataset.open = willOpen ? '1' : '0';
      _saveOpen(willOpen);
    });
  }
  return {
    setLines(newLines) {
      if (body) body.innerHTML = _renderLines(newLines);
    },
  };
}
