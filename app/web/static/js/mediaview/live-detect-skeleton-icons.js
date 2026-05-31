// ─── live-detect-skeleton-icons.js · inline tab/close/chevron/expand glyphs ──
export function _iconDetections() {
  return (
    '<svg class="mv-ld-tab-ico" width="13" height="13" viewBox="0 0 24 24" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<rect x="3" y="3" width="18" height="18" rx="3"/>' +
    '<circle cx="12" cy="12" r="2.4" fill="currentColor" stroke="none"/></svg>'
  );
}

export function _iconTrace() {
  return (
    '<svg class="mv-ld-tab-ico" width="13" height="13" viewBox="0 0 24 24" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<polyline points="3 18 9 12 13 14 21 6"/>' +
    '<circle cx="21" cy="6" r="1.6" fill="currentColor" stroke="none"/></svg>'
  );
}

export function _iconDebug() {
  return (
    '<svg class="mv-ld-tab-ico" width="13" height="13" viewBox="0 0 24 24" ' +
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<polyline points="9 6 4 12 9 18"/>' +
    '<polyline points="15 6 20 12 15 18"/>' +
    '<line x1="13.5" y1="4" x2="10.5" y2="20"/></svg>'
  );
}

export function _iconClose() {
  return (
    '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" ' +
    'aria-hidden="true">' +
    '<line x1="6" y1="6" x2="18" y2="18"/>' +
    '<line x1="18" y1="6" x2="6" y2="18"/></svg>'
  );
}

// Down-chevron. CSS rotates 180° when data-collapsed="1" on the
// wrapping zone, so the icon points UP when the zone is collapsed.
export function _iconChevron() {
  return (
    '<svg class="mv-ld-chevron-glyph" width="14" height="14" ' +
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" ' +
    'aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>'
  );
}

// Diagonal expand / collapse-back glyphs (top-right ↗ and bottom-left ↘
// arrows). Used by the tab-bar fullscreen toggle.
export function _iconExpand() {
  return (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M14 4 H20 V10"/>' +
    '<path d="M20 4 L13 11"/>' +
    '<path d="M10 20 H4 V14"/>' +
    '<path d="M4 20 L11 13"/></svg>'
  );
}

export function _iconCollapseBack() {
  return (
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M14 10 H20 V4"/>' +
    '<path d="M20 10 L13 3"/>' +
    '<path d="M10 14 H4 V20"/>' +
    '<path d="M4 14 L11 21"/></svg>'
  );
}
