"""Every Erkennungsprofil axis must be READ by something that runs.

``test_netz_tuning_frontend_wiring.py`` pins one half of the contract:
the key the chart draws is the key the PATCH route accepts and the key
``net_state`` sends back. That half was green on the day
``track_block_contain`` shipped — and the axis was still dead. The UI
wrote it, the route validated it, ``upsert_camera`` persisted it, the
response echoed it back under ``"effective"`` so the panel confirmed the
new value was active, and not one line of the detection pipeline ever
looked at it. The operator was promised "innen = streng zusammenfassen
(Gesicht + Körper = eine Person)" by a slider wired to nothing.

This file pins the OTHER half: the consumer. A source scan, in keeping
with the other static-assertion tests here — importing every runtime
module and diffing behaviour per axis would need a camera, a detector
and a frame, and would still not prove more than "somebody read it".

Two levels:

* every spoke is read somewhere under ``_RUNTIME_ROOTS`` — the modules
  that decide what the cameras actually do, as opposed to the
  declare / validate / persist / echo layer the other file covers;
* the tracker group additionally has to LAND: resolved by
  ``resolve_track_thresholds`` into a named field and pushed onto the
  LiveTracker by ``configure()``, which is the exact path
  ``routes/cameras.py`` live-applies on.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.tracker_core import LiveTracker, resolve_track_thresholds

_APP = Path(__file__).resolve().parents[1] / "app"
_SETTINGS_AXES_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_settings_axes.js"
).read_text(encoding="utf-8")

# The modules that turn a camera setting into camera behaviour. Anything
# outside this set can hold a key without the key doing anything —
# schema.py declares it, settings/defaults.py seeds it, routes/cameras.py
# validates and echoes it, _netz_helpers.py ships it to the chart,
# telemetry.py / _debug_snapshot / _sim_trace display it. All of those
# were present for track_block_contain while it was inert.
_RUNTIME_ROOTS = (
    "camera_runtime",
    "detectors",
    "thresholds",
    "tracker_core",
    "tracking_worker",
    "detect_setup.py",
    "detection_confirmer.py",
    "detection_tiling.py",
    "event_logic.py",
    "motion_blob_tracker.py",
)

# spoke key -> (TrackThresholds field, LiveTracker attribute, probe value)
# A probe value must differ from the module default, or the assertion
# passes on a resolver that ignores the key entirely.
_TRACKER_AXES = {
    "track_spawn_min_score": ("spawn", "spawn_default", 0.71),
    "track_miss_grace_seconds": ("grace_seconds", "grace_seconds", 9.0),
    "track_iou_match_threshold": ("iou", "iou_threshold", 0.33),
    "track_block_contain": ("block_contain", "block_contain", 0.42),
}


def _tune_axis_order() -> list[str]:
    m = re.search(r"TUNE_AXIS_ORDER\s*=\s*\[(.*?)\]", _SETTINGS_AXES_JS, re.DOTALL)
    assert m, "TUNE_AXIS_ORDER not found in _settings_axes.js"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _runtime_sources() -> dict[str, str]:
    out = {}
    for root in _RUNTIME_ROOTS:
        target = _APP / root
        files = sorted(target.rglob("*.py")) if target.is_dir() else [target]
        for p in files:
            out[str(p.relative_to(_APP))] = p.read_text(encoding="utf-8")
    return out


def _readers(key: str) -> list[str]:
    """Files that actually PULL the key out of a config dict.

    ``cfg.get("key")`` or ``cfg["key"]`` — not a bare mention, which a
    comment or a log line would satisfy without reading anything.
    """
    pat = re.compile(r'(?:get\(\s*|\[\s*)["\']%s["\']' % re.escape(key))
    return sorted(name for name, src in _runtime_sources().items() if pat.search(src))


def test_the_runtime_roots_all_exist():
    """Guards the guard: a renamed package would silently empty the scan
    below and turn every assertion in this file green."""
    for root in _RUNTIME_ROOTS:
        assert (_APP / root).exists(), f"_RUNTIME_ROOTS is stale: app/{root} is gone"


@pytest.mark.parametrize("key", _tune_axis_order())
def test_every_spoke_reaches_a_runtime_read(key):
    assert _readers(key), (
        f"{key} is a dead knob: the chart writes it, the route persists it and "
        f"net_state echoes it back as 'effective', but nothing under "
        f"{list(_RUNTIME_ROOTS)} ever reads it out of the camera config — so "
        f"moving the slider changes the stored number and nothing else.\n"
        f"Fix: read it where the behaviour lives (a tracker axis belongs in "
        f"tracker_core/_resolve.py's TrackThresholds, and every LiveTracker "
        f"call site has to pass it on), not only in routes/cameras.py. If the "
        f"consumer legitimately lives elsewhere, add that module to "
        f"_RUNTIME_ROOTS."
    )


def test_every_tracker_spoke_is_accounted_for_here():
    """A new ``track_*`` axis has to declare how it lands before it can
    ship — which is the step that got skipped last time."""
    spokes = {k for k in _tune_axis_order() if k.startswith("track_")}
    missing = spokes - set(_TRACKER_AXES)
    assert not missing, (
        f"new tracker axis {sorted(missing)}: add it to _TRACKER_AXES with the "
        f"TrackThresholds field and the LiveTracker attribute it lands on. If "
        f"there is no such pair yet, the axis is not wired to the tracker."
    )


@pytest.mark.parametrize(("key", "spec"), sorted(_TRACKER_AXES.items()))
def test_every_tracker_spoke_lands_on_the_live_tracker(key, spec):
    """The live-apply path of ``PATCH /api/cameras/<id>/detection-tuning``,
    end to end: camera config → resolver → configure() → the attribute the
    matcher reads. ``block_contain`` failed at the last step with
    ``AttributeError: 'LiveTracker' object has no attribute
    'block_contain'`` — __slots__ had no room for what configure() assigns."""
    field, attr, probe = spec
    thresholds = resolve_track_thresholds(lambda _cid: {key: probe}, "cam_axis")
    assert getattr(thresholds, field) == pytest.approx(probe), (
        f"{key}: resolve_track_thresholds does not carry it — TrackThresholds."
        f"{field} stayed at the module default."
    )
    tracker = LiveTracker("cam_axis")
    tracker.configure(
        spawn_default=thresholds.spawn,
        floor=thresholds.floor,
        grace_seconds=thresholds.grace_seconds,
        iou_threshold=thresholds.iou,
        block_contain=thresholds.block_contain,
    )
    assert getattr(tracker, attr) == pytest.approx(
        probe
    ), f"{key}: configure() never lands it on LiveTracker.{attr}."
