// ─── push.js ───────────────────────────────────────────────────────────────
// Stage 12 of the legacy.js → ES modules refactor — Telegram push
// settings (the "Was senden" tab + per-label thresholds + quiet
// hours + night alert + presets), plus the weather-events extension
// that hooks into the same "Was senden" panel. Both bind to a single
// settings.telegram.push subtree on the server.
import { byId, esc } from './core/dom.js';
import { state } from './core/state.js';
import { showToast, showConfirm } from './core/toast.js';
import { colors, OBJ_LABEL } from './core/icons.js';
import { WEATHER_TYPES } from './core/weather-types.js';
import { apiPost } from './core/api.js';
import { mergeDeep, pushCfg, pushDefaults } from './push-config.js';

// Order in the "Was senden" list — matches the spec's reading order
// (Person first, animals + person before motion).
const _PUSH_LABEL_ORDER = ['person', 'squirrel', 'dog', 'car', 'cat', 'bird', 'motion'];

// THE endpoint for every push write. There is no /api/settings/telegram/push
// route and there never was one: the ES-module refactor invented that URL,
// and because savePushCfg merged optimistically and swallowed nothing (it
// had no catch at all), every control in this panel 404'd while showing the
// change as applied. `/api/settings/app` deep-merges the section via
// SettingsStore.update_section, so a partial like
// {labels:{person:{push:false}}} lands without wiping its siblings.
const _PUSH_SAVE_URL = '/api/settings/app';

let _pushSaveTimer = null;

/** Persist a partial push config. Returns true on success, false on failure.
 *
 * The local merge stays optimistic so the UI reacts instantly, but a save
 * that fails must not look like a save that worked: the pre-save subtree is
 * snapshotted, restored on error, and the panel re-rendered from it.
 *
 * Exported so the URL, the payload shape and the rollback can be driven
 * directly by a test — this is the function that silently 404'd.
 */
export async function savePushCfg(partial) {
  // JSON round-trip rather than structuredClone: the push subtree is pure
  // JSON (bool / number / string / null), and this way the snapshot needs
  // no browser-version caveat.
  const before = state.config?.telegram?.push
    ? JSON.parse(JSON.stringify(state.config.telegram.push))
    : null;
  if (state.config) {
    state.config.telegram = state.config.telegram || {};
    state.config.telegram.push = mergeDeep(state.config.telegram.push || {}, partial);
  }
  try {
    await apiPost(_PUSH_SAVE_URL, { telegram: { push: partial } });
  } catch (err) {
    if (state.config?.telegram) {
      if (before === null) delete state.config.telegram.push;
      else state.config.telegram.push = before;
    }
    hydratePushUI();
    showToast('Speichern fehlgeschlagen — Einstellung zurückgesetzt.', 'error');
    console.error('[push] save failed', err);
    return false;
  }
  return true;
}

function _debouncedPushSave(partial, ms = 600) {
  // Coalesce a flurry of slider input events into one POST.
  clearTimeout(_pushSaveTimer);
  _pushSaveTimer = setTimeout(() => savePushCfg(partial), ms);
}

let _pushDepsTimer = null;

export function hydratePushUI() {
  const cfg = pushCfg();
  // ── "Wann senden" ────────────────────────────────────────────────────────
  const set = (id, prop, val) => {
    const el = byId(id);
    if (el) el[prop] = val;
  };
  set('push_enabled', 'checked', !!cfg.enabled);
  set('push_daily_enabled', 'checked', !!cfg.daily_report?.enabled);
  set('push_daily_time', 'value', cfg.daily_report?.time || '22:00');
  set('push_highlight_enabled', 'checked', !!cfg.highlight?.enabled);
  set('push_highlight_time', 'value', cfg.highlight?.time || '19:00');
  set('push_quiet_enabled', 'checked', !!cfg.quiet_hours?.start && !!cfg.quiet_hours?.end);
  set('push_quiet_start', 'value', cfg.quiet_hours?.start || '22:00');
  set('push_quiet_end', 'value', cfg.quiet_hours?.end || '07:00');
  set('push_night_enabled', 'checked', !!cfg.night_alert?.enabled);
  set('push_night_armed', 'checked', !!cfg.night_alert?.armed_only);
  const useSun = cfg.night_alert?.use_sun !== false;
  document.querySelectorAll('input[name="push_night_mode"]').forEach((r) => {
    r.checked = r.value === (useSun ? 'sun' : 'time');
  });
  set('push_night_start', 'value', cfg.night_alert?.start || '22:00');
  set('push_night_end', 'value', cfg.night_alert?.end || '07:00');
  _updatePushNightModeUI();

  // ── "Was senden" — labels list + bottom toggles ──────────────────────────
  _renderPushLabelsList(cfg.labels || {});
  set('push_timelapse_enabled', 'checked', !!cfg.timelapse?.enabled);
  set('push_system_enabled', 'checked', !!cfg.system?.enabled);

  // ── "Abhängigkeiten" ─────────────────────────────────────────────────────
  hydratePushDeps();
  if (!_pushDepsTimer) _pushDepsTimer = setInterval(hydratePushDeps, 30000);

  _bindPushHandlers();

  // Weather extension — extends the same "Was senden" tab with a
  // wetter-events row + recap toggle. Inlined here so the previous
  // monkey-patch (`hydratePushUI = function(){...}`) goes away.
  _hydratePushWeather();
  _bindPushWeatherHandlers();
}

function _renderPushLabelsList(labels) {
  const wrap = byId('pushLabelsList');
  if (!wrap) return;
  wrap.innerHTML = _PUSH_LABEL_ORDER
    .map((lbl) => {
      const l = labels[lbl] || { push: false, threshold: 0.8 };
      const color = colors[lbl] || '#5bc8f5';
      const name = OBJ_LABEL[lbl] || lbl;
      // D8 · the threshold slider is gone. Besides doubling the Netz it
      // carried a min="0.5" clamp that silently rewrote `motion` from
      // 0.0 to 0.5 the moment anyone touched it.
      return `
      <div class="push-label-row" data-label="${esc(lbl)}">
        <span class="push-label-chip" style="background:${esc(color)}22;border:1px solid ${esc(color)}55;color:${esc(color)}">${esc(name)}</span>
        <label class="switch push-label-toggle"><input type="checkbox" ${l.push ? 'checked' : ''} data-push-toggle/><span class="slider"></span></label>
      </div>`;
    })
    .join('');
}

function _updatePushNightModeUI() {
  const useSun = document.querySelector('input[name="push_night_mode"][value="sun"]')?.checked;
  const sunInfo = byId('push_night_sun_info');
  const timeRow = byId('push_night_time_row');
  if (timeRow) timeRow.style.display = useSun ? 'none' : 'grid';
  if (!sunInfo) return;
  if (useSun) {
    const cfg = pushCfg();
    const lat = cfg.night_alert?.lat,
      lon = cfg.night_alert?.lon;
    if (lat == null || lon == null) {
      sunInfo.innerHTML =
        '<span style="color:#ef4444">Standort in App &amp; Server festlegen, sonst fällt der Nacht-Alarm auf die feste Uhrzeit zurück.</span>';
    } else {
      sunInfo.textContent = `Standort gesetzt (lat ${lat}, lon ${lon}). Nacht-Erkennung über Sonnenstand (Civil Dusk = elev < −6°).`;
    }
  } else {
    sunInfo.textContent = '';
  }
}

// Bind-once guards. hydratePushUI() re-renders and is now also called from
// the save-failure rollback and after a preset — addEventListener would
// stack a second, third, … handler on the same control each time, and each
// duplicate would fire its own POST.
let _pushHandlersBound = false;
let _pushWeatherHandlersBound = false;

function _bindPushHandlers() {
  if (_pushHandlersBound) return;
  _pushHandlersBound = true;
  // Top-level master switch.
  byId('push_enabled')?.addEventListener('change', (e) =>
    savePushCfg({ enabled: e.target.checked }),
  );
  // Daily / highlight: toggle + time.
  for (const [id, key] of [
    ['push_daily_enabled', 'daily_report'],
    ['push_highlight_enabled', 'highlight'],
  ]) {
    byId(id)?.addEventListener('change', (e) =>
      savePushCfg({ [key]: { enabled: e.target.checked } }),
    );
  }
  byId('push_daily_time')?.addEventListener('change', (e) =>
    savePushCfg({ daily_report: { time: e.target.value } }),
  );
  byId('push_highlight_time')?.addEventListener('change', (e) =>
    savePushCfg({ highlight: { time: e.target.value } }),
  );
  // Quiet hours.
  byId('push_quiet_enabled')?.addEventListener('change', (e) => {
    // "off" ≈ start==end. Backend has no separate enabled flag — to actually
    // disable, blank out start/end (backend's is_quiet_now returns false).
    if (e.target.checked) {
      savePushCfg({
        quiet_hours: {
          start: byId('push_quiet_start').value || '22:00',
          end: byId('push_quiet_end').value || '07:00',
        },
      });
    } else {
      savePushCfg({ quiet_hours: { start: '00:00', end: '00:00' } });
    }
  });
  byId('push_quiet_start')?.addEventListener('change', (e) =>
    savePushCfg({ quiet_hours: { start: e.target.value } }),
  );
  byId('push_quiet_end')?.addEventListener('change', (e) =>
    savePushCfg({ quiet_hours: { end: e.target.value } }),
  );
  // Night alert.
  byId('push_night_enabled')?.addEventListener('change', (e) =>
    savePushCfg({ night_alert: { enabled: e.target.checked } }),
  );
  byId('push_night_armed')?.addEventListener('change', (e) =>
    savePushCfg({ night_alert: { armed_only: e.target.checked } }),
  );
  document.querySelectorAll('input[name="push_night_mode"]').forEach((r) => {
    r.addEventListener('change', () => {
      const useSun = document.querySelector('input[name="push_night_mode"][value="sun"]').checked;
      savePushCfg({ night_alert: { use_sun: useSun } });
      _updatePushNightModeUI();
    });
  });
  byId('push_night_start')?.addEventListener('change', (e) =>
    savePushCfg({ night_alert: { start: e.target.value } }),
  );
  byId('push_night_end')?.addEventListener('change', (e) =>
    savePushCfg({ night_alert: { end: e.target.value } }),
  );
  // Per-label rows (delegated).
  byId('pushLabelsList')?.addEventListener('change', (e) => {
    const row = e.target.closest('.push-label-row');
    if (!row) return;
    const lbl = row.dataset.label;
    if (e.target.matches('[data-push-toggle]')) {
      savePushCfg({ labels: { [lbl]: { push: e.target.checked } } });
    }
  });
  // Bottom toggles.
  byId('push_timelapse_enabled')?.addEventListener('change', (e) =>
    savePushCfg({ timelapse: { enabled: e.target.checked } }),
  );
  byId('push_system_enabled')?.addEventListener('change', (e) =>
    savePushCfg({ system: { enabled: e.target.checked } }),
  );
  // Presets.
  document.querySelectorAll('.push-preset-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!(await showConfirm('Aktuelle Push-Einstellungen überschreiben?'))) return;
      const preset = btn.dataset.preset;
      const block = _buildPushPreset(preset);
      // savePushCfg already rolls back and reports on failure — claiming
      // "Preset angewendet" on top of that would be the second lie.
      if (!(await savePushCfg(block))) return;
      hydratePushUI();
      showToast('Preset angewendet.', 'success');
    });
  });
}

// D8 · the presets keep their POLICY half (which labels alert at all,
// quiet hours, highlight) and lose their threshold half. A preset that
// rewrote the per-label thresholds would silently overwrite whatever the
// Netz had learned or the operator had dragged — the same drift the
// slider caused, just in one click instead of many.
function _buildPushPreset(name) {
  const def = pushDefaults();
  if (name === 'quiet') {
    return {
      enabled: true,
      quiet_hours: { start: '22:00', end: '08:00' },
      highlight: { enabled: false },
      labels: {
        person: { push: true },
        car: { push: true },
        squirrel: { push: false },
        dog: { push: false },
        cat: { push: false },
        bird: { push: false },
        motion: { push: false },
      },
    };
  }
  if (name === 'all') {
    return {
      enabled: true,
      quiet_hours: { start: '00:00', end: '00:00' },
      labels: {
        person: { push: true },
        car: { push: true },
        squirrel: { push: true },
        dog: { push: true },
        cat: { push: true },
        bird: { push: true },
        motion: { push: false },
      },
    };
  }
  return def;
}

function hydratePushDeps() {
  const wrap = byId('pushDepsList');
  if (!wrap) return;
  const tg = state.config?.telegram || {};
  const srv = state.config?.server || {};
  const cams = state.cameras || [];
  const someCoral = cams.some((c) => c.coral_available);
  const someBird = cams.some((c) => c.bird_species_available);
  const hasLoc = !!(srv.location?.lat || tg.push?.night_alert?.lat);
  const tgConn = !!(tg.enabled && tg.token && tg.chat_id);
  const rows = [
    [someCoral, 'Coral TPU aktiv', 'Wildlife-Erkennung verfügbar'],
    [someBird, 'iNaturalist-Modell vorhanden', 'Vogelarten-Klassifikation'],
    [hasLoc, 'Standort gesetzt', 'Sonnenstand-basierter Nacht-Alarm'],
    [tgConn, 'Telegram-Bot verbunden', 'Push-System sendet Nachrichten'],
  ];
  wrap.innerHTML = rows
    .map(
      ([ok, title, desc]) => `
    <div class="push-dep-row">
      <span class="push-dep-dot ${ok ? 'ok' : 'off'}"></span>
      <div class="push-dep-text">
        <div class="push-dep-title">${esc(title)}</div>
        <div class="push-dep-desc">${esc(desc)}</div>
      </div>
    </div>
  `,
    )
    .join('');
}

// ── Push Weather settings (extends the "Was senden" tab) ─────────────────

// Every entry must exist in WEATHER_TYPES — the fallback below would
// otherwise render the raw English key as the chip label. 'sunset' was
// exactly that: the score-based sunset event was retired into the
// sun-timelapse pipeline, WEATHER_TYPES dropped it, and the row stayed
// behind as an untranslated toggle for a push that can never be sent.
const _PUSH_WEATHER_ORDER = ['thunder', 'heavy_rain', 'snow', 'fog'];

function _renderPushWeatherEvents(weatherCfg) {
  const wrap = byId('pushWeatherEventsList');
  if (!wrap) return;
  const events = (weatherCfg && weatherCfg.events) || {};
  wrap.innerHTML = _PUSH_WEATHER_ORDER
    .map((t) => {
      const meta = WEATHER_TYPES[t] || { de: t, color: '#94a3b8', icon: '' };
      const on = events[t] !== undefined ? !!events[t] : false;
      return `
      <div class="push-label-row" data-weather-evt="${esc(t)}">
        <span class="push-label-chip" style="background:${meta.color}22;border:1px solid ${meta.color}55;color:${meta.color}">${meta.icon} ${esc(meta.de)}</span>
        <label class="switch push-label-toggle"><input type="checkbox" ${on ? 'checked' : ''} data-weather-event-toggle/><span class="slider"></span></label>
        <span></span>
        <span></span>
      </div>`;
    })
    .join('');
}

function _hydratePushWeather() {
  const w = (state.config?.telegram?.push || {}).weather || {};
  const en = byId('push_weather_enabled');
  if (en) en.checked = !!w.enabled;
  const recap = byId('push_weather_recap');
  if (recap) recap.checked = w.recap_push !== false;
  const sl = byId('push_weather_min_score');
  const lbl = byId('push_weather_min_score_pct');
  const v = w.min_score != null ? Number(w.min_score) : 0.4;
  if (sl) sl.value = v;
  if (lbl) lbl.textContent = Math.round(v * 100) + '%';
  _renderPushWeatherEvents(w);
}

function _bindPushWeatherHandlers() {
  if (_pushWeatherHandlersBound) return;
  _pushWeatherHandlersBound = true;
  byId('push_weather_enabled')?.addEventListener('change', (e) =>
    savePushCfg({ weather: { enabled: e.target.checked } }),
  );
  byId('push_weather_recap')?.addEventListener('change', (e) =>
    savePushCfg({ weather: { recap_push: e.target.checked } }),
  );
  byId('push_weather_min_score')?.addEventListener('input', (e) => {
    const v = parseFloat(e.target.value) || 0;
    const lbl = byId('push_weather_min_score_pct');
    if (lbl) lbl.textContent = Math.round(v * 100) + '%';
    _debouncedPushSave({ weather: { min_score: v } });
  });
  byId('pushWeatherEventsList')?.addEventListener('change', (e) => {
    const row = e.target.closest('.push-label-row[data-weather-evt]');
    if (!row) return;
    if (!e.target.matches('[data-weather-event-toggle]')) return;
    const evt = row.dataset.weatherEvt;
    savePushCfg({ weather: { events: { [evt]: !!e.target.checked } } });
  });
}
