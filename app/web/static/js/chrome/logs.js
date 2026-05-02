// ─── chrome/logs.js ────────────────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — the Logs tab.
// Pulls /api/logs?level=…&subsystem=… on demand and renders the
// in-memory ring buffer (see app/app/logging_setup.py:_LogBuffer)
// into a coloured-row stream. Refresh / clear / filter changes all
// fire loadLogs() — the first invocation runs from the import-time
// boot block at the bottom.
import { byId, esc } from '../core/dom.js';
import { j } from '../core/api.js';

function _logSubsystemShort(logger){
  if (!logger) return '';
  // Handle sub-loggers like camera_runtime.timelapse, camera_runtime.camera
  if (logger.includes('camera_runtime.timelapse')) return 'tl';
  if (logger.includes('camera_runtime.camera')) return 'cam';
  const p = logger.split('.').pop() || logger;
  const MAP = { camera_runtime: 'runtime', timelapse: 'tl', telegram_bot: 'tg', detectors: 'coral', storage: 'store', mqtt_service: 'mqtt', server: 'srv', discovery: 'disc' };
  return MAP[p] || p.slice(0, 8);
}

export async function loadLogs(){
  const level = byId('logLevelFilter')?.value || 'INFO';
  const subsystem = byId('logSubsystemFilter')?.value || '';
  try {
    const params = `level=${level}${subsystem ? '&subsystem=' + encodeURIComponent(subsystem) : ''}`;
    const r = await j(`/api/logs?${params}`);
    renderLogs(r.logs || []);
  } catch (e){
    byId('logOutput').innerHTML = `<div class="log-row ERROR"><span class="log-ts">--:--:--</span><span class="log-level">ERROR</span><span>${esc(String(e))}</span></div>`;
  }
}

export function renderLogs(logs){
  const out = byId('logOutput');
  if (!out) return;
  if (!logs.length){
    out.innerHTML = '<div class="log-row INFO"><span class="log-ts">—</span><span class="log-level">—</span><span>Keine Log-Einträge auf diesem Level.</span></div>';
    return;
  }
  out.innerHTML = logs.map(l => {
    const tag = _logSubsystemShort(l.logger);
    return `<div class="log-row ${esc(l.level)}"><span class="log-ts">${esc(l.ts || '')}</span><span class="log-level">${esc(l.level || '')}</span>${tag ? `<span class="log-subsys">${esc(tag)}</span>` : '<span class="log-subsys"></span>'}<span>${esc(l.msg || '')}</span></div>`;
  }).join('');
  out.scrollTop = out.scrollHeight;
}

byId('logRefreshBtn')?.addEventListener('click', loadLogs);
byId('logClearBtn')?.addEventListener('click', () => { byId('logOutput').innerHTML = ''; });
byId('logLevelFilter')?.addEventListener('change', loadLogs);
byId('logSubsystemFilter')?.addEventListener('change', loadLogs);

// Fire one immediate load so the panel isn't empty before the user
// opens it. Cheap enough — server-side buffer is in-memory.
loadLogs();
