// ─── weather/pin-toggle.js ──────────────────────────────────────────────────
// Standalone "keep forever" pin toggle for a weather sighting card.
//
// Split out on its own — NOT folded into _feed.js or sightings.js — so it
// can be built and reviewed independently of the unified-grid rewrite
// currently in progress on those two files (chart-zoom + a new manual-event
// kind). Integration is a single import + two call sites in whichever file
// ends up owning the card template:
//
//   import { pinToggleHTML, bindPinToggle } from './pin-toggle.js';
//   …
//   `${cardHtmlSoFar}${pinToggleHTML(s)}</div>`   // inside the card markup
//   …
//   grid.innerHTML = cards.join('');
//   bindPinToggle(grid);                          // after the HTML lands
//
// Backend: POST /api/weather/sightings/<id>/pin {pinned: true|false}
// (routes/weather_pin.py) flips the manifest's "pinned" field, which
// weather_service/_retention.py's nightly sweep reads to skip a sighting
// regardless of age — this button is the only UI for that flag.

import { esc } from '../core/dom.js';
import { apiPost } from '../core/api.js';
import { showToast } from '../core/toast.js';

const _PIN_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 21s-7-5.686-7-11a7 7 0 0 1 14 0c0 5.314-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>`;

function _pinTitle(pinned) {
  return pinned ? 'Dauerhaft behalten (angepinnt)' : 'Dauerhaft behalten';
}

/**
 * HTML for one card's pin/unpin button. Reads `item.pinned` (falsy =
 * unpinned, the sweep-eligible default). Markup + classes match the
 * existing `.mmc-btn` icon-button family (see `.mmc-delete` in
 * weather/sightings.js) so it sits naturally alongside a card's other
 * hover actions with no extra CSS beyond the `.mmc-pin` colour rule.
 *
 * @param {{id?: string, pinned?: boolean}} item
 * @returns {string}
 */
export function pinToggleHTML(item) {
  const pinned = !!item?.pinned;
  const title = _pinTitle(pinned);
  const id = esc(item?.id || '');
  return (
    `<button type="button" class="mmc-btn mmc-pin${pinned ? ' is-pinned' : ''}" ` +
    `data-id="${id}" data-pinned="${pinned}" title="${title}" aria-label="${title}" ` +
    `aria-pressed="${pinned}">${_PIN_ICON}</button>`
  );
}

async function _togglePin(btn) {
  const id = btn.dataset.id;
  if (!id || btn.disabled) return;
  const next = btn.dataset.pinned !== 'true';
  btn.disabled = true;
  try {
    const r = await apiPost(`/api/weather/sightings/${encodeURIComponent(id)}/pin`, {
      pinned: next,
    });
    const pinned = !!r?.pinned;
    btn.dataset.pinned = String(pinned);
    btn.classList.toggle('is-pinned', pinned);
    btn.setAttribute('aria-pressed', String(pinned));
    const title = _pinTitle(pinned);
    btn.title = title;
    btn.setAttribute('aria-label', title);
  } catch (e) {
    showToast('Pin fehlgeschlagen: ' + (e.message || e), 'error');
  } finally {
    btn.disabled = false;
  }
}

/**
 * Wire click handlers for every `.mmc-pin` button inside `container`.
 * Call once right after the card HTML (including `pinToggleHTML`'s
 * output) has landed in the DOM — e.g. straight after
 * `grid.innerHTML = ...`. `stopPropagation` keeps the click off the
 * card's own open-lightbox handler, mirroring how the delete button
 * is wired in weather/sightings.js.
 *
 * @param {ParentNode} container
 */
export function bindPinToggle(container) {
  container?.querySelectorAll?.('.mmc-pin').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      _togglePin(btn);
    });
  });
}
