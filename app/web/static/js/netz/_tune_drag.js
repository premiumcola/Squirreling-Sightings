// ─── netz/_tune_drag.js ─────────────────────────────────────────────────────
// Radial vertex-drag for the Fangnetz's PRIMARY (settings) radar.
//
// Deliberately NOT a reuse of _drag.js: that module's preview fetch
// (delta_alerts from a corpus of Telegram verdicts) and person-floor
// confirm both assume confidence-axis semantics that don't exist here —
// a setting axis has no evidence and nothing it can "blind the camera"
// by crossing. What IS shared, because it is pure geometry: pointer
// capture, the radial-only distance→E read, and the movement threshold
// before a tap counts as a drag. See _drag.js's own header for why those
// three patterns matter (iOS pointercancel, touch-action scoping, etc.).
import { showConfirm, showToast } from '../core/toast.js';
import { eFromRadius } from './_mapping.js';
import { chartRadius } from './_radar.js';
import { TUNE_SPECS, tuneDisplay, tuneRawFromE } from './_settings_axes.js';
import { netzState } from './_state.js';
import { patchTuning } from './_api.js';

const LONG_PRESS_MS = 500;

let _drag = null;

function _pillEl(host) {
  let el = host.querySelector('.netz-drag-pill');
  if (!el) {
    el = document.createElement('div');
    el.className = 'netz-drag-pill';
    host.appendChild(el);
  }
  return el;
}

function _paintPill(host, spec, raw) {
  const el = _pillEl(host);
  el.innerHTML = `<b>${spec.label}</b><span>${tuneDisplay(spec, raw)}</span>`;
  el.dataset.on = '1';
}

function _hidePill(host) {
  const el = host.querySelector('.netz-drag-pill');
  if (el) el.dataset.on = '0';
}

function _geometry(host) {
  const svg = host.querySelector('.netz-tune-chart .netz-svg');
  if (!svg) return null;
  const box = svg.getBoundingClientRect();
  const side = box.width;
  return { cx: box.left + side / 2, cy: box.top + side / 2, r: chartRadius(side) };
}

function _axisByKey(key) {
  return (netzState.tuneAxes || []).find((a) => a.key === key) || null;
}

export function bindTuneDrag(host, onRepaint, onStage) {
  host.querySelectorAll('.netz-tune-hit').forEach((node) => {
    node.addEventListener('pointerdown', (ev) => _onDown(ev, node, host, onRepaint, onStage));
  });
}

function _onDown(ev, node, host, onRepaint, onStage) {
  const key = node.dataset.tuneAxis;
  const axis = _axisByKey(key);
  const spec = TUNE_SPECS[key];
  if (!axis || !spec) return;
  ev.preventDefault();
  node.setPointerCapture?.(ev.pointerId);
  const geo = _geometry(host);
  _drag = {
    key,
    spec,
    node,
    geo,
    start: { x: ev.clientX, y: ev.clientY },
    moved: false,
    e: axis.E,
    raw: axis.raw,
    longPress: setTimeout(() => _onLongPress(host, key, spec, onRepaint, onStage), LONG_PRESS_MS),
  };
  _paintPill(host, spec, axis.raw);
  const move = (e2) => _onMove(e2, host);
  const up = (e2) => {
    node.removeEventListener('pointermove', move);
    node.removeEventListener('pointerup', up);
    node.removeEventListener('pointercancel', up);
    _onUp(e2, host, onRepaint, onStage);
  };
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', up);
}

function _onMove(ev, host) {
  if (!_drag) return;
  const dist = Math.hypot(ev.clientX - _drag.start.x, ev.clientY - _drag.start.y);
  if (!_drag.moved && dist < 4) return;
  if (!_drag.moved) {
    _drag.moved = true;
    clearTimeout(_drag.longPress);
  }
  const dx = ev.clientX - _drag.geo.cx;
  const dy = ev.clientY - _drag.geo.cy;
  const e = eFromRadius(Math.hypot(dx, dy), _drag.geo.r);
  const raw = tuneRawFromE(_drag.spec, e);
  _drag.e = e;
  _drag.raw = raw;
  _paintPill(host, _drag.spec, raw);
  host.dispatchEvent(new CustomEvent('netz:tunevertexmove', { detail: { key: _drag.key, e } }));
}

function _onUp(ev, host, onRepaint, onStage) {
  if (!_drag) return;
  const { key, moved, raw } = _drag;
  clearTimeout(_drag.longPress);
  _drag = null;
  _hidePill(host);
  if (!moved) return;
  onStage(key, raw);
  onRepaint();
}

async function _onLongPress(host, key, spec, onRepaint, onStage) {
  _drag = null;
  _hidePill(host);
  if (!(await showConfirm(`${spec.label} auf Werk zurücksetzen?`))) return;
  const res = await patchTuning(netzState.camId, { [key]: spec.default });
  if (res.ok) {
    onStage(key, spec.default, /* alreadySaved */ true);
    showToast(`${spec.label} steht wieder auf Werk.`, 'success');
  }
  onRepaint();
}
