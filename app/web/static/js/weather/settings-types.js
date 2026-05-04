// ─── weather/settings-types.js ─────────────────────────────────────────────
// R10 — extracted from settings.js. Ereignistypen tab: per-trigger
// enable toggle + threshold slider for the configurable global weather
// events (Gewitter, Nebel, Wind, …). _renderWeatherEventsList draws the
// rows; bindWeatherTypesHandlers wires the change/input listeners.
import { byId, esc } from "../core/dom.js";
import { WEATHER_TYPES } from "../core/weather-types.js";
import { WEATHER_THRESHOLD_HINTS } from "./stats.js";
import { _saveWeatherCfg, _debouncedWeatherSave } from "./settings.js";

export function _renderWeatherEventsList(events){
  const wrap = byId('weatherEventsList'); if (!wrap) return;
  // Sun-Timelapse types are configured in the per-camera section below;
  // they don't have a single global threshold to slide, so skip them in
  // this list to avoid an undefined-`hint` crash.
  const tunable = Object.keys(WEATHER_TYPES).filter(t => WEATHER_THRESHOLD_HINTS[t]);
  wrap.innerHTML = tunable.map(t => {
    const meta = WEATHER_TYPES[t];
    const cfg = events[t] || {};
    const hint = WEATHER_THRESHOLD_HINTS[t];
    const v = cfg[hint.key] != null ? Number(cfg[hint.key]) : (hint.min + (hint.max - hint.min) / 2);
    return `
      <div class="ws-event-row" data-event="${esc(t)}">
        <span class="ws-event-chip" style="background:${meta.color}22;border:1px solid ${meta.color}55;color:${meta.color}">${meta.icon} ${esc(meta.de)}</span>
        <label class="switch ws-event-toggle"><input type="checkbox" ${cfg.enabled !== false ? 'checked' : ''} data-ws-event-toggle/><span class="slider"></span></label>
        <input type="range" class="ws-event-slider" min="${hint.min}" max="${hint.max}" step="${hint.step}" value="${v}" data-ws-event-slider/>
        <span class="ws-event-val"><span class="ws-event-num">${v}</span> ${esc(hint.unit)}</span>
      </div>`;
  }).join('');
}

export function bindWeatherTypesHandlers(){
  byId('weatherEventsList')?.addEventListener('change', (e) => {
    const row = e.target.closest('.ws-event-row'); if (!row) return;
    const evt = row.dataset.event;
    if (e.target.matches('[data-ws-event-toggle]')) {
      _saveWeatherCfg({ events: { [evt]: { enabled: !!e.target.checked } } });
    }
  });
  byId('weatherEventsList')?.addEventListener('input', (e) => {
    if (!e.target.matches('[data-ws-event-slider]')) return;
    const row = e.target.closest('.ws-event-row');
    const evt = row.dataset.event;
    const hint = WEATHER_THRESHOLD_HINTS[evt];
    const v = parseFloat(e.target.value) || 0;
    row.querySelector('.ws-event-num').textContent = v;
    _debouncedWeatherSave({ events: { [evt]: { [hint.key]: v } } });
  });
}
