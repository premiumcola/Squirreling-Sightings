// ─── core/overlay-layers.js ────────────────────────────────────────────────
// The four overlay layers, their German labels, and — the part that
// matters — whether each one starts ON and whether the operator's choice
// survives the next open. Pure data, no DOM, no storage.
//
// It lives in core because THREE surfaces answer "which layers do I
// show" and only one of them owned the answer. mediaview/overlay-toggles.js
// held the table and also touches localStorage at module load, so
// vplayer/_config.js — which is deliberately pure, and is unit-tested
// without a browser for exactly that reason — could not read it. It
// derived its own defaults instead, from "is this layer in the mode's
// toggle list", and that list contains all four. So the unified player
// opened every clip with zones AND masks painted on.
//
// That is the annoyance this table was written to end, documented in
// overlay-toggles.js as the operator's own words: the red mask polygon
// on every clip, "I never asked for this". It came back through the new
// player because the rule lived in a module the new player could not
// import. One table, importable from anywhere, is the fix.
//
// THE TWO FLAGS ARE NOT THE SAME QUESTION:
//   default — is the layer on when a surface opens with no stored
//             preference? Detection layers yes: the operator opened the
//             player TO see what was detected. Survey layers no: zones
//             and masks are reference geometry, wanted now and then, not
//             every time.
//   persist — does flipping it stick? Only for the layers whose default
//             is "on", so turning bboxes off once keeps them off. Zones
//             and masks deliberately return to off on the next open
//             rather than quietly staying on for ever.

/**
 * @typedef {{label: string, default: boolean, persist: boolean, desc: string}} OverlayLayer
 */

/** @type {Record<string, OverlayLayer>} */
export const OVERLAY_LAYERS = {
  bboxes: {
    label: 'Bboxes',
    default: true,
    persist: true,
    desc: 'Erkannte Objekte als Rahmen über dem Video einblenden',
  },
  trails: {
    label: 'Trails',
    default: true,
    persist: true,
    desc: 'Bewegungspfade jeder erkannten Spur einzeichnen',
  },
  zones: {
    label: 'Zonen',
    default: false,
    persist: false,
    desc: 'Erkennungs-Zonen (grün) anzeigen',
  },
  masks: {
    label: 'Masken',
    default: false,
    persist: false,
    desc: 'Ausschluss-Masken (rot) anzeigen',
  },
};

/** Every layer key, in paint order. */
export const OVERLAY_LAYER_KEYS = Object.keys(OVERLAY_LAYERS);

/**
 * Is `key` on when a surface opens with nothing stored?
 *
 * Unknown keys answer `false` rather than throwing: a caller iterating
 * its own list must not be able to crash the open, and a layer nobody
 * defines is one nobody can paint anyway.
 */
export function overlayDefaultOn(key) {
  return OVERLAY_LAYERS[key]?.default === true;
}
