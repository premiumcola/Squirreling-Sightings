// ─── chrome/logs.js ────────────────────────────────────────────────────────
// Stage 10 of the legacy.js → ES modules refactor — the Logs tab.
// Pulls /api/logs?level=…&subsystem=… and renders the in-memory ring buffer
// (see app/app/logging_setup.py:_LogBuffer) into a coloured-row stream.
//
// Refreshes itself on a timer while the panel is actually on screen, so the
// operator never has to press anything to see current state; the manual
// Refresh button is gone. The Copy button hands the visible buffer over as
// plain text — the panel's real job is getting logs OUT of the box and into
// a chat window.
import { byId, esc } from '../core/dom.js';
import { j } from '../core/api.js';
import { copyText } from '../core/clipboard.js';

// Poll cadence while visible. The endpoint reads an in-memory ring buffer,
// so this is cheap — but it is still a request per tick per open tab, and
// nothing in a log stream needs sub-5-second latency.
const REFRESH_MS = 5000;
// How close to the bottom counts as "following the tail". Below this the
// operator is reading something and the view must not be yanked away.
const STICK_PX = 40;

let _lastLogs = [];
let _timer = 0;

function _logSubsystemShort(logger) {
  if (!logger) return '';
  // Handle sub-loggers like camera_runtime.timelapse, camera_runtime.camera
  if (logger.includes('camera_runtime.timelapse')) return 'tl';
  if (logger.includes('camera_runtime.camera')) return 'cam';
  const p = logger.split('.').pop() || logger;
  const MAP = {
    camera_runtime: 'runtime',
    timelapse: 'tl',
    telegram_bot: 'tg',
    detectors: 'coral',
    storage: 'store',
    mqtt_service: 'mqtt',
    server: 'srv',
    discovery: 'disc',
  };
  return MAP[p] || p.slice(0, 8);
}

export async function loadLogs() {
  const level = byId('logLevelFilter')?.value || 'INFO';
  const subsystem = byId('logSubsystemFilter')?.value || '';
  try {
    const params = `level=${level}${subsystem ? '&subsystem=' + encodeURIComponent(subsystem) : ''}`;
    const r = await j(`/api/logs?${params}`);
    _lastLogs = r.logs || [];
    renderLogs(_lastLogs);
  } catch (e) {
    _lastLogs = [];
    byId('logOutput').innerHTML =
      `<div class="log-row ERROR"><span class="log-ts">--:--:--</span><span class="log-level">ERROR</span><span>${esc(String(e))}</span></div>`;
  }
}

export function renderLogs(logs) {
  const out = byId('logOutput');
  if (!out) return;
  if (!logs.length) {
    out.innerHTML =
      '<div class="log-row INFO"><span class="log-ts">—</span><span class="log-level">—</span><span>Keine Log-Einträge auf diesem Level.</span></div>';
    return;
  }
  // Auto-scroll ONLY when already following the tail. Re-rendering every 5 s
  // while the operator is scrolled up reading an error would otherwise throw
  // them back to the bottom each tick and make the panel unusable.
  const following = out.scrollHeight - out.scrollTop - out.clientHeight < STICK_PX;
  const prevTop = out.scrollTop;
  out.innerHTML = logs
    .map((l) => {
      const tag = _logSubsystemShort(l.logger);
      return `<div class="log-row ${esc(l.level)}"><span class="log-ts">${esc(l.ts || '')}</span><span class="log-level">${esc(l.level || '')}</span>${tag ? `<span class="log-subsys">${esc(tag)}</span>` : '<span class="log-subsys"></span>'}<span>${esc(l.msg || '')}</span></div>`;
    })
    .join('');
  out.scrollTop = following ? out.scrollHeight : prevTop;
}

// Plain text, one line per entry — the format that survives a paste into a
// chat window. Columns are padded so levels and subsystems line up, and a
// header states which filter produced it, since "no errors" means nothing
// without knowing the level was not set to ERROR-only.
function _logsAsText() {
  const level = byId('logLevelFilter')?.value || 'INFO';
  const sub = byId('logSubsystemFilter')?.value || '';
  const now = new Date().toTimeString().slice(0, 8);
  const head =
    `System-Logs · Level=${level} · Subsystem=${sub || 'alle'} · ` +
    `${_lastLogs.length} Einträge · kopiert ${now}`;
  const body = _lastLogs.map((l) => {
    const ts = (l.ts || '').padEnd(8);
    const lvl = (l.level || '').padEnd(7);
    const tag = _logSubsystemShort(l.logger).padEnd(8);
    return `${ts}  ${lvl}  ${tag}  ${l.msg || ''}`;
  });
  return [head, '─'.repeat(head.length), ...body].join('\n');
}

function _flash(btn, text) {
  const prev = btn.dataset.label || btn.textContent.trim();
  btn.dataset.label = prev;
  btn.textContent = text;
  setTimeout(() => {
    btn.textContent = btn.dataset.label || prev;
  }, 1600);
}

function _wireCopy() {
  const btn = byId('logCopyBtn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    if (!_lastLogs.length) {
      _flash(btn, 'Nichts zu kopieren');
      return;
    }
    // Synchronous — see core/clipboard.js on why nothing may be awaited
    // before the write.
    copyText(_logsAsText(), {
      onOk: () => _flash(btn, `${_lastLogs.length} Zeilen kopiert`),
      onFail: () => _flash(btn, 'Kopieren fehlgeschlagen'),
    });
  });
}

// Poll only while the panel is on screen AND the tab is foregrounded. A
// background tab polling a log endpoint forever is exactly the kind of
// quiet waste this project has been auditing out.
function _startAutoRefresh() {
  const section = byId('logs');
  if (!section) return;
  let onScreen = false;
  const tick = () => {
    if (onScreen && !document.hidden) loadLogs();
  };
  const arm = () => {
    if (_timer) return;
    _timer = setInterval(tick, REFRESH_MS);
  };
  const disarm = () => {
    if (!_timer) return;
    clearInterval(_timer);
    _timer = 0;
  };
  const io = new IntersectionObserver(
    (entries) => {
      onScreen = entries.some((e) => e.isIntersecting);
      if (onScreen) {
        loadLogs();
        arm();
      } else {
        disarm();
      }
    },
    { threshold: 0 },
  );
  io.observe(section);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) disarm();
    else if (onScreen) arm();
  });
}

byId('logClearBtn')?.addEventListener('click', () => {
  byId('logOutput').innerHTML = '';
  _lastLogs = [];
});
byId('logLevelFilter')?.addEventListener('change', loadLogs);
byId('logSubsystemFilter')?.addEventListener('change', loadLogs);
_wireCopy();
_startAutoRefresh();

// Fire one immediate load so the panel isn't empty before the observer
// first reports. Cheap — the server-side buffer is in memory.
loadLogs();
