// ─── vplayer/_density.js ───────────────────────────────────────────────────
// How much the picture can actually carry, MEASURED.
//
// WHY THIS FILE EXISTS. At 375 px the picture is ~211 px tall and five
// things were drawn into it at once: the detection boxes, their identity
// plates, the per-object trail lanes, the pre-/post-roll rail with its
// captions, and the transport disc. Each of them is correct on a 1440 px
// window, so the crowding survived every desktop look — and each of them
// was positioned by a rule that never asks how much room is left.
//
// NOT A BREAKPOINT LIST. The same crowding appears on a SHORT desktop
// window: `.vp-stage` is capped at 58dvh of height, so a 500 px-tall
// browser window has a 290 px picture and exactly the same problem at
// 1440 px of width. A `@media (max-width: …)` rule cannot see that, which
// is why every rule here takes pixels — box size, strip height, picture
// height — and no rule here knows the viewport width at all.
//
// TWO RULES, ONE IDEA: something that does not fit gets smaller or gets
// out, and the picture wins the argument.
//
//   fitPlateText   a label wider than the box it names is worse than no
//                  label, so it steps down a ladder of shorter forms and
//                  falls off the end rather than printing across the
//                  picture.
//   stripDensity   the timeline strip may lie ON the picture only while
//                  it leaves a usable picture behind it. Otherwise it
//                  drops out of the stage's overlay and into its own row
//                  under the frame, where nothing competes with it.
//
// The plate metrics live here rather than in _overlay-svg.js because the
// fit test and the renderer have to agree on them to the pixel; two
// copies is how a label that "fits" still overflows its plate.

import { plateText } from './_box-model.js';

// ── Plate metrics, in CSS px on screen ─────────────────────────────────
// _overlay-svg.js multiplies each by `k` (viewBox units per CSS pixel)
// so a plate is the same physical size whatever the camera streams.
export const VP_PLATE_FONT_PX = 12;
export const VP_PLATE_H_PX = 18;
export const VP_PLATE_PAD_PX = 6;
export const VP_PLATE_GAP_PX = 3;

/**
 * Mean glyph advance for system-ui at weight 700, as a fraction of the
 * font size. SVG has no synchronous text metrics, and a few px of slack
 * is invisible — but it must be the SAME estimate the plate is sized
 * with, or the fit test answers a question about a different rectangle.
 */
const _GLYPH_W = 0.58;

/**
 * Below this much picture, no plate at all.
 *
 * A plate is VP_PLATE_H_PX tall; on a picture this short it is already a
 * seventh of everything the operator can see, and two stacked boxes put
 * a third of the frame under dark slabs. The boxes still paint — the
 * geometry is the information, the wording is the luxury.
 */
export const VP_PLATE_MIN_PICTURE_PX = 128;

/** Picture that must stay clear of the on-picture strip, in CSS px. */
export const VP_STRIP_MIN_CLEAR_PX = 132;

/** Share of the picture the strip may claim before it moves out. */
export const VP_STRIP_MAX_SHARE = 0.34;

/** Estimated on-screen width of the plate that would carry `text`. */
export function plateWidthPx(text) {
  if (!text) return 0;
  return text.length * VP_PLATE_FONT_PX * _GLYPH_W + VP_PLATE_PAD_PX * 2;
}

/**
 * The ladder of ever-shorter labels for one detection, longest first.
 *
 * Every rung is built by core's own `plateText` rather than by cutting
 * the finished string up: the marker, the separator and the „gefiltert"
 * tail are that function's rules, and a second formatter here would
 * drift from it the first time one of them changed.
 *
 * Rungs: everything · without the score · identity only · the bare
 * number (or, for a detection the tracker has not numbered, the status
 * marker alone, which is the last thing still worth saying).
 *
 * @param {object} det  detection or tracks.json sample
 * @param {string} cat  resolved status category
 * @returns {string[]} at least one rung, never an empty string
 */
export function plateTiers(det, cat) {
  const d = det || {};
  const num = Number.isFinite(d.track_num) && d.track_num > 0 ? `#${d.track_num}` : '';
  const rungs = [
    plateText(d, cat),
    plateText({ ...d, score: null }, cat),
    plateText({ track_num: d.track_num }, cat),
    num || plateText({}, cat),
  ];
  const out = [];
  for (const rung of rungs) {
    if (rung && rung !== out[out.length - 1]) out.push(rung);
  }
  return out;
}

/**
 * The label a box THIS SIZE can carry.
 *
 * @param {object} det   detection or tracks.json sample
 * @param {string} cat   resolved status category
 * @param {object} geom  { boxW, boxH, pictureH } — all in CSS px. An
 *   absent or non-positive value means "not measured", and an unmeasured
 *   dimension never shortens anything: a caller that has not sized the
 *   screen must not be silently given a stub label.
 * @returns {string} '' when nothing fits, which is the correct answer
 */
export function fitPlateText(det, cat, geom = {}) {
  const pictureH = geom.pictureH > 0 ? geom.pictureH : 0;
  if (pictureH && pictureH < VP_PLATE_MIN_PICTURE_PX) return '';
  const tiers = plateTiers(det, cat);
  const boxW = geom.boxW > 0 ? geom.boxW : Infinity;
  const boxH = geom.boxH > 0 ? geom.boxH : Infinity;
  // A box shorter than the plate that would sit on it cannot carry a
  // sentence — the plate would be the bigger object. Straight to the
  // last rung, and off the end if even that is too wide.
  const from = boxH < VP_PLATE_H_PX + VP_PLATE_GAP_PX ? tiers.length - 1 : 0;
  for (let i = from; i < tiers.length; i++) {
    if (plateWidthPx(tiers[i]) <= boxW) return tiers[i];
  }
  return '';
}

/**
 * PURE: may the timeline strip lie on the picture?
 *
 * Two conditions, because two different shapes of crowding exist and
 * neither alone catches both:
 *
 *   · a SMALL picture with an ordinary strip — a phone. What is left
 *     over has to still be a picture, hence an absolute floor.
 *   · a BIG picture with a huge strip — eight tracked objects on a short
 *     desktop window. 130 px of lanes over a 290 px picture leaves the
 *     floor satisfied and still buries the footage, hence the share.
 *
 * @param {number} pictureH  letterboxed picture height, CSS px
 * @param {number} stripH    the strip's own laid-out height, CSS px
 * @returns {'roomy'|'compact'}
 */
export function stripDensity(pictureH, stripH) {
  if (!(pictureH > 0) || !(stripH > 0)) return 'roomy';
  if (pictureH - stripH < VP_STRIP_MIN_CLEAR_PX) return 'compact';
  if (stripH > pictureH * VP_STRIP_MAX_SHARE) return 'compact';
  return 'roomy';
}

/**
 * Everything this player paints ON the picture and expects a finger on:
 * the layer switches and the ROI caption at the top, the two navigation
 * chevrons at the sides, and mediaview's transport disc in the middle.
 *
 * THE CHIPS, NOT THEIR HOST. `.vp-toggles--onstage` is a transparent
 * full-width box that on a 375 px screen wraps to two rows — measuring
 * IT declares 65 px of picture occupied when four chips and a caption
 * actually cover about half of that, and every label near the top of
 * the frame is then suppressed for a button that is not there.
 */
const _CHROME_SEL =
  '.vp-toggles--onstage .vp-seg, .vp-toggles--onstage .vp-roi-chip, ' +
  '.vp-glass-nav, .mv-player-btn';

/**
 * The on-picture chrome, as rects in the PICTURE's own CSS-px space.
 *
 * MEASURED, not tabulated. The switch row wraps to two lines at 375 px,
 * the chevrons only exist when there is somewhere to navigate, and the
 * transport is mediaview's markup — a constant here would be wrong on
 * exactly the widths that need it, and stale the first time any of the
 * three changes.
 *
 * Empty while the chrome is faded out: the stage carries
 * `data-chrome="0"` during playback, and a label suppressed for a button
 * nobody can see is information thrown away for nothing.
 *
 * @param {HTMLElement} stageEl
 * @param {{x:number,y:number}} rect  the letterboxed picture rect
 * @returns {Array<{x,y,w,h}>}
 */
export function chromeRects(stageEl, rect) {
  if (!stageEl || stageEl.dataset.chrome === '0') return [];
  const stage = stageEl.getBoundingClientRect();
  const ox = stage.left + (rect?.x || 0);
  const oy = stage.top + (rect?.y || 0);
  const out = [];
  for (const el of stageEl.querySelectorAll(_CHROME_SEL)) {
    const r = el.getBoundingClientRect();
    if (!(r.width > 0) || !(r.height > 0)) continue;
    out.push({ x: r.left - ox, y: r.top - oy, w: r.width, h: r.height });
  }
  return out;
}

/**
 * PURE: does this rect keep clear of every chrome rect?
 *
 * Both sides in CSS px relative to the picture's top-left corner. The
 * 2 px slack is the same hairline the screenshot harness's own overlap
 * rule allows — a shared edge is not a collision.
 */
export function clearOfChrome(rect, chrome) {
  for (const c of chrome || []) {
    const x = Math.min(rect.x + rect.w, c.x + c.w) - Math.max(rect.x, c.x);
    const y = Math.min(rect.y + rect.h, c.y + c.h) - Math.max(rect.y, c.y);
    if (x > 2 && y > 2) return false;
  }
  return true;
}

/** Write the verdict onto the stage, but only when it actually moved. */
function _write(stageEl, mode, stripH) {
  if (stageEl.dataset.density !== mode) stageEl.dataset.density = mode;
  const px = `${Math.round(stripH)}px`;
  if (stageEl.style.getPropertyValue('--vp-strip-h') !== px) {
    stageEl.style.setProperty('--vp-strip-h', px);
  }
}

/**
 * Watch the stage and keep `data-density` on it truthful.
 *
 * The strip's height changes when its DATA changes — a sidecar landing,
 * a live tick adding a lane — which no resize of the stage reports, so
 * the strip gets its own observer. The measurement itself cannot
 * oscillate: the frame is width-bound (`aspect-ratio`), so moving the
 * strip out of the picture does not change the picture it was measured
 * against.
 *
 * `--vp-strip-h` rides along because the on-picture chrome has to centre
 * on the FRAME once the stage is taller than it.
 *
 * @param {HTMLElement} stageEl       the shell's [data-slot="stage"]
 * @param {() => number} getPictureH  current picture height, CSS px
 */
export function mountDensity(stageEl, getPictureH) {
  if (!stageEl) return { measure: () => 'roomy', teardown: () => {} };
  const strip = stageEl.querySelector('[data-slot="timeline"]');
  const measure = () => {
    const stripH = strip ? strip.offsetHeight : 0;
    const mode = stripDensity(getPictureH(), stripH);
    _write(stageEl, mode, stripH);
    return mode;
  };
  const ro = strip && typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
  ro?.observe(strip);
  return {
    measure,
    teardown: () => {
      ro?.disconnect();
      delete stageEl.dataset.density;
      stageEl.style.removeProperty('--vp-strip-h');
    },
  };
}
