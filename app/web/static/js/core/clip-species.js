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

/** Evidence behind one `whole_clip.species` row: how many frames the
 *  clip held it, weighted by how sure the classifier was. The same
 *  measure `bird_species_rank.pick_headline_species` ranks by. */
function _rowEvidence(row) {
  const frames = Math.max(0, Number(row?.frames) || 0);
  const score = Math.max(0, Number(row?.best_score) || 0);
  return frames * score;
}

/** A co-species must carry at least this share of the best-supported
 *  one's evidence to be named at all. Mirrors
 *  bird_species_rank.RARITY_PROMOTION_SHARE — one clip, one bar. */
const SECONDARY_MIN_SHARE = 0.5;

/**
 * PURE: every species identified anywhere in the clip, best-scoring
 * first, de-duplicated by display name — and only the ones the clip
 * actually supports.
 *
 * THE FLOOR IS THE POINT. A real archive clip held 110 frames of Elster
 * at 0.70 and ONE frame of Graureiher at 0.29, and named both. Naming
 * the second is not extra information, it is a guess presented as an
 * observation: „nach dem Feintuning musst Du dich auf eins festlegen und
 * kannst nicht mehr mehrere Dinge raten". A bird that genuinely shared
 * the clip clears half the leader's evidence easily; a stray frame
 * never does.
 *
 * Rows written before `frames`/`best_score` existed carry no evidence at
 * all — then no row does, there is no leader to measure against, and
 * every name is kept exactly as it always was.
 *
 * @param {object} item  the event
 * @returns {string[]}  empty for an event with no `whole_clip`
 */
export function clipSpeciesNames(item) {
  const rows = item?.whole_clip?.species;
  if (!Array.isArray(rows)) return [];
  const best = rows.reduce((m, r) => Math.max(m, _rowEvidence(r)), 0);
  const floor = best * SECONDARY_MIN_SHARE;
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const name = row && typeof row.species === 'string' ? row.species.trim() : '';
    if (!name || seen.has(name)) continue;
    if (best > 0 && _rowEvidence(row) < floor) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}

/**
 * PURE: the species a surface has NOT already named.
 *
 * The headline is picked by `bird_species_rank.pick_headline_species`
 * and stays one name — that ranking is deliberate and other things
 * depend on it. This is what belongs BESIDE it, so nothing is said
 * twice on one card.
 *
 * @param {object} item
 * @param {string} shown  the name already on display
 * @returns {string[]}
 */
export function secondarySpeciesNames(item, shown) {
  const skip = typeof shown === 'string' ? shown.trim() : '';
  return clipSpeciesNames(item).filter((name) => name !== skip);
}

/**
 * PURE: the one quiet line of "and also these", or '' for nothing.
 *
 * A card is 160 px wide on an iPhone, so the list is bounded: at most
 * `max` names, then `+N` for the rest. An event whose clip held ONE
 * species returns '' and the caller renders no chip at all — the
 * headline already said everything there is to say.
 *
 * TRUNCATION IS NOT HIDDEN. `whole_clip.truncated` means a cap refused
 * something, so the names present are a partial answer and the line
 * ends in an ellipsis rather than reading as the complete set. The
 * block carries one merged flag for the row caps and the species cap
 * together, so this errs toward saying "there may be more" — the
 * direction that cannot mislead.
 *
 * @param {object} item
 * @param {string} shown  the name already on display
 * @param {number} max    names before the overflow count
 * @returns {string}
 */
export function speciesChipText(item, shown, max = 2) {
  const rest = secondarySpeciesNames(item, shown);
  if (!rest.length) return '';
  const head = rest.slice(0, Math.max(1, max));
  const parts = rest.length > head.length ? [...head, `+${rest.length - head.length}`] : head;
  const text = parts.join(' · ');
  return item?.whole_clip?.truncated ? `${text} …` : text;
}
