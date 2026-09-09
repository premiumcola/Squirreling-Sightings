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
//
// THE GRID BELOW `speciesPickerRows`' OWN CANDIDATES (allBirdPickerNames)
// exists because `species_candidates` is frequently empty or near-empty
// — it is only "the runner-up species of the best-scoring classified
// bird" (see this event's own `_resolve_species_candidates` on the
// Python side), nothing at all when the clip only ever resolved to one
// species. A sheet with zero rows below the guess is not a correction
// tool ("wieso kanns ich nicht anklicken" energy, one release earlier,
// for a different control) — the operator's own ask: "Spezies wechseln
// gibt keine sinnvollen Auswahlmöglichkeiten, ich möchte ein Popup
// aller Spezies mit den Icons aus dem Achievement Board". So the grid
// is ACH_DEFS' bird roster (the same ~20-species catalogue the
// Sichtungen achievement board tracks) — real candidates first
// (deduped, dropped if it's the current guess), the rest of the
// catalogue after, every tile using the SAME icon lookup
// (speciesIconMarkup) _achievements.js's own medal falls back to. A
// species outside that catalogue (a genuine rarity) is still reachable
// via "unsicher" → the Telegram/backfill correction path, same as
// before this existed.
import { esc } from '../../core/dom.js';
import { apiPost } from '../../core/api.js';
import { showToast } from '../../core/toast.js';
import { speciesIconMarkup } from '../../core/species-icon.js';
import { clipSpeciesNames } from '../../core/clip-species.js';
import { ACH_DEFS } from '../../sichtungen/_ach-defs.js';

/**
 * PURE: every pickable bird species for the grid, best-known first.
 *
 * Order: the species this clip actually holds (`clipSpecies`, headline
 * first), then the classifier's runner-up candidates, then the rest of
 * ACH_DEFS' bird catalogue alphabetically. Deduped case-insensitively.
 *
 * THE CURRENT GUESS IS NOT DROPPED any more. It used to be — correcting
 * a species to itself is not a correction — but that also hid it, and a
 * clip that held two birds then showed neither of them in the sheet
 * that is supposed to be about them: „Wenn 2 spezies drin sind dann zeig
 * die auch und markiere die auch beim choosen!". They are listed, and
 * `speciesMarks` below is what makes them read as already-present.
 *
 * Not capped: the whole point is „ein popup aller spezies", and ~20
 * catalogue entries plus a handful of candidates fit the sheet's scroll.
 */
export function allBirdPickerNames(candidates, currentSpecies, clipSpecies = []) {
  const seen = new Set();
  const rows = [];
  const push = (raw) => {
    const name = String(raw || '').trim();
    const key = name.toLowerCase();
    if (!name || seen.has(key)) return;
    seen.add(key);
    rows.push(name);
  };
  push(currentSpecies);
  for (const name of clipSpecies || []) push(name);
  for (const cand of candidates || []) push(cand && cand.name);
  ACH_DEFS.filter((d) => d.cat === 'birds')
    .map((d) => d.name)
    .sort((a, b) => a.localeCompare(b, 'de'))
    .forEach(push);
  return rows;
}

/**
 * PURE: which names the sheet marks, and how.
 *
 * `current` is the headline this clip carries now; `inClip` is every
 * other species the whole-clip tally saw. Both are drawn in colour while
 * everything else is greyed — „Alle objekte sind bunt wenn angewählt und
 * schwarz-weis / grautöne wenn nicht angewählt!" — so the sheet opens
 * already showing what this clip is, rather than as a flat catalogue.
 *
 * @returns {{current: string, inClip: Set<string>}} lowercased keys
 */
export function speciesMarks(item) {
  const lower = (v) =>
    String(v || '')
      .trim()
      .toLowerCase();
  const current = lower(item?.bird_species);
  const inClip = new Set();
  for (const name of clipSpeciesNames(item)) {
    const key = lower(name);
    if (key && key !== current) inClip.add(key);
  }
  return { current, inClip };
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

// Round bubble, name underneath — „Bird vectors in round bubbles! With
// name below". Its own classes rather than the Vogelarten grid's
// `.species-grid-tile`: that one is a boxed tile built for a browsing
// grid with a count chip, and borrowing it here left the picker as a
// field of unlabelled boxes. One shape per surface, each saying what it
// is.
function _speciesTileHtml(name, marks) {
  const key = name.trim().toLowerCase();
  const on = key === marks.current || marks.inClip.has(key);
  const cls = 'sp-pick-tile' + (on ? ' is-on' : '') + (key === marks.current ? ' is-current' : '');
  return (
    `<button type="button" class="${cls}" data-act="pick" data-species="${esc(name)}"` +
    ` aria-pressed="${on ? 'true' : 'false'}">` +
    `<span class="sp-pick-bubble">${speciesIconMarkup(name)}</span>` +
    `<span class="sp-pick-name">${esc(name)}</span></button>`
  );
}

function _sheetHtml(names, marks) {
  const tiles = names.map((n) => _speciesTileHtml(n, marks)).join('');
  return (
    `<div class="sp-pick-backdrop" data-act="cancel"></div>` +
    `<div class="sp-pick-sheet" role="dialog" aria-modal="true" aria-label="Art korrigieren">` +
    `<div class="sp-pick-title">Welche Art war es wirklich?</div>` +
    `<div class="sp-pick-grid">${tiles}</div>` +
    `<button type="button" class="sp-pick-row sp-pick-row--unsure" data-act="unsure">` +
    `❓ unsicher, welche genau</button>` +
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
 * @param {object} item  a cached event object — needs camera_id and
 *   event_id; species_candidates + bird_species only order/filter the
 *   grid, they are no longer what makes it non-empty.
 * @param {object} deps  { onSaved(res) } — called after a successful
 *   POST with the endpoint's `{ok, bird_species}` reply, so the caller
 *   can patch whichever caches and re-render whichever badge it owns.
 * @returns {{teardown: () => void}|null}
 */
export function openSpeciesPicker(item, deps = {}) {
  if (!item || !item.camera_id || !item.event_id) return null;
  _close();
  const marks = speciesMarks(item);
  const rows = allBirdPickerNames(
    item.species_candidates,
    item.bird_species,
    clipSpeciesNames(item),
  );
  const sheet = document.createElement('div');
  sheet.className = 'sp-pick';
  sheet.innerHTML = _sheetHtml(rows, marks);
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
