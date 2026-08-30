"""The live-detect overlays paint only classes the camera looks for.

The detector reports COCO's ~80 classes. On these cameras that means
bench / chair / umbrella / bowl on nearly every tick — 160 bench hits in
60 s on one of them. Two separate renderers drew them:

  * the bbox layer stacked "⊘ bench · 35 % · gefiltert" plates over the
    actual subject, and
  * the TRAIL layer, worse, groups a trackless detection by LABEL — so two
    unrelated bench hits at opposite edges of the frame became one white
    polyline drawn diagonally across the whole picture.

Both now ask `live-detect-classfilter.js`, which reads the camera's own
`object_filter` — the same source the Detections panel and the swimlane
already used. One predicate, not three that drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "mediaview"
_BBOX = (_JS_DIR / "live-detect-bbox.js").read_text(encoding="utf-8")
_OVERLAYS = (_JS_DIR / "live-detect-overlays.js").read_text(encoding="utf-8")

_SETUP = """
  const mod = await import(JS + '/mediaview/live-detect-classfilter.js');
  const { S } = await import(JS + '/mediaview/live-detect-state.js');
  const { state } = await import(JS + '/core/state.js');
  S.session = { camId: 'cam_a' };
"""


def test_a_configured_filter_keeps_only_its_own_classes():
    out = _js(
        f"""
        {_SETUP}
        state.cameras = [{{ id: 'cam_a', object_filter: ['person', 'cat'] }}];
        console.log(JSON.stringify({{
          person: mod.keepsLabel('person'),
          cat: mod.keepsLabel('cat'),
          bench: mod.keepsLabel('bench'),
          umbrella: mod.keepsLabel('umbrella'),
        }}));
        """
    )
    assert out == {"person": True, "cat": True, "bench": False, "umbrella": False}


@pytest.mark.parametrize("filt", ["[]", "null", "undefined"])
def test_no_configured_filter_means_no_restriction(filt):
    """An empty filter is "nothing configured", not "show nothing" — a
    camera with no filter must not go blank."""
    out = _js(
        f"""
        {_SETUP}
        state.cameras = [{{ id: 'cam_a', object_filter: {filt} }}];
        console.log(JSON.stringify({{
          bench: mod.keepsLabel('bench'),
          person: mod.keepsLabel('person'),
          set: mod.paintableLabels(),
        }}));
        """
    )
    assert out["bench"] is True
    assert out["person"] is True
    assert out["set"] is None


def test_an_unknown_camera_restricts_nothing():
    out = _js(
        f"""
        {_SETUP}
        state.cameras = [{{ id: 'someone_else', object_filter: ['person'] }}];
        console.log(JSON.stringify(mod.keepsLabel('bench')));
        """
    )
    assert out is True


def test_both_renderers_use_the_shared_predicate():
    """THE anti-drift guard. If either renderer grows its own copy again,
    one of them will quietly start painting benches after the next edit."""
    for name, src in (("bbox", _BBOX), ("trails", _OVERLAYS)):
        assert "live-detect-classfilter.js" in src, f"{name} renderer bypasses the shared filter"
        assert "paintableLabels(" in src, f"{name} renderer never calls the filter"


def test_the_trail_grouping_is_gated_before_the_label_bucket():
    """The gate has to sit BEFORE the `m:<label>` grouping — filtering
    afterwards would still build the cross-frame polyline and merely hide
    part of it."""
    grouping = _OVERLAYS.index("const byTrack = new Map();")
    gate = _OVERLAYS.index("const want = paintableLabels();")
    assert gate < grouping, "the trail layer filters after grouping, which is too late"


def test_only_tracked_detections_get_a_trail():
    """A trail claims "this ONE object went here, then here". A detection
    with no track number has no such history, and the old label-grouping
    fallback invented one: on a 2x2-tiled camera the detector emits several
    independent person/cat boxes per tick at opposite corners, and joining
    them by label drew dozens of lines across the picture."""
    assert "`m:${e.label}`" not in _OVERLAYS, "trackless detections are grouped into a trail again"
    assert "if (!Number.isFinite(e.track_num) || e.track_num <= 0) continue;" in _OVERLAYS
