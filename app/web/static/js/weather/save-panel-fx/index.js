// ─── weather/save-panel-fx/index.js ────────────────────────────────────
// Ambient weather behind the manual-event save panel, driven by the
// category chips the operator lit: Starkregen rains, Schnee snows
// (slower, drifting), Nebel hazes, Gewitter / "Gewitter zieht auf"
// flashes at irregular intervals — and any combination of them runs
// together, because the panel's whole point is that an event is often
// more than one thing. Nothing lit → nothing runs and nothing is even
// in the DOM; the panel is byte-for-byte what it was.
//
// It sits BEHIND the form (z-index 0 against the rows' z-index 1) and
// is pointer-events:none end to end, so it can never swallow a tap.
//
// Self-initialising leaf module, imported once by main.js for its side
// effect. It deliberately reaches into weather/_manual-event-save.js for
// nothing but the chip reader, and hooks the panel through the DOM
// rather than through that module's call sites: the panel is also
// closed by weather/stats.js::_closeZoomSavePanel on a fresh drag or a
// zoom reset, and one MutationObserver on the `hidden` attribute covers
// every one of those paths at once — including any added later.
import { byId } from '../../core/dom.js';
import { _selectedCategories } from '../_manual-event-save.js';
import { fxIsIdle, fxModesFor } from './_helpers.js';
import { createLightning } from './_lightning.js';
import { createParticleLayer } from './_particles.js';

const PANEL_ID = 'weatherZoomSavePanel';
const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

// Two drifting bands make the fog read as moving without a filter:
// gradients on the compositor, animated by transform only, zero JS.
const _LAYER_HTML =
  '<div class="ws-fx-fog"><div class="ws-fx-band"></div><div class="ws-fx-band"></div></div>' +
  '<canvas class="ws-fx-canvas"></canvas>' +
  '<div class="ws-fx-flash"></div>';

const _fx = {
  panel: null,
  root: null,
  particles: null,
  lightning: null,
  ro: null,
  mo: null,
  modes: null,
};

// The hard opt-out. Checked before anything is built, and re-checked
// whenever the setting changes, so flipping it mid-session tears the
// whole backdrop down rather than leaving a flash running.
function _reducedMotion() {
  return window.matchMedia?.(REDUCED_MOTION)?.matches === true;
}

function _onVisibility() {
  if (document.hidden) _pause();
  else _resume();
}

function _pause() {
  _fx.particles?.stop();
  _fx.lightning?.stop();
}

function _resume() {
  const m = _fx.modes;
  if (!m || !_fx.root || document.hidden) return;
  if (m.rain || m.snow) _fx.particles.start();
  else _fx.particles.stop();
  if (m.lightning) {
    _fx.lightning.setDistant(m.distant);
    _fx.lightning.start();
  } else {
    _fx.lightning.stop();
  }
}

function _mount() {
  // A re-render of the panel's innerHTML would have orphaned our layer;
  // rebuild rather than paint into a detached node.
  if (_fx.root?.isConnected) return;
  _unmount();
  const root = document.createElement('div');
  root.className = 'ws-fx';
  root.setAttribute('aria-hidden', 'true');
  root.innerHTML = _LAYER_HTML;
  _fx.panel.prepend(root);
  _fx.root = root;
  _fx.particles = createParticleLayer(root.querySelector('.ws-fx-canvas'));
  _fx.lightning = createLightning(root.querySelector('.ws-fx-flash'));
  _fx.ro = new ResizeObserver((entries) => {
    const box = entries[entries.length - 1]?.contentRect;
    if (box) _fx.particles.resize(box.width, box.height);
  });
  _fx.ro.observe(_fx.panel);
  document.addEventListener('visibilitychange', _onVisibility);
}

// Every teardown path lands here: panel closed, nothing selected,
// reduced motion switched on. Nothing may outlive it — no rAF handle,
// no timeout, no observer, not even the DOM node.
function _unmount() {
  if (!_fx.root) return;
  document.removeEventListener('visibilitychange', _onVisibility);
  _fx.ro?.disconnect();
  _fx.particles?.stop();
  _fx.lightning?.stop();
  _fx.root.remove();
  _fx.root = null;
  _fx.particles = null;
  _fx.lightning = null;
  _fx.ro = null;
  _fx.modes = null;
}

// Single entry point — the panel's `hidden` attribute, a chip tap and
// the reduced-motion media query all funnel through here, and the chip
// state is read from the DOM every time (CLAUDE.md's collector rule; a
// cached Set would drift the moment anything else touched a chip).
function _apply() {
  const panel = _fx.panel;
  if (!panel || panel.hidden || _reducedMotion()) {
    _unmount();
    return;
  }
  const modes = fxModesFor(_selectedCategories(panel));
  if (fxIsIdle(modes)) {
    _unmount();
    return;
  }
  _mount();
  _fx.modes = modes;
  _fx.root.classList.toggle('has-fog', modes.fog);
  _fx.root.classList.toggle('has-lightning', modes.lightning);
  _fx.root.classList.toggle('has-particles', _fx.particles.setKinds(modes));
  _resume();
}

function _initSavePanelFx() {
  const panel = byId(PANEL_ID);
  if (!panel) return;
  _fx.panel = panel;
  _fx.mo = new MutationObserver(_apply);
  _fx.mo.observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  // Delegated, so it survives the panel rebuilding its innerHTML on
  // every open. Bubble phase: the chip's own handler in
  // _manual-event-save.js has already flipped `.is-active` by the time
  // this runs, so the read above sees the post-tap state — including
  // the capped tap that was refused and changed nothing.
  panel.addEventListener('click', (ev) => {
    if (ev.target?.closest?.('.ws-zsave-cat')) _apply();
  });
  window.matchMedia?.(REDUCED_MOTION)?.addEventListener?.('change', _apply);
}

document.addEventListener('DOMContentLoaded', _initSavePanelFx);
