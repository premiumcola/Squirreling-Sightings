"""weather/pin-toggle.js — the standalone "keep forever" card button.

Built as an isolated module (a sibling change was in flight on
_feed.js/sightings.js at the time) so most of its own behaviour is
tested here directly rather than piggybacking on test_weather_feed.py's
harness. Same real-JS-under-node approach: pinToggleHTML is a pure
string builder, bindPinToggle wires real DOM events, and the network
call is stubbed via a fake fetch so no request ever leaves the process.

The module is now wired in (sightingCardHTML embeds pinToggleHTML;
_renderWeatherGrid calls bindPinToggle right after grid.innerHTML lands)
— the two tests at the bottom of this file pin that the wiring actually
happened, since a card that silently drops its own pin button, or a
grid that never binds the click, would look identical to "not built yet"
from the outside.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_JS_ROOT = Path(__file__).resolve().parents[1] / "web" / "static" / "js"


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


# ── wiring: the pin button actually reaches a real sighting card ────────


def test_sighting_card_html_embeds_the_pin_toggle():
    out = _js(
        """
        const feed = await import(JS + '/weather/_feed.js');
        const html = feed.sightingCardHTML(
          { id: 's7', event_type: 'fog', started_at: '2026-08-29T08:00:00', pinned: true },
          0,
          true,
        );
        console.log(JSON.stringify({
          hasPinBtn: html.includes('mmc-pin'),
          hasIsPinned: html.includes('is-pinned'),
          hasDeleteBtn: html.includes('mmc-delete'),
        }));
        """
    )
    assert out == {"hasPinBtn": True, "hasIsPinned": True, "hasDeleteBtn": True}


def test_library_page_binds_the_pin_toggle_after_the_grid_renders():
    """A static source check, not an executed one — the merged grid's
    paint step pulls in the whole library/weather module graph (apiGet,
    state, the storms package…), too much to stand up here just to prove
    one call site exists. Mirrors test_netz_tuning_frontend_wiring.py's
    approach to the same kind of "did the wiring survive" question.

    Stage 6 moved sightings.js's own grid painter (and its
    bindPinToggle(grid) call) into library/page.js's _paint() +
    library/_bind.js::bindLibraryGrid — the merged grid is now the one
    place any weather card (sighting/recap/manual/episode) renders."""
    page_src = (_JS_ROOT / "library" / "page.js").read_text(encoding="utf-8")
    body = page_src[page_src.index("function _paint") :]
    body = body[: body.index("\n}\n")]
    assert "renderLibraryGrid(grid" in body
    assert "bindLibraryGrid(grid" in body
    assert body.index("renderLibraryGrid(grid") < body.index("bindLibraryGrid(grid"), (
        "bindLibraryGrid must run AFTER the card HTML has actually " "landed in the DOM"
    )
    bind_src = (_JS_ROOT / "library" / "_bind.js").read_text(encoding="utf-8")
    assert "bindPinToggle } from '../weather/pin-toggle.js'" in bind_src
    assert "bindPinToggle(grid)" in bind_src
