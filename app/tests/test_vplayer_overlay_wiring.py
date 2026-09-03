"""Guard that the vplayer's overlay layers are actually fed.

Source-text pins, the same idiom test_vplayer_shell_markup.py uses: the
wiring is a handful of call sites in one composition function, and
reading them is the cheapest way to assert they exist without a browser.

WHAT SHIPPED, AND WHY A UNIT TEST COULD NOT SEE IT. Every part of the
overlay worked. _stage.js built three layer hosts, _overlay-svg.js could
paint boxes, canvas/zone-layer.js could paint polygons, and
_overlay-row.js rendered four switches that flipped their own
aria-pressed and persisted the choice. Nothing connected them. A recorded
clip painted into none of the three layers, and the switches were mounted
with no onChange at all — so every one of those modules passed its own
tests while the operator saw: "die buttons zur anwahl … haben keine
funktion … bbox oder zones seh ich alles nicht".

That is a wiring defect, and wiring is what this file pins:

  · THE SWITCHES REACH THE PAINTER. mountOverlayRow without an onChange
    is the exact shape that shipped — a control whose only effect is on
    its own attribute.

  · THE RECORDED SIDECAR REACHES THE PAINTER. Without setTracks the box
    layer has nothing to draw for a recorded clip, however the switches
    are set.

  · THE PLAYHEAD REPAINTS. An interpolated box only moves if something
    tells it the time changed; without this it would freeze at t=0,
    which for most clips means "no boxes at all", the same symptom
    again.

  · ONE PAINTER, NOT TWO. index.js used to call renderBoxLayer directly
    on the live path, which is how the simulation's own bbox switch also
    had nothing to switch. Importing the low-level painter here again
    would rebuild that second path.

  · IT IS TORN DOWN. The painter holds a stage refit subscription; a
    leaked one repaints into a stage that is gone.
"""

from __future__ import annotations

from pathlib import Path

_JS = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js" / "vplayer"
_INDEX = _JS / "index.js"
_PAINT = _JS / "_overlay-paint.js"


def _index() -> str:
    return _INDEX.read_text(encoding="utf-8")


def test_the_overlay_switches_reach_the_painter() -> None:
    src = _index()
    assert "mountOverlayRow(" in src, "the overlay row is no longer mounted"
    assert "onChange:" in src, (
        "mountOverlayRow is mounted without an onChange — that is exactly the "
        "state that shipped: four switches whose only effect was on their own "
        "aria-pressed attribute"
    )
    assert "setLayers" in src, "onChange must push the new layer state into the painter"


def test_the_recorded_sidecar_reaches_the_painter() -> None:
    src = _index()
    assert "setTracks(" in src, (
        "the recorded path never hands the sidecar to the painter, so the box "
        "layer has nothing to draw however the switches are set"
    )


def test_the_playhead_repaints_the_overlay() -> None:
    src = _index()
    assert "repaintAt(" in src, (
        "nothing repaints the overlay as the clip plays — an interpolated box "
        "would freeze at t=0, which for most clips means no box at all"
    )


def test_there_is_only_one_painter() -> None:
    src = _index()
    assert "renderBoxLayer" not in src, (
        "index.js paints a layer directly again. Every paint goes through "
        "_overlay-paint.js, which is what holds the operator's toggle state — "
        "a direct call is how the live surface's own bbox switch ended up "
        "with nothing to switch"
    )
    assert "mountOverlayPainter" in src


def test_the_painter_is_torn_down() -> None:
    src = _index()
    assert "overlays?.teardown()" in src, (
        "the painter subscribes to stage refits; a leaked subscription "
        "repaints into a stage that has been removed"
    )


def test_the_painter_never_solves_the_letterbox_a_second_time() -> None:
    # _stage.js already pins every layer host to the picture rect, so the
    # painter's canvas fit rect is the whole box. A containRect call here
    # would be the second, slightly different letterbox solve that puts a
    # box half a gutter off its subject — the failure core/box-model.js's
    # header lists as independently rediscovered three times.
    src = _PAINT.read_text(encoding="utf-8")
    assert "containRect" not in src
    assert "fittedRect" not in src
