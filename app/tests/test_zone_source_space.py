"""Stamping the drawing canvas onto zones that never recorded one.

`mask_zones.point_in_poly` scales a detection's centre into the polygon's
own coordinate space via `source_w`/`source_h`. A polygon drawn before
that stamp existed falls back to the hard-coded 1280x720 canvas — but the
real Werkstatt zone tops out at 636x356, i.e. it was drawn at 640x360.
The gate therefore probed y=468 against a polygon ending at y=356 and
rejected every person in the lower part of the frame as "outside
applicable zones". A security camera that saw a person at 87 % and never
reported it.

The numbers below are the REAL stored zone and the REAL logged detection
centres from that camera, so this file is the repro as much as the guard.
"""

from __future__ import annotations

import numpy as np
import pytest

from app import mask_zones
from app.settings.migrations import _infer_zone_canvas, migrate_zone_source_space

# Verbatim from storage/settings.json.
WERKSTATT_POINTS = [
    {"x": 3, "y": 133},
    {"x": 144, "y": 89},
    {"x": 213, "y": 100},
    {"x": 307, "y": 76},
    {"x": 469, "y": 25},
    {"x": 542, "y": 1},
    {"x": 636, "y": 1},
    {"x": 634, "y": 356},
    {"x": 2, "y": 356},
]
FRAME_W, FRAME_H = 2560, 1440


def _zone(**extra):
    return {"label": "Zone 1", "points": WERKSTATT_POINTS, **extra}


def test_the_canvas_is_inferred_from_the_points():
    pts = [(p["x"], p["y"]) for p in WERKSTATT_POINTS]
    assert _infer_zone_canvas(pts) == (640, 360)


def test_the_migration_stamps_an_unstamped_zone():
    data = {"cameras": [{"id": "werkstatt", "zones": [_zone()]}]}
    migrate_zone_source_space(data)
    z = data["cameras"][0]["zones"][0]
    assert (z["source_w"], z["source_h"]) == (640, 360)


def test_an_already_stamped_zone_is_left_alone():
    """Someone else's correct value is not ours to re-guess."""
    data = {"cameras": [{"id": "c", "zones": [_zone(source_w=960, source_h=540)]}]}
    migrate_zone_source_space(data)
    z = data["cameras"][0]["zones"][0]
    assert (z["source_w"], z["source_h"]) == (960, 540)


def test_the_migration_is_idempotent():
    data = {"cameras": [{"id": "c", "zones": [_zone()]}]}
    migrate_zone_source_space(data)
    once = dict(data["cameras"][0]["zones"][0])
    migrate_zone_source_space(data)
    assert data["cameras"][0]["zones"][0] == once


def test_masks_are_stamped_too():
    """Masks run through the same scaling path — an unstamped mask
    suppresses the wrong region just as silently."""
    data = {"cameras": [{"id": "c", "masks": [_zone()]}]}
    migrate_zone_source_space(data)
    assert data["cameras"][0]["masks"][0]["source_w"] == 640


# ── the actual behavioural claim ──────────────────────────────────────────


class _Det:
    def __init__(self, bbox):
        self.label = "person"
        self.score = 0.87
        self.bbox = bbox
        self.zone_flags = None


def _kept(zone, bbox):
    zones = [zone]
    img = mask_zones.build_zone_image(zones)
    frame = np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)
    return len(mask_zones.filter_zoned([_Det(bbox)], frame, zones, img, camera_id="werkstatt"))


# The two 86/87 % person centres from the live log were (396,936) and
# (404,940); a bbox spanning 700..1172 has its centre at 936.
PERSON_BBOX = (300, 700, 492, 1172)
# The 21 % detection in the top-right corner, which is genuinely outside.
CORNER_BBOX = (700, 20, 796, 76)


def test_the_person_is_rejected_before_the_stamp():
    """THE bug, reproduced: unstamped, the gate probes 1280x720 space."""
    assert _kept(_zone(), PERSON_BBOX) == 0


def test_the_person_survives_after_the_stamp():
    data = {"cameras": [{"id": "werkstatt", "zones": [_zone()]}]}
    migrate_zone_source_space(data)
    assert _kept(data["cameras"][0]["zones"][0], PERSON_BBOX) == 1


def test_the_stamp_does_not_simply_open_the_gate():
    """A repair that lets everything through would be worse than the bug —
    the corner detection must still be rejected."""
    data = {"cameras": [{"id": "werkstatt", "zones": [_zone()]}]}
    migrate_zone_source_space(data)
    assert _kept(data["cameras"][0]["zones"][0], CORNER_BBOX) == 0


@pytest.mark.parametrize(
    "points,expected",
    [
        ([(0, 0), (639, 359)], (640, 360)),
        ([(0, 0), (700, 400)], (960, 540)),
        ([(0, 0), (1000, 600)], (1280, 720)),
        ([(0, 0), (99999, 99999)], None),
    ],
)
def test_the_inference_picks_the_smallest_canvas_that_fits(points, expected):
    assert _infer_zone_canvas(points) == expected
