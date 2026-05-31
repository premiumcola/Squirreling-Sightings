import { CONTAINER_ID, ZONE_IDS, PANEL_PREFIX, LS_ACTIVE_TAB, LS_TITLE_COLLAPSED, LS_TIMELINE_COLLAPSED, LS_LAST_CAMERA, DEFAULT_TAB, _OVERLAY_HIDE_MS, _lsGet, _lsSet } from './live-detect-skeleton-consts.js';
import { _iconDetections, _iconTrace, _iconDebug, _iconExpand, _iconCollapseBack } from './live-detect-skeleton-icons.js';
import { _makeZone, _buildTitleBar, _renderTitleText, _buildTimelineHeader, _isTimelineCollapsed, _applyTimelineCollapsed } from './live-detect-skeleton-chrome.js';
// ─── mediaview/live-detect-skeleton.js ────────────────────────────────────
// SIMU-01 · the 5-zone DOM skeleton for the Live-Detect view.
//
// The Live-Detect modal reuses #lightboxMediaWrap as its host; on
// mount, this module inserts a flex-column container with five named
// zones (title · video · timeline · tabs · detail) and re-parents
// existing chrome (img, video, scrubber/swimlane, settings panel)
// into the matching zone. zone-detail is the only scrollable region —
// everything above sticks.
//
// Tab content is owned by callers — the skeleton creates empty panel
// elements (`#mvLdPanel-<id>`) and toggles `.active` on the active
// one. setActiveTab/getActiveTab/onTabChange are the public API.
//
// Lifecycle:
//   mountLdSkeleton({camId, cameraName}) — idempotent mount; updates
//                                          title text on a second call
//                                          with a different camera.
//   unmountLdSkeleton()                  — full teardown, returns
//                                          children to their original
//                                          parents so the recorded
//                                          lightbox keeps working.

import { byId } from '../core/dom.js';
import { renderStatusLegend } from './status-legend.js';


// Three fixed tabs, always in this order. Icons rendered inline so
// the skeleton has no asset dependency. currentColor inheritance
// matches the .active / muted state colours from CSS.

const TABS = [
  { id: 'detections', label: 'Detections', icon: _iconDetections },
  { id: 'trace', label: 'Trace', icon: _iconTrace },
  { id: 'debug', label: 'Debug', icon: _iconDebug },
];


let _activeTab = DEFAULT_TAB;
const _tabChangeHandlers = [];
// SIMU-04d · per-tab scroll-top memory. Tab content lives inside
// zone-detail (the only scrollable region); switching tabs hides
// one panel and shows another, so without this the user's scroll
// position is lost on every switch.
const _tabScrollTops = new Map();
// SIMU-01d · session-only fullscreen state. Snapshot of title +
// timeline collapse values taken when the ↗ button forces both
// collapsed, so the ↘ tap can restore them. NOT persisted —
// localStorage is reserved for the user's own chevron choices.
let _fullscreen = false;
let _fsRestore = null;
// SIMU-02c · tap-to-reveal overlay visibility. Defaults to hidden on
// every fresh mount (NOT persisted). Tap the video → 3 s reveal,
// tap again → hide. Pill taps reset the timer; bbox shapes don't
// toggle (their own click handler opens the detail pill).
let _overlayVisible = false;
let _hideTimer = 0;
// L3 · handle for the ONE shared status legend mounted over the video;
// kept so unmountLdSkeleton can tear down its document listeners.
let _legendHandle = null;

// Public: locate a zone or panel by name.
export function zoneEl(name) {
  return byId(ZONE_IDS[name]) || null;
}

export function panelEl(tabId) {
  return byId(PANEL_PREFIX + tabId) || null;
}

export function mountLdSkeleton({ camId, cameraName } = {}) {
  const wrap = byId('lightboxMediaWrap');
  if (!wrap) return;
  // Idempotency — second mount just refreshes the title text.
  if (byId(CONTAINER_ID)) {
    _renderTitleText(cameraName);
    return;
  }
  const oldChildren = Array.from(wrap.children);
  const container = document.createElement('div');
  container.id = CONTAINER_ID;
  container.className = 'mv-ld-container';
  const zoneTitle = _makeZone('title');
  const zoneVideo = _makeZone('video');
  const zoneTimeline = _makeZone('timeline');
  const zoneTabs = _makeZone('tabs');
  const zoneDetail = _makeZone('detail');
  container.append(zoneTitle, zoneVideo, zoneTimeline, zoneTabs, zoneDetail);
  wrap.appendChild(container);
  // Re-parent existing wrap children into zone-video — img/video,
  // labels, hidden close/confirm/delete buttons, etc.
  for (const child of oldChildren) {
    if (child === container) continue;
    zoneVideo.appendChild(child);
  }
  // Move #lightboxBottomStack into zone-timeline body (its renderer
  // still finds it via byId, just inside a new parent now).
  const bottomStack = byId('lightboxBottomStack');
  if (bottomStack) {
    bottomStack.dataset.ldOrigParent = 'lightboxInner';
    zoneTimeline.appendChild(_buildTimelineHeader());
    const body = document.createElement('div');
    body.id = 'mvLdTimelineBody';
    body.className = 'mv-ld-timeline-body';
    body.appendChild(bottomStack);
    zoneTimeline.appendChild(body);
  }
  // Build the tab bar + tab content panels. The Detections panel
  // hosts #lightboxSettings for now; SIMU-04+ will redistribute its
  // children into the right tab panels.
  zoneTabs.appendChild(_buildTabBar());
  for (const t of TABS) {
    const panel = document.createElement('div');
    panel.id = PANEL_PREFIX + t.id;
    panel.className = 'mv-ld-tab-panel';
    panel.dataset.tabId = t.id;
    zoneDetail.appendChild(panel);
  }
  const settings = byId('lightboxSettings');
  if (settings) {
    settings.dataset.ldOrigParent = 'lightboxInner';
    settings.hidden = false;
    byId(PANEL_PREFIX + 'detections').appendChild(settings);
  }
  // Title chrome — name + ● Live + chevron + close X.
  zoneTitle.appendChild(_buildTitleBar(cameraName));
  // L3 · the ONE shared status legend (Bestätigt / ↓ Schwach / ≈ Ghost
  // / ⊘ Maskiert · "Farbe = Person-Nr.") floats over the video, auto-
  // positioned opposite the OSD timestamp band so it never overlaps it.
  // The same component the recorded + weather modes mount — one legend
  // everywhere, replacing the old live-only pass/unter-Schwelle pill.
  _legendHandle = renderStatusLegend(zoneVideo, { float: true, osdBand: 'top' });
  // SIMU-02c · default hidden, pointerup listener handles the toggle.
  // passive:true so the gesture doesn't block scroll on the detail
  // panel below. pointerup (not click) for snappier response on iOS
  // Safari (skips the legacy 300 ms tap delay).
  zoneVideo.dataset.overlayVisible = '0';
  _overlayVisible = false;
  zoneVideo.addEventListener('pointerup', _onVideoPointerUp, { passive: true });
  // SIMU-01c · seed collapsed states from localStorage. Same camera
  // within the session → restore last-known state; new camera → reset
  // both zones to expanded so the user gets a fresh layout instead of
  // inheriting some other camera's preference.
  _applyInitialCollapsedStates(camId);
  // Restore active tab from localStorage, default to "detections".
  const remembered = _lsGet(LS_ACTIVE_TAB);
  const initialTab = TABS.find((t) => t.id === remembered) ? remembered : DEFAULT_TAB;
  setActiveTab(initialTab);
}

// SIMU-FIX-04c · title-bar collapse is gone; the title is
// permanently compact. Only the timeline still has a collapse
// state. The legacy `tam.ld.title.collapsed` key is purged on
// every mount so a stale value never resurrects the toggle.
function _applyInitialCollapsedStates(camId) {
  try {
    localStorage.removeItem(LS_TITLE_COLLAPSED);
  } catch {
    /* private-mode / quota — silent */
  }
  const lastCam = _lsGet(LS_LAST_CAMERA);
  const sameCam = !!camId && lastCam === camId;
  if (!sameCam) {
    _applyTimelineCollapsed(false);
    if (camId) _lsSet(LS_LAST_CAMERA, camId);
    return;
  }
  _applyTimelineCollapsed(_lsGet(LS_TIMELINE_COLLAPSED) === '1');
}

export function unmountLdSkeleton() {
  const container = byId(CONTAINER_ID);
  if (!container) return;
  // L3 · tear down the shared legend (document listeners + popover)
  // before the container goes so nothing leaks across re-opens.
  try {
    _legendHandle?.teardown();
  } catch {
    /* ignore */
  }
  _legendHandle = null;
  const inner = byId('lightboxInner');
  const wrap = byId('lightboxMediaWrap');
  if (!wrap || !inner) {
    container.remove();
    return;
  }
  // Move #lightboxBottomStack back to #lightboxInner.
  const bottomStack = byId('lightboxBottomStack');
  if (bottomStack) {
    inner.appendChild(bottomStack);
    delete bottomStack.dataset.ldOrigParent;
  }
  // Move #lightboxSettings back to #lightboxInner.
  const settings = byId('lightboxSettings');
  if (settings) {
    inner.appendChild(settings);
    delete settings.dataset.ldOrigParent;
  }
  // Move all remaining zone-video children back to #lightboxMediaWrap.
  const zoneVideo = byId(ZONE_IDS.video);
  if (zoneVideo) {
    for (const child of Array.from(zoneVideo.children)) {
      wrap.appendChild(child);
    }
  }
  container.remove();
  // SIMU-01d · session-only fullscreen state is not persisted by spec
  // — reset on teardown so the next mount starts in the expanded
  // (or last-LS-state) baseline.
  _fullscreen = false;
  _fsRestore = null;
  // SIMU-02c · overlay visibility is per-mount; reset on teardown so
  // the next openLiveDetect starts hidden (the spec's default).
  clearTimeout(_hideTimer);
  _hideTimer = 0;
  _overlayVisible = false;
  // SIMU-04d · per-tab scroll-top is per-mount. Reset so a re-open
  // on a different camera starts at the top of each tab.
  _tabScrollTops.clear();
}

// SIMU-02c · tap-on-video handler. Toggles the visibility of the
// floating pills and the legend; schedules a 3-s auto-hide on every
// show. Skips bbox <g> shapes (they have their own click handler in
// live-detect.js for the detail pill). Pill taps don't toggle but
// they DO reset the hide timer so the user can flick multiple pills
// in succession without the overlay vanishing.
function _onVideoPointerUp(ev) {
  if (ev?.target?.closest && ev.target.closest('[data-label]')) return;
  if (ev?.target?.closest && ev.target.closest('.mv-live-toggle')) {
    if (_overlayVisible) _scheduleOverlayHide();
    return;
  }
  if (_overlayVisible) {
    clearTimeout(_hideTimer);
    _hideTimer = 0;
    _setOverlayVisible(false);
  } else {
    _setOverlayVisible(true);
    _scheduleOverlayHide();
  }
}

function _setOverlayVisible(v) {
  _overlayVisible = !!v;
  const video = byId(ZONE_IDS.video);
  if (video) video.dataset.overlayVisible = _overlayVisible ? '1' : '0';
}

function _scheduleOverlayHide() {
  clearTimeout(_hideTimer);
  _hideTimer = setTimeout(() => {
    _setOverlayVisible(false);
    _hideTimer = 0;
  }, _OVERLAY_HIDE_MS);
}

function _buildTabBar() {
  const root = document.createElement('div');
  root.className = 'mv-ld-tab-bar-root';
  const bar = document.createElement('div');
  bar.className = 'mv-ld-tab-bar';
  for (const t of TABS) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mv-ld-tab-btn';
    btn.dataset.tabId = t.id;
    btn.innerHTML = `${t.icon()}<span>${t.label}</span>`;
    btn.addEventListener('click', () => setActiveTab(t.id));
    bar.appendChild(btn);
  }
  // SIMU-01d · expand-to-fullscreen button at the right edge.
  // POLISH-01f · since the title is permanently compact (SIMU-FIX-
  // 04c), this now toggles ONLY the timeline collapse — the title
  // has no collapse state left to flip.
  const fsBtn = document.createElement('button');
  fsBtn.type = 'button';
  fsBtn.className = 'mv-ld-iconbtn mv-ld-fs-btn';
  fsBtn.dataset.active = '0';
  fsBtn.setAttribute('aria-label', 'Timeline ausblenden');
  fsBtn.innerHTML = _iconExpand();
  fsBtn.addEventListener('click', _toggleFullscreen);
  root.appendChild(bar);
  root.appendChild(fsBtn);
  return root;
}

function _toggleFullscreen() {
  const btn = byId(CONTAINER_ID)?.querySelector('.mv-ld-fs-btn');
  if (!btn) return;
  if (!_fullscreen) {
    _fsRestore = { timeline: _isTimelineCollapsed() };
    _applyTimelineCollapsed(true);
    _fullscreen = true;
    btn.dataset.active = '1';
    btn.innerHTML = _iconCollapseBack();
    btn.setAttribute('aria-label', 'Timeline einblenden');
  } else {
    _applyTimelineCollapsed(!!_fsRestore?.timeline);
    _fsRestore = null;
    _fullscreen = false;
    btn.dataset.active = '0';
    btn.innerHTML = _iconExpand();
    btn.setAttribute('aria-label', 'Timeline ausblenden');
  }
}

export function setActiveTab(id) {
  if (!TABS.find((t) => t.id === id)) return;
  const container = byId(CONTAINER_ID);
  if (!container) {
    _activeTab = id;
    _lsSet(LS_ACTIVE_TAB, id);
    return;
  }
  // SIMU-04d · save the OLD tab's scroll-top before swapping panels.
  // The detail zone is the single scroll surface; each tab's view-
  // port snapshot lives in _tabScrollTops so switching back restores
  // exactly where the user left off.
  const detail = byId(ZONE_IDS.detail);
  if (detail && _activeTab) {
    _tabScrollTops.set(_activeTab, detail.scrollTop);
  }
  _activeTab = id;
  _lsSet(LS_ACTIVE_TAB, id);
  container.querySelectorAll('.mv-ld-tab-btn').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.tabId === id);
  });
  container.querySelectorAll('.mv-ld-tab-panel').forEach((p) => {
    p.classList.toggle('active', p.dataset.tabId === id);
  });
  // Restore the new tab's scroll-top, defaulting to 0 on first show.
  if (detail) {
    detail.scrollTop = _tabScrollTops.get(id) || 0;
  }
  for (const h of _tabChangeHandlers) {
    try {
      h(id);
    } catch (err) {
      console.warn('[mv-ld] tab handler error', err);
    }
  }
}

export function getActiveTab() {
  return _activeTab;
}

export function onTabChange(handler) {
  if (typeof handler === 'function') _tabChangeHandlers.push(handler);
}
