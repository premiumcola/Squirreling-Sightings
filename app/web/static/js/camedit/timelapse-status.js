// ─── camedit/timelapse-status.js ───────────────────────────────────────────
// Dashboard status pill + live storage panel for the timelapse profiles.
// Split out of timelapse-settings.js, which was past the 400-line ceiling
// before this panel grew.
//
// /api/timelapse/status now reports what each profile actually holds on
// disk — frames, bytes, oldest/newest frame, projected full-window size
// and the next build time — read through a 60 s server-side cache. The
// panel used to show only "N Frames heute", which was both the least
// interesting number and, for the custom profile, always 0.
import { byId, esc } from '../core/dom.js';
import { j } from '../core/api.js';
import { _TL_PROFILES_DEF, _tlIntervalLabel } from './timelapse-settings.js';

const _TL_FILMSTRIP = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#c4b5fd" stroke-width="2" stroke-linecap="round" style="flex-shrink:0"><line x1="6" y1="3" x2="18" y2="3"/><line x1="6" y1="21" x2="18" y2="21"/><polygon points="7,4 17,4 12,12" fill="#c4b5fd" opacity=".8"/><polygon points="12,12 7,20 17,20" fill="#c4b5fd" opacity=".5"/></svg>`;

// German number formatting — decimal comma, no thousands separator noise.
function _tlFmtBytes(bytes) {
  const n = Number(bytes) || 0;
  if (n <= 0) return '0 MB';
  if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + ' KB';
  const mb = n / (1024 * 1024);
  if (mb < 1024) return mb.toFixed(mb < 10 ? 1 : 0).replace('.', ',') + ' MB';
  return (mb / 1024).toFixed(1).replace('.', ',') + ' GB';
}

function _tlFmtBuildAt(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  const hhmm =
    String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  const today = new Date();
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate();
  if (sameDay) return `heute ${hhmm}`;
  const dm = String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0');
  return `${dm}. ${hhmm}`;
}

function _tlProfileRow(label, prof) {
  const have = Number(prof.frame_count) || 0;
  const want = Math.max(1, Number(prof.expected_frames) || 1);
  const pct = Math.max(0, Math.min(100, Math.round((have / want) * 100)));
  const projected = Number(prof.projected_bytes) || 0;
  const rejected = Number(prof.rejected) || 0;
  const projLine = projected > 0 ? ` · Ziel ~${esc(_tlFmtBytes(projected))}` : '';
  const rejLine = rejected > 0 ? ` · ${rejected} verworfen` : '';
  const clamped = prof.interval_clamped
    ? '<span class="tl-sb-prof-warn" title="Intervall auf 8 s begrenzt">⚠</span>'
    : '';
  return `<div class="tl-sb-profile">
      <div class="tl-sb-prof-top">
        <span class="tl-sb-prof-name">${esc(label)}</span>
        <span class="tl-sb-prof-interval">alle ~${esc(_tlIntervalLabel(prof.interval_s))}${clamped}</span>
      </div>
      <div class="tl-sb-prof-facts">
        <span class="tl-sb-prof-frames">${have} / ${want} Frames</span>
        <span class="tl-sb-prof-bytes">${esc(_tlFmtBytes(prof.bytes_on_disk))}${projLine}${rejLine}</span>
      </div>
      <div class="tl-sb-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"
           aria-valuenow="${pct}" aria-label="Fortschritt ${esc(label)}">
        <div class="tl-sb-bar-fill" style="width:${pct}%"></div>
      </div>
      <div class="tl-sb-prof-foot">
        <span>${pct} %</span>
        <span>Build ${esc(_tlFmtBuildAt(prof.next_build_at))}</span>
      </div>
    </div>`;
}

function _tlCamBlock(cam) {
  const rows = _TL_PROFILES_DEF
    .map((p) => {
      const prof = cam.profiles?.[p.key];
      return prof?.enabled ? _tlProfileRow(p.label, prof) : '';
    })
    .join('');
  return `<div class="tl-sb-cam">
      <div class="tl-sb-cam-name">${esc(cam.name)}</div>
      <div class="tl-sb-profiles">${rows}</div>
    </div>`;
}

function renderTlStatusBar() {
  const bar = byId('tlStatusBar');
  if (!bar) return;
  const s = window._tlStatus;
  if (!s || s.active_count === 0) {
    bar.innerHTML = '';
    return;
  }
  const activeCams = (s.cameras || []).filter((c) => c.any_active);
  const totalBytes = activeCams.reduce(
    (sum, cam) =>
      sum +
      _TL_PROFILES_DEF.reduce((cs, p) => {
        const prof = cam.profiles?.[p.key];
        return cs + (prof?.enabled ? Number(prof.bytes_on_disk) || 0 : 0);
      }, 0),
    0,
  );
  const panelId = 'tlSbPanel';
  bar.innerHTML = `
    <div class="tl-sb-pill" onclick="byId('${panelId}').classList.toggle('hidden')">
      ${_TL_FILMSTRIP}
      <span>Timelapse aktiv</span>
      <span class="tl-sb-count">${activeCams.length}</span>
      <span class="tl-sb-bytes">${esc(_tlFmtBytes(totalBytes))}</span>
    </div>
    <div class="tl-sb-panel hidden" id="${panelId}">
      ${activeCams.map(_tlCamBlock).join('')}
      <div class="tl-sb-footer small muted">
        Belegung der noch nicht kodierten Frames · Stand: ${esc(s.today || '—')}
      </div>
    </div>`;
}

async function loadTlStatus() {
  try {
    window._tlStatus = await j('/api/timelapse/status');
    renderTlStatusBar();
  } catch (_err) {
    /* silent — a failed poll must not blank the panel */
  }
}

window._tlStatus = null;
// loadAll() in live-update.js looks this up by global name; without it
// the dashboard timelapse status pill stays empty.
window.loadTlStatus = loadTlStatus;

export { loadTlStatus, renderTlStatusBar };
