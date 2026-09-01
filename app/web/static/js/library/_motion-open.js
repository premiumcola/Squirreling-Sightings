// ─── library/_motion-open.js ─────────────────────────────────────────────
// Pure resolver for window._openMediaItem's lookup order — split out of
// _bind.js so it stays importable (and unit-testable) without dragging
// in lightbox.js's whole dependency tree, the same pure/impure split this
// package already uses elsewhere (mediaview/device-tier.js's
// resolveDeviceTier vs getDeviceTier; mediaview/player/_detection-math.js
// vs _detection-nav.js).
//
// See _bind.js's own header for the regression this exists to fix:
// window._openMediaItem used to be defined ONLY by the per-camera
// drilldown's render pass, so a motion card in the merged "Alles
// gemischt" grid could be tapped before that ever ran, calling a
// function that plain did not exist yet.

/**
 * @param {Array<{event_id: string}>} items      this page's own motion items
 * @param {string} id                            the tapped card's event_id
 * @param {(id: string) => object|null} registryLookup  cross-grid fallback
 * @returns {object|null}
 */
export function resolveMotionItem(items, id, registryLookup) {
  return (items || []).find((x) => x.event_id === id) || registryLookup(id) || null;
}
