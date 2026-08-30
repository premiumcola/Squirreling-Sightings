"""`mask_zones.filter_zoned` — the gate that can silence an armed camera.

This module had ZERO test coverage while being the last thing standing
between a detected intruder and an alert. What prompted these tests: a
Werkstatt snapshot showed `person 87%` logged as "outside applicable
zones" on every single tick, with a zone configured and the person
plainly inside it on screen.

The mechanism reproduced below is a TOTAL BLACKOUT, and it is silent:
the prebaked raster says "inside", so `global_applies` is True and the
"no zone targets this label" escape is disabled — but the polygon
bucket list the runtime re-looks-the-match up in is empty, so nothing
can ever match and every detection is dropped. Loud in the log, invisible
in the UI, and the zone still renders correctly in the editor.

Whether THIS is what silenced Werkstatt is not established here (the
stored zones live on the Unraid host, not in the checkout) — but it is a
real defect either way, and these tests are the net that was missing.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import mask_zones

CAM = "cam_werkstatt"
FRAME_W, FRAME_H = 2560, 1440
# A zone drawn in the 960x540 editor covering the lower-left quadrant.
_PTS = [{"x": 0, "y": 200}, {"x": 600, "y": 200}, {"x": 600, "y": 540}, {"x": 0, "y": 540}]


class _Det:
    """Only what filter_zoned touches."""

    def __init__(self, label="person", score=0.87, bbox=(300, 700, 492, 1172)):
        self.label = label
        self.score = score
        self.bbox = bbox
        self.zone_flags = None


def _frame():
    return np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)


def _run(zones):
    """filter_zoned against a raster built from the same zone list, which
    is exactly how the runtime calls it."""
    img = mask_zones.build_zone_image(zones)
    return mask_zones.filter_zoned([_Det()], _frame(), zones, img, camera_id=CAM)


def _stamped(**extra):
    return [{"points": _PTS, "source_w": 960, "source_h": 540, **extra}]


# ── the shape that works, pinned so the rest means something ──────────────


def test_a_normal_stamped_zone_keeps_a_detection_inside_it():
    assert len(_run(_stamped())) == 1


def test_a_detection_outside_the_zone_is_still_dropped():
    """The gate must keep GATING — a fix that keeps everything is not a
    fix, it is a disabled zone."""
    zones = _stamped()
    img = mask_zones.build_zone_image(zones)
    far = _Det(bbox=(2300, 60, 2500, 240))  # top-right, outside the polygon
    assert mask_zones.filter_zoned([far], _frame(), zones, img, camera_id=CAM) == []


# ── the blackout family ───────────────────────────────────────────────────


def test_a_legacy_bare_list_zone_does_not_reject_everything():
    """THE regression test. Zones saved before 2026-04-22 are a bare list
    of points with no dict wrapper, and no migration ever converted them.
    Before the fix this dropped 100 % of detections at every position."""
    assert len(_run([_PTS])) == 1, "a legacy bare-list zone silences the whole camera"


def test_a_bare_list_zone_still_rejects_what_is_genuinely_outside():
    zones = [_PTS]
    img = mask_zones.build_zone_image(zones)
    far = _Det(bbox=(2300, 60, 2500, 240))
    assert mask_zones.filter_zoned([far], _frame(), zones, img, camera_id=CAM) == []


@pytest.mark.parametrize(
    "zone",
    [
        {"points": []},
        {"points": [{"x": 0, "y": 0}]},
        {"points": [{"x": 0, "y": 0}, {"x": 10, "y": 10}]},
    ],
    ids=["no-points", "one-point", "two-points"],
)
def test_a_degenerate_zone_does_not_silently_arm_an_empty_gate(zone):
    """A zone with fewer than 3 points cannot be filled, so the raster is
    all-zero — but it is not None, which used to leave `global_applies`
    True and drop everything. A polygon that cannot be evaluated must not
    be treated as a polygon that excludes the whole frame."""
    kept = _run([zone])
    assert len(kept) == 1, "an unusable zone blacked out the whole camera"


def test_a_point_list_pair_shape_does_not_crash_the_alarm_path():
    """`[x, y]` pairs are documented as an accepted point shape, but
    reached `p.get('x')` and raised AttributeError from inside
    build_zone_image — an uncaught crash on the alarm path."""
    pairs = [[0, 200], [600, 200], [600, 540], [0, 540]]
    img = mask_zones.build_zone_image([{"points": pairs, "source_w": 960, "source_h": 540}])
    assert img is not None


# ── label scoping must survive the normalisation ──────────────────────────


def test_a_zone_scoped_to_another_class_does_not_gate_this_one():
    """A zone that targets only `cat` must leave a person alone entirely,
    rather than being treated as a global zone the person falls outside."""
    zones = [{"points": _PTS, "source_w": 960, "source_h": 540, "labels": ["cat"]}]
    assert len(_run(zones)) == 1


def test_a_zone_scoped_to_this_class_still_gates_it():
    zones = [{"points": _PTS, "source_w": 960, "source_h": 540, "labels": ["person"]}]
    img = mask_zones.build_zone_image(zones)
    far = _Det(bbox=(2300, 60, 2500, 240))
    assert mask_zones.filter_zoned([far], _frame(), zones, img, camera_id=CAM) == []
    assert len(_run(zones)) == 1


def test_no_zones_configured_keeps_everything():
    assert len(mask_zones.filter_zoned([_Det()], _frame(), [], None, camera_id=CAM)) == 1
