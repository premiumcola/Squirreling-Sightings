"""The per-class Meldeschwelle — and the reachability contract.

This file exists because of a regression shipped earlier the same day:
the Erkennungsprofil's SECOND radar (the per-class one) was removed on
request — "ich will nicht zwei Netze" — and its values were demoted to a
read-only text line. That deleted the only control in the entire GUI
capable of moving a class's alert threshold. ``patchAxes`` in
``netz/_api.js`` was left with zero callers while
``PATCH /api/netz/<cam>/axes`` stayed live and fully functional.

The operator found it the way anyone would: they went looking for the
person threshold to fix a camera that never alerted, and it wasn't there.

The rows are gone again, but UPWARDS this time: „die Meldeschwelle muss
ja ins Netz mit rein". Each class is now a spoke on the ONE net, in its
own colour group, dragged by the same pointer layer as the camera-wide
axes — and still saved through ``patchAxes``, because that route is also
what writes the net-archive record.

The module keeps its filename. Renaming ``_class_rows.js`` (and this
file with it) would be a wide, purely cosmetic diff for zero behavioural
gain — the same call ``netz.html`` documents for its own ``netz*``
identifiers.

The last test below pins the property that actually matters — every
write endpoint the Netz exposes must have a live caller. A route nobody
can reach is indistinguishable from a broken feature.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js"


def _read(rel: str) -> str:
    return (_JS / rel).read_text(encoding="utf-8")


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_a_class_becomes_a_draggable_axis_seeded_with_the_current_e():
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const axes = cr.buildClassAxes({
          axes: [{ label: 'person', E: 50, push: 0.85, push_enabled: true }],
        });
        console.log(JSON.stringify({
          n: axes.length,
          key: axes[0].key,
          e: axes[0].E,
          group: axes[0].group,
          de: axes[0].label,
          display: axes[0].display,
          locked: axes[0].locked,
        }));
        """
    )
    assert out == {
        "n": 1,
        "key": "cls:person",
        "e": 50,
        "group": "meldung",
        "de": "Person",
        "display": "85 %",
        "locked": False,
    }


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_a_class_that_never_pushes_is_drawn_but_not_draggable():
    """`push_enabled: false` means the class cannot alert at all. A
    draggable spoke there would promise a threshold that is not consulted;
    dropping the spoke would hide that the camera is mute for the class.
    So: drawn, greyed, locked, and reading "aus"."""
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const [a] = cr.buildClassAxes({
          axes: [{ label: 'cat', E: 50, push: 0.8, push_enabled: false }],
        });
        const radar = await import(JS + '/netz/_tune_radar.js');
        const svg = radar.renderTuneRadar({ axes: [a, { ...a, key: 'x', locked: false }] });
        console.log(JSON.stringify({
          locked: a.locked,
          display: a.display,
          // the 44 px grab disc must not exist for the locked axis
          grabbable: svg.includes('data-tune-axis="cls:cat"><circle class="netz-tune-halo"'),
          drawn: svg.includes('data-tune-axis-label="cls:cat"'),
        }));
        """
    )
    assert out["locked"] is True
    assert out["display"] == "aus"
    assert out["grabbable"] is False, "a muted class still offers a drag handle"
    assert out["drawn"] is True, "the muted class vanished from the net entirely"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_printed_percentage_matches_the_shared_mapping():
    """The axis must print what the SERVER will compute, so it goes through
    the same pushFor() mirror the radar uses (pinned bit-for-bit against
    Python by test_netz_mapping_mirror.py) rather than its own formula."""
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const m = await import(JS + '/netz/_mapping.js');
        const e = 75;
        const spec = cr.classAxisSpec('cls:person');
        console.log(JSON.stringify({
          mapped: Math.round(m.pushFor('person', e) * 100),
          fromSpec: spec.fmt(e),
        }));
        """
    )
    # E=75 is the value that takes person from the 0.85 default to ~0.70.
    assert out["mapped"] == 70
    assert out["fromSpec"] == "70 %"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_class_spec_round_trips_e_through_the_shared_drag_maths():
    """The class axes reuse the settings radar's pointer layer, which means
    tuneRawFromE must hand back the dragged E untouched. If min/max/invert
    ever drift, a drag would save a different number than the one under
    the finger — silently, because both are integers."""
    out = _js(
        """
        const cr = await import(JS + '/netz/_class_rows.js');
        const sa = await import(JS + '/netz/_settings_axes.js');
        const spec = cr.classAxisSpec('cls:squirrel');
        console.log(JSON.stringify(
          [0, 17, 50, 83, 100].map((e) => sa.tuneRawFromE(spec, e)),
        ));
        """
    )
    assert out == [0, 17, 50, 83, 100]


def test_the_class_module_writes_through_the_axes_endpoint():
    """A source check: the class axes must PATCH the axes route, which is
    also what writes the net-archive record. Saving them through the
    camera-tuning route instead would silently skip that history."""
    src = _read("netz/_class_rows.js")
    assert "patchAxes(" in src, "the class axes must save through patchAxes"
    assert "patchTuning(" not in src, "the camera-tuning route skips the net archive"


def test_the_card_renders_the_class_axes_on_the_same_net():
    """The module can be perfect and still be unreachable — that is exactly
    how the original regression happened. And it must be ONE radar: a
    second renderTuneRadar call on a card is the rejected two-net layout
    coming back."""
    src = _read("netz/_cards.js")
    assert "buildClassAxes(" in src, "the card never puts the class axes on the net"
    assert src.count("renderTuneRadar(") == 1, "a card is drawing more than one net"


def test_the_drag_layer_commits_a_class_axis_instead_of_staging_it():
    """Two save paths on one net. A class axis that joined the staging bar
    would be written through patchTuning by „Übernehmen" — the route that
    skips the archive — instead of through patchAxes."""
    src = _read("netz/_tune_drag.js")
    assert "isClassAxisKey(" in src
    assert "saveClassAxis(" in src
    assert "resetClassAxis(" in src, "long-press must unpin, not just set E=50"


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
