// ─── core/species-icon.js ───────────────────────────────────────────────────
// PURE. A species row's icon — the real vector silhouette when the
// achievement catalogue has one, the same bird-emoji fallback
// sichtungen/_achievements.js uses when it doesn't.
//
// WHY IT LIVES HERE, SEPARATE FROM THE PICKER. Built ahead of (and meant
// to be imported by) the candidate-species picker sheet
// (mediaview/panels/species-picker.js or wherever that lands) so the
// icon lookup is one small, independently-tested module rather than
// logic inlined into the picker's row renderer. A picker row has only a
// German display name ("Grünfink"), not the achievement-id slug the SVG
// tables are keyed on — species-slug.js bridges that.
//
// THE FALLBACK PATTERN IS BORROWED, NOT REINVENTED.
// sichtungen/_achievements.js::_renderCard does:
//   iconSvg = BIRD_SVGS[a.id] || MAMMAL_SVGS[a.id] || null
//   iconSvg present → render it; else render the 🐦 emoji.
// This is exactly that lookup, same two tables, same fallback — so a
// species with no icon here has no icon there either. No new SVGs are
// drawn: an unmatched species (e.g. "Stockente", outside today's
// top-27 catalogue) is expected to fall back, not a bug to fix here.

import { BIRD_SVGS, MAMMAL_SVGS } from './animal-icons.js';
import { speciesSlug } from './species-slug.js';

export const SPECIES_ICON_FALLBACK_EMOJI = '🐦';

/**
 * PURE: the raw inline-SVG markup for a species' silhouette, or null
 * when core/animal-icons.js has no entry for it.
 *
 * @param {string} speciesName  a German display name, e.g. "Grünfink"
 * @returns {string|null}
 */
export function speciesIconSvg(speciesName) {
  const id = speciesSlug(speciesName);
  if (!id) return null;
  return BIRD_SVGS[id] || MAMMAL_SVGS[id] || null;
}

/**
 * PURE: ready-to-insert row-icon markup — the real SVG when one
 * exists, else the same bird-emoji fallback _achievements.js uses.
 * `speciesName` is never interpolated into the returned markup, so
 * this is safe to use with untrusted display names.
 *
 * @param {string} speciesName
 * @returns {string} HTML — never empty
 */
export function speciesIconMarkup(speciesName) {
  const svg = speciesIconSvg(speciesName);
  if (svg) return svg;
  return `<span class="species-icon-emoji" aria-hidden="true">${SPECIES_ICON_FALLBACK_EMOJI}</span>`;
}
