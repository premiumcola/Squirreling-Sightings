// ─── chrome/storage-stats.js ───────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — single source of
// truth for state.mediaStats. Every caller that mutates the archive
// (delete, bulk-delete, rescan, fix-thumbnails completion, processing
// poll completion) funnels through loadMediaStorageStats() so chips,
// size badges, and filter pills always reflect server reality.
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { j, apiPost } from '../core/api.js';
import { showToast, showConfirm } from '../core/toast.js';
import { renderTimeline } from '../timeline.js';

export async function loadMediaStorageStats() {
  const bar = byId('mediaStorageBar');
  if (!bar) return;
  try {
    const r = await j('/api/media/storage-stats');
    state.mediaStats = r.cameras || [];
    state.mediaArchived = r.archived || [];
    bar.innerHTML = '';
    // renderMediaOverview rebuilds the overview cards AND calls
    // renderMediaFilterPills('overview') internally. Both still live
    // in legacy.js for now, reached via window.X.
    if (typeof window.renderMediaOverview === 'function') window.renderMediaOverview();
    // Drilldown pill bar reads from the same state.mediaStats — keep
    // it in sync if the user is currently inside a drilldown.
    if (byId('mediaDrilldown')?.style.display !== 'none') {
      if (
        typeof window._pruneEmptyMediaFilters === 'function' &&
        window._pruneEmptyMediaFilters() &&
        typeof window._seedTopMediaLabel === 'function'
      ) {
        window._seedTopMediaLabel();
      }
      if (typeof window.renderMediaFilterPills === 'function') {
        window.renderMediaFilterPills('drilldown');
      }
    }
  } catch {
    bar.innerHTML = '';
    state.mediaStats = [];
    state.mediaArchived = [];
  }
}

// Targeted refresh after a delete / retag — keeps timeline dots and
// media-overview badges in sync without paying for a full loadAll().
export async function refreshTimelineAndStats() {
  const url = `/api/timeline?hours=${state.tlHours || 168}${state.label ? `&label=${encodeURIComponent(state.label)}` : ''}`;
  try {
    const [tl] = await Promise.all([j(url), loadMediaStorageStats()]);
    state.timeline = tl;
    renderTimeline();
  } catch {
    /* non-critical: leave previous render in place */
  }
}

// One-time wiring for the three buttons in the Mediathek settings
// section. All three guard against the elements being absent so the
// module is safe to import on pages without these controls.
byId('cleanupNowBtn')?.addEventListener('click', async () => {
  if (
    !(await showConfirm(
      'Jetzt bereinigen? Alle Dateien älter als die konfigurierte Aufbewahrungszeit werden gelöscht.',
    ))
  )
    return;
  const rdEl = byId('ms_retention_days');
  const payload = rdEl?.value ? { retention_days: Number(rdEl.value) } : {};
  try {
    const r = await j('/api/media/cleanup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    showToast(`Bereinigung abgeschlossen. ${r.removed || 0} Dateien entfernt.`, 'success');
    await loadMediaStorageStats();
  } catch (e) {
    showToast('Fehler: ' + e.message, 'error');
  }
});

byId('purgeOrphansBtn')?.addEventListener('click', async () => {
  if (
    !(await showConfirm(
      'Verwaiste Events löschen? Alle Event-Einträge ohne zugehörige Mediendatei werden entfernt.',
    ))
  )
    return;
  try {
    const r = await j('/api/media/purge-orphans', { method: 'POST' });
    showToast(`${r.removed || 0} verwaiste Events entfernt.`, 'success');
    if (typeof window.loadAll === 'function') await window.loadAll();
  } catch (e) {
    showToast('Fehler: ' + e.message, 'error');
  }
});

byId('mediaSettingsForm')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target.elements;
  const payload = {
    storage: {
      retention_days: Number(f['retention_days'].value || 14),
      auto_cleanup_enabled: !!f['auto_cleanup_enabled']?.checked,
    },
  };
  await apiPost('/api/settings/app', payload);
  if (typeof window.loadAll === 'function') await window.loadAll();
});
