import { esc } from '../../core/dom.js';
import { _scheduleSave, _flushSave, _saveTimers } from './_save.js';
export const _CLUSTER_CHEVRON =
  '<svg class="mv-ld-cluster-chevron" viewBox="0 0 24 24" width="14" height="14" ' +
  'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" ' +
  'stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

// SIMU-05b · default + recommended tuning values for Cluster 1.
const _CLUSTER1_DEFAULTS = {
  track_iou_match_threshold: 0.2,
  track_miss_grace_seconds: 8.0,
  track_continue_min_score: 0.2,
};
const _CLUSTER1_RECOMMENDED = {
  track_iou_match_threshold: 0.1,
  track_miss_grace_seconds: 15.0,
  track_continue_min_score: 0.1,
};

// SIMU-05b · Cluster 1 render. Three sliders (IoU / grace / floor)
// + evidence box + Speichern/Defaults/Empfohlene buttons. The slider
// component lives in this file (no separate module) since clusters
// 1/2 are the only callers; clusters 3+ use pill toggles instead.
export function _renderCluster1(ctx, cam) {
  const iou = _readField(cam, 'track_iou_match_threshold', _CLUSTER1_DEFAULTS.track_iou_match_threshold);
  const grace = _readField(cam, 'track_miss_grace_seconds', _CLUSTER1_DEFAULTS.track_miss_grace_seconds);
  const floor = _readField(cam, 'track_continue_min_score', _CLUSTER1_DEFAULTS.track_continue_min_score);
  return `
    <div class="mv-ld-cluster mv-ld-cluster-warn" data-cluster-id="1">
      ${_renderClusterHeader(1, 'Cluster 1 · Person/Objekt reißt ab beim Bewegen',
        'Track stirbt obwohl Subjekt noch im Bild ist · neue Person-ID nach Drehung',
        _cluster1HeaderHint(ctx))}
      <div class="mv-ld-cluster-body">
        ${_renderSlider({
          field: 'track_iou_match_threshold',
          label: 'IoU-Match-Schwelle',
          value: iou,
          min: 0.0,
          max: 0.95,
          step: 0.01,
          desc: 'Wie groß muss die Überlappung zur Vorgängerbox sein, damit es derselbe Track bleibt',
          hint: '↓ Senken (0.10) = toleranter bei Drehungen / Sprüngen',
        })}
        ${_renderSlider({
          field: 'track_miss_grace_seconds',
          label: 'Miss-Grace (Sek.)',
          value: grace,
          min: 1.0,
          max: 30.0,
          step: 0.5,
          desc: 'Wie lange ein Track ohne neue Detection überleben darf (z.B. Verdeckung)',
          hint: '↑ Erhöhen (15 s) = überlebt längere Verdeckung / Drehung',
        })}
        ${_renderSlider({
          field: 'track_continue_min_score',
          label: 'Floor-Score (Weiterführung)',
          value: floor,
          min: 0.0,
          max: 0.95,
          step: 0.01,
          desc: 'Minimale Confidence, damit existierender Track weiterläuft (≠ Spawn-Score!)',
          hint: '↓ Senken (0.10) = Track überlebt schwache Frames (Drehung, dunkle Pose)',
        })}
        ${_renderCluster1Evidence(ctx, cam)}
        <div class="mv-ld-cluster-actions">
          <button type="button" class="mv-ld-action-btn mv-ld-action-save" data-action="save-cluster1">Speichern (Cam)</button>
          <button type="button" class="mv-ld-action-btn" data-action="defaults-cluster1">Defaults</button>
          <button type="button" class="mv-ld-action-btn mv-ld-action-recommend" data-action="recommend-cluster1">Empfohlene Werte testen</button>
          <span class="mv-ld-save-status" data-save-status data-save-state="idle"></span>
        </div>
      </div>
    </div>`;
}

export function _renderClusterHeader(num, title, sub, hint) {
  // Q2-2 · the head is the collapse toggle (tap to expand the body).
  // role=button + aria-expanded for a11y; the leading chevron rotates
  // via the root's data-collapsed attribute.
  return `
    <div class="mv-ld-cluster-head" role="button" tabindex="0" aria-expanded="false">
      ${_CLUSTER_CHEVRON}
      <div class="mv-ld-cluster-head-text">
        <div class="mv-ld-cluster-head-title">${esc(title)}</div>
        <div class="mv-ld-cluster-head-sub">${esc(sub)}</div>
      </div>
      ${hint ? `<div class="mv-ld-cluster-head-hint" data-hint-tone="${hint.tone}">${esc(hint.text)}</div>` : ''}
    </div>`;
}

export function _cluster1HeaderHint(ctx) {
  // For SIMU-05b the evidence ring-buffer (SIMU-05h) isn't wired yet;
  // surface a calm placeholder so the cluster reads stable instead
  // of empty. SIMU-05h replaces this with a real count.
  const evidence = ctx.fullData?.cluster_evidence?.cluster1;
  if (!evidence) return { tone: 'mute', text: '· Live-Daten in Vorbereitung' };
  const n = Number(evidence.deaths_60s || 0);
  return n > 0
    ? { tone: 'warn', text: `⚠ Letzte 60 s: ${n} DEATH` }
    : { tone: 'ok', text: '· Letzte 60 s: 0 DEATH' };
}

export function _renderCluster1Evidence(ctx, cam) {
  const ev = ctx.fullData?.cluster_evidence?.cluster1;
  const clean = !ev || Number(ev.deaths_60s || 0) === 0;
  if (clean) {
    return `<div class="mv-ld-evidence mv-ld-evidence-ok" data-cluster-evidence="1">
      <div class="mv-ld-evidence-line">📊 Letzte 60 s an dieser Kamera:</div>
      <div class="mv-ld-evidence-mono">Aktuell stabil · keine Track-Abbrüche</div>
    </div>`;
  }
  const deaths = Number(ev.deaths_60s || 0);
  const spawns = Number(ev.spawns_60s || 0);
  const reids = Number(ev.reid_successes_60s || 0);
  const attempts = Array.isArray(ev.reid_attempts_60s) ? ev.reid_attempts_60s : [];
  // Diagnose: pick the worst failing IoU attempt and surface it.
  let diagnose = '';
  if (attempts.length) {
    const worst = attempts.reduce((a, b) => (Number(a.iou) < Number(b.iou) ? a : b));
    const iouCur = Number(cam.track_iou_match_threshold || 0.2).toFixed(2);
    diagnose = `Wahrscheinliche Ursache: IoU ${Number(worst.iou).toFixed(2)} unterschreitet Schwelle ${iouCur} beim Drehen`;
  }
  return `<div class="mv-ld-evidence mv-ld-evidence-warn" data-cluster-evidence="1">
    <div class="mv-ld-evidence-line">📊 Letzte 60 s an dieser Kamera:</div>
    <div class="mv-ld-evidence-mono">${deaths}× DEATH · ${spawns}× SPAWN · ${reids} erfolgreiche RE-ID</div>
    ${diagnose ? `<div class="mv-ld-evidence-diagnose">${esc(diagnose)}</div>` : ''}
  </div>`;
}

export function _readField(cam, key, defaultVal) {
  const v = Number(cam[key]);
  return Number.isFinite(v) && v > 0 ? v : defaultVal;
}

export function _renderSlider(cfg) {
  const valDisplay = _formatValue(cfg.value, cfg.step);
  const pct = _valToPct(cfg.value, cfg.min, cfg.max);
  return `
    <div class="mv-ld-slider" data-field="${esc(cfg.field)}" data-min="${cfg.min}" data-max="${cfg.max}" data-step="${cfg.step}" data-value="${cfg.value}">
      <div class="mv-ld-slider-top">
        <span class="mv-ld-slider-label">${esc(cfg.label)}</span>
        <span class="mv-ld-slider-value" data-slider-value>${esc(valDisplay)}</span>
      </div>
      <div class="mv-ld-slider-track" data-slider-track>
        <div class="mv-ld-slider-fill" data-slider-fill style="width:${pct.toFixed(2)}%"></div>
        <div class="mv-ld-slider-knob" data-slider-knob style="left:${pct.toFixed(2)}%"></div>
      </div>
      <div class="mv-ld-slider-bounds">
        <span>${esc(_formatValue(cfg.min, cfg.step))}</span>
        <span>${esc(_formatValue(cfg.max, cfg.step))}</span>
      </div>
      <div class="mv-ld-slider-desc">${esc(cfg.desc)}</div>
      <div class="mv-ld-slider-hint">${esc(cfg.hint)}</div>
    </div>`;
}

export function _formatValue(v, step) {
  return step >= 0.5 ? `${Number(v).toFixed(1)}` : `${Number(v).toFixed(2)}`;
}

export function _valToPct(v, min, max) {
  const range = Math.max(0.0001, max - min);
  return Math.min(100, Math.max(0, ((Number(v) - min) / range) * 100));
}

export function _pctToVal(pct, min, max, step) {
  const range = max - min;
  const raw = min + (range * pct) / 100;
  const snapped = Math.round(raw / step) * step;
  return Math.min(max, Math.max(min, snapped));
}

// SIMU-05b · wire up sliders + action buttons inside Cluster 1.
export function _wireCluster1(host, cam, ctx) {
  const camId = (ctx.session || {}).camId || cam.id;
  host.querySelectorAll('.mv-ld-slider').forEach((root) => {
    _wireSlider(root, camId);
  });
  host
    .querySelector('[data-action="save-cluster1"]')
    ?.addEventListener('click', () => _forceSave(camId, host));
  host
    .querySelector('[data-action="defaults-cluster1"]')
    ?.addEventListener('click', () => _applyClusterValues(host, camId, _CLUSTER1_DEFAULTS));
  host
    .querySelector('[data-action="recommend-cluster1"]')
    ?.addEventListener('click', () => _applyClusterValues(host, camId, _CLUSTER1_RECOMMENDED));
}

export function _wireSlider(root, camId) {
  if (root.dataset.wired === '1') return;
  root.dataset.wired = '1';
  const track = root.querySelector('[data-slider-track]');
  const knob = root.querySelector('[data-slider-knob]');
  const fill = root.querySelector('[data-slider-fill]');
  const valEl = root.querySelector('[data-slider-value]');
  if (!track || !knob || !fill || !valEl) return;
  const min = Number(root.dataset.min);
  const max = Number(root.dataset.max);
  const step = Number(root.dataset.step);
  const field = root.dataset.field;
  let dragging = false;
  const setFromX = (clientX) => {
    const rect = track.getBoundingClientRect();
    const pct = Math.min(100, Math.max(0, ((clientX - rect.left) / rect.width) * 100));
    const val = _pctToVal(pct, min, max, step);
    root.dataset.value = String(val);
    knob.style.left = `${pct.toFixed(2)}%`;
    fill.style.width = `${pct.toFixed(2)}%`;
    valEl.textContent = _formatValue(val, step);
    return val;
  };
  const onMove = (ev) => {
    if (!dragging) return;
    const val = setFromX(ev.clientX);
    const statusEl = root.closest('.mv-ld-cluster')?.querySelector('[data-save-status]');
    _scheduleSave(camId, { [field]: val }, statusEl);
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    document.removeEventListener('pointermove', onMove);
    document.removeEventListener('pointerup', onUp);
  };
  const onDown = (ev) => {
    dragging = true;
    setFromX(ev.clientX);
    const val = Number(root.dataset.value);
    const statusEl = root.closest('.mv-ld-cluster')?.querySelector('[data-save-status]');
    _scheduleSave(camId, { [field]: val }, statusEl);
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    ev.preventDefault();
  };
  knob.addEventListener('pointerdown', onDown);
  track.addEventListener('pointerdown', onDown);
}

export function _applyClusterValues(host, camId, values) {
  const patch = {};
  for (const [field, val] of Object.entries(values)) {
    const sliderRoot = host.querySelector(`.mv-ld-slider[data-field="${field}"]`);
    if (sliderRoot) {
      const min = Number(sliderRoot.dataset.min);
      const max = Number(sliderRoot.dataset.max);
      const step = Number(sliderRoot.dataset.step);
      const pct = _valToPct(val, min, max);
      sliderRoot.dataset.value = String(val);
      const knob = sliderRoot.querySelector('[data-slider-knob]');
      const fill = sliderRoot.querySelector('[data-slider-fill]');
      const valEl = sliderRoot.querySelector('[data-slider-value]');
      if (knob) knob.style.left = `${pct.toFixed(2)}%`;
      if (fill) fill.style.width = `${pct.toFixed(2)}%`;
      if (valEl) valEl.textContent = _formatValue(val, step);
    }
    patch[field] = val;
  }
  const statusEl = host.querySelector('[data-save-status]');
  _scheduleSave(camId, patch, statusEl);
}

export function _forceSave(camId, host) {
  // Force-flush any pending debounced timers for this camera.
  for (const [key, timerId] of Array.from(_saveTimers.entries())) {
    if (!key.startsWith(`${camId}:`)) continue;
    clearTimeout(timerId);
    _saveTimers.delete(key);
  }
  // Collect current slider values and send them all at once. The
  // backend's PATCH endpoint accepts the merged payload happily.
  const patch = {};
  host.querySelectorAll('.mv-ld-slider').forEach((root) => {
    const field = root.dataset.field;
    const val = Number(root.dataset.value);
    if (field && Number.isFinite(val)) {
      if (field.startsWith('label_thresholds:')) {
        const lbl = field.split(':')[1];
        patch.label_thresholds = patch.label_thresholds || {};
        patch.label_thresholds[lbl] = val;
      } else {
        patch[field] = val;
      }
    }
  });
  if (!Object.keys(patch).length) return;
  const statusEl = host.querySelector('[data-save-status]');
  _flushSave(camId, patch, statusEl, `${camId}:force`);
}
