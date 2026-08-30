// ─── weather/maintenance.js ────────────────────────────────────────────────
// "Wetter-Wartung" — two one-shot maintenance buttons parked in a
// collapsed settings header above the Wetter-Ereignisse grid:
//
//   * weatherRescanBtn      → POST /api/weather/rescan
//     Registers orphan mp4s, marks manifests whose clip vanished,
//     regenerates any missing thumbnails. Idempotent.
//
//   * weatherThumbRegenBtn  → POST /api/weather/thumbs/regen
//     Force-rebuilds every thumb (middle frame of the matching mp4).
//     Used after a codec change or when thumbs look stale.
//
// Both share the spinner-while-running + toast-on-done pattern from
// mediathek/rescan.js. After a successful rescan the grid reloads via
// the global `loadWeatherSightings()` exposed by sightings.js so the
// newly registered cards appear without a manual reload.
//
// Per-category retention sliders — one blanket slider used to govern
// every kind of weather media; a quarterly recap and a daily sunrise
// clip have nothing in common retention-wise, so each category now has
// its own slider + its own settings.json key. Consumed nightly by
// weather_service/_retention.py's sweep. RETENTION_FIELDS is the single
// source of truth for which slider maps to which payload/DOM name —
// add a category here and both the save and the bootstrap-paint below
// pick it up automatically.

import { byId } from '../core/dom.js';
import { j, apiGet, apiPost } from '../core/api.js';
import { showToast } from '../core/toast.js';

byId('weatherRescanBtn')?.addEventListener('click', async () => {
  const btn = byId('weatherRescanBtn');
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('scanning');
  try {
    const r = await j('/api/weather/rescan', { method: 'POST' });
    const parts = [];
    if (r.registered) parts.push(`${r.registered} registriert`);
    if (r.thumbs_regen) parts.push(`${r.thumbs_regen} Thumbs erzeugt`);
    if (r.missing) parts.push(`${r.missing} fehlend markiert`);
    if (r.errors) parts.push(`${r.errors} Fehler`);
    const summary = parts.length
      ? parts.join(', ')
      : `Nichts neues — ${r.scanned || 0} Dateien geprüft`;
    showToast(`Wetter-Scan: ${summary}`, r.errors ? 'error' : 'success');
    if (typeof window.loadWeatherSightings === 'function') {
      try {
        await window.loadWeatherSightings();
      } catch {
        /* ignore */
      }
    }
  } catch (e) {
    showToast('Wetter-Scan fehlgeschlagen: ' + (e.message || e), 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('scanning');
  }
});

// field name (also the settings.json key under `weather.`) → slider DOM id.
// Kept in one place so a category can't drift between the save handler
// and the bootstrap-paint below.
const RETENTION_FIELDS = {
  retention_sightings_days: 'ws_retention_sightings',
  retention_event_timelapses_days: 'ws_retention_event_tl',
  retention_sun_timelapses_days: 'ws_retention_sun_tl',
  retention_recaps_days: 'ws_retention_recaps',
};

// ── Retention / auto-cleanup save handler ─────────────────────────────────
// Mirrors the Mediathek mediaSettingsForm submit in chrome/storage-stats.js
// — POSTs the sliders + toggle into ``weather`` so the same
// /api/settings/app endpoint persists them. The legacy blanket
// `retention_days` field is deliberately NOT sent any more (the per-
// category sliders replace it in the UI) — update_section deep-merges,
// so omitting it leaves whatever a real install already saved there
// untouched; it keeps working server-side as the fallback bucket for
// any category this form doesn't cover.
byId('weatherMaintForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const weather = { auto_cleanup_enabled: !!f['auto_cleanup_enabled']?.checked };
  for (const field of Object.keys(RETENTION_FIELDS)) {
    if (f[field]) {
      weather[field] = Number(f[field].value || 0);
    }
  }
  try {
    await apiPost('/api/settings/app', { weather });
    showToast('Wetter-Aufbewahrung gespeichert.', 'success');
  } catch (err) {
    showToast('Speichern fehlgeschlagen: ' + (err.message || err), 'error');
  }
});

// ── Bootstrap initial values from current settings ────────────────────────
// On first load, paint every slider + the toggle with whatever the server
// already persisted (falls back to each category's shipped default the
// very first time — mirrors WEATHER_RETENTION_DEFAULTS server-side). Same
// approach as camedit/index.js for the mediathek slider — best-effort,
// silent on failure.
(async function _initWeatherMaintFromSettings() {
  try {
    const data = await apiGet('/api/bootstrap');
    const w = (data && data.app && data.app.weather) || {};
    const auto = w.auto_cleanup_enabled !== false;
    const tog = byId('ws_auto_cleanup');
    if (tog) {
      tog.checked = auto;
    }
    for (const [field, inputId] of Object.entries(RETENTION_FIELDS)) {
      const sl = byId(inputId);
      if (!sl) continue;
      const fallback = Number(sl.value || 90);
      const days = Number(w[field] ?? fallback);
      sl.value = days;
      const lbl = byId(inputId + '_val');
      if (lbl) {
        lbl.textContent = days + ' Tage';
      }
    }
  } catch {
    /* silent */
  }
})();

byId('weatherThumbRegenBtn')?.addEventListener('click', async () => {
  const btn = byId('weatherThumbRegenBtn');
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add('scanning');
  try {
    const r = await j('/api/weather/thumbs/regen', { method: 'POST' });
    const parts = [];
    if (r.regenerated) parts.push(`${r.regenerated} erzeugt`);
    if (r.errors) parts.push(`${r.errors} Fehler`);
    if (r.skipped) parts.push(`${r.skipped} verwaiste Thumbs`);
    const summary = parts.length ? parts.join(', ') : 'keine Thumbs gefunden';
    showToast(`Wetter-Thumbs: ${summary}`, r.errors ? 'error' : 'success');
    if (typeof window.loadWeatherSightings === 'function') {
      try {
        await window.loadWeatherSightings();
      } catch {
        /* ignore */
      }
    }
  } catch (e) {
    showToast('Thumb-Erzeugung fehlgeschlagen: ' + (e.message || e), 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('scanning');
  }
});
