// ─── netz/_drag.js ─────────────────────────────────────────────────────────
// Pointer Events, radial-only vertex drag, two-stage commit, undo,
// long-press reset.
//
// shape-editor/pointer.js is the closest precedent in this codebase —
// real touch vertex-drag with the iOS double-tap synthesis at line 239 —
// but it is <canvas>, bound to #maskCanvas in a load-time IIFE, and
// coupled to shapeState. Its LESSONS are copied; nothing is imported:
//
//   * setPointerCapture on pointerdown, so a finger that leaves the
//     element keeps driving the drag instead of dropping it;
//   * touch-action:none on the SVG ONLY, never on the page, so the
//     panel still scrolls;
//   * a movement threshold before treating a press as a drag, so a tap
//     is a tap;
//   * clean up on pointercancel — iOS fires it on a system gesture and
//     a drag that never ends leaves a stuck vertex.

import { showConfirm, showToast } from '../core/toast.js';
import { clampE, eFromRadius, E_FACTORY } from './_mapping.js';
import { netzState, shownE, axisByLabel } from './_state.js';
import { chartRadius } from './_radar.js';
import { labelDe, pct } from './_helpers.js';
import { fetchPreview, patchAxes, resetAxis } from './_api.js';
import { invalidateNetzCache } from './effective.js';

const LONG_PRESS_MS = 500;
const PREVIEW_DEBOUNCE_MS = 120;
// Below E 35, `person` on a security camera stops being a burglar alarm.
const PERSON_FLOOR_E = 35;

let _drag = null;
let _previewTimer = null;
let _lastCommit = null;

function _pillEl(host) {
  let el = host.querySelector('.netz-drag-pill');
  if (!el) {
    el = document.createElement('div');
    el.className = 'netz-drag-pill';
    host.appendChild(el);
  }
  return el;
}

function _previewLine(data) {
  if (!data || data.has_corpus === false) return 'Rückblick: noch keine Rückmeldungen';
  const d = data.delta_alerts;
  const f = data.delta_false;
  const sign = (n) => (n > 0 ? `+${n}` : String(n));
  return `Rückblick: ${sign(d)} Meldungen, davon ${sign(f)} Fehlalarm`;
}

function _directionLine(e, base) {
  if (e === base) return 'unverändert';
  return e > base
    ? 'meldet häufiger — auch unsicherere Treffer'
    : 'meldet seltener — nur klarere Treffer';
}

function _paintPill(host, label, e, data) {
  const el = _pillEl(host);
  el.innerHTML =
    `<b>${labelDe(label)} · Empfindlichkeit ${e}</b>` +
    `<span>${_directionLine(e, E_FACTORY)}</span>` +
    `<span>${_previewLine(data)}</span>`;
  el.dataset.on = '1';
}

function _hidePill(host) {
  const el = host.querySelector('.netz-drag-pill');
  if (el) el.dataset.on = '0';
}

// The consequence-before-commit line. Debounced and cached per
// (label, E) so a radius the pointer already visited on its way out
// never re-fires a request.
function _schedulePreview(host, label, e) {
  const key = `${label}:${e}`;
  if (netzState.previews[key]) {
    _paintPill(host, label, e, netzState.previews[key]);
    return;
  }
  if (_previewTimer) clearTimeout(_previewTimer);
  _previewTimer = setTimeout(async () => {
    const data = await fetchPreview(netzState.camId, label, e);
    netzState.previews[key] = data;
    if (_drag && _drag.label === label) _paintPill(host, label, e, data);
  }, PREVIEW_DEBOUNCE_MS);
}

function _geometry(host) {
  const svg = host.querySelector('.netz-svg');
  if (!svg) return null;
  const box = svg.getBoundingClientRect();
  const side = box.width;
  return { cx: box.left + side / 2, cy: box.top + side / 2, r: chartRadius(side) };
}

// RADIAL ONLY. The vertex slides along its own spoke and the angle is
// locked — a free-floating vertex would encode an angle that means
// nothing, and would let a drag change which class it belongs to.
function _eFromPointer(geo, ev) {
  const dx = ev.clientX - geo.cx;
  const dy = ev.clientY - geo.cy;
  return eFromRadius(Math.hypot(dx, dy), geo.r);
}

function _eFromBar(row, ev) {
  const track = row.querySelector('.netz-bar-track');
  const box = track.getBoundingClientRect();
  const raw = clampE(Math.round(((ev.clientX - box.left) / box.width) * 100));
  return Math.abs(raw - E_FACTORY) <= 2 ? E_FACTORY : raw;
}

function _stage(label, e) {
  const axis = axisByLabel(label);
  if (!axis) return;
  if (!(label in netzState.snapshot)) netzState.snapshot[label] = axis.E;
  netzState.staged[label] = e;
}

// ── the blocking confirm ──────────────────────────────────────────────
// A8 · only a MANUAL drag may cross the person floor, and only after
// being told exactly what it costs. The learner never can.
function _crossesPersonFloor(axes) {
  const st = netzState.state;
  return (
    st?.role === 'security' &&
    typeof axes.person === 'number' &&
    axes.person < PERSON_FLOOR_E
  );
}

async function _confirmPersonFloor(label, e) {
  const st = netzState.state;
  if (label !== 'person' || st?.role !== 'security' || e >= PERSON_FLOOR_E) return true;
  return showConfirm(
    `${st.cam_name} meldet Personen dann seltener. Ein Einbrecher unterhalb der ` +
      `Schwelle löst keine Meldung aus. Trotzdem setzen?`,
  );
}

// ── public wiring ─────────────────────────────────────────────────────

export function bindDrag(host, onRepaint) {
  const targets = host.querySelectorAll('.netz-hit, .netz-bar-hit');
  targets.forEach((node) => {
    node.addEventListener('pointerdown', (ev) => _onDown(ev, node, host, onRepaint));
  });
}

function _onDown(ev, node, host, onRepaint) {
  const label = node.dataset.axis;
  const axis = axisByLabel(label);
  if (!axis) return;
  ev.preventDefault();
  node.setPointerCapture?.(ev.pointerId);
  const isBar = node.classList.contains('netz-bar-hit');
  _drag = {
    label,
    node,
    isBar,
    row: isBar ? node.closest('.netz-bar-row') : null,
    geo: isBar ? null : _geometry(host),
    start: { x: ev.clientX, y: ev.clientY },
    moved: false,
    value: shownE(axis),
    longPress: setTimeout(() => _onLongPress(host, label, onRepaint), LONG_PRESS_MS),
  };
  _paintPill(host, label, _drag.value, netzState.previews[`${label}:${_drag.value}`]);
  const move = (e2) => _onMove(e2, host);
  const up = (e2) => {
    node.removeEventListener('pointermove', move);
    node.removeEventListener('pointerup', up);
    node.removeEventListener('pointercancel', up);
    _onUp(e2, host, onRepaint);
  };
  node.addEventListener('pointermove', move);
  node.addEventListener('pointerup', up);
  // iOS fires pointercancel on a system gesture; without this the drag
  // never ends and the vertex sticks to the finger that left.
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
  const e = _drag.isBar ? _eFromBar(_drag.row, ev) : _eFromPointer(_drag.geo, ev);
  _drag.value = e;
  _schedulePreview(host, _drag.label, e);
  _paintPill(host, _drag.label, e, netzState.previews[`${_drag.label}:${e}`]);
  _previewVertex(host, _drag, e);
}

// Move the visible vertex without a full re-render: a re-render on every
// pointermove would rebuild the SVG under the finger and drop the
// capture.
function _previewVertex(host, drag, e) {
  if (drag.isBar) {
    const fill = drag.row.querySelector('.netz-bar-fill');
    const knob = drag.row.querySelector('.netz-bar-knob');
    if (fill) fill.style.width = `${e}%`;
    if (knob) knob.style.left = `${e}%`;
    return;
  }
  host.dispatchEvent(
    new CustomEvent('netz:vertexmove', { detail: { label: drag.label, e } }),
  );
}

async function _onUp(ev, host, onRepaint) {
  if (!_drag) return;
  const { label, moved, value } = _drag;
  clearTimeout(_drag.longPress);
  _drag = null;
  _hidePill(host);
  if (!moved) return;
  if (!(await _confirmPersonFloor(label, value))) {
    onRepaint();
    return;
  }
  // Pointerup STAGES. It is not saved — the staging bar is.
  _stage(label, value);
  onRepaint();
}

async function _onLongPress(host, label, onRepaint) {
  _drag = null;
  _hidePill(host);
  if (!(await showConfirm(`${labelDe(label)} auf Werk zurücksetzen?`))) return;
  const res = await resetAxis(netzState.camId, label);
  if (res.ok) {
    delete netzState.staged[label];
    netzState.state = res.state || netzState.state;
    invalidateNetzCache(netzState.camId);
    showToast(`${labelDe(label)} steht wieder auf Werk.`, 'success');
  }
  onRepaint();
}

// ── commit / discard / undo ───────────────────────────────────────────

export async function commitStaged(onRepaint) {
  const axes = { ...netzState.staged };
  if (!Object.keys(axes).length) return;
  const before = { ...netzState.snapshot };
  // The authoritative ask. The stage-time confirm is immediate feedback;
  // this one is the answer the server acts on, because the server clamps
  // to the floor unless this request carries it.
  const crosses = _crossesPersonFloor(axes);
  if (crosses && !(await _confirmPersonFloor('person', axes.person))) {
    onRepaint();
    return;
  }
  const res = await patchAxes(netzState.camId, axes, crosses);
  if (!res.ok) {
    showToast('Konnte nicht gespeichert werden.', 'error');
    return;
  }
  netzState.state = res.state || netzState.state;
  netzState.staged = {};
  netzState.snapshot = {};
  netzState.previews = {};
  // Every other panel that prints an effective threshold reads the same
  // cache; a stale one there would show the pre-drag line.
  invalidateNetzCache(netzState.camId);
  _lastCommit = before;
  const first = Object.keys(axes)[0];
  const w = res.written?.[first];
  const detail = w ? ` Meldeschwelle ${labelDe(first)}: ${pct(w.push)}.` : '';
  showToast(`Netz übernommen.${detail}`, 'success', {
    action: { label: 'Rückgängig', onClick: () => undoLastCommit(onRepaint) },
  });
  onRepaint();
}

export function discardStaged(onRepaint) {
  netzState.staged = {};
  netzState.snapshot = {};
  onRepaint();
}

/** Undo within the toast's window. Beyond it, every commit is an archive
 *  record and the detail sheet offers "Netz zu diesem Zeitpunkt
 *  wiederherstellen" — so nothing is ever unrecoverable, only less
 *  convenient. */
export async function undoLastCommit(onRepaint) {
  if (!_lastCommit || !Object.keys(_lastCommit).length) return;
  // No confirm flag: undo restores a value the operator had, it is not a
  // fresh decision to blind the camera. A pre-drag person axis already
  // below the floor comes back clamped to it.
  const res = await patchAxes(netzState.camId, _lastCommit);
  _lastCommit = null;
  if (res.ok) {
    netzState.state = res.state || netzState.state;
    showToast('Änderung zurückgenommen.', 'info');
  }
  onRepaint();
}
