// ─── shape-editor/mode-toggle.js ───────────────────────────────────────────
// Wires the zone / mask segmented switcher inside the Zonen tab.
// Updates shapeState.mode, cancels any in-progress polygon points so a
// half-drawn shape doesn't accidentally commit into the wrong array,
// triggers a redraw + drawing-bar refresh, and persists the chosen
// mode under localStorage key 'tamspy.shapeMode' so the next time the
// user opens the tab the same mode is active.
//
// The active-pill visual + helper-line copy live here too so the
// "what does drawing here do?" question is answered without the user
// having to click around.
import { byId } from '../core/dom.js';
import { shapeState } from '../core/state.js';
import { showToast } from '../core/toast.js';
import { drawShapes } from './canvas.js';
import { _updateShapeDrawingBar } from './ui.js';

const STORAGE_KEY = 'tamspy.shapeMode';

// Helper-line copy per mode. Mirrors the backend semantics in
// camera_runtime/_zones.py — zones whitelist detections to their
// interior; masks suppress detections inside them.
const _MODE_HINTS = {
  zone: 'Erkennungen werden nur innerhalb der GRÜNEN Polygone gezählt.',
  mask: 'Erkennungen innerhalb der roten Polygone werden unterdrückt.',
};

function _normalise(mode) {
  return mode === 'mask' ? 'mask' : 'zone';
}

function _readStoredMode() {
  try {
    return _normalise(localStorage.getItem(STORAGE_KEY));
  } catch {
    return 'zone';
  }
}

function _writeStoredMode(mode) {
  try {
    localStorage.setItem(STORAGE_KEY, _normalise(mode));
  } catch {
    /* quota / private mode — fall through silently */
  }
}

// Sync the segmented control's visual + ARIA state to the current
// shapeState.mode. Idempotent — safe to call on every editor open
// even when the toggle DOM is freshly rendered.
export function _syncShapeModeUI() {
  const mode = _normalise(shapeState.mode);
  const toggle = byId('shapeModeToggle');
  if (toggle) {
    toggle.querySelectorAll('.shape-mode-pill').forEach((btn) => {
      const active = btn.dataset.mode === mode;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', active ? 'true' : 'false');
    });
  }
  const hint = byId('shapeModeHint');
  if (hint) hint.textContent = _MODE_HINTS[mode] || _MODE_HINTS.zone;
}

// Apply a mode change — pure state + UI update, no DOM event handling.
// Callers: the click handler in bindShapeModeToggle, and editCamera
// (via restoreShapeMode) when the editor opens.
function _applyMode(mode, { resetPoints = true } = {}) {
  const next = _normalise(mode);
  const prev = _normalise(shapeState.mode);
  shapeState.mode = next;
  // Discard any in-progress polygon points so a half-drawn shape
  // doesn't commit into the wrong array on the next click. Only
  // toast when there actually WAS something to discard AND the mode
  // genuinely changed.
  const hadPoints = (shapeState.points || []).length > 0;
  if (resetPoints && hadPoints) {
    shapeState.points = [];
    if (prev !== next) showToast('Modus gewechselt — Punkte verworfen');
  }
  _syncShapeModeUI();
  drawShapes();
  _updateShapeDrawingBar();
  _writeStoredMode(next);
}

// One-shot binding called from pointer.js's init IIFE so the click
// handlers attach before the user can interact. Idempotent guard via
// dataset.bound so a future re-render of the tab doesn't double-bind.
export function bindShapeModeToggle() {
  const toggle = byId('shapeModeToggle');
  if (!toggle || toggle.dataset.bound === '1') return;
  toggle.dataset.bound = '1';
  toggle.addEventListener('click', (ev) => {
    const btn = ev.target.closest?.('.shape-mode-pill');
    if (!btn) return;
    const mode = btn.dataset.mode;
    if (!mode || mode === shapeState.mode) return;
    _applyMode(mode);
  });
  _syncShapeModeUI();
}

// Called from editCamera() after shapeState.camera is set so the
// editor opens in the user's last-chosen mode. resetPoints=false
// because shapeState.points was just zeroed by the caller — no need
// to toast on a fresh open.
export function restoreShapeMode() {
  _applyMode(_readStoredMode(), { resetPoints: false });
}
