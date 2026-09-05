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
//   stripHeight    the timeline strip's measured height, published so
//                  the on-picture chrome can centre on the PICTURE and
//                  not on picture-plus-strip.
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

/**
 * The narrowest box that may still carry a plate wider than itself.
 *
 * THE SCORE IS THE POINT OF THE PLATE, and clamping the plate to the
 * box's own width took it away from exactly the boxes that need it most.
 * A person is a TALL, NARROW box: on a clip that triggered on a fence
 * post and a gravestone, both were labelled a confident „Person" with no
 * number, because „Person · 41 %" was a few pixels wider than a 95 px
 * box and the ladder dropped to the next rung. A 41 % guess presented as
 * a fact is the whole class of defect this player has been chasing.
 *
 * So a plate may overhang a box out to this width — but ONLY a box that
 * is also TALL, and that qualifier is the whole rule. Narrow-and-tall is
 * the shape of a standing person, an unmistakable subject with vertical
 * room to spare. Narrow-and-short is a distant bird or a speck, where a
 * plate wider than its box is the absurdity the original rule was
 * written against and stays forbidden. A wide box is untouched;
 * `_platePos` still clamps every plate inside the frame.
 */
export const VP_PLATE_MIN_ROOM_PX = 104;

/** How tall a box must be before it may lend its plate extra width. */
export const VP_PLATE_TALL_PX = 96;

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
  const boxH = geom.boxH > 0 ? geom.boxH : Infinity;
  // A TALL box gets a little room beyond its own width — the standing
  // person whose score was being dropped. See VP_PLATE_MIN_ROOM_PX.
  // An unmeasured box keeps Infinity.
  const tall = boxH >= VP_PLATE_TALL_PX;
  const boxW =
    geom.boxW > 0 ? (tall ? Math.max(geom.boxW, VP_PLATE_MIN_ROOM_PX) : geom.boxW) : Infinity;
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
 * Everything this player still paints ON the picture and expects a
 * finger on: the two navigation chevrons at the sides, and mediaview's
 * transport disc in the middle.
 *
 * The layer switches and the ROI caption used to be in here too. They
 * have left the stage for the shell's own row below the picture, so they
 * occupy none of it — and a selector that keeps hunting them would go on
 * suppressing labels near the top of the frame for buttons that are no
 * longer there.
 */
const _CHROME_SEL = '.vp-glass-nav, .mv-player-btn';

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

/** Publish the strip's height, but only when it actually moved. */
function _write(stageEl, stripH) {
  const px = `${Math.round(stripH)}px`;
  if (stageEl.style.getPropertyValue('--vp-strip-h') !== px) {
    stageEl.style.setProperty('--vp-strip-h', px);
  }
}

/**
 * Keep `--vp-strip-h` on the stage equal to the strip's real height.
 *
 * The strip sits under the picture, so the stage is always taller than
 * the frame — and everything pinned to the stage with `inset: 0` (the
 * chevron layer, mediaview's transport) would centre on frame-plus-strip
 * and drift below the middle of the picture. This is the number that
 * pulls them back onto it.
 *
 * The strip's height changes when its DATA changes — a sidecar landing,
 * a live tick adding a lane — which no resize of the stage reports, so
 * it gets its own observer.
 *
 * @param {HTMLElement} stageEl  the shell's [data-slot="stage"]
 */
export function mountStripHeight(stageEl) {
  if (!stageEl) return { measure: () => 0, teardown: () => {} };
  const strip = stageEl.querySelector('[data-slot="timeline"]');
  const measure = () => {
    const stripH = strip ? strip.offsetHeight : 0;
    _write(stageEl, stripH);
    return stripH;
  };
  const ro = strip && typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
  ro?.observe(strip);
  return {
    measure,
    teardown: () => {
      ro?.disconnect();
      stageEl.style.removeProperty('--vp-strip-h');
    },
  };
}
