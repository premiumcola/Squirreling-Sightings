// ─── core/clip-species.js ──────────────────────────────────────────────────
// PURE. What a clip's `whole_clip` block says about species, and the one
// rule for naming a subject.
//
// WHY IT LIVES IN core/. Two feature packages ask the same question of
// the same event key — mediathek/_cards.js for the card badge and
// vplayer/ for the player's object rows — and the rule "a bird that has
// been identified is called by its species, everything else by its
// German class name" was already written out inline in _cards.js. A
// second copy in the player is exactly the parallel implementation
// CLAUDE.md forbids, so the rule moved here and both call it.
//
// THE BLOCK IT READS. `event.whole_clip` is written by
// app/app/camera_runtime/_clip_tally.py::ClipTally.summary() and holds
// `{detections, species, frames, truncated}`. Its `species` rows are
// `{species, species_latin, best_score, frames}`, already sorted
// best-scoring first by the backend, and keyed on the LATIN binomial —
// so two rows can in principle carry one display name, and this
// de-duplicates on what is actually shown.
//
// EVERY READER DEGRADES TO EMPTY. Events recorded before the block
// existed simply have no `whole_clip`, and every function here answers
// "nothing" for them rather than throwing. That is what keeps an old
// event rendering exactly as it did.

import { OBJ_LABEL } from './icons.js';

/**
 * PURE: the display name for ONE subject.
 *
 * A bird the classifier has named is called by its species — the
 * operator wants "Grünfink", not a second row that says "Vogel" like
 * the one above it. Everything else, and a bird that was never
 * identified, keeps its German class name.
 *
 * @param {string} label    the object class (`bird`, `cat`, …)
 * @param {string|null} species  the identified species, when there is one
 * @returns {string}  '' when there is nothing to call it, so the caller
 *   picks its own placeholder rather than inheriting one.
 */
export function subjectLabel(label, species) {
  if (label === 'bird' && species) return species;
  return OBJ_LABEL[label] || label || '';
}

/**
 * PURE: every species identified anywhere in the clip, best-scoring
 * first, de-duplicated by display name.
 *
 * @param {object} item  the event
 * @returns {string[]}  empty for an event with no `whole_clip`
 */
export function clipSpeciesNames(item) {
  const rows = item?.whole_clip?.species;
  if (!Array.isArray(rows)) return [];
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const name = row && typeof row.species === 'string' ? row.species.trim() : '';
    if (!name || seen.has(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}
