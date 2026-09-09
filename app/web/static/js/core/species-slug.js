// ─── core/species-slug.js ───────────────────────────────────────────────────
// PURE. Turns a German species display name into the lowercase,
// umlaut-transliterated slug used as an achievement id.
//
// WHY THIS EXISTS. app/app/species_unlock.py::_SPECIES_TO_ACH_ID carries
// two keys per species — the German display name with umlauts, and its
// ASCII transliteration (ä→ae, ö→oe, ü→ue, ß→ss) — both mapping to the
// same id, e.g. "grünfink"/"gruenfink" → "gruenfink" and
// "rabenkrähe"/"rabenkraehe" → "rabenkraehe". That second key is not a
// hand-picked list, it is what the standard German transliteration rule
// produces from the first — so this mirrors the RULE in JS instead of
// duplicating the Python dict, and a species name resolves to the same
// key core/animal-icons.js's BIRD_SVGS / MAMMAL_SVGS are keyed on.
//
// NOT A MATCH FOR EVERY ENTRY. Two ids in that table were hand-spelled
// off the DIN rule ("eichelhäher" → "eichelhaher", not "eichelhaeher";
// "mönchsgrasmücke" → "moenchsgrasmucke", not "moenchsgrasmuecke") — this
// function produces the DIN-regular slug instead, so those two species
// miss their icon and fall back to the emoji like any other unmapped
// species (see core/species-icon.js). Deliberate: a couple of
// hand-spelled exceptions are not worth a duplicated name list.

const _UMLAUT_MAP = { ä: 'ae', ö: 'oe', ü: 'ue', ß: 'ss' };
const _UMLAUT_RE = /[äöüß]/g;

/**
 * PURE: normalise a German species display name to its achievement-id
 * slug — lowercase, trimmed, umlauts transliterated (ä→ae, ö→oe, ü→ue,
 * ß→ss).
 *
 * @param {string} name  a display name, e.g. "Grünfink"
 * @returns {string} the slug, e.g. "gruenfink" — '' for anything
 *   blank or non-string
 */
export function speciesSlug(name) {
  if (typeof name !== 'string') return '';
  return name
    .trim()
    .toLowerCase()
    .replaceAll(_UMLAUT_RE, (ch) => _UMLAUT_MAP[ch] || ch);
}
