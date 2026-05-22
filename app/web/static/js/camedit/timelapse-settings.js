// ─── camedit/timelapse-settings.js ─────────────────────────────────────────
// Stage 25 of the legacy.js → ES modules refactor — Timelapse subdomain.
// Profiles, period/target presets, camera list + mode grid in cam-edit,
// custom-preset chips, save handlers, status-bar pill on the dashboard,
// loadTimelapse + toggleTimelapse for the camera-card buttons.
// Pure code move from legacy.js, no behaviour changes.
//
// _TL_FILMSTRIP travels with renderTlStatusBar — it is the only consumer
// now that the Mediathek timelapse-card moved to orchestration.js.
// _tlFetchTimeline stays in legacy.js: despite the `tl` prefix it is
// timeline-fetch logic, paired with the dashboard-section slider.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { j, apiGet, apiPost } from '../core/api.js';
import { showToast } from '../core/toast.js';
import { loadAll } from '../live-update.js';
// _renderTlCameraList + _updateTlActiveTags use getCameraIcon to
// stamp the right thematic emoji (🐿️ / 🌿 / 🚗 / 📷) into each cam
// row + the "active" tag pill. Missing this import was the cause of
// "Fehler: getCameraIcon is not defined" on the Timelapse Settings tab.
import { getCameraIcon } from '../core/icons.js';

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

const _TL_PROFILES_DEF = [
  {
    key: 'daily',
    label: 'Täglich',
    defaultPeriod: 86400,
    defaultTarget: 60,
    minTarget: 10,
    maxTarget: 180,
    step: 5,
  },
  {
    key: 'weekly',
    label: 'Wöchentlich',
    defaultPeriod: 604800,
    defaultTarget: 120,
    minTarget: 30,
    maxTarget: 360,
    step: 10,
  },
  {
    key: 'monthly',
    label: 'Monatlich',
    defaultPeriod: 2592000,
    defaultTarget: 300,
    minTarget: 60,
    maxTarget: 600,
    step: 15,
  },
  {
    key: 'quarterly',
    label: 'Quartal',
    defaultPeriod: 7776000,
    defaultTarget: 600,
    minTarget: 120,
    maxTarget: 1800,
    step: 30,
  },
  {
    key: 'yearly',
    label: 'Jährlich',
    defaultPeriod: 31536000,
    defaultTarget: 900,
    minTarget: 300,
    maxTarget: 2700,
    step: 60,
  },
  {
    key: 'custom',
    label: 'Benutzerdefiniert',
    defaultPeriod: 3600,
    defaultTarget: 30,
    minTarget: 10,
    maxTarget: 2700,
    step: 10,
  },
];
const _TL_PERIOD_OPTIONS = [
  { v: 900, l: '15 Min' },
  { v: 3600, l: '1 Stunde' },
  { v: 21600, l: '6 Stunden' },
  { v: 43200, l: '12 Stunden' },
  { v: 86400, l: '1 Tag' },
  { v: 259200, l: '3 Tage' },
  { v: 604800, l: '1 Woche' },
  { v: 1209600, l: '2 Wochen' },
  { v: 2592000, l: '1 Monat' },
  { v: 7776000, l: '1 Quartal' },
  { v: 31536000, l: '1 Jahr' },
];
// Period+target presets for the "Benutzerdefiniert" profile — the user picks
// one tuple rather than two independent controls. Value is "<periodS>,<targetS>".
const _TL_CUSTOM_PRESETS = [
  { period: 900, target: 60, label: '15 Min → 1 Min Video' },
  { period: 1800, target: 60, label: '30 Min → 1 Min Video' },
  { period: 3600, target: 30, label: '1 Std → 30 Sek Video' },
  { period: 3600, target: 60, label: '1 Std → 1 Min Video' },
  { period: 10800, target: 60, label: '3 Std → 1 Min Video' },
  { period: 21600, target: 60, label: '6 Std → 1 Min Video' },
  { period: 21600, target: 120, label: '6 Std → 2 Min Video' },
  { period: 43200, target: 60, label: '12 Std → 1 Min Video' },
  { period: 43200, target: 120, label: '12 Std → 2 Min Video' },
  { period: 86400, target: 30, label: '24 Std → 30 Sek Video' },
  { period: 86400, target: 60, label: '24 Std → 1 Min Video' },
  { period: 86400, target: 120, label: '24 Std → 2 Min Video' },
];
function _tlClosestCustomPreset(periodS, targetS) {
  const pN = parseInt(periodS) || 3600,
    tN = parseInt(targetS) || 60;
  let best = _TL_CUSTOM_PRESETS[0],
    bd = Infinity;
  for (const p of _TL_CUSTOM_PRESETS) {
    // rank exact period match above exact target match
    const d = Math.abs(Math.log(p.period / pN)) * 2 + Math.abs(Math.log(p.target / tN));
    if (d < bd) {
      bd = d;
      best = p;
    }
  }
  return `${best.period},${best.target}`;
}
function _tlClosestPeriod(v) {
  const n = parseInt(v) || 3600;
  return _TL_PERIOD_OPTIONS.reduce((a, b) => (Math.abs(b.v - n) < Math.abs(a.v - n) ? b : a)).v;
}
// E2 · fps is now a system-wide constant (matches the backend's hard
// 15 fps lock from settings/migrations.py · migrate_timelapse_intervals).
// The user-tunable <select> is gone; the field still round-trips via
// a hidden input so the save payload shape is unchanged for any
// downstream consumer.
const _TL_FIXED_FPS = 15;
// _TL_MIN_INTERVAL_S mirrors the backend's 8 s capture-interval floor.
// _tlCalcInterval rounds up to this floor; the slider max bound on each
// non-custom profile is derived from period / (floor × fps) so the user
// can't choose a target the encoder would have to back-fill below 8 s.
const _TL_MIN_INTERVAL_S = 8;
function _tlFmtInterval(secs) {
  const s = Number(secs);
  if (!isFinite(s) || s <= 0) return '—';
  if (s < 10) {
    // 0.6 → "0,6s"  ·  5 → "5s"  ·  5.5 → "5,5s"
    const r = Math.round(s * 10) / 10;
    const str = r === Math.floor(r) ? String(Math.floor(r)) : r.toFixed(1).replace('.', ',');
    return `${str}s`;
  }
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}min`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}
function _tlSpeedupLabel(v) {
  if (v >= 10000) return (Math.round(v / 100) / 10).toFixed(1) + 'k×';
  return v + '×';
}
/* Custom inline SVG icon set for timelapse compact cards — black/white/violet only */
const _TL_ICO_SPAN = `<svg width="16" height="14" viewBox="0 0 14 12" fill="none" aria-hidden="true"><rect x="0.75" y="0.75" width="2" height="10.5" rx="1" fill="currentColor"/><line x1="3.5" y1="6" x2="7" y2="6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/><polygon points="7,3 13.5,6 7,9" fill="currentColor"/></svg>`;
const _TL_ICO_FRAMES = `<svg width="15" height="13" viewBox="0 0 13 11" fill="none" aria-hidden="true"><rect x="2.5" y="0.75" width="8" height="9.5" rx="1.2" stroke="currentColor" stroke-width="1.5"/><rect x="0.5" y="2.25" width="2" height="1.75" rx="0.5" fill="currentColor"/><rect x="0.5" y="7" width="2" height="1.75" rx="0.5" fill="currentColor"/><rect x="10.5" y="2.25" width="2" height="1.75" rx="0.5" fill="currentColor"/><rect x="10.5" y="7" width="2" height="1.75" rx="0.5" fill="currentColor"/></svg>`;
const _TL_ICO_SPEED = `<svg width="14" height="13" viewBox="0 0 12 11" fill="none" aria-hidden="true"><path d="M1 1.25L5 5.5L1 9.75" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/><path d="M6 1.25L10 5.5L6 9.75" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
function _tlIntervalLabel(interval_s) {
  if (interval_s < 60) return interval_s + 's';
  if (interval_s < 3600) return Math.round(interval_s / 60) + 'min';
  if (interval_s < 86400) return Math.round(interval_s / 3600) + 'h';
  return Math.round(interval_s / 86400) + 'd';
}
function _tlTargetLabel(secs) {
  const n = parseInt(secs) || 0;
  if (n < 60) return n + 's';
  return Math.round(n / 60) + 'min';
}
function _tlCalcInterval(periodS, targetS, fps) {
  // E2 · floor lifted 2 → 8 to match the system-wide capture floor.
  // Returns {interval_s, clamped} so the caller (e.g. _tlResultDesc)
  // can surface a "video will be shorter than chosen" hint when the
  // raw arithmetic wants something tighter than 8 s.
  const pN = parseInt(periodS) || 86400;
  const tN = Math.max(1, parseInt(targetS) || 60);
  const fN = Math.max(1, parseInt(fps) || _TL_FIXED_FPS);
  const raw = pN / (tN * fN);
  if (raw < _TL_MIN_INTERVAL_S) return { interval_s: _TL_MIN_INTERVAL_S, clamped: true, raw: raw };
  return { interval_s: Math.round(raw), clamped: false, raw: raw };
}
// E2 · derived max target so the slider can't be dragged into the
// clamp zone for a given period. Non-custom profiles call this when
// rendering + when the period changes.
function _tlMaxTargetForPeriod(periodS, profileMax) {
  const pN = parseInt(periodS) || 86400;
  const ceiling = Math.floor(pN / (_TL_MIN_INTERVAL_S * _TL_FIXED_FPS));
  return Math.max(1, Math.min(profileMax || ceiling, ceiling));
}
function _updateTlActiveTags(cameras) {
  const wrap = byId('tlActiveTags');
  if (!wrap) return;
  const active = (cameras || []).filter((cam) =>
    _TL_PROFILES_DEF.some((p) => (cam.timelapse || {}).profiles?.[p.key]?.enabled),
  );
  if (!active.length) {
    wrap.innerHTML = '';
    return;
  }
  wrap.innerHTML = active
    .map((cam) => `<span class="tl-cam-tag">${getCameraIcon(cam.name)} ${esc(cam.name)}</span>`)
    .join('');
}
window.loadTlSettings = async function () {
  const content = byId('tlSettingsContent');
  if (!content) return;
  content.innerHTML = '<div class="small muted" style="padding:10px 2px">Lade...</div>';
  try {
    const cameras = state.cameras || [];
    _updateTlActiveTags(cameras);
    content.innerHTML = _renderTlCameraList(cameras);
  } catch (e) {
    content.innerHTML = `<div class="small muted" style="padding:10px 2px">Fehler: ${esc(e.message)}</div>`;
  }
};
function _renderTlCameraList(cameras) {
  if (!cameras.length)
    return '<div class="small muted" style="padding:10px 2px">Keine Kameras konfiguriert.</div>';
  const firstCam = cameras[0];
  const tabs = cameras
    .map((cam, i) => {
      return `<button type="button" class="set-tab${i === 0 ? ' active' : ''}" id="tlTab_${esc(cam.id)}" onclick="selectTlCam('${esc(cam.id)}')">
      ${getCameraIcon(cam.name)} ${esc(cam.name)}
    </button>`;
    })
    .join('');
  return `<div class="set-tabs" id="tlCamTabs">${tabs}</div>
    <div class="sec-content" id="tlCamContent">${_renderTlModesGrid(firstCam)}</div>`;
}
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
window.selectTlCam = function (camId) {
  document
    .querySelectorAll('#tlCamTabs .set-tab')
    .forEach((b) => b.classList.toggle('active', b.id === `tlTab_${camId}`));
  const cam = (state.cameras || []).find((c) => c.id === camId);
  const content = byId('tlCamContent');
  if (cam && content) content.innerHTML = _renderTlModesGrid(cam);
};
// Renamed from _tlPeriodLabel — the original name collided with the
// item-shaped _tlPeriodLabel below at line ~5966. As a regular
// <script> the duplicate function declaration silently overrode this
// one, leaving "Timelapse" as the period label everywhere this was
// called; in module mode the duplicate is a SyntaxError. Restoring
// the original numeric→German-duration intent fixes a long-latent UI
// bug as a side effect of the rename.
function _tlDurationLabel(s) {
  const n = parseInt(s) || 0;
  if (n >= 31536000)
    return Math.round(n / 31536000) + ' Jahr' + (Math.round(n / 31536000) !== 1 ? 'e' : '');
  if (n >= 2592000)
    return Math.round(n / 2592000) + ' Monat' + (Math.round(n / 2592000) !== 1 ? 'e' : '');
  if (n >= 604800)
    return Math.round(n / 604800) + ' Woche' + (Math.round(n / 604800) !== 1 ? 'n' : '');
  if (n >= 86400) return Math.round(n / 86400) + ' Tag' + (Math.round(n / 86400) !== 1 ? 'e' : '');
  if (n >= 3600) return Math.round(n / 3600) + ' Stunde' + (Math.round(n / 3600) !== 1 ? 'n' : '');
  return Math.round(n / 60) + ' Min';
}
function _tlResultDesc(periodS, targetS, fps) {
  const pN = parseInt(periodS) || 86400,
    tN = parseInt(targetS) || 60,
    fN = parseInt(fps) || _TL_FIXED_FPS;
  const ci = _tlCalcInterval(pN, tN, fN);
  // E2 · when the clamp fires, the EFFECTIVE total frame count is
  // capped at period/floor and the realised video is shorter than
  // the user asked for. Surface that explicitly instead of silently
  // padding the encoder. ``effectiveFrames`` is what actually lands
  // on disk; ``realisedDuration`` is what the user will see in the
  // mediathek.
  const intervalS = ci.interval_s;
  const effectiveFrames = Math.max(1, Math.floor(pN / intervalS));
  const realisedDuration = effectiveFrames / fN;
  const requestedFrames = Math.max(1, Math.round(tN * fN));
  const totalFrames = ci.clamped ? effectiveFrames : requestedFrames;
  const periodLabel = _tlDurationLabel(pN);
  const intervalLabel = _tlFmtInterval(intervalS);
  const compression = Math.round(pN / Math.max(1, tN));
  // ~40 KB per JPEG at q≈72; sub-1s interval drops to q=50 ≈ 26 KB.
  const perFrameKb = intervalS < 1 ? 26 : 40;
  const diskMb = Math.max(1, Math.round((totalFrames * perFrameKb) / 1024));
  const targetLine = ci.clamped
    ? `<div class="tl-drow tl-drow-warn"><span class="tl-drow-ico">⚠</span><span class="tl-drow-text">Intervall auf Minimum ${_TL_MIN_INTERVAL_S} s begrenzt — Video wird ${Math.round(realisedDuration)} s statt ${tN} s lang</span></div>`
    : '';
  return `<div class="tl-drow"><span class="tl-drow-ico">⏱</span><span class="tl-drow-text">${periodLabel} → ${tN}s Video</span></div>${targetLine}<div class="tl-drow"><span class="tl-drow-ico">📸</span><span class="tl-drow-text">${totalFrames} Frames · Alle ${intervalLabel} ein Foto</span></div><div class="tl-drow tl-drow-accent"><span class="tl-drow-ico">⚡</span><span class="tl-drow-text">${compression}× Zeitraffer · ~${diskMb} MB Speicher</span></div>`;
}
// _renderTlProfileCards replaced by _renderTlModesGrid (4-column grid)
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
// toggleTlCamCard replaced by selectTlCam (tab-based camera selector)
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
  _updateTlActiveTags(state.cameras || []);
  const content = byId('tlSettingsContent');
  if (content) {
    content.innerHTML = _renderTlCameraList(state.cameras || []);
    window.selectTlCam(camId);
  }
};

// ── Timelapse Status Bar (Dashboard in Cameras section) ───────────────────────
window._tlStatus = null;
async function loadTlStatus() {
  try {
    window._tlStatus = await j('/api/timelapse/status');
    renderTlStatusBar();
  } catch (_err) {
    /* silent */
  }
}
function renderTlStatusBar() {
  const bar = byId('tlStatusBar');
  if (!bar) return;
  const s = window._tlStatus;
  if (!s || s.active_count === 0) {
    bar.innerHTML = '';
    return;
  }
  const activeCams = (s.cameras || []).filter((c) => c.any_active);
  const panelId = 'tlSbPanel';
  bar.innerHTML = `
    <div class="tl-sb-pill" onclick="byId('${panelId}').classList.toggle('hidden')">
      ${_TL_FILMSTRIP}
      <span>Timelapse aktiv</span>
      <span class="tl-sb-count">${activeCams.length}</span>
    </div>
    <div class="tl-sb-panel hidden" id="${panelId}">
      ${activeCams
        .map(
          (cam) => `
        <div class="tl-sb-cam">
          <div class="tl-sb-cam-name">${esc(cam.name)}</div>
          <div class="tl-sb-profiles">
            ${_TL_PROFILES_DEF
              .map((p) => {
                const prof = cam.profiles[p.key];
                if (!prof?.enabled) return '';
                return `<div class="tl-sb-profile">
                <span class="tl-sb-prof-name">${esc(p.label)}</span>
                <span class="tl-sb-prof-frames">${prof.frame_count} Frames heute</span>
                <span class="tl-sb-prof-interval">alle ~${_tlIntervalLabel(prof.interval_s)}</span>
              </div>`;
              })
              .join('')}
          </div>
        </div>`,
        )
        .join('')}
      <div class="tl-sb-footer small muted">Stand: ${esc(s.today || '—')}</div>
    </div>`;
}

// (Wizard form seeds + tab/prev/next/finish bindings moved into
//  camedit/wizard.js in stage 25 C.)

// CAM_COLORS, camColor, hexToRgba, getMediaAccentColor, fmtMedia*,
// mediaCardHTML, _MOC_*, renderMediaOverview, _setActiveMocCard,
// drilldown openers, _goToPage, renderMediaPagination, _ensureProcessingPoll,
// renderMediaGrid, _MEDIA_TITLE_SVG, updateMediaSectionTitle, syncMediaPills:
// all extracted to mediathek/orchestration.js in stage 23. _TL_FILMSTRIP
// stays here — still referenced by the timelapse-card snippet above.
const _TL_FILMSTRIP = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#c4b5fd" stroke-width="2" stroke-linecap="round" style="flex-shrink:0"><line x1="6" y1="3" x2="18" y2="3"/><line x1="6" y1="21" x2="18" y2="21"/><polygon points="7,4 17,4 12,12" fill="#c4b5fd" opacity=".8"/><polygon points="12,12 7,20 17,20" fill="#c4b5fd" opacity=".5"/></svg>`;

// Public surface — bridges in legacy.js consume these by name.

export { loadTimelapse, toggleTimelapse, loadTlStatus, _updateTlActiveTags };

// ── window.* bridges ────────────────────────────────────────────────────────
// loadAll() in live-update.js looks these up by global name; without
// them the dashboard timelapse status pill stays empty and the cam-
// edit Timelapse-Tab "active" tags never refresh.
window.loadTlStatus = loadTlStatus;
window._updateTlActiveTags = _updateTlActiveTags;
