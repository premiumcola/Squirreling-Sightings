// ─── netz/_detail_modal.js ─────────────────────────────────────────────────
// THE VERLAUF DETAIL GETS ITS OWN WINDOW.
//
// It used to paint into the Erkennungsnetz card's body, and that body is
// one panel in a column of panels: it has the height the net diagram
// needs, not the height a detail record needs. A record is a frame, a
// verdict, a reason, the whole class ladder as a table and a restore
// button — so the bottom of it was simply cut off, and the verdict
// controls were the part below the cut: „wie soll ich die bewertung hier
// im erkennungsnetz machen, die anzeige ist halb verdeckt! … ich kann
// hier die noch nicht bewerteten dinge nicht nachbewerten da ichs nicht
// komplett sehe!"
//
// Growing the card was the other option and the operator ruled it out
// for the right reason: a panel that changes height when you open
// something inside it pushes every section below it down the page („um
// das layout der hauptseite nicht umskalieren zu müssen, das wäre
// unschön"). A dialog costs the main column nothing.
//
// BUILT IN JS, not in partials/modals.html. The netz package already
// owns its own markup; adding a shell to the global template would put
// half of this feature in a file the other half never mentions. Same
// reasoning — and the same `.modal` / `.modal-card` classes — the
// vplayer shell uses for its own root.
import { renderArchiveDetail } from './_archive_detail.js';

let _open = null;

/** Close whatever detail dialog is up. Safe to call twice. */
export function closeNetzDetail() {
  if (!_open) return;
  const { root, onKey } = _open;
  _open = null;
  document.removeEventListener('keydown', onKey, true);
  root.remove();
}

/**
 * Show one archive record in a dialog over the page.
 *
 * `handlers` is `renderArchiveDetail`'s own contract, with one addition:
 * whatever `back` and `afterRestore` do, the dialog closes first — the
 * record's own „← Verlauf" button is the way out of the dialog, so it
 * must not leave it standing over a panel that has already moved on.
 */
export function openNetzDetail(rec, handlers = {}) {
  closeNetzDetail();
  const root = document.createElement('div');
  root.className = 'modal netz-detail-modal';
  root.setAttribute('role', 'dialog');
  root.setAttribute('aria-modal', 'true');
  root.setAttribute('aria-label', 'Erkennungsnetz — Verlaufseintrag');
  const card = document.createElement('div');
  card.className = 'modal-card panel netz-detail-card';
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'netz-detail-close';
  close.title = 'Schließen';
  close.setAttribute('aria-label', 'Schließen');
  close.innerHTML =
    `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" ` +
    `stroke-width="2.2" stroke-linecap="round" aria-hidden="true">` +
    `<path d="M6 6l12 12M18 6L6 18"/></svg>`;
  const body = document.createElement('div');
  body.className = 'netz-detail-body';
  card.appendChild(close);
  card.appendChild(body);
  root.appendChild(card);
  document.body.appendChild(root);

  const wrap =
    (fn) =>
    (...args) => {
      closeNetzDetail();
      fn?.(...args);
    };
  renderArchiveDetail(body, rec, {
    ...handlers,
    back: wrap(handlers.back),
    afterRestore: wrap(handlers.afterRestore),
  });

  // Capture phase: the panel behind this listens for keys too, and a
  // record open over it must be the one that answers Escape.
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    closeNetzDetail();
  };
  document.addEventListener('keydown', onKey, true);
  close.addEventListener('click', closeNetzDetail);
  // Backdrop only — a click that started inside the card and ended on the
  // backdrop (a text selection dragged out of it) must not close.
  root.addEventListener('click', (e) => {
    if (e.target === root) closeNetzDetail();
  });

  _open = { root, onKey };
  return closeNetzDetail;
}
