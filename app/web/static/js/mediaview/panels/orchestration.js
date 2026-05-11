// ─── mediaview/panels/orchestration.js ─────────────────────────────────────
// Composes the recorded-mode panel tabs and the fine-analysis fold
// into the existing #lightboxSettings host. Replaces the direct call
// to lbRenderSettingsPanel(item) from lightbox.js so the same DOM
// real-estate now carries: tabs ("Aufnahme-Settings" · "Nach-Erkennung"
// · optional "Wetter") + the always-on fine-analysis fold below.
//
// The settings tab is auto-expanded — inside a tab the user has
// already chosen to look at it, so the inner collapsible header from
// settings-panel.js opens by default. The legacy collapse button is
// kept (a second click hides the body again) so muscle-memory still
// works.
import { byId } from '../../core/dom.js';
import { showToast } from '../../core/toast.js';
import { lbRenderSettingsPanel } from '../../mediathek/bbox-overlay/settings-panel.js';
import { renderPanelTabs } from '../panel-tabs.js';
import { renderFineAnalysisFold } from '../fine-analysis-fold.js';

function _renderSettingsTab(host, item){
  // Reuse the existing settings renderer with a custom host. After
  // it renders, auto-expand the body so the user doesn't have to
  // click twice (once for the tab, once for the panel collapse).
  lbRenderSettingsPanel(item, host);
  const body = host.querySelector('.lbset-body');
  const header = host.querySelector('.lbset-header');
  if (body && header && body.hidden){
    body.hidden = false;
    header.setAttribute('aria-expanded', 'true');
  }
}

function _renderRescanTab(host, item){
  const eventId = item?.event_id;
  const camId = item?.camera_id || '';
  if (!eventId){
    host.innerHTML = `<div class="mv-rescan-empty">Event-ID fehlt — Re-Index nicht möglich</div>`;
    return;
  }
  host.innerHTML = `
    <div class="mv-rescan">
      <p class="mv-rescan-hint">Erkennt Objekte und Tracks für diese Aufnahme neu — nützlich nach Modell- oder Settings-Wechseln.</p>
      <button type="button" class="mv-rescan-btn">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 8A5.5 5.5 0 0 1 13 5M13.5 8A5.5 5.5 0 0 1 3 11"/><polyline points="12,2 12,5.5 8.5,5.5"/><polyline points="4,14 4,10.5 7.5,10.5"/></svg>
        <span>Tracking neu indexieren</span>
      </button>
      <div class="mv-rescan-status" hidden></div>
    </div>`;
  const btn = host.querySelector('.mv-rescan-btn');
  const status = host.querySelector('.mv-rescan-status');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    status.hidden = false;
    status.textContent = 'Wird neu indexiert …';
    status.dataset.tone = 'pending';
    try {
      const r = await fetch(
        `/api/events/${encodeURIComponent(eventId)}/rescan?camera_id=${encodeURIComponent(camId)}`,
        { method: 'POST' });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok){
        showToast('Tracking neu generiert', 'success');
        status.textContent = '✓ Worker hat den Job übernommen — Swimlane aktualisiert sich automatisch';
        status.dataset.tone = 'ok';
      } else {
        showToast(`Re-Index fehlgeschlagen: ${d.error || r.statusText}`, 'error');
        status.textContent = `Fehler: ${d.error || r.statusText}`;
        status.dataset.tone = 'err';
        btn.disabled = false;
      }
    } catch (err){
      const msg = err?.message || String(err);
      showToast(`Re-Index Fehler: ${msg}`, 'error');
      status.textContent = `Fehler: ${msg}`;
      status.dataset.tone = 'err';
      btn.disabled = false;
    }
  });
}

// Field-label / unit lookup for weather-sighting api_snapshot rows.
// Mirrors weather/sightings.js' WEATHER_FIELD_LABEL_DE / _UNIT_DE so
// the tab reads the same as the legacy ws-lb-rows block did. Kept
// inline (no shared module yet) because the rest of weather/* is in
// a different load order and importing it here would add a dependency
// cycle for one short dict.
const _WS_FIELD_LBL = {
  temperature_2m: 'Temperatur',
  humidity_2m: 'Luftfeuchte',
  precipitation: 'Niederschlag',
  rain: 'Regen',
  snowfall: 'Schnee',
  cloud_cover: 'Bewölkung',
  wind_speed_10m: 'Wind',
  wind_gusts_10m: 'Wind-Böen',
  pressure_msl: 'Luftdruck',
  weather_code: 'Wettercode',
  apparent_temperature: 'Gefühlt',
  visibility: 'Sicht',
};
const _WS_FIELD_UNIT = {
  temperature_2m: '°C',
  humidity_2m: '%',
  precipitation: 'mm',
  rain: 'mm',
  snowfall: 'cm',
  cloud_cover: '%',
  wind_speed_10m: 'km/h',
  wind_gusts_10m: 'km/h',
  pressure_msl: 'hPa',
  apparent_temperature: '°C',
  visibility: 'm',
};

function _renderWeatherTab(host, item){
  // Two shapes are supported:
  //   item.weather      → simple {temperature_c, cloud_cover_pct, …}
  //                       (motion-clip / future generic timelapse)
  //   item.api_snapshot → Open-Meteo raw snapshot dict (weather sighting)
  // The sighting variant also carries item.sun_snapshot for sunsets /
  // fog clips so the operator sees the altitude/azimuth alongside.
  const w = item?.weather;
  const snap = item?.api_snapshot;
  const sun = item?.sun_snapshot;
  if ((!w || typeof w !== 'object') && (!snap || typeof snap !== 'object')){
    host.innerHTML = `<div class="mv-rescan-empty">Keine Wetterdaten für diese Aufnahme.</div>`;
    return;
  }
  let rows = [];
  if (w && typeof w === 'object'){
    rows = [
      ['Temperatur',  w.temperature_c, '°C'],
      ['Bewölkung',   w.cloud_cover_pct, '%'],
      ['Niederschlag', w.precip_mm, ' mm'],
      ['Wind',        w.wind_kmh, ' km/h'],
      ['Luftfeuchte', w.humidity_pct, '%'],
      ['Bedingung',   w.condition, ''],
    ];
  } else if (snap){
    rows = Object.entries(snap)
      .filter(([k, v]) => v !== null && v !== undefined && k !== 'time')
      .map(([k, v]) => [_WS_FIELD_LBL[k] || k, v, _WS_FIELD_UNIT[k] || '']);
  }
  rows = rows.filter(([, v]) => v != null && v !== '');
  const sunRows = (sun && typeof sun === 'object')
    ? Object.entries(sun)
        .filter(([, v]) => v !== null && v !== undefined)
        .map(([k, v]) => [k === 'altitude' ? 'Sonne · Höhe' : 'Sonne · Azimut',
                          Number(v).toFixed(1), '°'])
    : [];
  const allRows = [...rows, ...sunRows];
  host.innerHTML = `
    <div class="mv-weather">
      ${allRows.map(([k, v, unit]) =>
        `<div class="mv-weather-row"><span class="mv-weather-key">${k}</span><span class="mv-weather-val">${v}${unit ? ' ' + unit : ''}</span></div>`,
      ).join('')}
    </div>`;
}

// Public entry — called from lightbox.js for BOTH motion clips and
// timelapses. Motion clips get the full tab set; timelapses get the
// Wetter + Nach-Erkennung pair plus the fold (no Aufnahme-Settings
// since timelapses don't carry recording_settings — they're not
// produced by the alarm pipeline). The fine-analysis fold renders
// for both kinds.
export function mountRecordedPanels(item){
  const host = byId('lightboxSettings');
  if (!host) return;
  if (!item){
    host.innerHTML = '';
    return;
  }
  const isTimelapse = item.type === 'timelapse';
  host.innerHTML = `
    <div class="mv-recorded-panels">
      <div class="mv-recorded-tabs"></div>
      <div class="mv-recorded-fafold"></div>
    </div>`;
  const tabsHost = host.querySelector('.mv-recorded-tabs');
  const faHost = host.querySelector('.mv-recorded-fafold');
  const tabs = [];
  if (!isTimelapse){
    tabs.push({ id: 'settings',
      label: 'Aufnahme-Settings',
      render: (h) => _renderSettingsTab(h, item) });
  }
  tabs.push({ id: 'rescan',
    label: 'Nach-Erkennung',
    render: (h) => _renderRescanTab(h, item) });
  // Weather tab — mounted whenever the item carries a weather
  // snapshot. Two shapes are accepted: item.weather (normalised
  // pairs) and item.api_snapshot (raw Open-Meteo dict, used by
  // weather sightings via openTLPlayer). Motion clips usually
  // carry neither; timelapses + weather sightings do.
  const hasWeather = !!((item.weather && typeof item.weather === 'object')
                         || (item.api_snapshot && typeof item.api_snapshot === 'object'));
  if (hasWeather){
    tabs.push({ id: 'weather',
      label: 'Wetter',
      render: (h) => _renderWeatherTab(h, item) });
  }
  // Initial tab — for timelapses default to Wetter when there's
  // weather data (the most useful view for a sun/event clip);
  // otherwise Nach-Erkennung. Motion clips keep Aufnahme-Settings
  // as the entry point.
  let initialId;
  if (isTimelapse && hasWeather) initialId = 'weather';
  else if (isTimelapse) initialId = 'rescan';
  else initialId = 'settings';
  renderPanelTabs(tabsHost, tabs, { initialId });
  // Recorded clips don't carry a server-side decision trace today —
  // the fold renders the standard "Trace nur im Live-Test verfügbar"
  // empty state. When the trace gets persisted (future change), pass
  // the lines through here.
  renderFineAnalysisFold(faHost, null);
}
