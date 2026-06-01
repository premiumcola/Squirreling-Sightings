// ─── mediaview/live-detect-overlays.js ─────────────────────────────────────
// Overlay-layer plumbing: ensure/create the SVG/canvas layers, the resize
// refresh, the 'N verworfen' suppressed-hint, and the trails + zone/mask
// renderers. Reuses _positionSvgOverImage from live-detect-bbox.js (call-time
// circular). Reads state via S.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { liveTrackColor } from '../core/track-color.js';
import { normalizePolygon } from '../core/polygon-source.js';
import { buildTrailSvg } from './canvas/trail-layer.js';
import { renderZoneLayerForMediaEl } from './canvas/zone-layer.js';
import { zoneEl } from './live-detect-skeleton.js';
import { S } from './live-detect-state.js';
import {
  _debugDiagOn,
  _updateDiagStrip,
  _refreshMediaRow,
  _renderDiagStrip,
} from './live-detect-diag.js';
import {
  _renderBboxOverlay,
  _positionSvgOverImage,
  _LIVE_TRAIL_MAX_POINTS,
} from './live-detect-bbox.js';
import { _renderDetectionsPanel } from './live-detect-panels.js';

export function _installLiveOverlayRefresh(mediaEl) {
  if (!mediaEl || mediaEl._zoneRefreshInstalled) return;
  const refresh = () => {
    _renderBboxOverlay();
    _renderTrailsOverlay();
    _renderZoneMaskOverlay();
  };
  // <video> uses `loadedmetadata` (videoWidth/videoHeight known);
  // <img> uses `load` (naturalWidth/Height known).
  mediaEl.addEventListener('loadedmetadata', refresh);
  mediaEl.addEventListener('load', refresh);
  try {
    const obs = new ResizeObserver(refresh);
    obs.observe(mediaEl);
    mediaEl._zoneResizeObs = obs;
  } catch {
    /* older browsers — listeners still help */
  }
  mediaEl._zoneRefreshInstalled = true;
}

// SIMU-FIX-04a · the bbox/trails/zonemask layers ALL belong inside
// zone-video so they sit on top of the <img>/<video>. The previous
// implementation only routed them on FIRST creation; if any prior
// session left the SVG in a different parent, or if the SVG was
// inserted before mountLdSkeleton finished reparenting, the layer
// would end up in #lightboxMediaWrap (outside zone-video) and the
// _positionSvgOverImage delta-math landed it at viewport Y=339
// (the BOTTOM edge of zone-video, off the visible video).
// _ensureXxxOverlay now ALSO moves an already-existing SVG into
// zone-video on every call — appendChild on a parented element
// re-parents it without recreating.
export function _ensureOverlayLayer(id, type, zIndex) {
  let el = byId(id);
  const zoneVid = zoneEl('video');
  if (el) {
    if (zoneVid && el.parentNode !== zoneVid) zoneVid.appendChild(el);
    return el;
  }
  const host = zoneVid || byId('lightboxMediaWrap');
  if (!host) return null;
  if (type === 'svg') {
    el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    el.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  } else {
    el = document.createElement(type);
  }
  el.id = id;
  // H2.b Fix 3 · z-indexes 14/15/16 — zones+masks bottom (14),
  // trails middle (15), bboxes top (16). Stack order is
  // deterministic regardless of DOM insertion order.
  el.style.cssText = `position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:${zIndex}`;
  host.appendChild(el);
  return el;
}

export function _ensureBboxOverlay() {
  return _ensureOverlayLayer('lightboxLiveOverlay', 'svg', 16);
}

export function _ensureTrailsOverlay() {
  return _ensureOverlayLayer('lightboxLiveTrails', 'svg', 15);
}

export function _ensureZoneMaskOverlay() {
  // Canvas (not SVG) so the SAME shared zone-layer the recorded
  // Mediathek lightbox uses can paint it — single source of truth
  // for the letterbox math and polygon source-resolution handling
  // (see mediaview/canvas/zone-layer.js + core/polygon-source.js).
  return _ensureOverlayLayer('lightboxLiveZoneMask', 'canvas', 14);
}

// wv612 — single-line legend that appears under the toggle row only
// while there's at least one suppressed bbox currently on screen.
// The user sees WHY a detection didn't trigger directly on the
// canvas (dashed stroke, muted color, suffix label); the legend
// translates the visual language. Auto-hides when every visible
// bbox is in the pass state so the row stays quiet in the common
// case. Mount lives next to the overlay toggle row.
// D52 · the verdict legend (three switches: solid/dashed/filtered)
// was removed because the same semantics now live in the Detections
// panel rows themselves (PASS / unter Schwelle / gefiltert badges).
// Replaced with a single muted "<n> verworfen — antippen für
// Details" line that appears only when at least one non-pass det
// is on the canvas, and tapping it toggles the detections panel
// between "pass-only" (the default) and "all detections" view.
// State persists in localStorage so the user's preference survives.
const _DETECTIONS_EXPAND_KEY = 'tam.livedetect.detections.expanded';

export function _detectionsExpanded() {
  try {
    return localStorage.getItem(_DETECTIONS_EXPAND_KEY) === '1';
  } catch {
    return false;
  }
}

export function _setDetectionsExpanded(v) {
  try {
    localStorage.setItem(_DETECTIONS_EXPAND_KEY, v ? '1' : '0');
  } catch {
    /* private-mode / quota — silent */
  }
}

export function _updateSuppressedHint(nonPassCount) {
  const toggleRow = byId('mvLiveToggles');
  if (!toggleRow) return;
  let hint = byId('mvLiveSuppressedHint');
  if (!nonPassCount) {
    if (hint) hint.remove();
    return;
  }
  if (!hint) {
    hint = document.createElement('button');
    hint.id = 'mvLiveSuppressedHint';
    hint.type = 'button';
    hint.className = 'mv-live-suppressed-hint';
    toggleRow.insertAdjacentElement('afterend', hint);
    hint.addEventListener('click', () => {
      const next = !_detectionsExpanded();
      _setDetectionsExpanded(next);
      // Re-render the panel immediately so the expand/collapse flips
      // without waiting for the next tick. S.session.lastFullData
      // (set in _renderFrame) carries the most recent backend reply.
      if (S.session?.lastFullData) _renderDetectionsPanel(S.session.lastFullData);
    });
  }
  hint.textContent = `${nonPassCount} verworfen (unter Schwelle oder gefiltert) — antippen für Details`;
}

// vh729 — one-shot diagnostic. Prints the state of every visual
// layer the user can't see when Simulieren looks black. Gated by
// S.session._diagLogged so the line fires exactly once per open.
// One console.warn per line so the lines stay readable in DevTools
// instead of folding into a single multi-line entry that's harder
// to copy-paste.

export function _renderTrailsOverlay() {
  // SIMU-FIX-03b · trails visibility is gated SOLELY by
  // `S.overlays.trails`. Independent of the pill-bar's own
  // visibility (which SIMU-02c animates in/out on tap). Persists
  // across pill-bar fade cycles.
  const svg = _ensureTrailsOverlay();
  if (!svg || !S.session) return;
  svg.style.display = S.overlays.trails ? 'block' : 'none';
  if (!S.overlays.trails) {
    svg.innerHTML = '';
    return;
  }
  const fs = S.session.lastFrameSize || { w: 1920, h: 1080 };
  svg.setAttribute('viewBox', `0 0 ${fs.w} ${fs.h}`);
  _positionSvgOverImage(svg);
  _refreshMediaRow();
  const rect = svg.getBoundingClientRect();
  if (_debugDiagOn()) {
    // A1 · same-shape rich row for trails. S.detBuffer length is the
    // number of buffered detection samples in the rolling window
    // (one entry per detection per tick, dropped after _LIVE_WINDOW_MS).
    const cs = window.getComputedStyle(svg);
    const wrap = byId('lightboxMediaWrap');
    const wrapBox = wrap?.getBoundingClientRect();
    const left = wrapBox ? Math.round(rect.left - wrapBox.left) : Math.round(rect.left);
    const top = wrapBox ? Math.round(rect.top - wrapBox.top) : Math.round(rect.top);
    _updateDiagStrip('trails', {
      buffer: S.detBuffer.length,
      viewBox: `${fs.w}×${fs.h}`,
      svgRect: `${Math.round(rect.width)}×${Math.round(rect.height)}@${left},${top}`,
      zIndex: cs.zIndex,
      display: cs.display,
      trailsOn: S.overlays.trails ? 'true' : 'false',
    });
  }
  // Same 0×0 guard as the bbox layer — wait for the image to size
  // before paint so the polylines don't land in a sub-pixel corner.
  if (rect.width <= 0 || rect.height <= 0) {
    _updateDiagStrip('position-fail', {
      svg: svg.id,
      svgRect: `${Math.round(rect.width)}×${Math.round(rect.height)}`,
    });
    svg.innerHTML = '';
    return;
  }
  // J2 · one trail per TRACK (not per class) so a trail matches that track's
  // bbox colour. Detections without a track number (motion-only) group by
  // label and render neutral grey via liveTrackColor's fallback. Pre-sort by
  // ms inside each group; detBuffer is push-order but a polling-cadence change
  // could technically interleave entries.
  const byTrack = new Map();
  for (const e of S.detBuffer) {
    const key =
      Number.isFinite(e.track_num) && e.track_num > 0 ? `t${e.track_num}` : `m:${e.label}`;
    if (!byTrack.has(key)) byTrack.set(key, []);
    byTrack.get(key).push(e);
  }
  const strokeW = Math.max(2, Math.round(fs.w / 720));
  const parts = [];
  for (const entries of byTrack.values()) {
    if (entries.length < 2) continue;
    entries.sort((a, b) => a.ms - b.ms);
    // Keep only the newest N centroids — same cap the recorded
    // Mediathek trail uses so the visual reads identically.
    const tail = entries.slice(-_LIVE_TRAIL_MAX_POINTS);
    const points = tail.map((e) => ({
      x: e.bbox[0] + e.bbox[2] / 2,
      y: e.bbox[1] + e.bbox[3] / 2,
    }));
    const c = liveTrackColor(entries[entries.length - 1].track_num);
    parts.push(buildTrailSvg(points, c, strokeW));
  }
  svg.innerHTML = parts.join('');
}

export function _renderZoneMaskOverlay() {
  // SIMU-FIX-03b · zones + masks visibility is gated SOLELY by
  // `S.overlays.zones` / `S.overlays.masks`. Independent of pill-bar
  // visibility. The two booleans are read once per render; the
  // canvas paints whichever combination is currently active.
  const canvas = _ensureZoneMaskOverlay();
  if (!canvas || !S.session) return;
  const showZones = S.overlays.zones;
  const showMasks = S.overlays.masks;
  if (!showZones && !showMasks) {
    const ctx = canvas.getContext('2d');
    if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    canvas.style.display = 'none';
    return;
  }
  canvas.style.display = 'block';
  const fs = S.session.lastFrameSize || { w: 1920, h: 1080 };
  const cam = (state.cameras || []).find((c) => c.id === S.session.camId) || {};
  // Normalise polygons through the shared resolver so source_w/h
  // are always present (modern stamp wins, legacy fall back to
  // preview_resolution / 1280×720 default).
  const zones = showZones
    ? (cam.zones || []).map((z) => normalizePolygon(z, cam)).filter(Boolean)
    : [];
  const masks = showMasks
    ? (cam.masks || []).map((m) => normalizePolygon(m, cam)).filter(Boolean)
    : [];
  // The MJPEG <img> never reports a reliable naturalWidth on Safari
  // (the multipart-replace stream confuses the natural-dims tracker).
  // Pass the backend-reported frame_size to the shared zone-layer
  // so its letterbox math uses the same coordinate base the rest of
  // the live-detect overlays (bbox, trails) already use.
  const liveImg = byId('lightboxImg');
  renderZoneLayerForMediaEl(canvas, liveImg, { zones, masks }, { srcW: fs.w, srcH: fs.h });
  _refreshMediaRow();
  const rect = canvas.getBoundingClientRect();
  if (_debugDiagOn()) {
    const cs = window.getComputedStyle(canvas);
    const wrap = byId('lightboxMediaWrap');
    const wrapBox = wrap?.getBoundingClientRect();
    const left = wrapBox ? Math.round(rect.left - wrapBox.left) : Math.round(rect.left);
    const top = wrapBox ? Math.round(rect.top - wrapBox.top) : Math.round(rect.top);
    _updateDiagStrip('zonemask', {
      zones: (cam.zones || []).length,
      masks: (cam.masks || []).length,
      viewBox: `${fs.w}×${fs.h}`,
      svgRect: `${Math.round(rect.width)}×${Math.round(rect.height)}@${left},${top}`,
      zIndex: cs.zIndex,
      display: cs.display,
      zonesOn: S.overlays.zones ? 'true' : 'false',
      masksOn: S.overlays.masks ? 'true' : 'false',
    });
  }
  if (rect.width <= 0 || rect.height <= 0) {
    _updateDiagStrip('position-fail', {
      svg: canvas.id,
      svgRect: `${Math.round(rect.width)}×${Math.round(rect.height)}`,
    });
  }
}
