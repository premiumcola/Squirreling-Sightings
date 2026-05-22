// ─── weather/settings-location.js ──────────────────────────────────────────
// R10 — extracted from settings.js. Standort tab: Leaflet map picker,
// lat/lon/elev inputs, auto-elevation lookup. Lazy: the map only inits
// the first time the Standort tab is opened (settings.js calls
// _initWeatherMap from its tab-activation handler).
import { byId } from '../core/dom.js';
import { state } from '../core/state.js';
import { _weatherPanelSave } from './settings.js';

// ── Weather location map (Leaflet) ──────────────────────────────────────────
// Lazy singleton — Leaflet can only render once its container is visible, so
// init is deferred until the Standort tab is opened. Subsequent opens just
// invalidateSize() so the tile grid refits the (possibly resized) container.
let _wsMap = null;
let _wsMarker = null;
let _wsSyncing = false; // suppresses input handlers while we write
// values from the map back into the inputs
let _wsLocSaveTimer = null;

function _wsPinIcon() {
  // Flat-design teardrop pin in storm-blue. 32×42 visual on a 44×44 hit area
  // so the touch target hits the project's iOS minimum.
  const svg =
    '<svg viewBox="0 0 32 44" width="32" height="42" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M16 2C9.4 2 4 7.4 4 14c0 9 12 26 12 26s12-17 12-26c0-6.6-5.4-12-12-12z" ' +
    'fill="rgb(127,174,201)" stroke="rgba(0,0,0,.35)" stroke-width="1"/>' +
    '<circle cx="16" cy="14" r="4.5" fill="#fff"/></svg>';
  return L.divIcon({
    className: 'ws-map-pin-wrap',
    html: '<div class="ws-map-pin-hit">' + svg + '</div>',
    iconSize: [44, 44],
    iconAnchor: [22, 42],
  });
}

export function _initWeatherMap() {
  const el = byId('weatherMap');
  if (!el) return;
  if (typeof L === 'undefined') return; // Leaflet CDN unreachable — fail silent
  if (_wsMap) {
    _wsMap.invalidateSize();
    return;
  }
  const lat = parseFloat(byId('ws_lat').value);
  const lon = parseFloat(byId('ws_lon').value);
  const hasLoc = Number.isFinite(lat) && Number.isFinite(lon);
  _wsMap = L.map(el, {
    center: hasLoc ? [lat, lon] : [51.16, 10.45],
    zoom: hasLoc ? 15 : 5,
    scrollWheelZoom: true,
  });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap',
  }).addTo(_wsMap);
  if (hasLoc) _setWeatherMapMarker(lat, lon, false);
  _wsMap.on('click', (e) => {
    _setWeatherMapMarker(e.latlng.lat, e.latlng.lng, false);
    _wsWriteInputsFromMap(e.latlng.lat, e.latlng.lng);
    _saveWeatherLocation();
  });
  // Container was hidden when init started in some flows — ensure tile grid
  // matches the visible size on the next paint.
  setTimeout(() => {
    if (_wsMap) _wsMap.invalidateSize();
  }, 60);
}

function _setWeatherMapMarker(lat, lon, panTo) {
  if (!_wsMap) return;
  const ll = [lat, lon];
  if (!_wsMarker) {
    _wsMarker = L.marker(ll, { draggable: true, icon: _wsPinIcon() }).addTo(_wsMap);
    _wsMarker.on('dragend', (ev) => {
      const p = ev.target.getLatLng();
      _wsWriteInputsFromMap(p.lat, p.lng);
      _saveWeatherLocation();
    });
  } else {
    _wsMarker.setLatLng(ll);
  }
  if (panTo) _wsMap.setView(ll, Math.max(_wsMap.getZoom(), 13));
}

function _wsWriteInputsFromMap(lat, lon) {
  _wsSyncing = true;
  const elLat = byId('ws_lat');
  if (elLat) elLat.value = lat.toFixed(6);
  const elLon = byId('ws_lon');
  if (elLon) elLon.value = lon.toFixed(6);
  _wsSyncing = false;
}

async function _saveWeatherLocation() {
  const lat = parseFloat(byId('ws_lat').value);
  const lon = parseFloat(byId('ws_lon').value);
  const elevRaw = byId('ws_elev').value;
  const elev = elevRaw === '' ? null : parseFloat(elevRaw);
  const partial = {
    server: {
      location: {
        lat: Number.isFinite(lat) ? lat : null,
        lon: Number.isFinite(lon) ? lon : null,
        elevation: Number.isFinite(elev) ? elev : null,
      },
    },
  };
  const r = await _weatherPanelSave('/api/settings/app', partial);
  if (r && r.ok) {
    state.config.server = state.config.server || {};
    state.config.server.location = partial.server.location;
    if (Number.isFinite(lat) && Number.isFinite(lon) && elevRaw === '') {
      _wsAutoFetchElevation(lat, lon);
    }
  }
}

async function _wsAutoFetchElevation(lat, lon) {
  // Open-Meteo /v1/elevation: free, no key, returns {elevation:[<m>]}.
  // Silent failure — manual elev entry stays the user's fallback.
  try {
    const r = await fetch(
      'https://api.open-meteo.com/v1/elevation?latitude=' + lat + '&longitude=' + lon,
    );
    if (!r.ok) return;
    const d = await r.json();
    const m = Array.isArray(d.elevation) ? d.elevation[0] : null;
    if (m == null || !Number.isFinite(m)) return;
    const elv = byId('ws_elev');
    if (!elv || elv.value !== '') return; // user filled it in meanwhile
    _wsSyncing = true;
    elv.value = Math.round(m);
    _wsSyncing = false;
    _saveWeatherLocation();
  } catch (_) {
    /* silent */
  }
}

export function _bindWsLocationInputs() {
  // Debounced input handler: pans the map and saves once typing settles.
  // The dataset guard makes re-binding (re-hydrate) a no-op.
  for (const id of ['ws_lat', 'ws_lon', 'ws_elev']) {
    const el = byId(id);
    if (!el || el.dataset.wsBound === '1') continue;
    el.dataset.wsBound = '1';
    el.addEventListener('input', () => {
      if (_wsSyncing) return;
      clearTimeout(_wsLocSaveTimer);
      _wsLocSaveTimer = setTimeout(() => {
        const lat = parseFloat(byId('ws_lat').value);
        const lon = parseFloat(byId('ws_lon').value);
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
          _setWeatherMapMarker(lat, lon, true);
        }
        _saveWeatherLocation();
      }, 400);
    });
  }
}
