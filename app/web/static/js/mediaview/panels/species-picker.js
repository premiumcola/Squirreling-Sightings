// ─── mediaview/panels/species-picker.js ────────────────────────────────────
// Event-level bird-species correction — the web analogue of the
// Telegram species picker (app/app/telegram_bot/_outbound/_question.py
// ::species_correction_markup + _inbound_event.py::_cb_species_pick /
// _cb_species_unsure), mirrored exactly by POST …/events/<id>/species
// (see app/app/routes/events.py::api_event_species for the write side).
//
// ONE bird_species PER EVENT, never per detection row — see
// vplayer/panels/_objects-list.js's header for the three incompatible
// numbering schemes a per-row control would have to reconcile, and the
// verdict ledger's event_id-only key. Do not reopen that here.
//
// TWO ENTRY POINTS, ONE SHEET. The species caption this opens from
// lives wherever labels.js renders it (the open player's Labels tab /
// photo lightbox) — but the same correction is also reachable straight
// off a Mediathek tile's own badge, with NO player open at all. So the
// sheet is appended straight to document.body, like
// mediathek/trash-modal.js's modal, never to a caller-supplied host.
// Both callers pass their own cached event object and get back a plain
// `onSaved(res)` — patching whichever caches THEY own is their job;
// mediaview/panels/labels.js::applyLabelSaveResult already does exactly
// that (the player, both grid arrays, the tile's bubble row, the
// timeline/stats) and both entry points reuse it rather than each
// growing a parallel copy — see labels.js and mediathek/_actions.js.
//
// ROW ICONS come from core/species-icon.js (real SVG silhouette, or
// the same 🐦 fallback sichtungen/_achievements.js uses) — see
// _sheetHtml below.
import { esc } from '../../core/dom.js';
import { apiPost } from '../../core/api.js';
import { showToast } from '../../core/toast.js';
import { speciesIconMarkup } from '../../core/species-icon.js';

/**
 * PURE: the picker's rows for one event — mirrors
 * `species_correction_markup` exactly (same rules, same cap). Dedupe by
 * lowercased name, drop the current guess (correcting it to itself is
 * not a correction — that is the bird bubble already being active),
 * cap at 5: a picker longer than the screen is worse than an
 * incomplete one.
 *
 * @param {Array<{name?: string}>} candidates  event.species_candidates
 * @param {string|null|undefined} currentSpecies  event.bird_species
 * @returns {string[]}
 */
export function speciesPickerRows(candidates, currentSpecies) {
  const cur = String(currentSpecies || '')
    .trim()
    .toLowerCase();
  const seen = new Set(cur ? [cur] : []);
  const rows = [];
  for (const cand of candidates || []) {
    const name = String((cand && cand.name) || '').trim();
    const key = name.toLowerCase();
    if (!name || seen.has(key)) continue;
    seen.add(key);
    rows.push(name);
    if (rows.length >= 5) break;
  }
  return rows;
}

/**
 * POST one species correction and, on success, hand the reply to
 * `deps.onSaved` — patching whichever caches the caller owns is left to
 * that callback (see labels.js::applyLabelSaveResult, which both real
 * callers pass through). Exported so the network + patch step is
 * testable without simulating a real DOM click through the sheet;
 * `openSpeciesPicker`'s click handler below calls this exact function.
 *
 * @param {object} item  needs camera_id + event_id
 * @param {string|null} species  a candidate name, or null for "unsicher"
 * @param {object} deps  { onSaved(res) }
 * @returns {Promise<object|null>} the endpoint's reply, or null on failure
 */
export async function submitSpeciesCorrection(item, species, deps = {}) {
  try {
    const res = await apiPost(
      `/api/camera/${encodeURIComponent(item.camera_id)}` +
        `/events/${encodeURIComponent(item.event_id)}/species`,
      { species },
    );
    if (res && res.ok) deps.onSaved?.(res);
    return res;
  } catch (e) {
    showToast('Art-Korrektur fehlgeschlagen: ' + (e?.message || e), 'error');
    return null;
  }
}

function _sheetHtml(rows) {
  const pickRows = rows
    .map(
      (name) =>
        `<button type="button" class="sp-pick-row" data-act="pick" data-species="${esc(name)}">` +
        `<span class="sp-pick-row-icon">${speciesIconMarkup(name)}</span>` +
        `<span class="sp-pick-row-label">${esc(name)}</span></button>`,
    )
    .join('');
  return (
    `<div class="sp-pick-backdrop" data-act="cancel"></div>` +
    `<div class="sp-pick-sheet" role="dialog" aria-modal="true" aria-label="Art korrigieren">` +
    `<div class="sp-pick-title">Welche Art war es wirklich?</div>` +
    `<div class="sp-pick-rows">${pickRows}` +
    `<button type="button" class="sp-pick-row sp-pick-row--unsure" data-act="unsure">` +
    `❓ unsicher, welche genau</button>` +
    `</div>` +
    `<button type="button" class="sp-pick-cancel" data-act="cancel">Abbrechen</button>` +
    `</div>`
  );
}

// Module-level singleton — a second open() call (double-tap, tap on a
// different tile before the first sheet closed) replaces rather than
// stacks. Mirrors trash-modal.js's one-modal-at-a-time contract.
let _openSheet = null;

function _close() {
  if (!_openSheet) return;
  _openSheet.el.removeEventListener('click', _openSheet.onClick);
  _openSheet.el.remove();
  _openSheet = null;
}

/**
 * Open the species-correction sheet for `item`.
 *
 * @param {object} item  a cached event object — needs camera_id,
 *   event_id, and (to render any rows at all) species_candidates +
 *   bird_species.
 * @param {object} deps  { onSaved(res) } — called after a successful
 *   POST with the endpoint's `{ok, bird_species}` reply, so the caller
 *   can patch whichever caches and re-render whichever badge it owns.
 * @returns {{teardown: () => void}|null}
 */
export function openSpeciesPicker(item, deps = {}) {
  if (!item || !item.camera_id || !item.event_id) return null;
  _close();
  const rows = speciesPickerRows(item.species_candidates, item.bird_species);
  const sheet = document.createElement('div');
  sheet.className = 'sp-pick';
  sheet.innerHTML = _sheetHtml(rows);
  document.body.appendChild(sheet);

  const submit = async (species) => {
    await submitSpeciesCorrection(item, species, deps);
    _close();
  };

  const onClick = (ev) => {
    const act = ev.target.closest?.('[data-act]')?.dataset.act;
    if (!act || act === 'cancel') {
      _close();
      return;
    }
    if (act === 'unsure') {
      submit(null);
      return;
    }
    if (act === 'pick') {
      submit(ev.target.closest('[data-species]')?.dataset.species);
    }
  };
  sheet.addEventListener('click', onClick);
  _openSheet = { el: sheet, onClick };
  return { teardown: _close };
}
