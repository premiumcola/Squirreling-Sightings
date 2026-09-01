// ─── weather/_manual-events.js ──────────────────────────────────────────
// Data layer + click-to-view for manual weather events — user-saved
// chart ranges from the Wetterdaten-chart's drag-zoom "als Ereignis
// speichern" action. Fetch/create/delete + the view modal live here;
// the SAVE FORM itself is _manual-event-save.js — a different concern
// (building/validating a new record vs. serving existing ones).
//
// The post-delete reload reaches for `window.loadWeatherSightings` (the
// bridge sightings.js publishes "for cross-module callers") rather than
// an ES import of sightings.js — sightings.js imports
// `openManualEventView`/`loadWeatherManualEvents` FROM this module for
// its grid loading + click-wiring, so an import the other way would be
// circular.
import { byId, esc } from '../core/dom.js';
import { state } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { apiGet, apiPost, apiDelete } from '../core/api.js';
import { _LB_TRASH_ICON_ONLY } from '../mediaview/panels/lb-helpers.js';
import { manualEventCategories, manualCategoryMeta } from './_manual-event-cats.js';
import { renderStatsChartInto } from './stats-chart/index.js';

export async function fetchManualEvents() {
  try {
    const d = await apiGet('/api/weather/manual-events');
    return d.items || [];
  } catch (_err) {
    return [];
  }
}

export function createManualEvent(payload) {
  return apiPost('/api/weather/manual-events', payload);
}

// Populates state.weather.manualEvents. Deliberately does NOT re-render
// the grid itself — see the module docstring on why this stays a leaf
// module with respect to sightings.js.
export async function loadWeatherManualEvents() {
  state.weather.manualEvents = await fetchManualEvents();
  return state.weather.manualEvents;
}

function _closeManualEventModal() {
  byId('wsManualEventModal')?.remove();
}

// The modal is where the categories get spelled out in words — the grid
// card only has room for their icons.
function _manualEventHeaderHTML(m, metas) {
  const primary = metas[0];
  const badges = metas
    .map(
      (meta) =>
        `<span class="ws-manual-modal-badge" style="color:${meta.color}" aria-hidden="true">${meta.icon}</span>`,
    )
    .join('');
  return `
    <div class="ws-manual-modal-head">
      ${badges}
      <div class="ws-manual-modal-title">
        <div class="ws-manual-modal-name">${esc(m.name || primary.de)}</div>
        <div class="ws-manual-modal-cat">${esc(metas.map((meta) => meta.de).join(' · '))}</div>
      </div>
      <button type="button" class="ws-manual-modal-close" aria-label="Schließen">✕</button>
    </div>`;
}

function _manualEventBodyHTML(m) {
  const note = m.characteristic
    ? `<p class="ws-manual-modal-note">${esc(m.characteristic)}</p>`
    : '';
  return `
    ${note}
    <div class="ws-stats-chart-wrap" id="wsManualEventChart"></div>
    <div class="ws-manual-modal-foot">
      <button type="button" class="ws-manual-modal-delete">${_LB_TRASH_ICON_ONLY} Löschen</button>
    </div>`;
}

// Milliseconds an armed delete button stays armed before quietly
// reverting — long enough for a deliberate second tap, short enough
// that a button left alone doesn't stay in its "sicher?" state
// indefinitely.
const _DELETE_ARM_MS = 4000;

// Press-again-in-place delete, replacing a separate confirm popup the
// operator reported rendering BEHIND the modal that opened it ("der
// Bestätigungsscreen... ist hinter dem eigentlichen Screen") — a
// second, independently-stacked overlay was never necessary here; the
// button that starts the action can just as well be the one that
// confirms it. First tap arms the button (label + colour flip to a
// clearly "this is now dangerous" dark red, matching the operator's
// own "sicher Fragezeichen dunkelrot"); a second tap while armed
// deletes for real. Any other interaction (blur, the auto-revert
// timer, a failed delete) disarms it, so a stray tap minutes later can
// never land on an already-armed button.
export function _wireDeleteButton(btn, id) {
  let armed = false;
  let timer = 0;
  const disarm = () => {
    armed = false;
    if (timer) {
      clearTimeout(timer);
      timer = 0;
    }
    btn.classList.remove('is-armed');
    btn.innerHTML = `${_LB_TRASH_ICON_ONLY} Löschen`;
  };
  const doDelete = () => {
    apiDelete(`/api/weather/manual-events/${encodeURIComponent(id)}`)
      .then(() => {
        _closeManualEventModal();
        window.loadWeatherSightings(state.weather.filter);
        window.reloadLibraryPage?.();
      })
      .catch((err) => {
        disarm();
        showToast('Löschen fehlgeschlagen: ' + (err?.message || err), 'error', {
          action: { label: 'Erneut versuchen', onClick: doDelete },
        });
      });
  };
  btn.addEventListener('click', () => {
    if (armed) {
      disarm();
      doDelete();
      return;
    }
    armed = true;
    btn.classList.add('is-armed');
    btn.innerHTML = `${_LB_TRASH_ICON_ONLY} Sicher?`;
    timer = setTimeout(disarm, _DELETE_ARM_MS);
  });
}

function _mountManualEventModal(m, metas) {
  byId('wsManualEventModal')?.remove();
  const modal = document.createElement('div');
  modal.className = 'ws-manual-modal';
  modal.id = 'wsManualEventModal';
  modal.innerHTML = `<div class="ws-manual-modal-card">${_manualEventHeaderHTML(m, metas)}${_manualEventBodyHTML(m)}</div>`;
  document.body.appendChild(modal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) _closeManualEventModal();
  });
  modal.querySelector('.ws-manual-modal-close')?.addEventListener('click', _closeManualEventModal);
  const deleteBtn = modal.querySelector('.ws-manual-modal-delete');
  if (deleteBtn) _wireDeleteButton(deleteBtn, m.id);
  const onEsc = (e) => {
    if (e.key !== 'Escape') return;
    _closeManualEventModal();
    document.removeEventListener('keydown', onEsc);
  };
  document.addEventListener('keydown', onEsc);
  return modal;
}

// Draw exactly this saved range/curves — the smallest reasonable "click
// a manual event" affordance: no video player, there is no clip, only a
// chart range. Re-fetches /api/weather/history with the ADDITIVE
// since/until params (routes/weather.py) because the saved range may no
// longer fall inside the live panel's own "last N hours" window.
export async function openManualEventView(id) {
  const m = (state.weather.manualEvents || []).find((it) => it.id === id);
  if (!m) return;
  const cats = manualEventCategories(m);
  const metas = (cats.length ? cats : ['']).map(manualCategoryMeta);
  const modal = _mountManualEventModal(m, metas);
  const wrap = modal.querySelector('#wsManualEventChart');
  try {
    const q = `since=${encodeURIComponent(m.range_start)}&until=${encodeURIComponent(m.range_end)}`;
    const data = await apiGet(`/api/weather/history?${q}`);
    renderStatsChartInto(wrap, data, { fields: m.curves });
  } catch (_err) {
    if (wrap) {
      wrap.innerHTML = '<div class="ws-stats-empty">Verlauf konnte nicht geladen werden.</div>';
    }
    showToast('Wetterverlauf konnte nicht geladen werden', 'error');
  }
}
