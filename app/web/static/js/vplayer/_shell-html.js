// ─── vplayer/_shell-html.js ────────────────────────────────────────────────
// The shell's slot skeleton, alone in its own file.
//
// WHY ITS OWN FILE. Four pytest files pin mediaview/shell.js's data-slot
// markup by reading that file's SOURCE TEXT, which means its markup
// cannot move without a test edit even when no behaviour changes — the
// header of shell.js says as much, and the layout that would naturally
// have been extracted stayed put for exactly that reason. Giving this
// markup a stable path from the first commit means the guard in
// app/tests/test_vplayer_shell_markup.py never has to move as _shell.js
// grows.
//
// LAYOUT, top → bottom:
//
//   topbar    prev / title / next, the overflow trigger and close.
//   stage     the picture. Owns the media element and the overlay
//             layers (frame), AND the timeline — mounting the timeline
//             INSIDE the stage instead of in a strip below it is the
//             central structural change of this player.
//   toggles   the overlay segmented control + the ROI chip.
//   controls  the transport's below-stage row (speed, frame-step, loop,
//             detection-nav, snapshot), owned by mediaview/player/*.
//   panel     the context panel: objects + details for a recorded clip,
//             tracks + raw detections for live and simulation.
//
// Empty slots collapse via :empty rather than being conditionally
// rendered, so every mode composes from one skeleton and teardown has
// one shape.

/** Every slot name in the skeleton, in mount order. */
export const VP_SHELL_SLOTS = [
  'topbar',
  'stage',
  'frame',
  'timeline',
  'toggles',
  'controls',
  'panel',
];

/** The class on the package's own root node. Nothing else may use it. */
export const VP_ROOT_CLASS = 'vp-root';

export const VP_SHELL_HTML =
  `<div class="vp-topbar" data-slot="topbar"></div>` +
  `<div class="vp-stage" data-slot="stage">` +
  `<div class="vp-frame" data-slot="frame"></div>` +
  `<div class="vp-timeline" data-slot="timeline"></div>` +
  `</div>` +
  `<div class="vp-toggles" data-slot="toggles"></div>` +
  `<div class="vp-controls" data-slot="controls"></div>` +
  `<div class="vp-panel" data-slot="panel"></div>`;
