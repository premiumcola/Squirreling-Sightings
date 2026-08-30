"""The per-class Meldeschwelle rows — and the reachability contract.

This file exists because of a regression I shipped earlier the same day:
the Erkennungsprofil's SECOND radar (the per-class one) was removed on
request — "ich will nicht zwei Netze" — and its values were demoted to a
read-only text line. That deleted the only control in the entire GUI
capable of moving a class's alert threshold. ``patchAxes`` in
``netz/_api.js`` was left with zero callers while
``PATCH /api/netz/<cam>/axes`` stayed live and fully functional.

The operator found it the way anyone would: they went looking for the
person threshold to fix a camera that never alerted, and it wasn't there.

So the rows are editable again (text-shaped, one slider each), and the
last test below pins the property that actually matters — every write
endpoint the Netz exposes must have a live caller. A route nobody can
reach is indistinguishable from a broken feature.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js"


def _read(rel: str) -> str:
    return (_JS / rel).read_text(encoding="utf-8")


def test_a_class_row_renders_a_slider_seeded_with_the_current_e():
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const html = cr.classRowsHtml({
          axes: [{ label: 'person', E: 50, push: 0.85, push_enabled: true }],
        });
        console.log(JSON.stringify({
          hasSlider: html.includes('netz-cls-slider'),
          seededE: html.includes('value="50"'),
          showsPct: html.includes('85 %'),
          carriesLabel: html.includes('data-cls="person"'),
        }));
        """
    )
    assert out == {"hasSlider": True, "seededE": True, "showsPct": True, "carriesLabel": True}


def test_a_class_that_never_pushes_shows_no_slider():
    """`push_enabled: false` means the class cannot alert at all. A slider
    there would promise a threshold that is not consulted."""
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const html = cr.classRowsHtml({
          axes: [{ label: 'person', E: 50, push: 0.85, push_enabled: false }],
        });
        console.log(JSON.stringify({
          hasSlider: html.includes('netz-cls-slider'),
          saysOff: html.includes('aus'),
        }));
        """
    )
    assert out["hasSlider"] is False
    assert out["saysOff"] is True


def test_the_printed_percentage_matches_the_shared_mapping():
    """The row must print what the SERVER will compute, so it goes through
    the same pushFor() mirror the radar uses (pinned bit-for-bit against
    Python by test_netz_mapping_mirror.py) rather than its own formula."""
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const m = await import(JS + '/netz/_mapping.js');
        const e = 75;
        const html = cr.classRowsHtml({
          axes: [{ label: 'person', E: e, push: m.pushFor('person', e), push_enabled: true }],
        });
        console.log(JSON.stringify({
          mapped: Math.round(m.pushFor('person', e) * 100),
          inHtml: html.includes(Math.round(m.pushFor('person', e) * 100) + ' %'),
        }));
        """
    )
    # E=75 is the value that takes person from the 0.85 default to ~0.70.
    assert out["mapped"] == 70
    assert out["inHtml"] is True


def test_the_row_module_writes_through_the_axes_endpoint():
    """A source check: the rows must PATCH the axes route, which is also
    what writes the net-archive record. Saving them through the
    camera-tuning route instead would silently skip that history."""
    src = _read("netz/_class_rows.js")
    assert "patchAxes" in src, "the class rows must save through patchAxes"
    assert "patchTuning" not in src, "the camera-tuning route skips the net archive"


def test_the_card_renders_and_binds_the_class_rows():
    """The module can be perfect and still be unreachable — that is exactly
    how the original regression happened."""
    src = _read("netz/_cards.js")
    assert "classRowsHtml(" in src, "the card never renders the rows"
    assert "bindClassRows(" in src, "the rows render but nothing wires the slider"


def test_every_netz_write_endpoint_has_a_live_caller():
    """THE anti-recurrence test.

    `patchAxes` sat with zero callers while its route stayed live. Assert
    that every exported writer in `netz/_api.js` is called from somewhere
    other than its own definition — a helper nobody invokes is a feature
    the operator cannot reach.
    """
    api_src = _read("netz/_api.js")
    writers = set(re.findall(r"export function (patch\w+|post\w+|delete\w+)\(", api_src))
    assert writers, "no writer helpers found — has _api.js been restructured?"
    others = [
        p.read_text(encoding="utf-8")
        for p in sorted((_JS / "netz").glob("*.js"))
        if p.name != "_api.js"
    ]
    unreachable = [w for w in sorted(writers) if not any(f"{w}(" in src for src in others)]
    assert not unreachable, (
        f"these Netz write helpers have no caller: {unreachable} — "
        "the route is live but nothing in the UI can reach it"
    )
