// ─── camedit/timelapse-settings.js ─────────────────────────────────────────
// Stage 25 of the legacy.js → ES modules refactor — Timelapse subdomain.
// Profiles, period/target presets, camera list + mode grid in cam-edit,
// custom-preset chips, save handlers, loadTimelapse + toggleTimelapse
// for the camera-card buttons.
//
// The dashboard status pill lives in timelapse-status.js — it grew a
// live storage panel and this file was already past the 400-line ceiling.
// _tlFetchTimeline stays in legacy.js: despite the `tl` prefix it is
// timeline-fetch logic, paired with the dashboard-section slider.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { apiGet, apiPost } from '../core/api.js';
import { showToast } from '../core/toast.js';
import { loadAll } from '../live-update.js';
// getCameraIcon is gone with the settings section's camera tab bar and
// its "active" tag pills — the grid renders for one already-identified
// camera, so it never names a camera itself.
// The profile catalogue and every pure period→interval→disk
// computation live in _timelapse-model.js; this file is the renderer.
import {
  _TL_PROFILES_DEF,
  _TL_PERIOD_OPTIONS,
  _TL_CUSTOM_PRESETS,
  _TL_FIXED_FPS,
  _TL_MIN_INTERVAL_S,
  _tlClosestCustomPreset,
  _tlClosestPeriod,
  _tlIntervalLabel,
  _tlSpeedupLabel,
  _tlTargetLabel,
  _tlCalcInterval,
  _tlMaxTargetForPeriod,
  _tlResultDesc,
} from './_timelapse-model.js';

async function loadTimelapse(camId) {
  let r;
  try {
    r = await apiGet(`/api/camera/${encodeURIComponent(camId)}/timelapse`);
  } catch {
    showToast('Timelapse-Anfrage fehlgeschlagen.', 'error');
    return;
  }
  if (r.ok && r.url) {
    window.open(r.url, '_blank');
    return;
  }
  if (r.error === 'building') {
    showToast('Timelapse wird gerade gebaut – bitte in ~15 Sekunden nochmal klicken.', 'info');
    return;
  }
  if (r.error === 'no_frames') {
    showToast('Noch keine Bilder für heute aufgezeichnet.', 'warn');
    return;
  }
  if (r.error === 'timelapse disabled') {
    showToast(
      'Timelapse ist für diese Kamera deaktiviert. Bitte in den Kamera-Einstellungen aktivieren.',
      'warn',
    );
    return;
  }
  showToast('Kein Zeitraffer verfügbar für ' + (r.day || 'heute') + '.', 'warn');
}
window.loadTimelapse = loadTimelapse;

async function toggleTimelapse(camId, currentlyEnabled) {
  const cam =
    (state.config?.cameras || []).find((c) => c.id === camId) ||
    (state.cameras || []).find((c) => c.id === camId);
  if (!cam) return;
  const newEnabled = !currentlyEnabled;
  const payload = { ...cam, timelapse: { ...(cam.timelapse || {}), enabled: newEnabled } };
  try {
    const r = await apiPost('/api/settings/cameras', payload);
    if (!r?.ok) {
      showToast('Error: ' + (r?.error || 'unknown'), 'error');
      return;
    }
    showToast(newEnabled ? 'Timelapse enabled.' : 'Timelapse disabled.', 'success');
    await loadAll();
  } catch (e) {
    showToast('Save failed: ' + e.message, 'error');
  }
}
window.toggleTimelapse = toggleTimelapse;

/* Custom inline SVG icon set for timelapse compact cards — black/white/violet only */
const _TL_ICO_SPAN = `<svg width="16" height="14" viewBox="0 0 14 12" fill="none" aria-hidden="true"><rect x="0.75" y="0.75" width="2" height="10.5" rx="1" fill="currentColor"/><line x1="3.5" y1="6" x2="7" y2="6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><polygon points="7,3 13.5,6 7,9" fill="currentColor"/></svg>`;
const _TL_ICO_FRAMES = `<svg width="15" height="13" viewBox="0 0 13 11" fill="none" aria-hidden="true"><rect x="2.5" y="0.75" width="8" height="9.5" rx="1.2" stroke="currentColor" stroke-width="1.5"/><rect x="0.5" y="2.25" width="2" height="1.75" rx="0.5" fill="currentColor"/><rect x="0.5" y="7" width="2" height="1.75" rx="0.5" fill="currentColor"/><rect x="10.5" y="2.25" width="2" height="1.75" rx="0.5" fill="currentColor"/><rect x="10.5" y="7" width="2" height="1.75" rx="0.5" fill="currentColor"/></svg>`;
const _TL_ICO_SPEED = `<svg width="14" height="13" viewBox="0 0 12 11" fill="none" aria-hidden="true"><path d="M1 1.25L5 5.5L1 9.75" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/><path d="M6 1.25L10 5.5L6 9.75" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
function _renderTlModesGrid(cam) {
  const tl = cam.timelapse || {};
  const profs = tl.profiles || {};
  const cols = _TL_PROFILES_DEF
    .map((p) => {
      const prof = profs[p.key] || {};
      const enabled = !!prof.enabled;
      const targetS = prof.target_seconds ?? p.defaultTarget;
      const periodS = prof.period_seconds ?? p.defaultPeriod;
      // E2 · fps is always 15 now (backend lock + this UI no longer
      // exposes a selector). Legacy profile fps values are read from
      // settings but ignored; the hidden input below carries the
      // fixed 15 to the save handler.
      const profFps = _TL_FIXED_FPS;
      const isCustom = p.key === 'custom';
      const minT = p.minTarget || 10;
      // E2 · effective max target derived from the 8 s × 15 fps
      // capture floor for this profile's period. Caps at the profile's
      // own maxTarget when that's tighter (long periods like yearly
      // keep their declared bound).
      const profileMax = p.maxTarget || 900;
      const maxT = _tlMaxTargetForPeriod(periodS, profileMax);
      const clampedTarget = Math.max(minT, Math.min(maxT, targetS));
      const cid = esc(cam.id);
      const pk = p.key;
      // Read-only "15 fps" indicator + a hidden form input so existing
      // save logic keeps writing the field. No <select>, no chrome.
      const fpsSelectHtml = `<div class="tl-fps-readout" aria-label="Video-Framerate"><span class="tl-fps-readout-num">${_TL_FIXED_FPS}</span><span class="tl-fps-readout-unit">fps</span></div>
      <input type="hidden" id="tlProfFps_${cid}_${pk}" value="${_TL_FIXED_FPS}" />`;
      let controlHtml;
      if (isCustom) {
        const currentKey = `${periodS},${clampedTarget}`;
        const closestKey = _tlClosestCustomPreset(periodS, clampedTarget);
        const selectedKey = _TL_CUSTOM_PRESETS.some(
          (pp) => `${pp.period},${pp.target}` === currentKey,
        )
          ? currentKey
          : closestKey;
        controlHtml = `<div class="field-wrap">
        <select id="tlProfPreset_${cid}_${pk}" style="width:100%"
          onchange="_tlApplyCustomPreset('${cid}','${pk}',this.value)">
          ${_TL_CUSTOM_PRESETS
            .map((pp) => {
              const k = `${pp.period},${pp.target}`;
              return `<option value="${k}"${k === selectedKey ? ' selected' : ''}>${esc(pp.label)}</option>`;
            })
            .join('')}
        </select>
        <span class="field-label">Timelapse-Profil</span>
      </div>
      <input type="hidden" id="tlProfTarget_${cid}_${pk}" value="${clampedTarget}" />
      <input type="hidden" id="tlProfPeriod_${cid}_${pk}" value="${periodS}" />`;
      } else {
        // E2 · slider max is the dynamic _tlMaxTargetForPeriod ceiling
        // (= floor(period/(8*15))) intersected with the profile's own
        // declared max — keeps yearly's 2700 s cap, tightens daily's
        // 180 s when it would otherwise allow sub-8 s capture intervals.
        controlHtml = `<div class="field-wrap">
        <div style="display:flex;align-items:center;gap:8px">
          <input type="range" id="tlProfTarget_${cid}_${pk}" min="${minT}" max="${maxT}" step="${p.step || 10}" value="${clampedTarget}" style="flex:1;accent-color:#a855f7"
            oninput="_tlRefreshDesc('${cid}','${pk}')" />
          <span id="tlProfTargetLbl_${cid}_${pk}" style="font-size:11px;color:#a855f7;font-weight:700;min-width:36px;text-align:right">${_tlTargetLabel(clampedTarget)}</span>
        </div>
        <span class="field-label">Zieldauer Video</span>
      </div>
      <input type="hidden" id="tlProfPeriod_${cid}_${pk}" value="${periodS}" />`;
      }
      return `<div class="tl-mode-col${enabled ? ' tl-mode-col--on' : ''}" id="tlProfCard_${cid}_${pk}">
      <div class="tl-mode-col-head">
        <div>
          <div class="tl-mode-col-name">${esc(p.label)}</div>
        </div>
        <label class="switch switch-sm" onclick="event.stopPropagation()">
          <input type="checkbox" id="tlProf_${cid}_${pk}" ${enabled ? 'checked' : ''}
            onchange="byId('tlProfCard_${cid}_${pk}').classList.toggle('tl-mode-col--on',this.checked);_tlRefreshDesc('${cid}','${pk}')" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="tl-mode-col-desc" id="tlProfDesc_${cid}_${pk}">${_tlResultDesc(periodS, clampedTarget, profFps)}</div>
      ${controlHtml}
      ${fpsSelectHtml}
    </div>`;
    })
    .join('');
  return `<div class="tl-modes-grid">${cols}</div>
    <div style="display:flex;justify-content:flex-end;margin-top:8px">
      <button class="btn btn-save" onclick="saveTlCameraProfiles('${esc(cam.id)}')"><svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 2.5h8L13.5 5v8.5h-11z"/><polyline points="5,2.5 5,6.5 10,6.5 10,2.5"/><polyline points="4.5,13.5 4.5,9 11.5,9 11.5,13.5"/></svg>Speichern</button>
    </div>`;
}
window._tlApplyCustomPreset = function (camId, profKey, val) {
  const [periodS, targetS] = (val || '').split(',').map((x) => parseInt(x) || 0);
  const pEl = byId(`tlProfPeriod_${camId}_${profKey}`);
  const tEl = byId(`tlProfTarget_${camId}_${profKey}`);
  if (pEl) pEl.value = periodS;
  if (tEl) tEl.value = targetS;
  window._tlRefreshDesc(camId, profKey);
};
// _renderTlProfileCards replaced by _renderTlModesGrid (4-column grid).
// selectTlCam is gone with the settings section's camera tab bar — the
// grid now renders for the one camera whose edit panel is open, so there
// is nothing left to select between.
window._tlRefreshDesc = function (camId, profKey) {
  const targetEl = byId(`tlProfTarget_${camId}_${profKey}`);
  const periodEl = byId(`tlProfPeriod_${camId}_${profKey}`);
  const descEl = byId(`tlProfDesc_${camId}_${profKey}`);
  const lblEl = byId(`tlProfTargetLbl_${camId}_${profKey}`);
  if (!targetEl || !periodEl) return;
  // E2 · fps always the constant; hidden input carries it but we
  // don't read from it here — the constant IS the source of truth.
  if (lblEl) lblEl.textContent = _tlTargetLabel(parseInt(targetEl.value) || 10);
  if (descEl) descEl.innerHTML = _tlResultDesc(periodEl.value, targetEl.value, _TL_FIXED_FPS);
};
window.saveTlCameraProfiles = async function (camId) {
  const cam = (state.cameras || []).find((c) => c.id === camId);
  if (!cam) return;
  const profiles = {};
  let latestFps = _TL_FIXED_FPS;
  for (const p of _TL_PROFILES_DEF) {
    const enabledEl = byId(`tlProf_${camId}_${p.key}`);
    const targetEl = byId(`tlProfTarget_${camId}_${p.key}`);
    const periodEl = byId(`tlProfPeriod_${camId}_${p.key}`);
    // E2 · always write 15. The hidden tlProfFps_<…> input reads the
    // same constant; we hard-code here so a tampered DOM can't slip
    // a legacy 24/25 past the save handler.
    profiles[p.key] = {
      enabled: !!enabledEl?.checked,
      target_seconds: parseInt(targetEl?.value) || p.defaultTarget,
      period_seconds: parseInt(periodEl?.value) || p.defaultPeriod,
      fps: _TL_FIXED_FPS,
    };
  }
  const anyEnabled = Object.values(profiles).some((p) => p.enabled);
  // Keep a camera-level fps too (most recently edited) for legacy readers.
  const payload = {
    ...cam,
    timelapse: { ...(cam.timelapse || {}), enabled: anyEnabled, fps: latestFps, profiles },
  };
  await apiPost('/api/settings/cameras', payload);
  showToast(`Timelapse für ${cam.name} gespeichert.`, 'success');
  await loadAll();
  // Re-render from the reloaded camera so the grid shows what was
  // actually persisted, not what was typed. loadAll() replaces
  // state.cameras, so the stale `cam` above must not be reused here.
  const content = byId('camTlModes');
  const fresh = (state.cameras || []).find((c) => c.id === camId);
  if (content && fresh) content.innerHTML = _renderTlModesGrid(fresh);
};

// (Wizard form seeds + tab/prev/next/finish bindings moved into
//  camedit/wizard.js in stage 25 C.)

// CAM_COLORS, camColor, hexToRgba, getMediaAccentColor, fmtMedia*,
// mediaCardHTML, _MOC_*, renderMediaOverview, _setActiveMocCard,
// drilldown openers, _goToPage, renderMediaPagination, _ensureProcessingPoll,
// renderMediaGrid, _MEDIA_TITLE_SVG, updateMediaSectionTitle, syncMediaPills:
// all extracted to mediathek/orchestration.js in stage 23. The dashboard
// status pill (and _TL_FILMSTRIP with it) moved to timelapse-status.js
// when this file passed the 400-line ceiling.

// Public surface — bridges in legacy.js consume these by name.

export { loadTimelapse, toggleTimelapse };
// Consumed by timelapse-status.js — the profile catalogue and the
// interval formatter are shared, not duplicated. _renderTlModesGrid is
// consumed by edit-panel.js, which mounts it into the camera's own
// Timelapse tab.
export { _TL_PROFILES_DEF, _tlIntervalLabel, _renderTlModesGrid };

// The _updateTlActiveTags bridge is gone with #tlActiveTags, the chip row
// in the removed settings-section header. Which cameras record is answered
// by the dashboard's "Timelapse aktiv" tile now — one place, not two.
