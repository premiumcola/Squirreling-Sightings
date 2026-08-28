// ─── camedit/edit-panel.js ─────────────────────────────────────────────────
// The cam-edit panel: open it, hydrate every tab from the camera record,
// slide it into the clicked row. Plus the three tracker presets, which
// are the one control in the panel that saves on click rather than on
// submit.
//
// Extracted from camedit/index.js, which was 919 lines against a
// 400-line ceiling and carried a single 326-line `editCamera` against a
// 60-line function ceiling. The hydration is now one function per tab,
// which is also the boundary the try/catch cares about: any one of them
// throwing has to leave panelState recoverable.
import { state, shapeState } from '../core/state.js';
import { byId } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { getCameraIcon, getCameraColor } from '../core/icons.js';
import { panelState, _restoreEditWrapper, _closeEditPanel } from './panel.js';
import { hydrateSecretField } from '../chrome/secret-field.js';
import {
  RTSP_PATH_OPTS,
  _applyUrlMask,
  _defaultRtspPathForManufacturer,
  _updateRtspErweitertVisuals,
  initRtspBuilder,
  parseRtspUrl,
} from './rtsp.js';
import { setWhitelistState, _updateWhitelistHidden } from './whitelist.js';
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
  getCamObjectFilterState,
  setCamObjectFilterState,
  _renderGlobalStatusRows,
  _renderCamConfirmGrid,
} from './detection.js';
import {
  drawShapes,
  loadMaskSnapshot,
  _renderShapeList,
  restoreShapeMode,
} from '../shape-editor/index.js';
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
} from '../alerting.js';
import { hydrateErkennungFields } from './hydration/erkennung.js';
import { hydrateAlertingFields } from './hydration/alerting.js';
import { initCameraEditTabs } from './tabs.js';
import { _wireTrackingPresets } from './tracking-presets.js';

// ── Identity · id, name, vendor, colour, avatar ────────────────────────────

function _hydrateIdentity(f, c) {
  f['id'].value = c.id || '';
  f['id'].dataset.autoGen = '0';
  f['name'].value = c.name || '';
  if (f['manufacturer']) f['manufacturer'].value = c.manufacturer || '';
  if (f['model']) f['model'].value = c.model || '';
  // tx412 — the icon-emoji <input> was retired. The icon derives at
  // render time from getCameraIcon(name); writing it back into an input
  // is what produced the "<svg…> as input value" bug.
  //
  // B1 · the avatar mirrors the dashboard tile icon and is tinted via
  // --cam-color on its button parent, so the SVG's stroke="currentColor"
  // picks up the active tone. dataset.auto stays load-bearing for the
  // submit path (writes "" when '1', so settings.json never persists a
  // derivable tone) and drives the "↺ auto" reset link's visibility.
  const avatarBtn = byId('camAvatarBtn');
  const avatarIcon = byId('camAvatarIcon');
  const resetBtn = byId('camColorReset');
  const syncAvatar = (color, isAuto) => {
    if (avatarBtn) avatarBtn.style.setProperty('--cam-color', color);
    if (resetBtn) resetBtn.hidden = !!isAuto;
  };
  const renderAvatarIcon = (name) => {
    if (avatarIcon) avatarIcon.innerHTML = getCameraIcon(name || '');
  };
  if (f['color']) {
    const autoTone = getCameraColor({ name: c.name || c.id });
    f['color'].value = c.color || autoTone;
    f['color'].dataset.auto = c.color ? '0' : '1';
    renderAvatarIcon(c.name || c.id);
    syncAvatar(f['color'].value, f['color'].dataset.auto === '1');
    f['color'].oninput = () => {
      f['color'].dataset.auto = '0';
      syncAvatar(f['color'].value, false);
    };
  }
  if (avatarBtn && f['color']) {
    avatarBtn.onclick = (e) => {
      e.preventDefault();
      f['color'].click();
    };
  }
  if (resetBtn) {
    resetBtn.onclick = () => {
      if (!f['color']) return;
      const autoTone = getCameraColor({ name: f['name']?.value || c.name || c.id });
      f['color'].value = autoTone;
      f['color'].dataset.auto = '1';
      syncAvatar(autoTone, true);
    };
  }
  // Live-track display-name edits so the avatar icon and the auto-tone
  // follow what is being typed. A manual colour override stays put.
  f['name']?.addEventListener('input', () => {
    const n = f['name'].value || c.name || c.id;
    renderAvatarIcon(n);
    if (f['color'] && f['color'].dataset.auto === '1') {
      const autoTone = getCameraColor({ name: n });
      f['color'].value = autoTone;
      syncAvatar(autoTone, true);
    }
  });
}

// ── Verbindung · RTSP parts, the secret, the masked URLs ───────────────────

function _hydrateConnection(formEl, f, c) {
  const p = parseRtspUrl(c.rtsp_url || '');
  f['rtsp_ip'].value = p.host || '';
  f['rtsp_user'].value = p.user || '';
  // A populated type=password input sitting next to a populated username
  // input is the canonical credential pair Chrome offers to save on
  // submit — and this panel IS hidden after a save XHR, which is exactly
  // the shape that fires the prompt. The server no longer ships the
  // password (c.password_set is a boolean, and rtsp_url arrives
  // credential-free), so the field hydrates empty; the save path puts the
  // stored secret back unless the operator typed or cleared one.
  hydrateSecretField(f['rtsp_pass'], c.password_set, 'Passwort');
  f['rtsp_port'].value = p.port || '554';
  if (f['reolink_http_port']) f['reolink_http_port'].value = c.reolink_http_port || '';
  const matchedPath = RTSP_PATH_OPTS.find((o) => o.value === p.path);
  if (f['rtsp_path']) {
    const def = _defaultRtspPathForManufacturer(c.manufacturer || '');
    // Existing cam with a path → use it; fresh cam with none → fall back
    // to the manufacturer default so manual='0' from the start instead of
    // flagging the legacy RTSP_PATH_OPTS[0] as custom.
    f['rtsp_path'].value = matchedPath ? matchedPath.value : def;
    f['rtsp_path'].dataset.manual = f['rtsp_path'].value !== def ? '1' : '0';
    _updateRtspErweitertVisuals();
  }
  f['rtsp_url'].value = c.rtsp_url || '';
  f['snapshot_url'].value = c.snapshot_url || '';
  // Password masking on the URL display fields; the eye toggle reveals.
  delete f['rtsp_url'].dataset.real;
  delete f['snapshot_url'].dataset.real;
  _applyUrlMask(f['rtsp_url']);
  _applyUrlMask(f['snapshot_url']);
  formEl.querySelectorAll('.url-eye').forEach((b) => {
    b.classList.remove('revealed');
    b.textContent = '👁';
  });
}

// ── Alarmierung · severity matrix, channels, cooldowns, test push ─────────

function _hydrateAlerting(formEl, c) {
  // Legacy alarm_profile is a hidden bridge field — the source of truth
  // is the per-class severity matrix. Carry the stored value through the
  // form so back-end code that still reads it keeps working.
  const f = formEl.elements;
  if (f['alarm_profile']) f['alarm_profile'].value = c.alarm_profile || 'soft';
  // Rendered after the form id is set so handlers reference the right cam.
  _renderSeverityMatrix(formEl, c);
  _bindAlertingConflictWatch(formEl);
  _checkAlertingConflicts(formEl);
  // Fire-and-forget; handles its own error states and never throws.
  _renderAlertStatusStrip();
  // Wires once per session; the result panel resets on every reopen so a
  // stale "✓ Telegram angekommen" doesn't linger.
  _bindAlertTestButton();
  const alertTestResult = byId('alertTestResult');
  if (alertTestResult) alertTestResult.hidden = true;
  // Cooldown drilldown stays collapsed by default — the matrix is the
  // first impression, the drilldown is for fine-tuning.
  _renderAlertCooldownGrid(formEl, c);
  _bindAlertCooldownToggle();
  const alertCooldownGrid = byId('alertCooldownGrid');
  if (alertCooldownGrid) alertCooldownGrid.hidden = true;
  hydrateAlertingFields(formEl, c);
}

// ── Erkennung · object filter, sliders, per-class drilldowns ──────────────

function _hydrateErkennung(formEl, c) {
  const f = formEl.elements;
  _renderGlobalStatusRows();
  // The object filter renders as a pill bar; the hidden input is kept in
  // sync because the submit handler still reads f['object_filter'].value.
  setCamObjectFilterState(c.object_filter || ['person', 'cat', 'bird']);
  f['object_filter'].value = getCamObjectFilterState().join(',');
  _renderCamObjectPills();
  hydrateErkennungFields(formEl, c, state);
  _wireTrackingPresets(formEl);
  // Null-safe: returns early while #camConfirmGrid is [hidden].
  _renderCamConfirmGrid(c);
  // motion_enabled, resolution, snapshot_interval_s, bottom_crop_px and
  // wildlife_motion_sensitivity have no UI in this layout; their stored
  // values survive via the existingCam fallback in the submit handler.
  _initErkSliders(formEl);
  // Both drilldowns stay collapsed unless the user asks for them.
  _renderErkPerClassConfidence(formEl, c);
  _bindErkPerClassToggle();
  _renderErkPerClassConfirm(formEl, c);
  _bindErkConfirmPerClassToggle();
  _bindDetectionRoiControls(formEl, c);
  setWhitelistState(c.whitelist_names || []);
  _updateWhitelistHidden();
}

// ── Zonen/Masken ──────────────────────────────────────────────────────────

function _hydrateShapes(f, c, camId) {
  shapeState.camera = camId;
  shapeState.zones = JSON.parse(JSON.stringify(c.zones || []));
  shapeState.masks = JSON.parse(JSON.stringify(c.masks || []));
  shapeState.points = [];
  shapeState.pulse = null;
  f['zones_json'].value = JSON.stringify(shapeState.zones);
  f['masks_json'].value = JSON.stringify(shapeState.masks);
  // Reapplies the persisted mode (localStorage `tamspy.shapeMode`,
  // default 'zone'). Implicitly calls drawShapes() + _updateShapeDrawingBar().
  restoreShapeMode();
  _renderShapeList();
  byId('deleteCameraBtn').dataset.camId = camId;
  loadMaskSnapshot(camId);
  drawShapes();
}

// ── Open · slide the wrapper into the clicked row ─────────────────────────

function _openPanelInRow(camId) {
  const camRow = byId('cameraSettingsList')?.querySelector(`[data-camid="${camId}"]`);
  const wrapper = byId('cameraEditWrapper');
  if (camRow) {
    camRow.appendChild(wrapper);
    camRow.classList.add('editing');
    // Move the recovery button out of the tab bar and into the cam-item
    // header (left of the chevron). On iPhone widths the tab list scrolls
    // horizontally and the button overlapped the tabs there. Same DOM
    // node, so the JS driving its .is-warn / .is-pulsing state is intact.
    const recBtn = byId('camTabRecoveryBtn');
    const headRight = camRow.querySelector('.cam-item-head-right');
    const chevron = headRight && headRight.querySelector('.cam-item-chevron');
    if (recBtn && headRight && chevron) headRight.insertBefore(recBtn, chevron);
  }
  requestAnimationFrame(() => wrapper?.classList.add('slide-open'));
  panelState.camId = camId;
  setTimeout(() => wrapper.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 120);
}

export function editCamera(camId) {
  // Defensive: if the cam-edit form isn't in the DOM yet (a first-click
  // page-load race, or a wrapper detached by a previous
  // renderCameraSettings() and not re-created), wait one frame and retry
  // once. Without the guard the next line crashes on .elements of null
  // and the toast fires on every click forever.
  const formEl = byId('cameraForm');
  if (!formEl) {
    requestAnimationFrame(() => {
      if (byId('cameraForm')) editCamera(camId);
      else showToast('Bearbeitungs-Form nicht bereit — Seite neu laden (F5)', 'error');
    });
    return;
  }
  const c =
    (state.config?.cameras || []).find((x) => x.id === camId) ||
    (state.cameras || []).find((x) => x.id === camId);
  if (!c) {
    // Camera not in current state → drop any half-set lock so a retry
    // works once loadAll() refreshes state. Without this the lock sticks
    // when a stale camId (post-rename) races through here.
    panelState.camId = null;
    return;
  }
  // Toggle: clicking the same camera closes the panel.
  if (panelState.camId === camId) {
    _closeEditPanel();
    return;
  }
  // From here on, ANY exception in a hydration helper would historically
  // leave panelState.camId stale and the wrapper detached from #cameras —
  // every future click then matched the stale lock and bailed via the
  // toggle-close branch. The catch resets to a known-good baseline.
  try {
    _restoreEditWrapper();
    _initCameraFormListeners();
    initCameraEditTabs();
    initRtspBuilder();
    // formEl was captured and null-checked above; reuse it rather than
    // paying for a byId lookup that could race a mid-flight detach.
    const f = formEl.elements;
    _hydrateIdentity(f, c);
    _bindCamIdPreviewListeners();
    _bindCamProbeDeviceInfo();
    // Wires once; visibility flips live on manufacturer-field edits.
    _bindReolinkImageMode();
    // A fresh open must not retain an auto-detect hint from a previous save.
    formEl.querySelectorAll('.cam-autodetected-hint').forEach((el) => {
      el.hidden = true;
    });
    byId('cameraEditTitle').textContent = `Kamera bearbeiten · ${c.name || c.id}`;
    _hydrateConnection(formEl, f, c);
    _hydrateErkennung(formEl, c);
    _hydrateAlerting(formEl, c);
    _hydrateShapes(f, c, camId);
    _openPanelInRow(camId);
    _loadCamDiagnostics(camId);
    // Tab-bar recovery indicator + field highlights. Drives off the live
    // form values, not the persisted dict, so it reacts to edits. Runs
    // AFTER every field is populated so the historical "race during
    // _applyUrlMask" can't fire a false positive on a valid camera.
    _refreshConnectionWarn();
    _refreshCamIdPreview();
  } catch (e) {
    // A hydration helper threw — restore the lock to a clean state so the
    // next click re-attempts instead of hitting the toggle-close branch,
    // tell the user, and rethrow so the original stack stays in DevTools.
    panelState.camId = null;
    _restoreEditWrapper();
    showToast('Kamera-Bearbeitung konnte nicht öffnen — bitte erneut versuchen', 'warn');
    throw e;
  }
}
