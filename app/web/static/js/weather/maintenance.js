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

import { byId } from '../core/dom.js';
import { j } from '../core/api.js';
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
      try { await window.loadWeatherSightings(); } catch { /* ignore */ }
    }
  } catch (e){
    showToast('Wetter-Scan fehlgeschlagen: ' + (e.message || e), 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('scanning');
  }
});

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
      try { await window.loadWeatherSightings(); } catch { /* ignore */ }
    }
  } catch (e){
    showToast('Thumb-Erzeugung fehlgeschlagen: ' + (e.message || e), 'error');
  } finally {
    btn.disabled = false;
    btn.classList.remove('scanning');
  }
});
