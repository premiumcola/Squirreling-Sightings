"""weather/pin-toggle.js — the standalone "keep forever" card button.

Built as an isolated module (not wired into _feed.js/sightings.js —
another change was in flight on both) so it needs its own tests rather
than piggybacking on test_weather_feed.py's harness. Same real-JS-under-
node approach: pinToggleHTML is a pure string builder, bindPinToggle
wires real DOM events, and the network call is stubbed via a fake
apiPost so no fetch ever leaves the process.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)


def test_unpinned_item_renders_the_base_button_with_no_is_pinned_class():
    out = _js(
        """
        const pin = await import(JS + '/weather/pin-toggle.js');
        const html = pin.pinToggleHTML({ id: 's1', pinned: false });
        console.log(JSON.stringify({
          hasBtn: html.includes('mmc-pin'),
          hasIsPinned: html.includes('is-pinned'),
          hasId: html.includes('data-id="s1"'),
          ariaPressed: html.includes('aria-pressed="false"'),
        }));
        """
    )
    assert out == {"hasBtn": True, "hasIsPinned": False, "hasId": True, "ariaPressed": True}


def test_pinned_item_renders_with_the_is_pinned_class():
    out = _js(
        """
        const pin = await import(JS + '/weather/pin-toggle.js');
        const html = pin.pinToggleHTML({ id: 's2', pinned: true });
        console.log(JSON.stringify({
          hasIsPinned: html.includes('is-pinned'),
          ariaPressed: html.includes('aria-pressed="true"'),
          dataPinned: html.includes('data-pinned="true"'),
        }));
        """
    )
    assert out == {"hasIsPinned": True, "ariaPressed": True, "dataPinned": True}


def test_a_missing_id_does_not_crash_and_renders_an_empty_data_id():
    out = _js(
        """
        const pin = await import(JS + '/weather/pin-toggle.js');
        const html = pin.pinToggleHTML({});
        console.log(JSON.stringify({ hasEmptyId: html.includes('data-id=""') }));
        """
    )
    assert out["hasEmptyId"] is True


def test_clicking_the_button_posts_to_the_pin_endpoint_and_flips_state():
    # apiPost is a live ES-module binding (read-only from outside), so it
    # can't be monkeypatched the way a plain object method could. Stub
    # globalThis.fetch instead — the same seam the shared _STUB already
    # uses to keep every test network-free — and let apiPost's own
    # _request() run for real against it.
    out = _js(
        """
        const calls = [];
        globalThis.fetch = async (url, init) => {
          calls.push({ url, init });
          const body = init && init.body ? JSON.parse(init.body) : {};
          return {
            ok: true,
            headers: { get: () => 'application/json' },
            json: async () => ({ ok: true, pinned: body.pinned }),
          };
        };
        const pin = await import(JS + '/weather/pin-toggle.js');

        const listeners = [];
        const btn = {
          dataset: { id: 's9', pinned: 'false' },
          disabled: false,
          classList: { toggle(name, on) { this[name] = !!on; } },
          setAttribute(k, v) { this[k] = v; },
          addEventListener(_type, fn) { listeners.push(fn); },
        };
        const wrap = { querySelectorAll: (sel) => (sel === '.mmc-pin' ? [btn] : []) };
        pin.bindPinToggle(wrap);
        // The click handler fires _togglePin without returning its promise
        // (a real DOM 'click' listener can't be awaited by its dispatcher
        // either), so flush a macrotask to let the fire-and-forget async
        // function's own awaits (apiPost → the stubbed fetch) settle.
        listeners[0]({ stopPropagation() {} });
        await new Promise((resolve) => setTimeout(resolve, 0));

        console.log(JSON.stringify({
          url: calls[0] && calls[0].url,
          sentPinned: calls[0] && JSON.parse(calls[0].init.body).pinned,
          nowPinned: btn.dataset.pinned,
          ariaPressed: btn['aria-pressed'],
        }));
        """
    )
    assert out["url"] == '/api/weather/sightings/s9/pin'
    assert out["sentPinned"] is True
    assert out["nowPinned"] == 'true'
    assert out["ariaPressed"] == 'true'


def test_bind_pin_toggle_tolerates_a_container_with_no_pin_buttons():
    out = _js(
        """
        const pin = await import(JS + '/weather/pin-toggle.js');
        let threw = false;
        try {
          pin.bindPinToggle({ querySelectorAll: () => [] });
        } catch {
          threw = true;
        }
        console.log(JSON.stringify({ threw }));
        """
    )
    assert out["threw"] is False
