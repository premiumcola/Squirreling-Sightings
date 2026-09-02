"""weather/save-panel-fx/index.js — the real module, driven under node.

The pure half (which chips mean which effect, the flash cadence, how a
particle moves) is covered by weather/_tests/save-panel-fx.test.js. What
that cannot reach is the half every bug in this feature will actually
live in: the lifecycle. This backdrop opens inside an editing panel on a
box that is also decoding camera streams and feeding a Coral TPU, so a
requestAnimationFrame or a timer surviving the panel's close is not a
cosmetic defect — it is a loop running forever behind a closed form.

So these tests import the module for real (the shared _node_js harness
already carries a DOM stub big enough for its import graph), replace the
few globals it touches with recording fakes, and drive it through the
whole sequence: open with nothing selected, open with chips lit, a chip
tapped mid-session, the tab hidden, and the close.

The panel is hidden/shown by FOUR different call sites — this module
hooks none of them, it observes the `hidden` attribute — so the drive
below flips the attribute exactly the way those call sites do.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


# A DOM small enough to read, real enough to drive: listeners are
# recorded and fired, classes are observable, and every scheduling
# global is counted so the teardown assertions can be exact.
_SETUP = """
const log = { raf: 0, cancelRaf: 0, timeouts: 0, clearTimeouts: 0, roDisconnect: 0 };

function fakeEl(tag) {
  const listeners = {};
  const classes = new Set();
  const el = {
    tagName: tag, style: {}, dataset: {}, innerHTML: '', hidden: false,
    offsetWidth: 500, isConnected: false, removed: false,
    children: [], q: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
    },
    classes: () => [...classes].sort(),
    setAttribute() {}, getAttribute: () => null,
    addEventListener(t, cb) { (listeners[t] = listeners[t] || []).push(cb); },
    removeEventListener(t, cb) {
      listeners[t] = (listeners[t] || []).filter((f) => f !== cb);
    },
    listenerCount: (t) => (listeners[t] || []).length,
    fire(t, ev) { (listeners[t] || []).slice().forEach((cb) => cb(ev)); },
    prepend(child) { el.children.unshift(child); child.isConnected = true; },
    remove() { el.removed = true; el.isConnected = false; },
    querySelector: (sel) => el.q[sel] || null,
    querySelectorAll: () => [],
    getContext: () => ctx,
  };
  return el;
}

const ctx = {
  clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, arc() {},
  stroke() {}, fill() {}, setTransform() {},
};

// One chip per manual category, exactly as _categoryChipsHTML renders
// them: the lit ones carry .is-active and every one carries
// data-category. The fx module reads them through the SAME
// _selectedCategories the save payload uses.
function makeChips(active) {
  return ['thunder', 'heavy_rain', 'snow', 'fog', 'thunder_rising'].map((key) => {
    const c = fakeEl('button');
    c.dataset.category = key;
    if (active.includes(key)) c.classList.add('is-active');
    return c;
  });
}

const panel = fakeEl('div');
let chips = [];
panel.querySelectorAll = (sel) =>
  sel === '.ws-zsave-cat.is-active'
    ? chips.filter((c) => c.classList.contains('is-active'))
    : [];
panel.hidden = true;

globalThis.window = {
  addEventListener() {}, location: { hash: '', href: '', search: '' },
  devicePixelRatio: 2,
  matchMedia: (q) => ({ matches: REDUCED && q.includes('reduced-motion'),
                        addEventListener() {} }),
};
const docListeners = {};
globalThis.document = {
  hidden: false,
  addEventListener(t, cb) { (docListeners[t] = docListeners[t] || []).push(cb); },
  removeEventListener(t, cb) {
    docListeners[t] = (docListeners[t] || []).filter((f) => f !== cb);
  },
  fire(t) { (docListeners[t] || []).slice().forEach((cb) => cb()); },
  count: (t) => (docListeners[t] || []).length,
  getElementById: (id) => (id === 'weatherZoomSavePanel' ? panel : fakeEl('div')),
  querySelector: () => null, querySelectorAll: () => [],
  createElement(tag) {
    const el = fakeEl(tag);
    // The fx layer builds its three children from one innerHTML string;
    // resolve the selectors index.js then looks them up by.
    el.q['.ws-fx-canvas'] = fakeEl('canvas');
    el.q['.ws-fx-flash'] = fakeEl('div');
    return el;
  },
  body: fakeEl('body'), documentElement: fakeEl('html'),
};
globalThis.MutationObserver = class {
  constructor(cb) { this.cb = cb; }
  observe(target) { target.mo = this; }
  disconnect() {}
};
// Fires immediately, so the canvas gets a real size (and therefore real
// particles) the way a laid-out panel would.
globalThis.ResizeObserver = class {
  constructor(cb) { this.cb = cb; }
  observe() { this.cb([{ contentRect: { width: 520, height: 430 } }]); }
  disconnect() { log.roDisconnect += 1; }
};
globalThis.IntersectionObserver = class { observe() {} disconnect() {} };
globalThis.history = { replaceState() {} };
globalThis.fetch = () => Promise.reject(new Error('no network in tests'));

// Never invoke the callback: the loop must not self-schedule inside a
// test, and what matters is the start/cancel balance.
globalThis.requestAnimationFrame = () => { log.raf += 1; return log.raf; };
globalThis.cancelAnimationFrame = () => { log.cancelRaf += 1; };
globalThis.setTimeout = () => { log.timeouts += 1; return log.timeouts; };
globalThis.clearTimeout = () => { log.clearTimeouts += 1; };

// The panel is opened/closed by flipping the attribute, then letting the
// observer run — exactly what _toggleSaveForm / _exitMarkMode /
// stats.js::_closeZoomSavePanel do.
function openPanel(active) {
  chips = makeChips(active);
  panel.children.length = 0;
  panel.hidden = false;
  panel.mo.cb([]);
}
function closePanel() {
  panel.hidden = true;
  panel.mo.cb([]);
}
function tapChip(key) {
  const chip = chips.find((c) => c.dataset.category === key);
  const on = chip.classList.contains('is-active');
  chip.classList.toggle('is-active', !on);
  panel.fire('click', { target: { closest: (sel) => (sel === '.ws-zsave-cat' ? chip : null) } });
}
function layer() { return panel.children[0] || null; }
function snapshot() {
  const l = layer();
  return {
    mounted: !!l && !l.removed,
    classes: l ? l.classes() : [],
    visibility_listeners: document.count('visibilitychange'),
    ...log,
  };
}
"""


def _run(scenario: str, reduced: str = "false"):
    return _js(
        "const REDUCED = {};\n{}\nawait import(JS + '/weather/save-panel-fx/index.js');\n"
        "document.fire('DOMContentLoaded');\n{}".format(reduced, _SETUP, scenario)
    )


def test_nothing_selected_builds_nothing_at_all():
    """The operator's own condition: with no category lit the panel is
    exactly what it was — not a running loop drawing zero particles."""
    out = _run("openPanel([]);\nconsole.log(JSON.stringify(snapshot()));")
    assert out["mounted"] is False
    assert out["raf"] == 0
    assert out["timeouts"] == 0
    assert out["visibility_listeners"] == 0


def test_starkregen_runs_the_canvas_and_nothing_else():
    out = _run("openPanel(['heavy_rain']);\nconsole.log(JSON.stringify(snapshot()));")
    assert out["mounted"] is True
    assert "has-particles" in out["classes"]
    assert "has-lightning" not in out["classes"]
    assert "has-fog" not in out["classes"]
    assert out["raf"] == 1, "exactly one rAF loop"
    assert out["timeouts"] == 0, "no strike scheduled without a thunder chip"


def test_a_storm_with_rain_runs_both_at_once():
    """The multi-select case the panel was built for."""
    out = _run("openPanel(['thunder', 'heavy_rain']);\nconsole.log(JSON.stringify(snapshot()));")
    assert "has-particles" in out["classes"]
    assert "has-lightning" in out["classes"]
    assert out["raf"] == 1
    assert out["timeouts"] == 1, "one strike scheduled, one timer"


def test_fog_alone_needs_no_javascript_loop():
    """The haze is two transform-animated gradients — CSS only."""
    out = _run("openPanel(['fog']);\nconsole.log(JSON.stringify(snapshot()));")
    assert out["mounted"] is True
    assert out["classes"] == ["has-fog"]
    assert out["raf"] == 0
    assert out["timeouts"] == 0


def test_tapping_a_chip_changes_the_weather_without_reopening():
    out = _run(
        "openPanel(['snow']);\ntapChip('thunder');\nconsole.log(JSON.stringify(snapshot()));"
    )
    assert "has-particles" in out["classes"]
    assert "has-lightning" in out["classes"]
    assert out["timeouts"] == 1


def test_clearing_the_last_chip_tears_the_backdrop_down():
    out = _run(
        "openPanel(['heavy_rain']);\ntapChip('heavy_rain');\n"
        "console.log(JSON.stringify(snapshot()));"
    )
    assert out["mounted"] is False
    assert out["cancelRaf"] == 1
    assert out["roDisconnect"] == 1
    assert out["visibility_listeners"] == 0


def test_closing_the_panel_leaves_nothing_running():
    """The one that matters. Every scheduled thing is cancelled, the
    observer is disconnected, the listener is off and the layer is gone
    from the DOM."""
    out = _run(
        "openPanel(['thunder', 'heavy_rain']);\nclosePanel();\n"
        "console.log(JSON.stringify(snapshot()));"
    )
    assert out["mounted"] is False
    assert out["raf"] == out["cancelRaf"] == 1
    assert out["timeouts"] == out["clearTimeouts"] == 1
    assert out["roDisconnect"] == 1
    assert out["visibility_listeners"] == 0


def test_reopening_after_a_close_starts_exactly_one_loop_again():
    """A leak would show up here as a second, orphaned rAF."""
    out = _run(
        "openPanel(['heavy_rain']);\nclosePanel();\nopenPanel(['heavy_rain']);\n"
        "console.log(JSON.stringify(snapshot()));"
    )
    assert out["mounted"] is True
    assert out["raf"] == 2 and out["cancelRaf"] == 1, "one live loop, one cancelled"
    assert out["visibility_listeners"] == 1


def test_a_hidden_tab_stops_the_work_and_a_visible_one_resumes_it():
    out = _run(
        "openPanel(['thunder', 'heavy_rain']);\n"
        "document.hidden = true; document.fire('visibilitychange');\n"
        "const paused = snapshot();\n"
        "document.hidden = false; document.fire('visibilitychange');\n"
        "console.log(JSON.stringify({ paused, resumed: snapshot() }));"
    )
    assert out["paused"]["cancelRaf"] == 1
    assert out["paused"]["clearTimeouts"] == 1
    assert out["paused"]["mounted"] is True, "paused, not torn down"
    assert out["resumed"]["raf"] == 2
    assert out["resumed"]["timeouts"] == 2


def test_reduced_motion_builds_no_layer_whatsoever():
    """Not 'slower', not 'dimmer' — nothing is created, so there is no
    flash to mis-fire and no loop to run."""
    out = _run(
        "openPanel(['thunder', 'heavy_rain', 'snow']);\nconsole.log(JSON.stringify(snapshot()));",
        reduced="true",
    )
    assert out["mounted"] is False
    assert out["raf"] == 0
    assert out["timeouts"] == 0
