// ─── weather/_manual-event-save.js ─────────────────────────────────────
// The Wetterdaten-chart's drag-zoom "als Ereignis speichern" form —
// name + one to three categories (keys of core/weather-types.js's
// WEATHER_TYPES, so the saved record renders with the same
// badge/icon/colour machinery every other event uses; several because a
// storm that also brings heavy rain genuinely is both) + which curves
// the operator marked as the evidence
// + a free-text "Charakteristik" describing how those curves moved
// together (the operator's own example: "Regen setzt ein, dann Blitze
// auf hohem Niveau, Wind nimmt zu und wieder ab … mittelgroßes
// Gewitter" — genuinely their own narrative, not something this module
// infers).
//
// Self-initialising leaf module (imported once, for its side effect, by
// main.js) — it reads the chart's zoom range and visible-fields state
// from ./_zoom.js and ./stats.js respectively, and now also owns the
// "Kurven markieren" toggle for weather/_chart-annotations.js's chart
// markers (the ACTUAL pointer-mode + rendering logic lives there and in
// stats-chart/_hover.js — this file only reads its collected payload and
// flips its on/off state). None of those modules import anything back
// from here, so this file still adds no new import cycle.
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
  renderWeatherStatsChart,
} from './stats.js';
import { buildLinePath, fieldDataExtent } from './stats-chart/_paths.js';
import { createManualEvent, loadWeatherManualEvents } from './_manual-events.js';
import { MANUAL_CATEGORIES_MAX } from './_manual-event-cats.js';
import {
  annotationsPayload,
  isMarkModeActive,
  resetChartAnnotations,
  setMarkModeActive,
} from './_chart-annotations.js';

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

// How far a curve must actually move before it may pre-select a
// category — in PHYSICAL units, deliberately not in the normalised
// emphasis score. Normalisation is right for "which line should be
// drawn boldest" and wrong for "did anything happen": a 0.02 cm/h trace
// of snow looks respectable against a 1 cm/h reference span, and is
// nothing in the sky. Snow is the rarest thing this garden sees, so
// guessing it from a trace is the most conspicuous version of the
// mistake — but the floor gates every field, not just that one.
const _MIN_SWING_FOR_GUESS = {
  precipitation: 0.5, // mm/h — light rain, not a stray drop
  snowfall: 0.5, // cm/h — real snowfall, not a dusting
  lightning_potential: 0.3, // J/kg, on the corrected LPI trigger scale
  visibility: 1500, // m — a drop deep enough to read as fog forming
};

// The curve that moved the MOST relative to its own reference span
// (wsLineEmphasis — the same "how interesting is this line" score the
// chart itself uses to draw bolder curves) wins the default category
// guess, among those that cleared their floor above. `null` when
// nothing in the mapped set moved enough — the category picker then
// opens with nothing pre-selected.
//
// That null used to be unreachable in practice: wsLineEmphasis never
// returns a width below 1.4, so ANY mapped field carrying data beat the
// -1 the search started from. A flat, dry window therefore always got a
// guess — whichever field the loop reached first — and a trace of snow
// beat an empty sky.
export function _deriveDefaultCategory(samples) {
  let best = null;
  let bestScore = -1;
  for (const [field, category] of Object.entries(_FIELD_TO_CATEGORY)) {
    const meta = buildLinePath(samples, field, 0, 0, 1, 1);
    if (!meta) continue;
    // The RAW extent, not meta.lo/hi — those carry the flat-line
    // padding the chart needs to draw a straight line mid-band.
    const extent = fieldDataExtent(samples, field);
    if (!extent) continue;
    const swing = Math.abs(extent.hi - extent.lo);
    if (swing < (_MIN_SWING_FOR_GUESS[field] ?? 0)) continue;
    const { width } = wsLineEmphasis(field, meta.lo, meta.hi);
    if (width > bestScore) {
      bestScore = width;
      best = category;
    }
  }
  return best;
}

// The categories a manually-saved event can actually be. WEATHER_TYPES
// itself carries more keys than this — sun_timelapse_rise/_set and the
// thunder_rising/front_passing/storm_front trio are trigger subtypes
// for the automatic 60-min weather-timelapse capture mechanism (see
// core/weather-types.js's own comment on that table), not categories an
// operator judging a storm by hand would ever pick between — showing
// all nine here read as "the others didn't hold up" ("was sind das für
// Ausreißer, die alle raus"). thunder_rising survives because it's a
// real judgement call ("Gewitter zieht auf" — a storm building) an
// operator can make about a window they're looking at, same as the
// four core categories; the other three are report-format artefacts
// of the capture pipeline, not storm characterisations.
const _MANUAL_EVENT_CATEGORY_KEYS = ['thunder', 'heavy_rain', 'snow', 'fog', 'thunder_rising'];

// Multi-select: an event is genuinely more than one thing (the
// operator's own example is a thunderstorm that ALSO brings heavy rain),
// so several chips can be lit at once — up to MANUAL_CATEGORIES_MAX.
// `aria-pressed` carries the selected state, not colour alone.
export function _categoryChipsHTML(activeCategories) {
  return _MANUAL_EVENT_CATEGORY_KEYS.map((key) => {
    const meta = WEATHER_TYPES[key];
    const on = activeCategories.has(key);
    return `<button type="button" class="ws-zsave-cat${on ? ' is-active' : ''}" aria-pressed="${on}" data-category="${esc(key)}" style="--cb:${meta.color}"><span class="ws-zsave-cat-ic" aria-hidden="true">${meta.icon}</span>${esc(meta.de)}</button>`;
  }).join('');
}

// Flag glyph — "a small flag/pin rendered at that exact (curve,
// timestamp) point" is literally what marking places on the chart, so
// the toggle that turns marking on/off carries the same shape.
const _MARK_TOGGLE_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 3v18M5 4h11l-2 4 2 4H5"/></svg>`;

function _markToggleHTML() {
  const on = isMarkModeActive();
  return (
    `<button type="button" class="ws-zsave-mark-toggle${on ? ' is-active' : ''}" ` +
    `id="wsZsaveMarkToggle" aria-pressed="${on}">${_MARK_TOGGLE_ICON}Kurven markieren</button>`
  );
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

function _formHTML(activeCategories, checkedFields) {
  return `
    <div class="ws-zsave-row">
      <label class="ws-zsave-label" for="wsZsaveName">Name</label>
      <input type="text" class="ws-zsave-input" id="wsZsaveName" maxlength="120" placeholder="z. B. Gewitter mit Blitzen">
    </div>
    <div class="ws-zsave-row">
      <span class="ws-zsave-label">Kategorie <span class="ws-zsave-hint">mehrere möglich</span></span>
      <div class="ws-zsave-cats" id="wsZsaveCats">${_categoryChipsHTML(activeCategories)}</div>
    </div>
    <div class="ws-zsave-row">
      <span class="ws-zsave-label">Relevante Kurven</span>
      <div class="ws-zsave-curves" id="wsZsaveCurves">${_curveCheckboxesHTML(checkedFields)}</div>
    </div>
    <div class="ws-zsave-row">
      ${_markToggleHTML()}
      <p class="ws-zsave-mark-hint">Optional — antippen, um eine Kurve im gezeigten Zeitraum an einem Punkt zu markieren und die Phase (Aufbau / Kern / Abbau) zuzuordnen.</p>
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

// DOM-walk, not a cached JS Set — the panel's markup is the single
// source of truth for what is currently ticked (CLAUDE.md's collector
// rule), so a chip toggled by any path is picked up. Exported because
// weather/save-panel-fx/ needs the SAME answer to pick its backdrop —
// one reader, so the payload and the animation can never disagree.
export function _selectedCategories(panel) {
  return [...panel.querySelectorAll('.ws-zsave-cat.is-active')].map((el) => el.dataset.category);
}

function _selectedCurves(panel) {
  return [...panel.querySelectorAll('.ws-zsave-curves input:checked')].map((el) => el.value);
}

export function _collectPayload(panel, range) {
  const name = panel.querySelector('#wsZsaveName').value.trim();
  const categories = _selectedCategories(panel);
  const curves = _selectedCurves(panel);
  const characteristic = panel.querySelector('#wsZsaveNote').value.trim();
  if (!name) return { error: 'Bitte einen Namen eingeben.' };
  if (!categories.length) return { error: 'Bitte mindestens eine Kategorie auswählen.' };
  if (!curves.length) return { error: 'Bitte mindestens eine Kurve auswählen.' };
  return {
    payload: {
      name,
      categories,
      characteristic,
      range_start: range.start,
      range_end: range.end,
      curves,
      annotations: annotationsPayload(),
    },
  };
}

// Toggle, not radio-select. The cap is enforced here AND server-side;
// hitting it is an error the operator must see, not a silently ignored
// tap.
function _wireCategoryChips(panel) {
  panel.querySelectorAll('.ws-zsave-cat').forEach((btn) => {
    btn.addEventListener('click', () => {
      const on = btn.classList.contains('is-active');
      if (!on && _selectedCategories(panel).length >= MANUAL_CATEGORIES_MAX) {
        showToast(`Höchstens ${MANUAL_CATEGORIES_MAX} Kategorien.`, 'error');
        return;
      }
      btn.classList.toggle('is-active', !on);
      btn.setAttribute('aria-pressed', String(!on));
    });
  });
}

// The chart's own pointer behaviour flips to marking mode (see
// stats-chart/_hover.js's markMode branch) — needs a chart redraw to
// take effect, since the mode is read once per bind, not live-polled.
function _wireMarkModeToggle(panel) {
  const btn = panel.querySelector('#wsZsaveMarkToggle');
  if (!btn) return;
  btn.addEventListener('click', () => {
    setMarkModeActive(!isMarkModeActive());
    btn.classList.toggle('is-active', isMarkModeActive());
    btn.setAttribute('aria-pressed', String(isMarkModeActive()));
    renderWeatherStatsChart();
  });
}

// Every path that closes the save panel must also leave marking mode —
// otherwise the chart stays bound with markMode:true (and the now-
// discarded marker set still drawn) after the panel the markers belong
// to is gone. Pure state reset + a redraw so the chart reflects it
// immediately; see weather/_chart-annotations.js's own "pure state,
// caller redraws" contract.
function _exitMarkMode(panel) {
  panel.hidden = true;
  resetChartAnnotations();
  renderWeatherStatsChart();
}

// The saved record IS the confirmation — the operator asked for it to
// land visibly in the list below instead of a toast ("es sollte in dem
// Editscreen weggehen und eben runter in die History direkt kommen").
// So the fresh card announces itself with a short tint and, if it is
// off-screen after the panel collapsed, scrolls into view. Nothing
// permanent: the next grid render rebuilds innerHTML and the class is
// gone. Motion opts out via prefers-reduced-motion (see
// css/23b-weather-zoom.css).
function _revealSavedCard(id) {
  if (!id) return;
  const grid = byId('libraryGrid');
  if (!grid) return;
  const cards = Array.from(grid.querySelectorAll('.ws-manual-card') || []);
  const card = cards.find((el) => el.dataset?.manualId === id);
  if (!card) return;
  card.classList.add('ws-manual-card--new');
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// A FAILED save keeps its toast — loudly. Only the success toast went
// away, and only because the new card replaces it; a save that fails
// must never look like a save that worked.
export function _submitSave(panel, range) {
  const { payload, error } = _collectPayload(panel, range);
  if (error) {
    showToast(error, 'error');
    return Promise.resolve();
  }
  return createManualEvent(payload)
    .then((res) => {
      _exitMarkMode(panel);
      return loadWeatherManualEvents().then(() => res?.item?.id || null);
    })
    .then((newId) => {
      // The merged grid (library/page.js) owns the card now — reload it
      // before revealing, so the new manual-event card actually exists
      // in the DOM to scroll to.
      const reload =
        typeof window.reloadLibraryPage === 'function'
          ? window.reloadLibraryPage()
          : Promise.resolve();
      return Promise.resolve(reload).then(() => _revealSavedCard(newId));
    })
    .catch((err) => showToast('Speichern fehlgeschlagen: ' + (err?.message || err), 'error'));
}

function _wireForm(panel, range) {
  _wireCategoryChips(panel);
  _wireMarkModeToggle(panel);
  panel.querySelector('#wsZsaveCancel')?.addEventListener('click', () => {
    _exitMarkMode(panel);
  });
  panel.querySelector('#wsZsaveSubmit')?.addEventListener('click', () => {
    _submitSave(panel, range);
  });
}

function _toggleSaveForm() {
  const panel = byId('weatherZoomSavePanel');
  if (!panel) return;
  if (!panel.hidden) {
    _exitMarkMode(panel);
    return;
  }
  const range = getZoomRange();
  if (!range) return; // the button only shows while zoomed; defensive no-op otherwise
  const samples = zoomedSamples(_wsStatsState.data?.samples || []);
  const defaultCategory = _deriveDefaultCategory(samples);
  const activeCategories = new Set(defaultCategory ? [defaultCategory] : []);
  const checkedFields = new Set(wsVisibleFields());
  panel.innerHTML = _formHTML(activeCategories, checkedFields);
  panel.hidden = false;
  _wireForm(panel, range);
}

function _initWeatherZoomSave() {
  byId('weatherZoomSaveBtn')?.addEventListener('click', _toggleSaveForm);
}

document.addEventListener('DOMContentLoaded', _initWeatherZoomSave);
