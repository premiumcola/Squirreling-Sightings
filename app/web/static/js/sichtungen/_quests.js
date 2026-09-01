// ─── sichtungen/_quests.js ───────────────────────────────────────────────
// Quest pinboard (F09) + upcoming-preview + archive. Split out of the
// former sichtungen.js monolith — self-contained sub-section, no
// cross-talk with the achievement grid or the species dossier panel
// beyond sharing the page. `setQuestsData` is called once per
// `/api/achievements` roundtrip (see index.js::loadAchievements); the
// three render functions then read that module-scoped snapshot so they
// can still be invoked standalone (e.g. the archive header's collapse
// toggle re-renders nothing, but keeping the zero-arg signature matches
// every other render* export in this package).
import { byId, esc } from '../core/dom.js';

let _questsData = {};
let _questsUpcoming = [];
let _questsArchive = {};

export function setQuestsData(questsData, upcoming, archive) {
  _questsData = questsData || {};
  _questsUpcoming = Array.isArray(upcoming) ? upcoming : [];
  _questsArchive = archive || {};
}

function _relativeTime(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return '';
  const delta = Math.max(0, Date.now() - t);
  const min = Math.floor(delta / 60000);
  if (min < 60) return `vor ${min} Min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `vor ${h} h`;
  const d = Math.floor(h / 24);
  return `vor ${d} ${d === 1 ? 'Tag' : 'Tagen'}`;
}

function _isQuestVisible(q) {
  // Always show active quests. Completed quests linger for 30 days as
  // a reward display, then get hidden so the pinboard doesn't keep
  // bloating with last-year's wins.
  if (!q || typeof q !== 'object') return false;
  if (!q.completed_at) return true;
  const t = Date.parse(q.completed_at);
  if (!Number.isFinite(t)) return false;
  return Date.now() - t < 30 * 24 * 3600 * 1000;
}

// Note: the manual "Re-Eval" button used to live in the pinboard head
// here. Removed because users had no obvious reason to click it — the
// hourly cron in server.py and the per-event hook in
// _recording.py::_finalize_motion_clip already keep quest progress
// fresh. The POST /api/achievements/quests/reevaluate route is kept
// for ops (curl / scripts), it just no longer has a UI affordance.

export function renderQuestsPinboard() {
  const wrap = byId('questsPinboard');
  if (!wrap) return;
  const all = Object.values(_questsData || {});
  const visible = all.filter(_isQuestVisible);
  // Sort: active (no completed_at) first, then most-recently completed.
  visible.sort((a, b) => {
    const ac = a.completed_at ? 1 : 0;
    const bc = b.completed_at ? 1 : 0;
    if (ac !== bc) return ac - bc;
    if (ac && bc) return (b.completed_at || '').localeCompare(a.completed_at || '');
    return (
      (b.progress || 0) / Math.max(1, b.target || 1) -
      (a.progress || 0) / Math.max(1, a.target || 1)
    );
  });

  if (!visible.length) {
    wrap.innerHTML = `
      <div class="quests-pinboard-head">
        <h4 class="quests-pinboard-title">🎯 Saison-Quests</h4>
      </div>
      <div class="quests-pinboard-empty">Aktuell keine aktiven Quests.</div>`;
    return;
  }

  const cards = visible
    .map((q) => {
      const target = Math.max(1, q.target || 1);
      const progress = Math.max(0, Math.min(target, q.progress || 0));
      const pct = Math.round((progress / target) * 100);
      const done = !!q.completed_at;
      const stateCls = done ? ' quest-card--done' : '';
      const badge = done
        ? `<span class="quest-done-badge" title="${esc(q.completed_at || '')}">✓ ${esc(_relativeTime(q.completed_at))}</span>`
        : `<span class="quest-progress-num">${progress}/${target}</span>`;
      return `<article class="quest-card${stateCls}">
      <div class="quest-card-head">
        <span class="quest-icon">${esc(q.icon || '🎯')}</span>
        <div class="quest-titles">
          <div class="quest-title">${esc(q.title || q.id || '')}</div>
          <div class="quest-desc">${esc(q.description || '')}</div>
        </div>
        ${badge}
      </div>
      <div class="quest-progress-track">
        <div class="quest-progress-fill${done ? ' quest-progress-fill--done' : ''}"
             style="width:${pct}%"></div>
      </div>
    </article>`;
    })
    .join('');

  wrap.innerHTML = `
    <div class="quests-pinboard-head">
      <h4 class="quests-pinboard-title">🎯 Saison-Quests</h4>
    </div>
    <div class="quests-pinboard-grid">${cards}</div>`;
}
window.renderQuestsPinboard = renderQuestsPinboard;

// ── Upcoming-quests preview (F09 v2) ──────────────────────────────────────
// Shows quests whose NEXT window opens within ~60 days. Strictly read-
// only — no progress bar, no live counter, just icon + title + "öffnet
// in X Tagen · läuft bis DD.MM.". Hidden entirely when nothing is on
// the horizon, so the section doesn't add chrome to a quiet pinboard.
function _fmtGermanShortDate(iso) {
  if (!iso) return '';
  const dt = new Date(iso);
  if (!Number.isFinite(dt.getTime())) return '';
  const dd = String(dt.getDate()).padStart(2, '0');
  const mm = String(dt.getMonth() + 1).padStart(2, '0');
  return `${dd}.${mm}.`;
}

export function renderQuestsUpcoming() {
  const wrap = byId('questsUpcoming');
  if (!wrap) return;
  const list = (_questsUpcoming || []).slice(0, 4); // cap at 4 cards
  if (!list.length) {
    wrap.innerHTML = '';
    return;
  }
  const cards = list
    .map((u) => {
      const days = Number.isFinite(u.opens_in_days) ? u.opens_in_days : 0;
      const dayLbl = days <= 0 ? 'heute' : `in ${days} ${days === 1 ? 'Tag' : 'Tagen'}`;
      const closeLbl = u.closes_at ? `läuft bis ${_fmtGermanShortDate(u.closes_at)}` : '';
      const sub = closeLbl ? `${dayLbl} · ${closeLbl}` : dayLbl;
      return `<article class="quest-card quest-card--upcoming">
      <div class="quest-card-head">
        <span class="quest-icon">${esc(u.icon || '🌱')}</span>
        <div class="quest-titles">
          <div class="quest-title">${esc(u.title || u.id || '')}</div>
          <div class="quest-desc">${esc(u.description || '')}</div>
        </div>
        <span class="quest-upcoming-when">${esc(sub)}</span>
      </div>
    </article>`;
    })
    .join('');
  wrap.innerHTML = `
    <div class="quests-pinboard-head">
      <h4 class="quests-pinboard-title">🌱 Demnächst</h4>
    </div>
    <div class="quests-pinboard-grid">${cards}</div>`;
}
window.renderQuestsUpcoming = renderQuestsUpcoming;

// ── Quests archive (F09 v2) ───────────────────────────────────────────────
// Closed-window-incomplete + catalog-removed entries with progress > 0
// land here. Header is collapsible; state persists in localStorage so
// the user doesn't have to expand/collapse on every page load. Hidden
// entirely when archive is empty — keeps the pinboard area quiet.
const _ARCHIVE_STORAGE_KEY = 'tamspy.questsArchiveOpen';

function _archiveOpen() {
  try {
    return localStorage.getItem(_ARCHIVE_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}
function _setArchiveOpen(on) {
  try {
    localStorage.setItem(_ARCHIVE_STORAGE_KEY, on ? '1' : '0');
  } catch {
    /* quota / private mode — best-effort */
  }
}

const _ARCHIVE_REASON_LABELS = {
  window_closed_incomplete: 'Fenster geschlossen',
  catalog_removed: 'aus Katalog entfernt',
};

export function renderQuestsArchive() {
  const wrap = byId('questsArchive');
  if (!wrap) return;
  const entries = Object.values(_questsArchive || {});
  if (!entries.length) {
    wrap.innerHTML = '';
    return;
  }
  // Sort newest archived_at first.
  entries.sort((a, b) => (b.archived_at || '').localeCompare(a.archived_at || ''));
  const open = _archiveOpen();
  const cards = entries
    .map((q) => {
      const target = Math.max(1, q.target || 1);
      const progress = Math.max(0, Math.min(target, q.progress || 0));
      const reasonLbl = _ARCHIVE_REASON_LABELS[q.archived_reason] || q.archived_reason || '';
      const ageLbl = _relativeTime(q.archived_at);
      return `<article class="quest-card quest-card--archived">
      <div class="quest-card-head">
        <span class="quest-icon">${esc(q.icon || '📦')}</span>
        <div class="quest-titles">
          <div class="quest-title">${esc(q.title || q.id || '')}</div>
          <div class="quest-desc">${esc(q.description || '')}</div>
        </div>
        <span class="quest-archive-final">${progress} / ${target}</span>
      </div>
      <div class="quest-archive-meta">
        <span class="quest-archive-age">${esc('archiviert · ' + ageLbl)}</span>
        ${reasonLbl ? `<span class="quest-archive-reason">${esc(reasonLbl)}</span>` : ''}
      </div>
    </article>`;
    })
    .join('');
  wrap.innerHTML = `
    <button type="button" class="quests-archive-header${open ? ' is-open' : ''}" id="questsArchiveHeader" aria-expanded="${open ? 'true' : 'false'}">
      <span class="quests-archive-title">📦 Archiv</span>
      <span class="quests-archive-count">${entries.length}</span>
      <svg class="quests-archive-chev" viewBox="0 0 12 12" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4.5l3 3 3-3"/></svg>
    </button>
    <div class="quests-archive-body" id="questsArchiveBody" ${open ? '' : 'hidden'}>
      <div class="quests-pinboard-grid">${cards}</div>
    </div>`;
  const hdr = byId('questsArchiveHeader');
  const body = byId('questsArchiveBody');
  if (hdr && body) {
    hdr.addEventListener('click', () => {
      const nowOpen = !!body.hasAttribute('hidden');
      if (nowOpen) body.removeAttribute('hidden');
      else body.setAttribute('hidden', '');
      hdr.classList.toggle('is-open', nowOpen);
      hdr.setAttribute('aria-expanded', nowOpen ? 'true' : 'false');
      _setArchiveOpen(nowOpen);
    });
  }
}
window.renderQuestsArchive = renderQuestsArchive;
