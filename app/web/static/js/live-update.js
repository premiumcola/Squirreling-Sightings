// ─── live-update.js ────────────────────────────────────────────────────────
// Stage 6 of the legacy.js → ES modules refactor — the 3-second
// camera-status poll + the cross-domain loadAll() bootstrapper. Both
// orchestrate every other module by calling its exported render
// function; for renderers that still live in legacy.js we resolve via
// window.X (transitional — the bridge shrinks one stage at a time as
// each domain extracts).
import { state } from './core/state.js';
import { byId } from './core/dom.js';
import { j } from './core/api.js';
import {
  renderDashboard, showCameraReloadAnimation,
  startPreviewRefresh, startBgLuminanceMonitor, _refreshLivePillForCard,
  _resetFailedSnapshotIds,
} from './dashboard.js';
import { renderTimeline } from './timeline.js';
import { _renderGlobalStatusRows } from './camedit/detection.js';
import {
  renderShell, renderCameraSettings, renderProfiles, renderAudit,
  hydrateSettings,
} from './camedit/index.js';
import { loadMediaStorageStats } from './chrome/storage-stats.js';
import { hydrateTelegram, initTelegramTabs } from './telegram.js';
import { hydratePushUI } from './push.js';
import { _renderAlertStatusStrip } from './alerting.js';

let _liveUpdateInterval = null;
const _prevCamStatuses = new Map();

export function startLiveUpdate() {
  if (_liveUpdateInterval) clearInterval(_liveUpdateInterval);
  state.cameras.forEach(c => _prevCamStatuses.set(c.id, c.status));
  _liveUpdateInterval = setInterval(async () => {
    try {
      const r = await j('/api/cameras');
      let needsRedraw = false;
      (r.cameras || []).forEach(c => {
        const prev = _prevCamStatuses.get(c.id);
        _prevCamStatuses.set(c.id, c.status);
        if (prev !== c.status) {
          const wasActive = prev === 'active';
          const nowActive = c.status === 'active';
          if (wasActive !== nowActive) needsRedraw = true;
          if (c.status === 'starting') showCameraReloadAnimation(c.id);
          // Camera settings list badge
          const item = byId('cameraSettingsList')?.querySelector(`[data-camid="${CSS.escape(c.id)}"]`);
          if (item) {
            const stCol = s => s === 'active' ? 'good' : s === 'error' ? 'danger' : 'warn';
            const b = item.querySelector('.badge');
            if (b) { b.className = `badge ${stCol(c.status)}`; b.textContent = c.status || '—'; }
          }
        }
        // Always update live pill and FPS display
        const card = byId('cameraCards')?.querySelector(`[data-camid="${CSS.escape(c.id)}"]`);
        if (card) {
          const livePill = card.querySelector('.cv-pill-live-wrap');
          if (livePill) {
            const isActive = c.status === 'active';
            livePill.classList.toggle('cv-live-active', isActive);
            livePill.classList.toggle('cv-live-off', !isActive);
            // Renamed from .cv-live-exp-header during the ground-up
            // rewrite of the pill — see 03-dashboard.css for the new
            // structure. The inner span carrying "Livestream aktiv /
            // inaktiv" is the second span (after the dot) under the
            // detail header.
            const hdr = livePill.querySelector('.cv-live-detail-header span:last-child');
            if (hdr) hdr.textContent = 'Livestream ' + (isActive ? 'aktiv' : 'inaktiv');
            const cached = (state.cameras || []).find(x => x.id === c.id);
            if (cached) {
              cached.preview_fps = c.preview_fps;
              cached.stream_mode = c.stream_mode;
              cached.preview_resolution = c.preview_resolution;
              cached.resolution = c.resolution;
              cached.status = c.status;
            }
            _refreshLivePillForCard(c.id);
          }
          // Object-icon red glow: each .cv-surveil-tgt whose data-cls
          // is in c.recent_detections (within the 10 s window the
          // backend filters to) gets .is-hot. Tgts whose class is
          // absent on this tick get .is-hot stripped. classList.toggle
          // with a boolean second arg is idempotent — the DOM only
          // mutates when the state actually flips, so steady-state
          // polls don't churn. Backend feeds this list only when an
          // event was finalised, so absence of glow during a walk-
          // through means no event ever fired (capture/motion/confirm
          // upstream of telegram).
          const recentSet = new Set((c.recent_detections || []).map(d => d.label));
          card.querySelectorAll('.cv-surveil-tgt').forEach(tgt => {
            const cls = tgt.dataset.cls;
            tgt.classList.toggle('is-hot', !!cls && recentSet.has(cls));
          });
        }
      });
      if (needsRedraw) {
        state.cameras = r.cameras || state.cameras;
        renderDashboard();
      }
      // Erkennung + Alerting status strips refresh on every tick.
      // Both are direct named imports since stages 8 + 17.
      _renderGlobalStatusRows();
      _renderAlertStatusStrip();
    } catch { /* silent */ }
  }, 3000);
}

// Cross-domain bootstrap — fetch the bootstrap+config+cameras+timeline
// triad, then invoke every domain's render. Renderers from already-
// extracted modules import directly; renderers still in legacy.js
// route via window.X. Order matches the original byte-for-byte so
// shell-render → dashboard → timeline → settings-list → … ships in
// the same sequence.
export async function loadAll() {
  if (typeof window._restoreEditWrapper === 'function') window._restoreEditWrapper();
  state.bootstrap = await j('/api/bootstrap');
  state.config    = await j('/api/config');
  state.cameras   = (await j('/api/cameras')).cameras || [];
  _resetFailedSnapshotIds();
  if (typeof window._updateMobileDockLiveDot === 'function') window._updateMobileDockLiveDot();
  state.timeline = await j(`/api/timeline?hours=${state.tlHours || 168}${state.label ? `&label=${encodeURIComponent(state.label)}` : ''}`);
  await loadMediaStorageStats();
  renderShell();
  renderDashboard();
  renderTimeline();
  renderCameraSettings();
  await renderProfiles();
  await renderAudit();
  hydrateSettings();
  hydrateTelegram();
  initTelegramTabs();
  hydratePushUI();
  if (typeof window.initWeatherTabs === 'function')       window.initWeatherTabs();
  if (typeof window.initWeatherStats === 'function')      window.initWeatherStats();
  if (typeof window.loadWeatherSightings === 'function')  await window.loadWeatherSightings();
  if (typeof window.hydrateWeatherSettings === 'function') window.hydrateWeatherSettings();
  if (typeof window.loadTlStatus === 'function')          window.loadTlStatus();
  if (typeof window._updateTlActiveTags === 'function')   window._updateTlActiveTags(state.cameras || []);
  if (state.bootstrap.needs_wizard && typeof window.openWizard === 'function') window.openWizard();
  const wizBtn = byId('openWizardBtn');
  if (wizBtn) wizBtn.classList.toggle('hidden', !!state.bootstrap?.wizard_completed || !state.bootstrap?.needs_wizard);
  startPreviewRefresh();
  startBgLuminanceMonitor();
  if (typeof window.updateMediaSectionTitle === 'function') window.updateMediaSectionTitle();
}

// loadAll has many callsites in legacy.js (toggleArm, cam-edit save,
// quick-delete, etc.) — exposing on window keeps those callers
// resolving without a per-callsite import edit. Once those domains
// migrate they can switch to a named import.
window.loadAll = loadAll;
