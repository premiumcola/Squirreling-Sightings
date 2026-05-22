// ─── camedit/rtsp.js ───────────────────────────────────────────────────────
// Stage 7 of the legacy.js → ES modules refactor — the RTSP URL
// builder used by the cam-edit form. Owns:
//   • RTSP_PATH_OPTS — vendor path catalogue used by the picker dropdown
//   • _rtspEnc          — minimal URL-reserved-char escape for passwords
//   • URL password masking helpers (_maskUrlPassword, _applyUrlMask, …)
//   • initRtspBuilder   — wires the input listeners that rebuild rtsp_url
//   • parseRtspUrl      — regex-free URL parser used by recovery + diagnostics
//   • _defaultRtspPathForManufacturer — vendor → main-stream path mapping
import { byId } from '../core/dom.js';
import { _setEyeState } from '../chrome/password-toggle.js';

export const RTSP_PATH_OPTS = [
  { label: 'Reolink H.264 – Main (RLC-810A, ältere FW)', value: '/h264Preview_01_main' },
  { label: 'Reolink H.265 – Main (CX810, neuere FW)', value: '/h265Preview_01_main' },
  { label: 'Reolink – Sub (immer H.264)', value: '/h264Preview_01_sub' },
  { label: 'Hikvision – Main', value: '/Streaming/Channels/101' },
  { label: 'Hikvision – Sub', value: '/Streaming/Channels/102' },
  { label: 'Dahua – Main', value: '/cam/realmonitor?channel=1&subtype=0' },
  { label: 'Dahua – Sub', value: '/cam/realmonitor?channel=1&subtype=1' },
  { label: 'Generic stream0', value: '/stream0' },
  { label: 'Generic stream1', value: '/stream1' },
  { label: 'Generic /live', value: '/live' },
];

// Encode only URL-reserved chars that break parsing (?=query, @=host, #=fragment)
// ! is allowed unencoded in userinfo per RFC 3986
export function _rtspEnc(s) {
  return (s || '')
    .replaceAll('%', '%25')
    .replaceAll('?', '%3F')
    .replaceAll('@', '%40')
    .replaceAll('#', '%23');
}

// Replace only the password portion of a URL with dots. The real URL is
// stored in input.dataset.real; .value holds the masked text so the input
// visibly hides the secret. Before form submit we unmask (_unmaskUrlsForSubmit)
// so the saved value is the real URL. In masked state the input is also
// readonly — clicking the eye reveals AND makes the field editable.
export function _maskUrlPassword(url) {
  return (url || '').replace(/:([^@:/]+)@/, ':••••••••@');
}

export function _applyUrlMask(input) {
  if (!input) return;
  const real = input.dataset.real != null ? input.dataset.real : input.value;
  input.dataset.real = real;
  input.value = _maskUrlPassword(real);
  input.setAttribute('readonly', 'readonly');
  input.dataset.masked = '1';
}

export function _revealUrl(input) {
  if (!input) return;
  if (input.dataset.real != null) input.value = input.dataset.real;
  input.dataset.masked = '0';
  // rtsp_url keeps its inherent readonly, only snapshot_url becomes editable
  if (input.name !== 'rtsp_url') input.removeAttribute('readonly');
}

// Inline onclick="_toggleUrlMask(this)" in the cam-edit form.
window._toggleUrlMask = function (btn) {
  const wrap = btn.closest('.url-wrap');
  const input = wrap?.querySelector('input[data-mask-url="1"]');
  if (!input) return;
  const nowRevealed = input.dataset.masked === '1';
  if (nowRevealed) {
    _revealUrl(input);
    _setEyeState(btn, true);
  } else {
    // User just edited the revealed value — stash new real before re-masking.
    input.dataset.real = input.value;
    _applyUrlMask(input);
    _setEyeState(btn, false);
  }
};

export function _unmaskUrlsForSubmit(form) {
  form.querySelectorAll('input[data-mask-url="1"]').forEach((inp) => {
    if (inp.dataset.masked === '1' && inp.dataset.real != null) {
      inp.value = inp.dataset.real;
    }
  });
}

// Maps the manufacturer field to the vendor's RTSP "Main" stream path.
// Used as the auto-default in the camera-edit form so the user never has
// to know vendor-specific path strings. Discovery results have their
// own _defaultRtspPath() (different — H.264 fallback, kept for legacy).
export function _defaultRtspPathForManufacturer(mfg) {
  const m = (mfg || '').toLowerCase().trim();
  if (m.startsWith('reolink')) return '/h265Preview_01_main';
  if (m.startsWith('hikvision')) return '/Streaming/Channels/101';
  if (m.startsWith('dahua') || m.startsWith('amcrest'))
    return '/cam/realmonitor?channel=1&subtype=0';
  return '/stream0';
}

// Inline onclick="_toggleCamRtspErw()" in the cam-edit form's
// "Erweitert" disclosure.
window._toggleCamRtspErw = function () {
  const body = byId('rtspPathErwBody');
  const btn = byId('camRtspErwBtn');
  if (!body || !btn) return;
  const wasOpen = !body.hidden;
  body.hidden = wasOpen;
  btn.setAttribute('aria-expanded', wasOpen ? 'false' : 'true');
};

// Drive the "manuell überschrieben" pill + auto-open the Erweitert
// disclosure when the path doesn't match the manufacturer default.
export function _updateRtspErweitertVisuals() {
  const sel = byId('rtspPathSelect');
  if (!sel) return;
  const isManual = sel.dataset.manual === '1';
  const pill = byId('rtspPathCustomPill');
  if (pill) pill.hidden = !isManual;
  if (isManual) {
    const body = byId('rtspPathErwBody');
    const btn = byId('camRtspErwBtn');
    if (body) body.hidden = false;
    if (btn) btn.setAttribute('aria-expanded', 'true');
  }
}

export function initRtspBuilder() {
  const sel = byId('rtspPathSelect');
  // Defensive: editCamera can fire from a setTimeout race after the
  // recovery / restart flow before the cam-edit form has been
  // re-rendered into the DOM. Without this guard, sel is null and
  // .options throws TypeError mid-init — leaving panelState.camId
  // stale and locking every future cam-edit click until F5.
  if (!sel) return;
  const form = byId('cameraForm');
  if (!form) return;
  if (!sel.options.length) {
    RTSP_PATH_OPTS.forEach((p) => {
      const o = document.createElement('option');
      o.value = p.value;
      o.textContent = p.label;
      sel.appendChild(o);
    });
  }
  const f = form.elements;
  const rebuild = () => {
    const ip = (f['rtsp_ip']?.value || '').trim();
    const user = (f['rtsp_user']?.value || '').trim();
    const pass = (f['rtsp_pass']?.value || '').trim();
    const port = (f['rtsp_port']?.value || '554').trim();
    const path = f['rtsp_path']?.value || '';
    const setMaskable = (input, realVal) => {
      if (!input) return;
      input.dataset.real = realVal;
      // Re-mask iff the eye is currently in masked mode; otherwise show real
      if (input.dataset.masked === '1') input.value = _maskUrlPassword(realVal);
      else input.value = realVal;
    };
    if (!ip) {
      setMaskable(f['rtsp_url'], '');
      if (typeof window._refreshConnectionWarn === 'function') window._refreshConnectionWarn();
      return;
    }
    const auth = user ? user + (pass ? ':' + _rtspEnc(pass) : '') + '@' : '';
    const portPart = port && port !== '554' ? ':' + port : '';
    setMaskable(f['rtsp_url'], `rtsp://${auth}${ip}${portPart}${path}`);
    // auto-fill snapshot if empty
    const snapReal = f['snapshot_url']?.dataset.real || f['snapshot_url']?.value || '';
    if (!snapReal && user) {
      setMaskable(f['snapshot_url'], `http://${user}:${_rtspEnc(pass)}@${ip}/cgi-bin/snapshot.cgi`);
    }
    if (typeof window._refreshConnectionWarn === 'function') window._refreshConnectionWarn();
  };
  ['rtsp_ip', 'rtsp_user', 'rtsp_pass', 'rtsp_port'].forEach((n) =>
    f[n]?.addEventListener('input', rebuild),
  );
  sel.addEventListener('change', () => {
    const def = _defaultRtspPathForManufacturer(f['manufacturer']?.value);
    sel.dataset.manual = sel.value !== def ? '1' : '0';
    _updateRtspErweitertVisuals();
    rebuild();
  });
  // Manufacturer typing propagates to the path picker unless the user
  // has explicitly overridden it via the dropdown.
  f['manufacturer']?.addEventListener('input', () => {
    if (sel.dataset.manual === '1') return;
    const def = _defaultRtspPathForManufacturer(f['manufacturer'].value);
    if (sel.value !== def) {
      sel.value = def;
      rebuild();
    }
  });
}

export function parseRtspUrl(url) {
  try {
    const u = new URL(url.replace(/^rtsp:\/\//, 'http://'));
    return {
      user: decodeURIComponent(u.username || ''),
      pass: decodeURIComponent(u.password || ''),
      host: u.hostname || '',
      port: u.port || '554',
      path: u.pathname + (u.search || '') || '',
    };
  } catch {
    return {};
  }
}
