// ─── live-detect-skeleton-chrome.js · stateless DOM builders (zone/title/timeline) ──
import { byId } from '../core/dom.js';
import { CONTAINER_ID, ZONE_IDS, LS_TIMELINE_COLLAPSED, _lsSet } from './live-detect-skeleton-consts.js';
import { _iconClose, _iconChevron } from './live-detect-skeleton-icons.js';

export function _makeZone(name) {
  const el = document.createElement('div');
  el.id = ZONE_IDS[name];
  el.className = `mv-ld-zone mv-ld-zone-${name}`;
  return el;
}

// SIMU-FIX-04c · the title bar is now permanently compact — single
// muted line "<Cam> · Live" + close X. The collapse chevron + its
// localStorage state are removed; the only collapse-control left is
// the expand-to-fullscreen button on the tab bar (which now toggles
// just the timeline since title is already at its smallest form).
export function _buildTitleBar(camName) {
  const titleEl = document.createElement('div');
  titleEl.className = 'mv-ld-title-row';
  titleEl.style.cssText = 'display:contents';
  titleEl.innerHTML =
    '<span class="mv-ld-title-text" data-mv-ld-title-text></span>' +
    `<button type="button" class="mv-ld-iconbtn mv-ld-close-btn" aria-label="Schließen">${_iconClose()}</button>`;
  titleEl.querySelector('.mv-ld-close-btn')?.addEventListener('click', () => {
    if (typeof window.closeLightbox === 'function') {
      window.closeLightbox();
    } else {
      const closeBtn = byId('lightboxClose');
      if (closeBtn) closeBtn.click();
    }
  });
  const camText = camName || '';
  titleEl.querySelector('[data-mv-ld-title-text]').textContent = camText
    ? `${camText} · Live`
    : 'Live';
  return titleEl;
}

export function _renderTitleText(camName) {
  const textEl = byId(CONTAINER_ID)?.querySelector('[data-mv-ld-title-text]');
  const camText = camName || '';
  if (textEl) textEl.textContent = camText ? `${camText} · Live` : 'Live';
}

export function _buildTimelineHeader() {
  const head = document.createElement('div');
  head.className = 'mv-ld-timeline-head';
  head.innerHTML =
    '<span class="mv-ld-timeline-head-label" data-mv-ld-timeline-label>Timeline · letzte 60 s</span>' +
    `<button type="button" class="mv-ld-iconbtn mv-ld-timeline-chevron" aria-label="Timeline ein-/ausblenden">${_iconChevron()}</button>`;
  head.querySelector('.mv-ld-timeline-chevron')?.addEventListener('click', () => {
    const next = !_isTimelineCollapsed();
    _applyTimelineCollapsed(next);
    _lsSet(LS_TIMELINE_COLLAPSED, next ? '1' : '0');
  });
  return head;
}

// Collapsed-state accessors. The data-collapsed attribute on the
// timeline zone is the single source of truth; localStorage seeds
// it on mount + remembers user clicks.
// POLISH-01f · the title-collapse stubs (_isTitleCollapsed /
// _applyTitleCollapsed) were removed — the title is permanently
// compact (SIMU-FIX-04c) and nothing flips its state anymore.
export function _isTimelineCollapsed() {
  return byId(ZONE_IDS.timeline)?.dataset.collapsed === '1';
}

export function _applyTimelineCollapsed(v) {
  const zone = byId(ZONE_IDS.timeline);
  if (!zone) return;
  zone.dataset.collapsed = v ? '1' : '0';
  const chev = zone.querySelector('.mv-ld-timeline-chevron');
  if (chev) chev.dataset.collapsed = v ? '1' : '0';
}

