// ─── camedit/index.js ──────────────────────────────────────────────────────
// Stage 25 D of the legacy.js → ES modules refactor — camera-settings
// root: hero/sidebar shell renderer, camera list, edit-panel hydrator
// (the big editCamera function), profiles + audit + arm toggles, the
// Settings tab hydrator, system info panel, cam-edit tab bar,
// config import/export. Pure code move from legacy.js,
// no behaviour changes.
//
// Most cam-edit functionality already lives in dedicated modules
// (camedit/rtsp.js, whitelist.js, detection.js, recovery.js,
// camera_id.js, panel.js, coral-test.js, timelapse-settings.js,
// wizard.js, discovery.js); this file is the orchestration layer that
// wires them together when a camera is opened for editing.
//
// Public surface bridged on window for inline onclicks + loadAll() in
// live-update.js: editCamera, toggleArm, toggleCameraEnabled,
// _reconnectCam, _quickDeleteCamera, _flashDetection,
// renderShell, renderCameraSettings, renderProfiles, renderAudit,
// hydrateSettings.
import { state } from '../core/state.js';
import { byId, esc } from '../core/dom.js';
import { j, apiPost } from '../core/api.js';
import { showToast, showConfirm } from '../core/toast.js';
import { getCameraIcon } from '../core/icons.js';
import { loadAll } from '../live-update.js';
import { reloadCamera } from '../dashboard.js';
import { panelState, _restoreEditWrapper, _closeEditPanel } from './panel.js';
import { hydrateMqttSettings } from './mqtt-settings.js';
// The cam-edit panel itself lives in edit-panel.js — index.js keeps the
// shell, the camera list and the Settings-tab hydrator. Imported for
// local use AND re-exported: a re-export alone does not bring the name
// into this file's scope, and the window bridge at the bottom needs it.
import { editCamera } from './edit-panel.js';
export { editCamera };
import {
  _applyUrlMask,
  _defaultRtspPathForManufacturer,
  _updateRtspErweitertVisuals,
} from './rtsp.js';
import { _updateWhitelistHidden } from './whitelist.js';
import { _refreshCamIdPreview, _bindCamIdPreviewListeners } from './camera_id.js';
import { _loadCamDiagnostics, _refreshConnectionWarn } from './recovery.js';
import {
  _initCameraFormListeners,
  _initErkSliders,
  _renderErkPerClassConfidence,
  _bindErkPerClassToggle,
  _renderErkPerClassConfirm,
  _bindErkConfirmPerClassToggle,
  _bindDetectionRoiControls,
  _renderCamObjectPills,
  _renderGlobalStatusRows,
  _renderCamConfirmGrid,
} from './detection.js';
import { _renderShapeList, _updateShapeDrawingBar } from '../shape-editor/index.js';
import { _bindCamProbeDeviceInfo } from './discovery.js';
import { _bindReolinkImageMode } from './reolink-imgmode.js';
import {
  _renderSeverityMatrix,
  _checkAlertingConflicts,
  _renderAlertCooldownGrid,
  _bindAlertCooldownToggle,
  _bindAlertTestButton,
  _bindAlertingConflictWatch,
  _renderAlertStatusStrip,
  _refreshSeverityLockState,
} from '../alerting.js';

// Coral pipeline tree + device info + test cam list — direct ES imports
// since R13 dropped the window-bridge thunks that used to wait for
// coral-test.js's load order. Static imports guarantee these are
// callable by the time index.js's module body runs.
import {
  _updateCoralDeviceInfo,
  _renderCoralPipelineTree,
  _populateCoralTestCameras,
} from './coral-test.js';

// Tiny helper used by the export-config buttons in the App-Section.
const download = (url) => window.open(url, '_blank');

export function renderShell() {
  // Hero title is now a static "Squirreling · Sightings" lockup with the squirrel-on-
  // hyphen ornament — no longer driven by config.app.{name,tagline,
  // subtitle}. Side-nav app-name still hydrates if present so users
  // who renamed the app via Settings keep their custom label there.
  const _sideAppName = byId('sideAppName');
  if (_sideAppName) _sideAppName.textContent = state.config.app.name || 'Squirreling · Sightings';
  // Null-guard the legacy hero IDs so a config still containing
  // tagline/subtitle doesn't crash renderShell — they just no-op.
  const nameEl = byId('appName');
  if (nameEl) nameEl.textContent = state.config.app.name || 'Squirreling · Sightings';
  const tagEl = byId('appTagline');
  if (tagEl) tagEl.textContent = state.config.app.tagline || 'Motion · Objekte · Timelapse';
  const subEl = byId('appSubtitle');
  if (subEl)
    subEl.textContent =
      state.config.app.subtitle || 'RTSP-Streams · KI-Erkennung · Vogelarten · Telegram-Alerts';
}

// _camGridCols / SURVEIL_ACC / SURVEIL_LABEL / _isInScheduleWindow /
// _surveilMode / _surveilEyeSvg now live in dashboard.js (Stage 3a).

// renderDashboard now lives in dashboard.js (Stage 3b).

// Live-detection 3 s flash on the .cv-surveil-tgt of a class. CSS already
// supports the .is-detecting class (animation gated by prefers-reduced-
// motion). Per-(cam,cls) throttle so a sustained detection stream doesn't
// spam: minimum 2 s between flashes for the same target. Exposed on
// window so the backend pipeline (when it lands — currently detections
// live in container logs only, no SSE / WebSocket on the frontend) can
// trigger it via window._flashDetection(camId, cls).
const _flashThrottle = new Map();
window._flashDetection = function (camId, cls) {
  if (!camId || !cls) return;
  const key = camId + '|' + cls;
  const now = Date.now();
  const last = _flashThrottle.get(key) || 0;
  if (now - last < 2000) return;
  _flashThrottle.set(key, now);
  const tile = document.querySelector(`.cv-card[data-camid="${CSS.escape(camId)}"]`);
  if (!tile) return;
  const tgt = tile.querySelector(`.cv-surveil-tgt[data-cls="${CSS.escape(cls)}"]`);
  if (!tgt) return;
  tgt.classList.remove('is-detecting');
  void tgt.offsetWidth; // force reflow so animation restarts
  tgt.classList.add('is-detecting');
  setTimeout(() => tgt.classList.remove('is-detecting'), 3000);
};

// _defaultRtspPathForManufacturer, _updateRtspErweitertVisuals,
// initRtspBuilder, parseRtspUrl all moved together. Inline-onclick
// handlers (_toggleUrlMask, _toggleCamRtspErw) keep their window
// bridges from inside the new module.

window.toggleCameraEnabled = async function (camId, enabled) {
  const cam = (state.cameras || []).find((x) => x.id === camId);
  if (!cam) return;
  await apiPost('/api/settings/cameras', { ...cam, enabled });
  await loadAll();
};
export function renderCameraSettings() {
  byId('cameraSettingsList').innerHTML = state.cameras
    .map((c) => {
      // Merge is offered only for cameras that have been offline for ≥ 10 min
      // straight (frame_age_s is the seconds-since-last-good-frame counter the
      // runtime maintains; null = camera never produced a frame and is also
      // not "abandoned" in the merge sense). Brief disconnects (network blip,
      // camera reboot) keep the button hidden; the moment a camera reconnects
      // and frame_age_s drops back under the threshold, the next render hides
      // the button automatically — no manual dismiss needed.
      const MERGE_OFFLINE_THRESHOLD_S = 600;
      const canMerge =
        typeof c.frame_age_s === 'number' && c.frame_age_s >= MERGE_OFFLINE_THRESHOLD_S;
      // Collapsed Geräte row keeps only the icon+name on the left and the
      // expand chevron on the right. The previous cluster (active toggle,
      // Verbinden button, Zusammenführen, trash) was removed because:
      //   - configured cameras are always treated as active (auto-connect
      //     on boot via rebuild_runtimes); no per-row toggling needed
      //   - manual "Verbinden" duplicates auto-connect
      //   - trash already lives inside the expanded settings (#deleteCameraBtn)
      // canMerge is intentionally unused here now — the merge affordance
      // is reachable from the camera-merge modal flow elsewhere. Keep the
      // data-camid attribute so the bulk re-renderer can locate the row.
      void canMerge;
      return `
    <div class="cam-item" data-camid="${esc(c.id)}">
      <div class="cam-item-head" style="cursor:pointer" onclick="editCamera('${esc(c.id)}')">
        <div class="cam-item-head-left">
          <span class="cam-item-head-icon">${getCameraIcon(c.name)}</span>
          <span class="cam-item-head-name">${esc(c.name)}</span>
        </div>
        <div class="cam-item-head-right">
          <!-- Expand chevron — pure visual cue; the whole row is clickable. -->
          <svg class="cam-item-chevron" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="5,3 11,8 5,13"/></svg>
        </div>
      </div>
    </div>`;
    })
    .join('');
}

// ── Camera merge modal ────────────────────────────────────────────────────────
// Now lives in camera-merge.js (Stage 6). bindMergeModal() is called
// once at the bottom of this file to wire its DOM listeners.
window._reconnectCam = function (camId, btn) {
  btn.classList.add('spinning');
  setTimeout(() => btn.classList.remove('spinning'), 520);
  reloadCamera(camId);
};
// Delete-with-confirm — shared between the cam-row trash icon
// (window._quickDeleteCamera) and the in-panel "Kamera löschen"
// button. Both entry points need the SAME confirm dialog and
// success path, so we factor the body into one helper and wire two
// thin callers around it.
async function _deleteCameraWithConfirm(camId, camName) {
  if (
    !(await showConfirm(
      `Kamera "${camName}" wirklich löschen?\n\nDie Kamera wird aus der Konfiguration entfernt. Medien bleiben im Speicher erhalten und erscheinen unter "Archivierte Kameras".`,
    ))
  )
    return;
  try {
    const r = await j(`/api/settings/cameras/${encodeURIComponent(camId)}`, { method: 'DELETE' });
    if (r.event_count > 0)
      showToast(`${r.event_count} gespeicherte Ereignisse bleiben im Archiv erhalten.`, 'warn');
    if (panelState.camId === camId) _restoreEditWrapper();
    await loadAll();
  } catch (_err) {
    showToast('Fehler beim Löschen: ' + (_err.message || _err), 'error');
  }
}
window._quickDeleteCamera = _deleteCameraWithConfirm;
// In-panel "Kamera löschen" button. The form-template puts the
// button in the DOM at boot time (it's static markup), so we bind
// once here. The current camId is stamped onto the button's
// dataset by editCamera(), and the camera name comes from the
// live state lookup so a rename between edit-open and delete-click
// still picks the latest label.
byId('deleteCameraBtn')?.addEventListener('click', () => {
  const btn = byId('deleteCameraBtn');
  const camId = btn?.dataset.camId;
  if (!camId) {
    showToast('Keine Kamera ausgewählt.', 'error');
    return;
  }
  const cam =
    (state.cameras || []).find((c) => c.id === camId) ||
    (state.config?.cameras || []).find((c) => c.id === camId);
  _deleteCameraWithConfirm(camId, cam?.name || camId);
});

export async function renderProfiles() {
  const cats = await j('/api/cats');
  const persons = await j('/api/persons');
  const catEl = byId('catList');
  const perEl = byId('personList');
  if (catEl)
    catEl.innerHTML =
      cats.profiles
        .map((p) => `<div style="padding:3px 0;font-size:13px">${esc(p.name)}</div>`)
        .join('') || '<span class="muted small">—</span>';
  if (perEl)
    perEl.innerHTML =
      persons.profiles
        .map(
          (p) =>
            `<div style="padding:3px 0;font-size:13px">${esc(p.name)}${p.whitelisted ? ' <span class="muted small">(Whitelist)</span>' : ''}</div>`,
        )
        .join('') || '<span class="muted small">—</span>';
}
export async function renderAudit() {
  const actions = await j('/api/telegram/actions');
  byId('auditPanel').innerHTML =
    actions.items
      .map(
        (a) =>
          `<div class="audit-item"><strong>${esc(a.action)}</strong><div class="small">${esc(a.time)}${a.camera_id ? ` · ${esc(a.camera_id)}` : ''}</div></div>`,
      )
      .join('') || '<div class="audit-item">Noch keine Telegram-Aktionen.</div>';
}

async function toggleArm(camId, armed) {
  await apiPost(`/api/camera/${camId}/arm`, { armed });
  await loadAll();
}
window.toggleArm = toggleArm;
// _cvCardClick now lives in dashboard.js (Stage 3b). Its window

export function hydrateSettings() {
  const proc = state.config.processing || {},
    coral = state.config.coral || {};
  // App section — Public Base URL + Discovery-Subnet now render read-only
  // inside updateSystemPanel(); no inputs to hydrate here.
  updateSystemPanel();
  // MQTT section owns its own module (camedit/mqtt-settings.js).
  hydrateMqttSettings();
  // Coral section — unified .switch toggles (checkbox-driven)
  const coralActive = !!(proc.coral_enabled ?? coral.mode === 'coral');
  const birdActive = !!(proc.bird_species_enabled ?? coral.bird_species_enabled);
  const wildlifeActive = !!proc.wildlife_enabled;
  const coralInp = byId('coralTpuEnabled');
  if (coralInp) coralInp.checked = coralActive;
  const birdInp = byId('birdSpeciesEnabled');
  if (birdInp) birdInp.checked = birdActive;
  const wildInp = byId('wildlifeEnabled');
  if (wildInp) wildInp.checked = wildlifeActive;
  // Wildlife toggle stays fully interactive even when the model file is
  // missing — the warning beneath the row tells the user what's wrong;
  // we never want to gate the checkbox itself.
  const wildRow = byId('wildlifeEnabledRow');
  if (wildRow) {
    wildRow.classList.remove('toggle-row--disabled');
  }
  if (wildInp) wildInp.disabled = false;
  const cam0 = state.cameras[0];
  const coralAvail = !!cam0?.coral_available;
  const detMode = cam0?.detection_mode || null;
  const chip = byId('coralStatusChip');
  if (chip) {
    // Four states. CPU fallback is now orange (warn-orange) instead of
    // the prior yellow — green/yellow/grey was visually too soft for what
    // is in practice a degraded mode the user should notice.
    let label = 'aus',
      cls = 'set-status-badge--off';
    if (coralActive) {
      if (detMode === 'coral' && coralAvail) {
        label = 'Coral TPU aktiv';
        cls = 'set-status-badge--on';
      } else if (detMode === 'cpu') {
        label = '⚠ CPU-Fallback aktiv';
        cls = 'set-status-badge--warn-orange';
      } else {
        label = '✗ KI nicht verfügbar';
        cls = 'set-status-badge--off';
      }
    } else {
      label = 'KI-Objekterkennung aus';
    }
    chip.textContent = label;
    chip.className = 'set-status-badge ' + cls;
  }
  const hint = byId('coralStatusHint');
  if (hint) {
    const reason = cam0?.coral_reason || '—';
    // Happy-path "Coral TPU erkannt und aktiv" line was a duplicate of the
    // status chip in the section header — only WARNING/ERROR lines stay.
    const lines = [];
    if (!coralAvail && coralActive) {
      lines.push(`💻 CPU Fallback aktiv (${esc(reason)})`);
    } else if (!coralActive) {
      lines.push('⏸ Erkennung deaktiviert');
    }
    if (birdActive && proc.bird_model_available === false) {
      const p = proc.bird_model_path || 'inat_bird_quant.tflite';
      lines.push(
        `⚠️ Vogelarten-Modell nicht gefunden. Bitte <code>${esc(p.split('/').pop())}</code> in <code>models/</code> ablegen.`,
      );
    } else if (birdActive && cam0?.bird_species_available === false && cam0?.bird_species_reason) {
      lines.push(`⚠️ Vogelarten-Klassifikation: ${esc(cam0.bird_species_reason)}`);
    }
    // Warn whenever the model is missing, even if the user hasn't enabled
    // wildlife yet — the missing-file hint is what tells them WHY enabling
    // does nothing useful right now.
    if (proc.wildlife_model_available === false) {
      const p = proc.wildlife_model_path || 'mobilenet_v2_1.0_224_quant.tflite';
      lines.push(
        `⚠️ Modell nicht gefunden: <code>${esc(p.split('/').pop())}</code> — bitte in <code>models/</code> ablegen.`,
      );
    }
    hint.innerHTML = lines.join('<br>');
    hint.style.display = lines.length ? '' : 'none';
  }
  // Coral device info from /api/system (async, non-blocking)
  _updateCoralDeviceInfo();
  _renderCoralPipelineTree();
  _populateCoralTestCameras();
  // Models list is now behind the Modelle sub-tab; load it lazily on
  // first open via toggleCoralTab, so hydrate doesn't spin up a request
  // users aren't looking at.
  // Hydrate media settings form
  const storageSec = state.config.storage || {};
  const rdVal = storageSec.retention_days || 14;
  const rdEl = byId('ms_retention_days');
  if (rdEl) rdEl.value = rdVal;
  const rdLbl = byId('ms_retention_days_val');
  if (rdLbl) rdLbl.textContent = rdVal + ' Tage';
  const acEl = byId('ms_auto_cleanup');
  if (acEl) acEl.checked = !!storageSec.auto_cleanup_enabled;
}

async function updateSystemPanel() {
  const panel = byId('systemInfoPanel');
  if (!panel) return;
  const storagePath = state.config?.storage?.root || 'storage/';
  try {
    const s = await j('/api/system');
    const b = s.build || {};
    const commit = b.commit || 'dev';
    const date = b.date || '—';
    const count = b.count || '—';
    // Letzter Neustart — the Flask process start time, NOT the build date.
    let restartShort = '—';
    if (s.process_start) {
      try {
        const d = new Date(s.process_start);
        const pad = (n) => String(n).padStart(2, '0');
        restartShort = `${pad(d.getDate())}.${pad(d.getMonth() + 1)}. ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      } catch {}
    }
    const heroEl = byId('heroBuildInfo');
    if (heroEl) {
      const url = 'https://github.com/premiumcola/cam-manager/commits/main/';
      const shortCommit = commit.length > 7 ? commit.slice(0, 7) : commit;
      const countPart =
        b.count && b.count !== '—'
          ? `<a href="${url}" target="_blank" class="hero-build-count">Build #${esc(String(b.count))}</a>`
          : `<span class="hero-build-count hero-build-count--dev">Build · dev</span>`;
      const commitPart = `<code class="hero-build-commit" title="Git commit">${esc(shortCommit)}</code>`;
      const restartPart = s.process_start
        ? `<span class="hero-build-date" title="Letzter Neustart: ${esc(s.process_start)}">⟳ ${esc(restartShort)}</span>`
        : '';
      heroEl.innerHTML = `${countPart}<span class="hero-build-sep">·</span>${commitPart}${restartPart ? `<span class="hero-build-sep">·</span>${restartPart}` : ''}`;
    }
    const memUsed = s.mem_used_mb || 0;
    const memTotal = s.mem_total_mb || 0;
    const procMem = s.proc_mem_mb || 0;
    const uptime = s.uptime_s || 0;
    const uptimeStr =
      uptime > 3600
        ? `${Math.floor(uptime / 3600)}h ${Math.floor((uptime % 3600) / 60)}m`
        : uptime > 60
          ? `${Math.floor(uptime / 60)}m`
          : `${Math.round(uptime)}s`;
    const shortCommit = commit.length > 7 ? commit.slice(0, 7) : commit;
    const publicUrl = state.config?.server?.public_base_url || '';
    const subnet = state.config?.default_discovery_subnet || '';
    panel.innerHTML = `
      <div class="app-info-block">
        <div class="app-info-section-title">Build &amp; System</div>
        <div class="app-info-row"><span class="app-info-row-label">Build</span><span class="app-info-row-val"><code>${esc(shortCommit)}</code> · ${esc(date)}</span></div>
        <div class="app-info-row"><span class="app-info-row-label">Commits</span><span class="app-info-row-val">${esc(String(count))}</span></div>
        ${s.process_start ? `<div class="app-info-row"><span class="app-info-row-label">Letzter Neustart</span><span class="app-info-row-val" title="${esc(s.process_start)}">${esc(restartShort)}</span></div>` : ''}
        ${uptime ? `<div class="app-info-row"><span class="app-info-row-label">Container-Uptime</span><span class="app-info-row-val">${uptimeStr}</span></div>` : ''}
        ${s.camera_count !== undefined ? `<div class="app-info-row"><span class="app-info-row-label">Aktive Kameras</span><span class="app-info-row-val">${s.camera_count}</span></div>` : ''}

        <div class="app-info-section-title">Ressourcen</div>
        ${procMem ? `<div class="app-info-row"><span class="app-info-row-label">RAM (App)</span><span class="app-info-row-val">${procMem} MB</span></div>` : ''}
        ${memTotal ? `<div class="app-info-row"><span class="app-info-row-label">RAM (System)</span><span class="app-info-row-val">${memUsed} / ${memTotal} MB</span></div>` : ''}
        <div class="app-info-row"><span class="app-info-row-label">Storage</span><span class="app-info-row-val"><code>${esc(storagePath)}</code></span></div>

        <div class="app-info-section-title">Netzwerk</div>
        <div class="app-info-row"><span class="app-info-row-label">Public Base URL</span><span class="app-info-row-val">${publicUrl ? `<code>${esc(publicUrl)}</code>` : '—'}</span></div>
        <div class="app-info-row"><span class="app-info-row-label">Discovery-Subnet</span><span class="app-info-row-val">${subnet ? `<code>${esc(subnet)}</code>` : '—'}</span></div>
      </div>`;
  } catch (_err) {
    /* silent — system info optional */
  }
}

byId('reloadConfigBtn').onclick = () => loadAll();

byId('closeCameraEdit')?.addEventListener('click', () => _closeEditPanel());
// Camera-card placeholder rendering moved with the dashboard module

byId('exportJsonBtn').onclick = () => download('/api/settings/export?format=json');
byId('exportYamlBtn').onclick = () => download('/api/settings/export?format=yaml');
byId('clearImportBtn').onclick = () => {
  byId('importBox').value = '';
};
byId('importJsonBtn').onclick = async () => {
  await importConfig('json');
};
byId('importYamlBtn').onclick = async () => {
  await importConfig('yaml');
};
async function importConfig(format) {
  const content = byId('importBox').value.trim();
  if (!content) {
    showToast('Bitte Inhalt einfügen.', 'warn');
    return;
  }
  await j('/api/settings/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ format, content }),
  });
  byId('importBox').value = '';
  await loadAll();
  showToast('Import erfolgreich.', 'success');
}

// ── Inline-onclick bridges (template + JS-rendered HTML handlers) ──────────
// Only names read by `onclick="..."` strings (template-side or
// rendered into innerHTML by other modules) survive here. Every other
// bridge dropped in R13 — direct ES imports replaced them.
//
// editCamera               — onclick on cam-rows in renderCameraSettings()
// toggleCameraEnabled      — onchange on the cam-row enable switch
// _reconnectCam            — onclick on the cam-row "Verbinden" button
// _quickDeleteCamera       — onclick on the cam-row delete button
// _flashDetection          — debug entry-point (DevTools / future SSE bridge)
// toggleArm                — assigned next to its definition higher up
window.editCamera = editCamera;
