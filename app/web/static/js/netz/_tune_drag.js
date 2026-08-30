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
import { classAxisSpec, isClassAxisKey, resetClassAxis, saveClassAxis } from './_class_rows.js';
import { TUNE_SPECS, tuneDisplay, tuneRawFromE } from './_settings_axes.js';
import { eFromEllipse, moveTuneVertex, tuneGeometry, TUNE_H, TUNE_W } from './_tune_radar.js';
import { applySaved, axisFor, netzState, stageValue, unstage } from './_state.js';

const LONG_PRESS_MS = 500;
const MOVE_THRESHOLD_PX = 4;

let _drag = null;
let _rafId = 0;

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
  // `note` is only set on class axes — the two save paths on this one net
  // behave differently on release (stage vs. commit), so the pill says
  // which one the finger is on rather than leaving it to be discovered.
  el.innerHTML =
    `<b>${spec.label}</b><span>${tuneDisplay(spec, raw)}</span>` +
    (spec.note ? `<em>${spec.note}</em>` : '');
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
  // One pointer layer for both concerns on the net. A class axis carries
  // a TUNE_SPECS-shaped spec (see _class_rows.js) precisely so this stays
  // a lookup rather than a second drag implementation.
  const spec = TUNE_SPECS[key] || classAxisSpec(key);
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

// Pointer events fire faster than the screen refreshes, so the paint is
// coalesced into one animation frame. Without this a fast drag does the
// same DOM work three or four times for a single visible update.
function _schedulePaint() {
  if (_rafId) return;
  _rafId = requestAnimationFrame(() => {
    _rafId = 0;
    if (!_drag) return;
    const axes = netzState.tuneAxes[_drag.camId];
    if (!axes) return;
    const i = axes.findIndex((a) => a.key === _drag.key);
    if (i < 0) return;
    // Mutate the row in place so the next frame — and the pointerup that
    // stages the value — both read the value actually on screen.
    axes[i] = {
      ...axes[i],
      E: _drag.e,
      raw: _drag.raw,
      display: tuneDisplay(_drag.spec, _drag.raw),
    };
    moveTuneVertex(_drag.card.querySelector('.netz-tune-svg'), axes, _drag.key);
    _paintPill(_drag.card, _drag.spec, _drag.raw);
  });
}

function _onMove(ev) {
  if (!_drag) return;
  const dist = Math.hypot(ev.clientX - _drag.start.x, ev.clientY - _drag.start.y);
  if (!_drag.moved && dist < MOVE_THRESHOLD_PX) return;
  if (!_drag.moved) {
    _drag.moved = true;
    clearTimeout(_drag.longPress);
    _drag.card
      .querySelector(`.netz-vertex[data-tune-axis="${CSS.escape(_drag.key)}"]`)
      ?.classList.add('is-dragging');
  }
  const e = eFromEllipse(
    ev.clientX - _drag.geo.cx,
    ev.clientY - _drag.geo.cy,
    _drag.geo,
    _drag.axis.defaultE,
  );
  _drag.e = e;
  _drag.raw = tuneRawFromE(_drag.spec, e);
  _schedulePaint();
}

function _onUp(ev, onRepaint) {
  if (!_drag) return;
  const { camId, key, moved, raw, card } = _drag;
  clearTimeout(_drag.longPress);
  if (_rafId) {
    cancelAnimationFrame(_rafId);
    _rafId = 0;
  }
  _drag = null;
  _hidePill(card);
  card
    .querySelector(`.netz-vertex[data-tune-axis="${CSS.escape(key)}"]`)
    ?.classList.remove('is-dragging');
  // TWO SAVE PATHS, one net. A camera-wide axis STAGES — nothing is
  // written until "Übernehmen", the two-stage commit the confidence radar
  // used. A per-class Meldeschwelle COMMITS on release through
  // PATCH /api/netz/<cam>/axes, which also writes the net-archive record:
  // one drag, one write, one history entry. Repainting here would snap
  // the vertex back to the stored value for the length of the request, so
  // the save owns the repaint.
  if (moved && isClassAxisKey(key)) {
    saveClassAxis(camId, key, raw, onRepaint);
    return;
  }
  if (moved) stageValue(camId, key, raw);
  onRepaint();
}

async function _onLongPress(card, camId, key, spec, onRepaint) {
  _drag = null;
  _hidePill(card);
  if (!(await showConfirm(`${spec.label} auf Werk zurücksetzen?`))) return;
  // A class axis resets through POST /api/netz/<cam>/reset, which also
  // UNPINS it. `patchAxes(…, 50)` would land on the same number and leave
  // the learner locked out of the axis for good.
  if (isClassAxisKey(key)) {
    await resetClassAxis(camId, key);
    onRepaint();
    return;
  }
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
