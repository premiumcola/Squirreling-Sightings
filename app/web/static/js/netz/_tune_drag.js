// ─── netz/_tune_drag.js ─────────────────────────────────────────────────────
// Radial vertex-drag for the Erkennungsprofil's settings radars.
//
// CARD-SCOPED. Every geometry read and every write resolves through the
// `.netz-card` the pointer went down on, not through module state: with
// N radars on the page a `host.querySelector('.netz-card-chart')` silently
// returns camera 1's chart and the drag then computes a correct-looking E
// against the wrong centre. That failure is geometric, not an exception —
// it would survive any smoke test that only checks "something moved".
//
// Deliberately NOT a reuse of the confidence radar's pointer layer: that
// one fetches an alert-delta preview and guards the person floor, neither
// of which exists for a setting. What IS shared, because it is pure
// pointer hygiene (see shape-editor/pointer.js, the original precedent):
// setPointerCapture so a finger leaving the element keeps driving the
// drag, a movement threshold so a tap stays a tap, and cleanup on
// pointercancel because iOS fires it on a system gesture and a drag that
// never ends leaves a vertex stuck to a finger that is gone.

import { showConfirm, showToast } from '../core/toast.js';
import { patchTuning } from './_api.js';
import { TUNE_SPECS, tuneDisplay, tuneRawFromE } from './_settings_axes.js';
import { eFromEllipse, tuneGeometry, TUNE_H, TUNE_W } from './_tune_radar.js';
import { applySaved, axisFor, stageValue, unstage } from './_state.js';

const LONG_PRESS_MS = 500;
const MOVE_THRESHOLD_PX = 4;

let _drag = null;

function _pillEl(card) {
  let el = card.querySelector('.netz-drag-pill');
  if (!el) {
    el = document.createElement('div');
    el.className = 'netz-drag-pill';
    card.appendChild(el);
  }
  return el;
}

function _paintPill(card, spec, raw) {
  const el = _pillEl(card);
  el.innerHTML = `<b>${spec.label}</b><span>${tuneDisplay(spec, raw)}</span>`;
  el.dataset.on = '1';
}

function _hidePill(card) {
  const el = card.querySelector('.netz-drag-pill');
  if (el) el.dataset.on = '0';
}

/** Screen geometry of THIS card's radar, mapped back to viewBox units.
 *  The SVG scales uniformly (viewBox and width/height share an aspect
 *  ratio), so one scale factor converts client px to viewBox px. */
function _geometry(card) {
  const svg = card.querySelector('.netz-tune-svg');
  if (!svg) return null;
  const box = svg.getBoundingClientRect();
  if (!(box.width > 0)) return null;
  const scale = box.width / TUNE_W;
  const geo = tuneGeometry();
  return {
    cx: box.left + geo.cx * scale,
    cy: box.top + (TUNE_H / 2) * scale,
    rx: geo.rx * scale,
    ry: geo.ry * scale,
  };
}

export function bindTuneDrag(host, onRepaint) {
  host.querySelectorAll('.netz-tune-hit').forEach((node) => {
    node.addEventListener('pointerdown', (ev) => _onDown(ev, node, onRepaint));
  });
}

function _onDown(ev, node, onRepaint) {
  const card = node.closest('.netz-card');
  if (!card) return;
  const camId = card.dataset.cam;
  const key = node.dataset.tuneAxis;
  const spec = TUNE_SPECS[key];
  const axis = axisFor(camId, key);
  if (!spec || !axis) return;
  const geo = _geometry(card);
  if (!geo) return;
  ev.preventDefault();
  node.setPointerCapture?.(ev.pointerId);
  _drag = {
    camId,
    key,
    spec,
    axis,
    card,
    geo,
    start: { x: ev.clientX, y: ev.clientY },
    moved: false,
    raw: axis.raw,
    longPress: setTimeout(() => _onLongPress(card, camId, key, spec, onRepaint), LONG_PRESS_MS),
  };
  _paintPill(card, spec, axis.raw);
  const move = (e2) => _onMove(e2);
  const up = (e2) => {
    node.removeEventListener('pointermove', move);
    node.removeEventListener('pointerup', up);
    node.removeEventListener('pointercancel', up);
    _onUp(e2, onRepaint);
  };
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  node.addEventListener('pointercancel', up);
}

function _onMove(ev) {
  if (!_drag) return;
  const dist = Math.hypot(ev.clientX - _drag.start.x, ev.clientY - _drag.start.y);
  if (!_drag.moved && dist < MOVE_THRESHOLD_PX) return;
  if (!_drag.moved) {
    _drag.moved = true;
    clearTimeout(_drag.longPress);
  }
  const e = eFromEllipse(
    ev.clientX - _drag.geo.cx,
    ev.clientY - _drag.geo.cy,
    _drag.geo,
    _drag.axis.defaultE,
  );
  const raw = tuneRawFromE(_drag.spec, e);
  _drag.raw = raw;
  _paintPill(_drag.card, _drag.spec, raw);
  _drag.card.dispatchEvent(
    new CustomEvent('netz:tunevertexmove', {
      bubbles: true,
      detail: { camId: _drag.camId, key: _drag.key, e },
    }),
  );
}

function _onUp(ev, onRepaint) {
  if (!_drag) return;
  const { camId, key, moved, raw, card } = _drag;
  clearTimeout(_drag.longPress);
  _drag = null;
  _hidePill(card);
  // Pointerup STAGES. Nothing is saved until "Übernehmen" — the same
  // two-stage commit the confidence radar used.
  if (moved) stageValue(camId, key, raw);
  onRepaint();
}

async function _onLongPress(card, camId, key, spec, onRepaint) {
  _drag = null;
  _hidePill(card);
  if (!(await showConfirm(`${spec.label} auf Werk zurücksetzen?`))) return;
  const res = await patchTuning(camId, { [key]: spec.default });
  if (res.ok) {
    // The reset already hit the server, so drop any staged value for this
    // key — otherwise a later "Übernehmen" would resend the pre-reset one.
    unstage(camId, key);
    applySaved(camId, res.effective || { [key]: spec.default });
    showToast(`${spec.label} steht wieder auf Werk.`, 'success');
  }
  onRepaint();
}

/** True while a vertex is actively being dragged — the resize handler
 *  skips repaints then, which would rebuild the SVG under the finger and
 *  drop the pointer capture. */
export function isTuneDragging() {
  return _drag !== null && _drag.moved;
}
