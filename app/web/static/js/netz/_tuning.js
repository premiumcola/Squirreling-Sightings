// ─── netz/_tuning.js ────────────────────────────────────────────────────────
// Kamera-Feinschliff — the camera-WIDE capture/motion/tracking loop
// settings that used to live on the Erkennung tab's own form
// (Analyse-Intervall, Bewegungs-Vortrigger/Nachlauf, Objekt-Tracking,
// Kleintier-ROI). They can never become per-class radar axes — every one
// of them runs before the pipeline has classified anything — so they
// render as a plain collapsed fold below the net instead of a second
// radar. Saved through the same `PATCH .../detection-tuning` route the
// Simulieren debug panel already uses; the tracker presets keep their
// existing "auto-save on click" behaviour.
import { esc, qs, qsa } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { patchTuning } from './_api.js';
import { netzState } from './_state.js';

const _TRACK_PRESETS = {
  careful: { spawn: 0.55, cont: 0.3, grace: 4, iou: 0.3 },
  balanced: { spawn: 0.5, cont: 0.2, grace: 6, iou: 0.2 },
  robust: { spawn: 0.45, cont: 0.15, grace: 10, iou: 0.15 },
};
const _TRACK_PRESET_LABELS = { careful: 'Vorsichtig', balanced: 'Ausgewogen', robust: 'Robust' };

const _POST_MOTION_OPTIONS = [
  ['0', 'Standard (Global-Wert)'],
  ['3', '3 Sekunden'],
  ['5', '5 Sekunden'],
  ['8', '8 Sekunden'],
  ['10', '10 Sekunden'],
  ['15', '15 Sekunden'],
];
const _ROI_MODES = [
  ['off', 'Aus'],
  ['roi', 'Motion-ROI'],
  ['2x2', '2×2'],
  ['3x3', '3×3'],
];

export function tuningHtml(st) {
  const t = st.tuning || {};
  const tail = String(t.post_motion_tail_s || 0);
  const roiMode = t.roi_mode || 'off';
  return (
    `<details class="netz-tune"><summary>Kamera-Feinschliff</summary>` +
    `<div class="netz-tune-body">` +
    `<span class="lbl">Kamera-weite Aufnahme- und Tracking-Werte — nicht pro Klasse, ` +
    `laufen vor der Erkennung.</span>` +
    _scanCard(t) +
    _motionCard(t) +
    _tailCard(tail) +
    _trackingCard(t) +
    _roiCard(t, roiMode) +
    `<div class="netz-tune-save">` +
    `<button type="button" class="netz-btn" data-netz-tune-save disabled>Übernehmen</button>` +
    `</div>` +
    `</div></details>`
  );
}

function _scanCard(t) {
  const v = Number(t.frame_interval_ms) || 350;
  const fps = Math.max(1, Math.round(1000 / v));
  return (
    `<div class="erk-card">` +
    `<div class="row"><input type="range" data-tune="frame_interval_ms" min="100" max="2000" ` +
    `step="50" value="${v}"><span class="val" data-tune-val="frame_interval_ms">${v} ms</span></div>` +
    `<span class="lbl" data-tune-hint="frame_interval_ms">≈ ${fps} fps · niedriger = mehr ` +
    `Coral-Last</span></div>`
  );
}

function _motionCard(t) {
  const v = Number(t.motion_sensitivity ?? 0.5);
  return (
    `<div class="erk-card">` +
    `<div class="row"><input type="range" data-tune="motion_sensitivity" min="0.1" max="1.0" ` +
    `step="0.1" value="${v}"><span class="val" data-tune-val="motion_sensitivity">` +
    `${Math.round(v * 100)}%</span></div>` +
    `<span class="lbl">Bewegungs-Vortrigger · niedrig = nur große Bewegung</span></div>`
  );
}

function _tailCard(tail) {
  const opts = _POST_MOTION_OPTIONS
    .map(
      ([v, label]) => `<option value="${v}"${v === tail ? ' selected' : ''}>${esc(label)}</option>`,
    )
    .join('');
  return (
    `<div class="erk-card"><div class="row"><select data-tune="post_motion_tail_s">${opts}` +
    `</select></div><span class="lbl">Nachlauf-Aufnahme nach letzter Bewegung</span></div>`
  );
}

function _trackingCard(t) {
  const grace = Number(t.track_miss_grace_seconds) || 0;
  const iou = Number(t.track_iou_match_threshold) || 0;
  const ghostChecked = t.track_filter_ghosts !== false;
  const presets = Object.keys(_TRACK_PRESETS)
    .map(
      (k) =>
        `<button type="button" class="erk-track-preset" data-tune-preset="${k}">${_TRACK_PRESET_LABELS[k]}</button>`,
    )
    .join('');
  return (
    `<div class="erk-card">` +
    `<span class="field-help" style="margin-bottom:6px">Objekt-Tracking · hält erkannte ` +
    `Objekte über kurze Konfidenz-Einbrüche hinweg auf demselben Track.</span>` +
    `<div class="erk-track-presets" role="group" aria-label="Tracking-Vorlagen">` +
    `<span class="erk-track-presets-lbl">Vorlage anwenden:</span>${presets}</div>` +
    `<label class="erk-track-toggle"><span class="erk-track-toggle-text">` +
    `<span class="erk-track-toggle-name">Ghost-Spuren in Aufnahmen ausblenden</span>` +
    `<span class="erk-track-toggle-sub">Spuren, deren beste Konfidenz nie über der ` +
    `Spawn-Schwelle lag, werden nach der Aufnahme aus dem Track-Sidecar entfernt.</span>` +
    `</span><input type="checkbox" data-tune="track_filter_ghosts" class="switch-input"` +
    `${ghostChecked ? ' checked' : ''}><span class="switch"></span></label>` +
    `<details class="erk-expert"><summary>Experte · Track-Kontinuität</summary>` +
    `<span class="erk-track-warn">Betrifft nicht die Konfidenz, sondern ob ein Objekt über ` +
    `Frames hinweg dasselbe bleibt. Nur anfassen, wenn eine Kamera Spuren zerreißt.</span>` +
    `<div class="erk-track-grid">` +
    `<label class="erk-track-cell"><span class="erk-track-lbl">Gnadenfrist (Sek.)</span>` +
    `<input type="number" data-tune="track_miss_grace_seconds" min="0" max="30" step="0.5" ` +
    `value="${grace}" inputmode="decimal" placeholder="8,0">` +
    `<span class="erk-track-sub">Wie lange darf ein Track ohne Treffer überleben</span></label>` +
    `<label class="erk-track-cell"><span class="erk-track-lbl">IoU-Schwelle</span>` +
    `<input type="number" data-tune="track_iou_match_threshold" min="0" max="0.95" step="0.05" ` +
    `value="${iou}" inputmode="decimal" placeholder="0,20">` +
    `<span class="erk-track-sub">Wie ähnlich die Box-Lage frame-übergreifend sein muss. ` +
    `Niedriger = großzügiger.</span></label></div></details></div>`
  );
}

function _roiCard(t, roiMode) {
  const wl = Number(t.wildlife_motion_sensitivity) || 0;
  const net = Number(t.roi_min_net_disp_frac) || 0;
  const seg = _ROI_MODES
    .map(
      ([mode, label]) =>
        `<button type="button" class="erk-seg-btn${mode === roiMode ? ' is-active' : ''}" ` +
        `data-tune-roi="${mode}" aria-pressed="${mode === roiMode}">${esc(label)}</button>`,
    )
    .join('');
  return (
    `<div class="erk-section"><div class="cam-field-label">Kleintier-Erkennung (ROI / ` +
    `Tiling)</div><div class="erk-seg" role="group" aria-label="Erkennungsmodus">${seg}</div>` +
    `<div class="erk-roi-hint">Läuft nur, wenn die Vollbild-Erkennung nichts findet und eine ` +
    `zusammenhängende Bewegung erkannt wurde.</div>` +
    `<div class="erk-card"><div class="row"><input type="range" data-tune="wildlife_motion_sensitivity" ` +
    `min="0" max="3" step="0.1" value="${wl}"><span class="val" ` +
    `data-tune-val="wildlife_motion_sensitivity">${wl <= 0 ? 'auto' : wl.toFixed(1) + '×'}</span>` +
    `</div><span class="lbl">Wildtier-Empfindlichkeit · niedrigere Bewegungsschwelle für kleine ` +
    `Tiere (0 = auto)</span></div>` +
    `<div class="erk-card"><div class="row"><input type="range" data-tune="roi_min_net_disp_frac" ` +
    `min="0" max="0.2" step="0.01" value="${net}"><span class="val" ` +
    `data-tune-val="roi_min_net_disp_frac">${net <= 0 ? 'auto (4 %)' : Math.round(net * 100) + ' %'}` +
    `</span></div><span class="lbl">Min. Bewegungs-Strecke zum Auslösen · trennt laufendes Tier ` +
    `von Wind-Flackern (0 = Standard 4 %)</span></div></div>`
  );
}

function _fieldValue(inp) {
  if (inp.type === 'checkbox') return inp.checked;
  if (inp.type === 'number' || inp.type === 'range') return parseFloat(inp.value || '0');
  return inp.value;
}

function _markDirty(host) {
  host.querySelector('[data-netz-tune-save]')?.removeAttribute('disabled');
}

export function bindTuning(host, onSaved) {
  const root = host.querySelector('.netz-tune');
  if (!root) return;

  qsa('[data-tune]', root).forEach((inp) => {
    inp.addEventListener('input', () => {
      if (inp.dataset.tune === 'frame_interval_ms') {
        const v = parseFloat(inp.value);
        root.querySelector('[data-tune-val="frame_interval_ms"]').textContent = `${v} ms`;
        const fps = Math.max(1, Math.round(1000 / v));
        root.querySelector('[data-tune-hint="frame_interval_ms"]').textContent =
          `≈ ${fps} fps · niedriger = mehr Coral-Last`;
      } else if (inp.dataset.tune === 'motion_sensitivity') {
        const v = parseFloat(inp.value);
        root.querySelector('[data-tune-val="motion_sensitivity"]').textContent =
          `${Math.round(v * 100)}%`;
      } else if (inp.dataset.tune === 'wildlife_motion_sensitivity') {
        const v = parseFloat(inp.value);
        root.querySelector('[data-tune-val="wildlife_motion_sensitivity"]').textContent =
          v <= 0 ? 'auto' : v.toFixed(1) + '×';
      } else if (inp.dataset.tune === 'roi_min_net_disp_frac') {
        const v = parseFloat(inp.value);
        root.querySelector('[data-tune-val="roi_min_net_disp_frac"]').textContent =
          v <= 0 ? 'auto (4 %)' : Math.round(v * 100) + ' %';
      }
      _markDirty(host);
    });
  });

  qsa('[data-tune-roi]', root).forEach((btn) =>
    btn.addEventListener('click', () => {
      qsa('[data-tune-roi]', root).forEach((b) => {
        const on = b === btn;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      _markDirty(host);
    }),
  );

  root.querySelector('[data-netz-tune-save]')?.addEventListener('click', async (e) => {
    const btn = e.target;
    const fields = {};
    qsa('[data-tune]', root).forEach((inp) => {
      fields[inp.dataset.tune] = _fieldValue(inp);
    });
    const roiBtn = root.querySelector('[data-tune-roi].is-active');
    if (roiBtn) fields.roi_mode = roiBtn.dataset.tuneRoi;
    const res = await patchTuning(netzState.camId, fields);
    if (res.ok) {
      btn.setAttribute('disabled', '');
      showToast('Kamera-Feinschliff gespeichert.', 'success');
      onSaved?.(res.effective);
    } else {
      showToast('Konnte nicht gespeichert werden: ' + (res.error || '—'), 'error');
    }
  });

  qsa('[data-tune-preset]', root).forEach((btn) =>
    btn.addEventListener('click', async () => {
      const preset = _TRACK_PRESETS[btn.dataset.tunePreset];
      if (!preset) return;
      const fields = {
        track_spawn_min_score: preset.spawn,
        track_continue_min_score: preset.cont,
        track_miss_grace_seconds: preset.grace,
        track_iou_match_threshold: preset.iou,
      };
      const grace = qs('[data-tune="track_miss_grace_seconds"]', root);
      const iou = qs('[data-tune="track_iou_match_threshold"]', root);
      if (grace) grace.value = preset.grace;
      if (iou) iou.value = preset.iou;
      const res = await patchTuning(netzState.camId, fields);
      if (res.ok) {
        showToast(
          `Vorlage gespeichert · ${_TRACK_PRESET_LABELS[btn.dataset.tunePreset]}`,
          'success',
        );
        onSaved?.(res.effective);
      } else {
        showToast('Vorlage konnte nicht gespeichert werden: ' + (res.error || '—'), 'error');
      }
    }),
  );
}
