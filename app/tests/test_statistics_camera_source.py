"""The Statistik charts must not depend on load order.

Reported: "Events pro Kamera · letzter Monat" and "Letzte 24h ·
Aktivität nach Stunde" both showed nothing, while the cards beside them
("Heute / Diese Woche / Dieser Monat", "Top Erkennungen") showed real
numbers from the SAME `/api/timeline` response.

Cause: the two empty charts iterated `state.cameras`, the other two
iterated the response. `statistics.js` hydrates on its own
IntersectionObserver, so scrolling to Statistik before `loadAll()`
populated `state.cameras` rendered "Keine Ereignisse" over a payload
full of events. Exactly the load-order trap that also left the
Erkennungsprofil reading "Keine Kamera konfiguriert"
(test_netz_first_paint.py).

The list is now the union of the configured cameras and the ids present
in the data, so a late `state.cameras` can no longer empty a chart — and
a camera deleted after its events were recorded still contributes them.
"""

from __future__ import annotations

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_SETUP = """
  const mod = await import(JS + '/statistics.js');
  const { state } = await import(JS + '/core/state.js');
"""


def test_the_charts_survive_an_empty_camera_list():
    """THE regression: data present, `state.cameras` not yet loaded."""
    out = _js(
        _SETUP
        + """
        state.cameras = [];
        const month = { tracks: [{ camera_id: 'cam_a', points: [{}, {}, {}] }], merged: [] };
        const day = { tracks: [], merged: [] };
        console.log(JSON.stringify(mod._camerasFromData(month, day).map((c) => c.id)));
        """
    )
    assert out == ["cam_a"], "an unloaded camera list still empties the chart"


def test_configured_cameras_keep_their_name_and_come_first():
    out = _js(
        _SETUP
        + """
        state.cameras = [{ id: 'cam_a', name: 'Werkstatt' }];
        const month = { tracks: [{ camera_id: 'cam_b', points: [{}] }] };
        const cams = mod._camerasFromData(month);
        console.log(JSON.stringify(cams.map((c) => [c.id, c.name])));
        """
    )
    assert out == [["cam_a", "Werkstatt"], ["cam_b", "cam_b"]]


def test_a_camera_is_never_listed_twice():
    """It appears in both the config and the data on every normal run."""
    out = _js(
        _SETUP
        + """
        state.cameras = [{ id: 'cam_a', name: 'Werkstatt' }];
        const month = { tracks: [{ camera_id: 'cam_a', points: [{}] }] };
        const day = { tracks: [{ camera_id: 'cam_a', points: [{}] }] };
        console.log(JSON.stringify(mod._camerasFromData(month, day).map((c) => c.id)));
        """
    )
    assert out == ["cam_a"]


def test_the_payloads_name_is_used_when_the_camera_list_is_late():
    """The reported defect: raw ids in the donut legend and the heatmap.

    `state.cameras` is three serial requests away, the panel renders on an
    IntersectionObserver long before they land, and it never re-renders.
    /api/timeline now ships `camera_name`, which is the only name this
    panel can rely on having.
    """
    out = _js(
        _SETUP
        + """
        state.cameras = [];
        const month = { tracks: [
          { camera_id: 'reolink_cx810_gartendachterrasse_181',
            camera_name: "Garten 'Dach Terrasse'", points: [{}] },
        ] };
        console.log(JSON.stringify(mod._camerasFromData(month).map((c) => c.name)));
        """
    )
    assert out == ["Garten 'Dach Terrasse'"]


def test_a_nameless_camera_is_shortened_not_printed_whole():
    """The operator's fallback: a short form, with the icon carrying the rest.

    A raw id is ~36 characters of one unbreakable token. Printed whole it
    inflated the card's grid track to 462 px inside a 351 px section and
    took the percentage column off the right of a 375 px screen.
    """
    out = _js(
        """
        const { camLabel } = await import(JS + '/core/icons.js');
        console.log(JSON.stringify([
          camLabel({ id: 'reolink_cx810_gartendachterrasse_181',
                     name: 'reolink_cx810_gartendachterrasse_181' }),
          camLabel({ id: 'reolink_rlc810a_garten_51', name: 'Garten Nord' }),
          camLabel({ id: 'cam_a', name: 'cam_a' }),
          camLabel({}),
        ]));
        """
    )
    assert out == ["Gartendachterrasse", "Garten Nord", "cam_a", ""]


def test_a_missing_or_malformed_payload_does_not_throw():
    out = _js(
        _SETUP
        + """
        state.cameras = [];
        let threw = false;
        let n = -1;
        try {
          n = mod._camerasFromData(undefined, {}, { tracks: null }, { tracks: [{}] }).length;
        } catch {
          threw = true;
        }
        console.log(JSON.stringify({ threw, n }));
        """
    )
    assert out == {"threw": False, "n": 0}
