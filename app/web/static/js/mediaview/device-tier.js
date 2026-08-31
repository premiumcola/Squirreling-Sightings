// ─── mediaview/device-tier.js ──────────────────────────────────────────────
// Device/pointer-capability tier for the MediaView shell — the axis
// `_MODE_FLAGS` in shell.js does NOT cover. Mode flags answer "what
// content is this" (recorded / live / weather / …); tier answers "what
// kind of screen + pointer is looking at it". Foundation only in this
// stage: nothing reads `tier` to change rendering yet — it exists so a
// later stage building PC-only transport features (the concept-analysis
// pass's "full desktop experience vs compact iOS one" split) has
// somewhere to plug in without another flag-system invention.
//
// Resolution rule — width AND pointer capability, not either alone:
//
//   < FULL_TIER_MIN_WIDTH_PX             → always 'compact'.
//   >= FULL_TIER_MIN_WIDTH_PX + a real
//     mouse (hover:hover AND pointer:fine) → 'full'.
//   >= FULL_TIER_MIN_WIDTH_PX + touch     → 'compact'.
//
// The touch case is the one worth spelling out: a landscape iPad is
// "wide" by the same breakpoint a desktop window is, but it is a
// touch-primary device with no hover affordance, so PC-only chrome
// (hover-revealed controls, dense mouse-precision targets) would be
// exactly as wrong there as on a phone. This mirrors the codebase's
// existing `@media (hover: hover)` gating (25-mobile.css et al.) rather
// than inventing a new capability vocabulary — a real mouse/trackpad
// attached to that same iPad (hover:hover + pointer:fine both go true)
// correctly resolves to 'full', which matches how iPadOS itself reports
// pointer capability once an external pointer is connected.
//
// FULL_TIER_MIN_WIDTH_PX matches the repo's one existing mobile/desktop
// breakpoint (25-mobile.css: "Desktop layout at >= 769 px is
// unaffected") rather than inventing a second breakpoint vocabulary.
import { getViewportSize } from '../core/viewport.js';

export const TIER_COMPACT = 'compact';
export const TIER_FULL = 'full';

export const FULL_TIER_MIN_WIDTH_PX = 769;

/**
 * Pure resolver — no DOM reads. Exposed separately from `getDeviceTier`
 * so the resolution RULE is testable without a browser environment.
 *
 * @param {Object} [sample]
 * @param {number} [sample.width]      viewport width in px
 * @param {boolean} [sample.hoverFine] true when both `(hover: hover)`
 *   and `(pointer: fine)` match — i.e. a real mouse/trackpad, not touch.
 * @returns {'full'|'compact'}
 */
export function resolveDeviceTier(sample = {}) {
  const width = Number.isFinite(sample.width) ? sample.width : 0;
  if (width < FULL_TIER_MIN_WIDTH_PX) return TIER_COMPACT;
  return sample.hoverFine ? TIER_FULL : TIER_COMPACT;
}

/**
 * Live capability read — viewport width via core/viewport.js (already
 * shared across the app) + a `matchMedia` capability probe, feature-
 * detected exactly like core/ios-video.js's fullscreen chain: no
 * `navigator.userAgent` anywhere in this file.
 *
 * @returns {'full'|'compact'}
 */
export function getDeviceTier() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return TIER_COMPACT;
  }
  const { width } = getViewportSize();
  const hoverFine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
  return resolveDeviceTier({ width, hoverFine });
}
