// ─── alerting.js ───────────────────────────────────────────────────────────
// Stage 17 of the legacy.js → ES modules refactor — the Alerting tab on
// the cam-edit panel: per-class severity matrix (off / info / alarm),
// per-class notification cooldowns, conflict warning banner, test-push
// button, and the live status strip pulled from /api/system/telegram.
//
// Replaces the legacy 4-valued alarm_profile select. The runtime
// computes an event's effective severity by reading the detected
// labels and picking the highest-rank entry from class_severity[].
import { byId, esc } from './core/dom.js';
import { apiGet, apiPost } from './core/api.js';
import { _fmtRelativeAgeS } from './camedit/detection.js';
import { objIconSvg } from './core/icons.js';
import { getCamObjectFilterState } from './camedit/detection-objectfilter.js';

// Object-class order MIRRORS camedit/detection-objectfilter.js
// _CAM_OBJ_OPTIONS (person, cat, bird, car, dog, squirrel) so the Alerting
// matrix reads in the same sequence as the Erkennung object-filter pills,
// with the project SVG icons (not emoji). `motion` is NOT an object-filter
// class — it's a separate trigger, always shown LAST and NEVER locked.
// `obj:true` marks the rows the object-filter lock applies to.
const _ALERT_SEV_CLASSES = [
  { key: 'person', label: 'Person', obj: true },
  { key: 'cat', label: 'Katze', obj: true },
  { key: 'bird', label: 'Vogel', obj: true },
  { key: 'car', label: 'Auto', obj: true },
  { key: 'dog', label: 'Hund', obj: true },
  { key: 'squirrel', label: 'Eichhörnchen', obj: true },
  { key: 'motion', label: 'Bewegung', obj: false },
];

// Module refs to the last-rendered form/cam so a live object-filter change
// (or an Alerting-tab activation) can re-evaluate the lock state without a
// full re-render that would drop the user's in-progress selections.
let _sevForm = null;
let _sevCam = null;

// Current object-filter, live-first: read the Erkennung pills' live state
// (mirrored as the user toggles), falling back to the saved cam.object_filter
// on the very first render before the pills initialise. An EMPTY filter means
// "no filter — all classes detected" (matches the runtime), so nothing locks.
function _currentObjFilter() {
  const live = getCamObjectFilterState();
  if (live && live.length) return live;
  return (_sevCam && _sevCam.object_filter) || [];
}

// Grey out + force-off + de-interactivate the rows whose class is NOT in the
// current object-filter (motion is exempt). Mutates the existing DOM so an
// unlocked row's in-progress selection survives. Toggles the one-line hint.
function _applySeverityLocks() {
  const wrap = byId('alertSeverityMatrix');
  if (!wrap) return;
  const allowed = _currentObjFilter();
  const lockActive = allowed.length > 0;
  const allowedSet = new Set(allowed);
  let lockedCount = 0;
  for (const c of _ALERT_SEV_CLASSES) {
    if (!c.obj) continue; // motion is never locked
    const locked = lockActive && !allowedSet.has(c.key);
    wrap
      .querySelectorAll(`[data-cls="${c.key}"]`)
      .forEach((el) => el.classList.toggle('is-locked', locked));
    const radios = wrap.querySelectorAll(`.sev-radio[data-cls="${c.key}"]`);
    radios.forEach((r) => {
      if (locked) r.dataset.locked = '1';
      else delete r.dataset.locked;
    });
    const lbl = wrap.querySelector(`.sev-row-label[data-cls="${c.key}"]`);
    if (locked) {
      lockedCount++;
      // Force the row to OFF — a deselected class must never carry alarm/info.
      radios.forEach((r) => {
        const isOff = r.dataset.val === 'off';
        r.classList.remove('is-on', 'is-off-mode', 'is-info-mode', 'is-alarm-mode');
        if (isOff) r.classList.add('is-on', 'is-off-mode');
        r.setAttribute('aria-checked', isOff ? 'true' : 'false');
        r.textContent = isOff ? '●' : '○';
      });
      if (lbl) lbl.title = 'In Erkennung aktivieren, um Alerting zu konfigurieren';
    } else if (lbl) {
      lbl.removeAttribute('title');
    }
  }
  const hint = byId('alertSeverityLockHint');
  if (hint) hint.hidden = lockedCount === 0;
}

// Re-evaluate locks against the LIVE object-filter — called when the
// Erkennung pills toggle and when the Alerting tab is (re)activated.
export function _refreshSeverityLockState() {
  if (!byId('alertSeverityMatrix')) return;
  _applySeverityLocks();
  if (_sevForm) _checkAlertingConflicts(_sevForm);
}

export function _renderSeverityMatrix(form, cam) {
  const wrap = byId('alertSeverityMatrix');
  if (!wrap) return;
  _sevForm = form;
  _sevCam = cam;
  const cs = cam?.class_severity || {};
  // Header row (Klasse | Aus | Info | Alarm).
  let html = `
    <div class="sev-cell sev-header">Klasse</div>
    <div class="sev-cell sev-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><line x1="2" y1="2" x2="22" y2="22"/></svg>
      Aus
    </div>
    <div class="sev-cell sev-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/></svg>
      Info
    </div>
    <div class="sev-cell sev-header">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M2 5l4-3M22 5l-4-3"/></svg>
      Alarm
    </div>
  `;
  for (const c of _ALERT_SEV_CLASSES) {
    const cur = cs[c.key] || 'off';
    const cell = (val, mode) => {
      const on = cur === val;
      const cls = `sev-cell sev-radio${on ? ' is-on is-' + mode + '-mode' : ''}`;
      return `<div class="${cls}" data-cls="${c.key}" data-val="${val}" role="radio" aria-checked="${on}" tabindex="0">${on ? '●' : '○'}</div>`;
    };
    html += `
      <div class="sev-cell sev-row-label" data-cls="${c.key}"><span class="sev-row-ico" aria-hidden="true">${objIconSvg(c.key, 18) || ''}</span>${esc(c.label)}</div>
      ${cell('off', 'off')}
      ${cell('info', 'info')}
      ${cell('alarm', 'alarm')}
    `;
  }
  wrap.innerHTML = html;
  // Single delegated click handler per render (innerHTML wipes prior
  // listeners). Touch + mouse + pen all share the same path. Locked
  // (object-filter-disabled) cells are inert.
  wrap.addEventListener('click', (e) => {
    const cell = e.target.closest('.sev-radio');
    if (!cell || cell.dataset.locked === '1') return;
    const cls = cell.dataset.cls;
    const val = cell.dataset.val;
    wrap.querySelectorAll(`.sev-radio[data-cls="${cls}"]`).forEach((r) => {
      r.classList.remove('is-on', 'is-off-mode', 'is-info-mode', 'is-alarm-mode');
      r.setAttribute('aria-checked', 'false');
      r.textContent = '○';
    });
    cell.classList.add('is-on', 'is-' + val + '-mode');
    cell.setAttribute('aria-checked', 'true');
    cell.textContent = '●';
    _checkAlertingConflicts(form);
  });
  // Lock rows for classes not in the current object-filter.
  _applySeverityLocks();
}

// Read the matrix back into the dict shape settings.json expects.
// Drops unset rows silently (every row has exactly one is-on cell after
// render so the .is-on selector is the source of truth).
export function _collectClassSeverity(_form) {
  const wrap = byId('alertSeverityMatrix');
  const out = {};
  if (!wrap) return out;
  wrap.querySelectorAll('.sev-radio.is-on').forEach((r) => {
    // Data safety: a locked (object-filter-disabled) class must NEVER
    // persist alarm/info — coerce to 'off' regardless of DOM state so a
    // class deselected in Erkennung can't carry a stale alarm to disk.
    out[r.dataset.cls] = r.dataset.locked === '1' ? 'off' : r.dataset.val;
  });
  return out;
}

// Conflict-warning banner — flags Alerting-tab settings that wouldn't
// reach the user. Two checks:
//   1. Any class is set to alarm/info but BOTH channels (Telegram +
//      MQTT) are off → push has nowhere to go.
//   2. Any class is set to alarm/info but the master "Alerting aktiv"
//      switch (armed) is off → push is globally muted.
// Banner is purely informational — never blocks save.
export function _checkAlertingConflicts(form) {
  const banner = byId('alertConflictBanner');
  const text = byId('alertConflictText');
  if (!banner || !text) return;
  const cs = _collectClassSeverity(form);
  const anyAlarming = Object.values(cs).some((v) => v === 'alarm' || v === 'info');
  const tg = !!form.querySelector('[name="telegram_enabled"]')?.checked;
  const mq = !!form.querySelector('[name="mqtt_enabled"]')?.checked;
  const armed = !!form.querySelector('[name="armed"]')?.checked;
  const messages = [];
  if (anyAlarming && !tg && !mq) {
    messages.push(
      'Klassen sind auf <strong>Alarm</strong> oder <strong>Info</strong> gesetzt, aber <strong>kein Kanal aktiv</strong> — es kommt nichts an. Aktiviere Telegram oder MQTT in Schritt 2.',
    );
  }
  if (anyAlarming && !armed) {
    messages.push(
      'Der globale <strong>Stumm-Schalter</strong> in Schritt 5 ist aus — alle Pushes werden blockiert.',
    );
  }
  if (messages.length) {
    text.innerHTML = messages.join(' · ');
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

// Per-class notification-cooldown drilldown rendered into
// #alertCooldownGrid when "Cooldown pro Klasse anpassen ▾" is opened.
// Defaults match _NOTIFY_COOLDOWN_DEFAULTS in telegram_bot so the
// surfaced values reflect the actual runtime fallback.
// Same object-class order as _ALERT_SEV_CLASSES / the Erkennung pills,
// motion last; project SVG icons (not emoji) added in the renderer.
const _ALERT_COOLDOWN_CLASSES = [
  { key: 'person', label: 'Person', def: 60 },
  { key: 'cat', label: 'Katze', def: 120 },
  { key: 'bird', label: 'Vogel', def: 300 },
  { key: 'car', label: 'Auto', def: 30 },
  { key: 'dog', label: 'Hund', def: 120 },
  { key: 'squirrel', label: 'Eichhörnchen', def: 300 },
  { key: 'motion', label: 'Bewegung', def: 30 },
];

function _fmtCooldownVal(s) {
  const v = parseInt(s, 10);
  if (!Number.isFinite(v)) return '—';
  if (v === 0) return 'aus';
  if (v < 60) return v + ' s';
  return Math.round(v / 60) + ' min';
}

export function _renderAlertCooldownGrid(form, cam) {
  const wrap = byId('alertCooldownGrid');
  if (!wrap) return;
  const cd = cam?.notification_cooldown || {};
  wrap.innerHTML = _ALERT_COOLDOWN_CLASSES
    .map((c) => {
      const raw = cd[c.key];
      const v = raw != null && Number.isFinite(parseInt(raw, 10)) ? parseInt(raw, 10) : c.def;
      return `
      <div class="erk-card">
        <div class="row">
          <input type="range" name="cooldown_${c.key}" min="0" max="600" step="15" value="${v}" />
          <span class="val" id="erkCD_${c.key}_val">${esc(_fmtCooldownVal(v))}</span>
        </div>
        <span class="lbl"><span class="cd-row-ico" aria-hidden="true">${objIconSvg(c.key, 16) || ''}</span>${esc(c.label)} · min. Abstand zwischen zwei Pushes</span>
      </div>`;
    })
    .join('');
  _ALERT_COOLDOWN_CLASSES.forEach((c) => {
    const inp = wrap.querySelector(`[name="cooldown_${c.key}"]`);
    const lbl = byId(`erkCD_${c.key}_val`);
    if (inp && lbl) {
      inp.addEventListener('input', () => {
        lbl.textContent = _fmtCooldownVal(inp.value);
      });
    }
  });
}

export function _bindAlertCooldownToggle() {
  const btn = byId('alertCooldownToggle');
  const wrap = byId('alertCooldownGrid');
  const lbl = byId('alertCooldownToggleLbl');
  if (!btn || !wrap || !lbl || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', () => {
    const open = wrap.hidden;
    wrap.hidden = !open;
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    lbl.textContent = open ? 'Weniger anzeigen' : 'Cooldown pro Klasse anpassen';
  });
}

// Read every cooldown_<class> slider from the form into the dict
// shape settings.json expects. Empty grid (drilldown never opened)
// yields {}, which the runtime treats as "use _NOTIFY_COOLDOWN_DEFAULTS".
export function _collectAlertCooldown(form) {
  const out = {};
  form.querySelectorAll('[name^="cooldown_"]').forEach((inp) => {
    const key = inp.name.replace('cooldown_', '');
    const v = parseInt(inp.value, 10);
    if (key && Number.isFinite(v)) out[key] = v;
  });
  return out;
}

// Test-Push button on the Alerting tab — fires
// /api/cameras/<id>/test-alert, animates the play-icon while in
// flight, then renders a per-channel result panel below: ✓ Telegram
// angekommen / ✗ MQTT: Kanal aus. Idempotent wiring via dataset.wired.
export function _bindAlertTestButton() {
  const btn = byId('alertTestBtn');
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  btn.addEventListener('click', _onAlertTestClick);
}

const _ALERT_CHAN_LABELS = { telegram: 'Telegram', mqtt: 'MQTT' };

async function _onAlertTestClick(ev) {
  const btn = ev.currentTarget;
  const camId = byId('cameraForm')?.elements?.['id']?.value;
  const result = byId('alertTestResult');
  if (!camId || !result) return;
  const lblEl = btn.querySelector('.alert-test-btn-lbl');
  const original = lblEl?.textContent || '';
  btn.disabled = true;
  btn.classList.add('is-busy');
  if (lblEl) lblEl.textContent = ' sende…';
  result.hidden = true;
  let data = null;
  try {
    data = await apiPost(`/api/cameras/${encodeURIComponent(camId)}/test-alert`);
  } catch {
    data = null;
  }
  btn.disabled = false;
  btn.classList.remove('is-busy');
  if (lblEl) lblEl.textContent = original;
  if (!data) {
    result.className = 'alert-test-result is-err';
    result.innerHTML = `<strong>Fehler:</strong> Netzwerk · keine Antwort vom Server`;
    result.hidden = false;
    return;
  }
  const lines = [];
  for (const [chan, res] of Object.entries(data.channels || {})) {
    const label = _ALERT_CHAN_LABELS[chan] || chan;
    if (res?.ok) lines.push(`✓ ${label} angekommen`);
    else lines.push(`✗ ${label}: ${res?.error || 'Fehler'}`);
  }
  result.className = 'alert-test-result ' + (data.ok ? 'is-ok' : 'is-err');
  const head = data.ok ? 'Erfolg' : 'Fehler';
  result.innerHTML = `<strong>${head}</strong><ul>${lines.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`;
  result.hidden = false;
}

// Hydrate the Alerting-tab status strip from /api/system/telegram.
// Mutates the existing static markup rather than re-rendering so the
// dot's CSS animation isn't restarted on every poll. Three pieces:
//   - Dot variant: is-ok / is-cpu / is-off
//   - alertStatusBot: "verbunden" / "getrennt" / "deaktiviert"
//   - alertStatusLast: relative "vor X Min." since last push
// Errors during fetch leave the strip showing whatever it had — a
// transient flake shouldn't blank the UI.
export async function _renderAlertStatusStrip() {
  const host = byId('alertStatusStrip');
  if (!host) return;
  let data = null;
  try {
    data = await apiGet('/api/system/telegram');
  } catch {}
  const dot = byId('alertStatusDot');
  const txt = byId('alertStatusBot');
  const last = byId('alertStatusLast');
  if (!data) {
    if (dot) {
      dot.classList.remove('is-ok', 'is-cpu', 'is-off');
      dot.classList.add('is-off');
    }
    if (txt) txt.textContent = '—';
    if (last) last.textContent = '—';
    return;
  }
  let variant, label;
  if (!data.enabled) {
    variant = 'is-off';
    label = 'deaktiviert';
  } else if (data.connected) {
    variant = 'is-ok';
    label = 'verbunden';
  } else {
    variant = 'is-cpu';
    label = 'getrennt';
  }
  if (dot) {
    dot.classList.remove('is-ok', 'is-cpu', 'is-off');
    dot.classList.add(variant);
  }
  if (txt) txt.textContent = label;
  if (last) last.textContent = _fmtRelativeAgeS(data.last_send_age_s);
}

// Wire the conflict banner to react to channel/master switches in the
// Alerting tab. Idempotent via dataset.wired so re-opening cam-edit
// doesn't double-bind. The matrix click handler in
// _renderSeverityMatrix already calls _checkAlertingConflicts on every
// cell click.
export function _bindAlertingConflictWatch(form) {
  if (!form || form.dataset.alertingConflictWired) return;
  form.dataset.alertingConflictWired = '1';
  ['telegram_enabled', 'mqtt_enabled', 'armed', 'recording_enabled'].forEach((name) => {
    const inp = form.querySelector(`[name="${name}"]`);
    if (inp) inp.addEventListener('change', () => _checkAlertingConflicts(form));
  });
}

// Legacy 4-valued alarm_profile select hint — kept for templates that
// still surface the old dropdown. The matrix above is the source of
// truth on save; this dropdown survives only for the rare flow where
// the user wants to bulk-set a profile and let the matrix fill in.
const _ALARM_PROFILE_HINTS = {
  hard: 'Telegram nur bei Person/Auto. Tiere & reine Bewegung werden ignoriert.',
  medium: 'Telegram bei Person/Auto (Alarm) und bei Tieren (Info-Meldung). Reine Bewegung still.',
  soft: 'Telegram bei jedem Event — Person, Tier oder reine Bewegung.',
  info: 'Telegram nur bei Tieren (Katze, Vogel, Fuchs …). Personen & Bewegung still.',
};
window._updateAlarmProfileHint = function () {
  const sel = byId('camAlarmProfileSelect');
  const hint = byId('camAlarmProfileHint');
  if (!sel || !hint) return;
  hint.textContent = _ALARM_PROFILE_HINTS[sel.value] || '';
};

// live-update.js polls _renderAlertStatusStrip every 3 s through this
// bridge — kept as window.X so live-update can stay agnostic about the
// alerting module's layout. (Direct named import is also possible but
// the bridge means live-update doesn't need a re-edit when alerting
// itself changes shape.)
window._renderAlertStatusStrip = _renderAlertStatusStrip;

// B2 · re-evaluate the matrix lock state whenever the Erkennung object-
// filter changes (a pill is toggled). detection-objectfilter.js dispatches
// this event; using an event (not an import) avoids a module cycle. Wired
// once at module load — idempotent for the single matrix instance.
document.addEventListener('cam-objfilter-change', () => _refreshSeverityLockState());
