// ─── vplayer/_box-model.js ─────────────────────────────────────────────────
// The box model moved to core/box-model.js, because the two EXISTING
// painters adopt it too and neither may import from this package.
//
// This file is the package's own door onto it: package code imports
// `./_box-model.js` the way it always did, and the shared home is a
// single edit away rather than forty.
//
// Kept as re-exports only — no wrapper, no local additions. A shim that
// grew logic of its own would be the second box model this whole
// exercise exists to prevent.

export {
  MASKED_STROKE as VP_MASKED_STROKE,
  PLATE_BG as VP_PLATE_BG,
  plateText,
  resolveBox,
} from '../core/box-model.js';
