// ─── weather/_manual-event-save.js ─────────────────────────────────────
// The Wetterdaten-chart's drag-zoom "als Ereignis speichern" form —
// name + category (one of core/weather-types.js's WEATHER_TYPES, so the
// saved record renders with the same badge/icon/colour machinery every
// other event uses) + which curves the operator marked as the evidence
// + a free-text "Charakteristik" describing how those curves moved
// together (the operator's own example: "Regen setzt ein, dann Blitze
// auf hohem Niveau, Wind nimmt zu und wieder ab … mittelgroßes
// Gewitter" — genuinely their own narrative, not something this module
// infers).
//
// Self-initialising leaf module (imported once, for its side effect, by
// main.js) — it reads the chart's zoom range and visible-fields state
// from ./_zoom.js and ./stats.js respectively but neither of those
// modules import anything back from here, so this file adds no new
// import cycle.
import { byId, esc } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { WEATHER_TYPES } from '../core/weather-types.js';
import { getZoomRange, zoomedSamples } from './_zoom.js';
import {
  _wsStatsState,
  _WS_FIELD_ORDER,
  WEATHER_STATS_PALETTE,
  WEATHER_FIELD_LABEL_DE,
  wsVisibleFields,
  wsLineEmphasis,
} from './stats.js';
import { buildLinePath } from './stats-chart/_paths.js';
import { createManualEvent, loadWeatherManualEvents } from './_manual-events.js';

// Only fields with an unambiguous 1:1 detector-category mapping earn a
// default guess (see routes/weather.py's HISTORY_FIELD_TO_EVENT for the
// backend's equivalent table) — wind_gusts_10m/cloud_cover/sun_altitude
// have no such category and are left for the operator to judge.
const _FIELD_TO_CATEGORY = {
  precipitation: 'heavy_rain',
  snowfall: 'snow',
  lightning_potential: 'thunder',
  visibility: 'fog',
};

// The curve that moved the MOST relative to its own reference span
// (wsLineEmphasis — the same "how interesting is this line" score the
// chart itself uses to draw bolder curves) wins the default category
// guess. `null` when nothing in the mapped set moved at all — the
// category picker then opens with nothing pre-selected.
export function _deriveDefaultCategory(samples) {
  let best = null;
  let bestScore = -1;
  for (const [field, category] of Object.entries(_FIELD_TO_CATEGORY)) {
    const meta = buildLinePath(samples, field, 0, 0, 1, 1);
    if (!meta) continue;
    const { width } = wsLineEmphasis(field, meta.lo, meta.hi);
    if (width > bestScore) {
      bestScore = width;
      best = category;
    }
  }
  return best;
}

function _categoryChipsHTML(activeCategory) {
  return Object.keys(WEATHER_TYPES)
    .map((key) => {
      const meta = WEATHER_TYPES[key];
      const active = key === activeCategory ? ' is-active' : '';
      return `<button type="button" class="ws-zsave-cat${active}" data-category="${esc(key)}" style="--cb:${meta.color}"><span class="ws-zsave-cat-ic" aria-hidden="true">${meta.icon}</span>${esc(meta.de)}</button>`;
    })
    .join('');
}

function _curveCheckboxesHTML(checkedFields) {
  return _WS_FIELD_ORDER
    .map((key) => {
      const checked = checkedFields.has(key) ? ' checked' : '';
      const label = WEATHER_FIELD_LABEL_DE[key] || key;
      const colour = WEATHER_STATS_PALETTE[key] || '#94a3b8';
      return `<label class="ws-zsave-curve">
        <input type="checkbox" value="${esc(key)}"${checked}>
        <span class="ws-zsave-curve-dot" style="background:${colour}"></span>${esc(label)}
      </label>`;
    })
    .join('');
}

function _formHTML(range, defaultCategory, checkedFields) {
  return `
    <div class="ws-zsave-row">
      <label class="ws-zsave-label" for="wsZsaveName">Name</label>
      <input type="text" class="ws-zsave-input" id="wsZsaveName" maxlength="120" placeholder="z. B. Gewitter mit Blitzen">
    </div>
    <div class="ws-zsave-row">
      <span class="ws-zsave-label">Kategorie</span>
      <div class="ws-zsave-cats" id="wsZsaveCats">${_categoryChipsHTML(defaultCategory)}</div>
    </div>
    <div class="ws-zsave-row">
      <span class="ws-zsave-label">Relevante Kurven</span>
      <div class="ws-zsave-curves" id="wsZsaveCurves">${_curveCheckboxesHTML(checkedFields)}</div>
    </div>
    <div class="ws-zsave-row">
      <label class="ws-zsave-label" for="wsZsaveNote">Charakteristik</label>
      <textarea class="ws-zsave-note" id="wsZsaveNote" maxlength="2000" rows="3"
        placeholder="z. B. Regen setzt ein, dann Blitze auf hohem Niveau, Wind nimmt zu und wieder ab, Wolkendecke maximal und fällt danach ab, Sicht sehr niedrig und erholt sich wieder — mittelgroßes Gewitter."></textarea>
    </div>
    <div class="ws-zsave-actions">
      <button type="button" class="btn" id="wsZsaveCancel">Abbrechen</button>
      <button type="button" class="btn btn-action action-green" id="wsZsaveSubmit">Speichern</button>
    </div>`;
}

function _selectedCategory(panel) {
  return panel.querySelector('.ws-zsave-cat.is-active')?.dataset.category || null;
}

function _selectedCurves(panel) {
  return [...panel.querySelectorAll('.ws-zsave-curves input:checked')].map((el) => el.value);
}

function _collectPayload(panel, range) {
  const name = panel.querySelector('#wsZsaveName').value.trim();
  const category = _selectedCategory(panel);
  const curves = _selectedCurves(panel);
  const characteristic = panel.querySelector('#wsZsaveNote').value.trim();
  if (!name) return { error: 'Bitte einen Namen eingeben.' };
  if (!category) return { error: 'Bitte eine Kategorie auswählen.' };
  if (!curves.length) return { error: 'Bitte mindestens eine Kurve auswählen.' };
  return {
    payload: {
      name,
      category,
      characteristic,
      range_start: range.start,
      range_end: range.end,
      curves,
    },
  };
}

function _wireForm(panel, range) {
  panel.querySelectorAll('.ws-zsave-cat').forEach((btn) => {
    btn.addEventListener('click', () => {
      panel
        .querySelectorAll('.ws-zsave-cat')
        .forEach((b) => b.classList.toggle('is-active', b === btn));
    });
  });
  panel.querySelector('#wsZsaveCancel')?.addEventListener('click', () => {
    panel.hidden = true;
  });
  panel.querySelector('#wsZsaveSubmit')?.addEventListener('click', () => {
    const { payload, error } = _collectPayload(panel, range);
    if (error) {
      showToast(error, 'error');
      return;
    }
    createManualEvent(payload)
      .then(() => {
        panel.hidden = true;
        showToast('Wetter-Ereignis gespeichert', 'success');
        return loadWeatherManualEvents();
      })
      .then(() => {
        if (typeof window.renderWeatherSightings === 'function') window.renderWeatherSightings();
      })
      .catch((err) => showToast('Speichern fehlgeschlagen: ' + (err?.message || err), 'error'));
  });
}

function _toggleSaveForm() {
  const panel = byId('weatherZoomSavePanel');
  if (!panel) return;
  if (!panel.hidden) {
    panel.hidden = true;
    return;
  }
  const range = getZoomRange();
  if (!range) return; // the button only shows while zoomed; defensive no-op otherwise
  const samples = zoomedSamples(_wsStatsState.data?.samples || []);
  const defaultCategory = _deriveDefaultCategory(samples);
  const checkedFields = new Set(wsVisibleFields());
  panel.innerHTML = _formHTML(range, defaultCategory, checkedFields);
  panel.hidden = false;
  _wireForm(panel, range);
}

function _initWeatherZoomSave() {
  byId('weatherZoomSaveBtn')?.addEventListener('click', _toggleSaveForm);
}

document.addEventListener('DOMContentLoaded', _initWeatherZoomSave);
