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
import { renderPanelTabs } from './panel-tabs.js';


// Three fixed tabs, always in this order. Icons rendered inline so
// the skeleton has no asset dependency. currentColor inheritance
// matches the .active / muted state colours from CSS.

const TABS = [
  { id: 'detections', label: 'Detections', icon: _iconDetections },
  { id: 'trace', label: 'Trace', icon: _iconTrace },
  { id: 'debug', label: 'Debug', icon: _iconDebug },
];


// L5 · the tab strip + persistent panels are now one renderPanelTabs
// instance (variant 'ld'). It owns the active tab, per-tab scroll-top
// memory, the fullscreen button's on/off state, and LS persistence; this
// module keeps only the cross-mount bridges + the timeline-collapse
// target the ↗ button drives. Recreated per mount, torn down on unmount.
let _tabsInst = null;
// onTabChange handlers registered before the first mount (live-detect-
// tabs.js subscribes at module-eval time) buffer here, then replay into
// every instance — so the subscription survives across re-opens.
const _pendingHandlers = [];
// SIMU-01d · the ↗ button collapses the timeline zone; snapshot its prior
// collapse state so the ↘ tap restores exactly what the user had. NOT
// persisted — localStorage is reserved for the user's own chevron choice.
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
  // L5 · one renderPanelTabs (variant 'ld') owns the strip in zone-tabs
  // + the persistent tab panels in zone-detail. It reads LS_ACTIVE_TAB
  // for the remembered tab (falling back to DEFAULT_TAB), wires the ↗
  // fullscreen button to the timeline collapse, and replays any pre-mount
  // onTabChange subscriptions. The Detections panel hosts #lightboxSettings
  // (moved in below); Trace/Debug are caller-painted by the tick bridges.
  _tabsInst = renderPanelTabs(zoneTabs, TABS, {
    variant: 'ld',
    contentHost: zoneDetail,
    persistentPanels: true,
    panelIdPrefix: PANEL_PREFIX,
    scrollMemory: true,
    persistKey: LS_ACTIVE_TAB,
    initialId: DEFAULT_TAB,
    onChange: _pendingHandlers,
    fullscreen: {
      expandIcon: _iconExpand,
      collapseIcon: _iconCollapseBack,
      expandLabel: 'Timeline ausblenden',
      collapseLabel: 'Timeline einblenden',
      btnClass: 'mv-ld-iconbtn mv-ld-fs-btn',
      onToggle: _onFullscreenToggle,
    },
  });
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
  // The renderPanelTabs instance already selected the initial tab (from
  // LS_ACTIVE_TAB or DEFAULT_TAB) + fired the replayed onChange handlers
  // during construction, so no setActiveTab call is needed here.
  _applyInitialCollapsedStates(camId);
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
  // L5 · drop the tab-strip instance (removes the strip + panels, clears
  // its scroll-top + handler copies). _pendingHandlers is NOT cleared —
  // it re-seeds the next mount's instance so onTabChange survives.
  try {
    _tabsInst?.teardown();
  } catch {
    /* already detached */
  }
  _tabsInst = null;
  container.remove();
  // SIMU-01d · session-only fullscreen snapshot is per-mount — reset so
  // the next mount starts from the expanded (or last-LS-state) baseline.
  _fsRestore = null;
  // SIMU-02c · overlay visibility is per-mount; reset on teardown so
  // the next openLiveDetect starts hidden (the spec's default).
  clearTimeout(_hideTimer);
  _hideTimer = 0;
  _overlayVisible = false;
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

// SIMU-01d · the ↗ tab-strip button (owned by renderPanelTabs) toggles
// ONLY the timeline collapse — the title is permanently compact
// (SIMU-FIX-04c), so there's no title state left to flip. Snapshot the
// timeline's prior collapse on the way in, restore it on the way out;
// renderPanelTabs owns the button's own on/off state + icon swap.
function _onFullscreenToggle(active) {
  if (active) {
    _fsRestore = { timeline: _isTimelineCollapsed() };
    _applyTimelineCollapsed(true);
  } else {
    _applyTimelineCollapsed(!!_fsRestore?.timeline);
    _fsRestore = null;
  }
}

// SIMU-04d · public tab API — thin bridges over the current
// renderPanelTabs instance. panelEl (above) stays a plain byId since the
// instance builds panels with stable ids (PANEL_PREFIX + tab id), so it
// resolves them without going through the instance.
export function setActiveTab(id) {
  _tabsInst?.setActive(id);
}

export function getActiveTab() {
  return _tabsInst ? _tabsInst.getActive() : DEFAULT_TAB;
}

export function onTabChange(handler) {
  if (typeof handler !== 'function') return;
  if (_tabsInst) _tabsInst.onChange(handler);
  else _pendingHandlers.push(handler);
}
