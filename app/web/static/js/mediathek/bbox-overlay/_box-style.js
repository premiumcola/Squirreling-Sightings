// ─── mediathek/bbox-overlay/_box-style.js ──────────────────────────────────
// Thin adapter from the recorded painter's positional call shape onto
// the shared resolver in core/box-model.js.
//
// The export name is unchanged, so svg-boxes.js is untouched. What
// changed is where the answer comes from: recorded and live had each
// grown their own pill convention, plate design and masked grey, and
// the differences were invisible unless the two were opened side by
// side. There is one of each now.
//
// The `masked` flag stays a separate argument because the recorded
// painter decides masking GEOMETRICALLY — is this sample's foot point
// inside an exclusion polygon — which is outside the status vocabulary
// the sidecar stores. resolveBox takes it as an override.

import { resolveBox } from '../../core/box-model.js';

/**
 * Resolve every paint parameter for one recorded box.
 *
 * @param {object} sample     tracks.json sample: {bbox, score, label}
 * @param {string} trackColor per-track identity hue
 * @param {string} status     confirmed | weak | ghost
 * @param {boolean} masked    sample's foot point is inside a mask
 * @param {number|null} trackNum
 * @returns {{dash, alpha, stroke, pillBg, pillTextColor, text}}
 */
export function resolveBoxStyle(sample, trackColor, status, masked, trackNum) {
  const s = sample || {};
  const style = resolveBox(
    { status, score: s.score, label: s.label, track_num: trackNum },
    { colour: trackColor, masked },
  );
  return {
    dash: style.dash,
    alpha: style.alpha,
    stroke: style.stroke,
    // Key names kept for svg-boxes.js's plate markup. The VALUES are
    // now the shared plate: a dark slab carrying the track's own
    // colour as its text, instead of a colour-filled pill with
    // darkened text.
    pillBg: style.plateBg,
    pillTextColor: style.plateFg,
    text: style.plateText,
  };
}
