// ─── live-detect-skeleton-consts.js · zone ids, LS keys, localStorage helpers ──
export const CONTAINER_ID = 'mvLdContainer';
export const ZONE_IDS = {
  title: 'mvLdZoneTitle',
  video: 'mvLdZoneVideo',
  timeline: 'mvLdZoneTimeline',
  tabs: 'mvLdZoneTabs',
  detail: 'mvLdZoneDetail',
};
export const PANEL_PREFIX = 'mvLdPanel-';

export const LS_ACTIVE_TAB = 'tam.ld.activetab';
export const LS_TITLE_COLLAPSED = 'tam.ld.title.collapsed';
export const LS_TIMELINE_COLLAPSED = 'tam.ld.timeline.collapsed';
export const LS_LAST_CAMERA = 'tam.ld.lastcamera';
export const DEFAULT_TAB = 'detections';

export const _OVERLAY_HIDE_MS = 3000;

export function _lsGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function _lsSet(key, val) {
  try {
    localStorage.setItem(key, val);
  } catch {
    /* private mode / quota — silent */
  }
}

