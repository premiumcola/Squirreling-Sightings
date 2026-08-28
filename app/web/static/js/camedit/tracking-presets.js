// ─── camedit/tracking-presets.js ───────────────────────────────────────────
// The three one-click tracker presets on the Erkennung tab. The only
// control in the cam-edit panel that saves on click instead of on
// submit, which is why it carries its own POST helper.
//
// Extracted from camedit/index.js (919 lines against a 400-line ceiling).
import { state } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { apiPost } from '../core/api.js';

// ── Tracking presets ────────────────────────────────────────────────────────
// Three one-click presets fill the four tracker fields (Spawn-Schwelle,
// Fortsetzungs-Schwelle, Gnadenfrist, IoU-Schwelle). Values are chosen
// to bracket the module defaults so a power user can pick the right
// trade-off without reading the docs:
//   "Vorsichtig" — stricter, more likely to spawn fresh ids on dips.
//   "Ausgewogen" — module defaults (post 2026-05 retune); good for
//                  garden-cams with one or two subjects walking past.
//   "Robust"     — looser, holds onto subjects across longer occlusions.
// Pressing a preset writes into the input fields AND auto-persists the
// four track_* values to settings.json. The auto-save uses a partial
// payload (existing cam record spread + 4 overrides) so it touches
// nothing else — the user's other in-progress edits stay live in the
// form, and the regular Speichern still commits them. Without the
// auto-save the preset values disappeared on the next docker restart;
// most users assumed clicking a preset meant the camera was already
// using the new thresholds.
const _TRACK_PRESETS = {
  careful: { spawn: 0.55, cont: 0.3, grace: 4, iou: 0.3 },
  balanced: { spawn: 0.5, cont: 0.2, grace: 6, iou: 0.2 },
  robust: { spawn: 0.45, cont: 0.15, grace: 10, iou: 0.15 },
};

const _TRACK_PRESET_LABELS = {
  careful: 'Vorsichtig',
  balanced: 'Ausgewogen',
  robust: 'Robust',
};

export async function _saveTrackingPresetPatch(formEl, presetLabel, fields) {
  const camId = formEl.elements['id']?.value;
  if (!camId) return false;
  // Spread the stored cam record then override the four track_* keys.
  // The backend's `existing.update(camera)` (settings/store.py ja847) is
  // a non-destructive shallow merge, but its conn_changed check in
  // routes/cameras.py compares payload.get(f) != old_cfg.get(f) for
  // _CONN_FIELDS — sending a partial payload missing rtsp_url etc.
  // would compare `undefined != "rtsp://…"` and falsely trigger a
  // runtime restart on every preset click. Spreading the stored record
  // keeps those values identical and skips the restart path. We pull
  // from state.config.cameras (the full persisted dict) and fall back
  // to state.cameras (the live runtime-augmented dict) — same lookup
  // order editCamera() uses to open the panel.
  const stored =
    (state.config?.cameras || []).find((c) => c.id === camId) ||
    (state.cameras || []).find((c) => c.id === camId);
  if (!stored) return false;
  const payload = { ...stored, ...fields };
  try {
    await apiPost('/api/settings/cameras', payload);
    showToast(`Vorlage gespeichert · ${presetLabel}`, 'success');
    // Mutate the in-memory cam record so the next state-read (e.g. a
    // later partial save from another control) sees the new values.
    // A full loadAll() would re-render and likely close the panel,
    // which is the very thing we wanted to avoid.
    Object.assign(stored, fields);
    return true;
  } catch (e) {
    showToast('Vorlage konnte nicht gespeichert werden: ' + (e?.message || e), 'error');
    return false;
  }
}

export function _wireTrackingPresets(formEl) {
  if (!formEl || formEl.dataset.tpresetsWired === '1') return;
  formEl.dataset.tpresetsWired = '1';
  const buttons = formEl.querySelectorAll('.erk-track-preset');
  if (!buttons.length) return;
  buttons.forEach((btn) => {
    btn.addEventListener('click', async (ev) => {
      ev.preventDefault();
      const presetKey = btn.dataset.preset;
      const preset = _TRACK_PRESETS[presetKey];
      if (!preset) return;
      const f = formEl.elements;
      const fields = {
        track_spawn_min_score: preset.spawn,
        track_continue_min_score: preset.cont,
        track_miss_grace_seconds: preset.grace,
        track_iou_match_threshold: preset.iou,
      };
      Object.entries(fields).forEach(([name, value]) => {
        const inp = f[name];
        if (inp) {
          inp.value = value;
          // Fire input event so any listeners (e.g. dirty-state
          // tracking, autosave shimmers) update.
          inp.dispatchEvent(new Event('input', { bubbles: true }));
        }
      });
      // Visual feedback — flash the chosen preset, reset after 1 s
      // so the user sees confirmation without a permanent active
      // state.
      buttons.forEach((b) => {
        b.dataset.flash = '0';
      });
      btn.dataset.flash = '1';
      setTimeout(() => {
        btn.dataset.flash = '0';
      }, 900);
      const label = _TRACK_PRESET_LABELS[presetKey] || presetKey;
      await _saveTrackingPresetPatch(formEl, label, fields);
    });
  });
}
