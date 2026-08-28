"""Pre-roll ring buffer for the weather event timelapse.

The three event-tl triggers are forecast-based, but a thunderstorm only
*reveals* itself once it is already overhead: ``_run_event_tl_capture``
started writing frames at trigger time and ran forward, so the build-up —
the minutes the operator actually wants — was gone before the first frame
existed.

This file covers the ring itself and its lifecycle:

  * eviction at the frame boundary AND at the byte cap;
  * arming retains exactly the configured window and nothing more;
  * handover moves the ring into the capture scratch dir and stops the
    rolling loop, so there is never a second hires grabber on one camera;
  * a camera that drops offline keeps the frames it already has;
  * a second trigger in quick succession cannot claim a running capture;
  * nothing survives teardown — not the ring, not an orphan scratch dir,
    not a part-encoded mp4 from a container restart mid-encode;
  * the config keys exist, are additively backfilled, and validate.

The pre/post seam ordering lives next door in
``test_weather_prebuffer_seam.py``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.weather_service._event_tl import EventTimelapseMixin
from app.weather_service._event_tl_ring import EventTLRing, purge_event_tl_scratch


class _Store:
    def __init__(self, cams, storage_root):
        self.data = {"cameras": cams}
        self.base_config = {"storage": {"root": str(storage_root)}}


class _Svc(EventTimelapseMixin):
    """WeatherService stand-in: only the collaborators the ring touches."""

    def __init__(self, storage_root: Path, cams=None, runtimes=None):
        self.cfg = {}
        self.runtimes = runtimes if runtimes is not None else {}
        self._storage_root = Path(storage_root)
        self.settings_store = _Store(cams or [], storage_root)

    def _sightings_dir(self) -> Path:
        return self._storage_root / "weather"

    def _cam_name(self, cam_id: str) -> str:
        return cam_id

    def _cfg_cameras(self) -> list:
        return list(self.settings_store.data.get("cameras") or [])


def _cam(cam_id="cam1", **evt):
    block = {
        "enabled": True,
        "prebuffer_min": 15,
        "prebuffer_mode": "always",
        "interval_s": 8,
        "triggers": {"thunder_rising": True, "front_passing": True, "storm_front": True},
    }
    block.update(evt)
    return {"id": cam_id, "name": cam_id, "weather": {"enabled": True, "event_timelapse": block}}


# ── The ring ────────────────────────────────────────────────────────────────


def test_the_ring_evicts_at_the_frame_boundary(tmp_path: Path):
    ring = EventTLRing(tmp_path / "ring", capacity=5, max_bytes=10_000_000)
    for i in range(8):
        ring.push(b"frame-%02d" % i)

    kept = [p.read_bytes() for p in ring.frames()]

    assert len(ring) == 5, "ring grew past its capacity — the window is unbounded"
    assert kept == [b"frame-%02d" % i for i in range(3, 8)], "evicted the wrong end"
    assert len(list((tmp_path / "ring").glob("*.jpg"))) == 5, "evicted frames left on disk"


def test_the_byte_cap_binds_before_the_frame_cap(tmp_path: Path):
    """A 2560x1440 JPEG at q92 can be 1.5 MB. The frame count alone is
    not a budget — an unusually detailed scene must still be bounded."""
    ring = EventTLRing(tmp_path / "ring", capacity=1000, max_bytes=30)

    for i in range(10):
        ring.push(b"0123456789")  # 10 bytes each

    assert len(ring) == 3, "byte cap did not evict"
    assert ring.bytes_held <= 30


def test_arming_retains_exactly_the_window_and_stops_the_ring(tmp_path: Path):
    ring = EventTLRing(tmp_path / "ring", capacity=5, max_bytes=10_000_000)
    for i in range(8):
        ring.push(b"pre-%02d" % i)

    retained = ring.arm()

    assert retained == 5, "arming did not freeze the configured window"
    assert ring.push(b"post-00") is None, "an armed ring kept accepting pushes"
    assert len(ring) == 5, "the capture wrote into the ring instead of the scratch dir"
    assert ring.arm() == 5, "a second trigger re-armed instead of no-op"


def test_purge_takes_the_directory_with_it(tmp_path: Path):
    ring = EventTLRing(tmp_path / "ring", capacity=5, max_bytes=10_000_000)
    ring.push(b"x")
    ring.purge()

    assert not (tmp_path / "ring").exists()
    assert len(ring) == 0


# ── Handover ────────────────────────────────────────────────────────────────


def test_the_handover_moves_the_ring_into_the_capture_scratch(tmp_path: Path):
    svc = _Svc(tmp_path, cams=[_cam()])
    svc._start_event_tl_ring("cam1", pre_min=15, interval_s=8)
    ring = svc._event_tl_ring_state()["rings"]["cam1"]
    for i in range(4):
        ring.push(b"pre-%02d" % i)
    frames_dir = tmp_path / "scratch"
    frames_dir.mkdir()

    moved = svc._event_tl_take_preroll("cam1", frames_dir)

    assert moved == 4
    names = sorted(p.name for p in frames_dir.glob("*.jpg"))
    assert names == ["00000.jpg", "00001.jpg", "00002.jpg", "00003.jpg"], (
        "pre-roll must land as 00000.jpg upward so the forward capture can "
        "continue the numbering and sorted() stays chronological"
    )
    assert [(frames_dir / n).read_bytes() for n in names] == [b"pre-%02d" % i for i in range(4)]
    assert ring.armed, "handover left the ring rolling — it would keep evicting mid-capture"
    svc._stop_event_tl_prebuffers()


def test_an_empty_ring_hands_over_zero_frames(tmp_path: Path):
    """The trigger can fire before the ring has anything — a camera that
    was offline, or a watch that armed one poll ago. Must be a plain 0,
    not an exception, so the forward-only clip still gets built."""
    svc = _Svc(tmp_path, cams=[_cam()])
    frames_dir = tmp_path / "scratch"
    frames_dir.mkdir()

    assert svc._event_tl_take_preroll("cam1", frames_dir) == 0, "no ring at all"

    svc._start_event_tl_ring("cam1", pre_min=15, interval_s=8)
    assert svc._event_tl_take_preroll("cam1", frames_dir) == 0, "ring exists but is empty"
    assert list(frames_dir.iterdir()) == []
    svc._stop_event_tl_prebuffers()


def test_two_triggers_in_quick_succession_claim_once(tmp_path: Path):
    svc = _Svc(tmp_path, cams=[_cam()])

    assert svc._event_tl_claim_capture("cam1") is True
    assert svc._event_tl_claim_capture("cam1") is False, (
        "a second trigger started a parallel capture — both would consume "
        "the same ring and both would grab hires frames off one camera"
    )

    svc._event_tl_release_capture("cam1")
    assert svc._event_tl_claim_capture("cam1") is True


def test_a_running_capture_is_not_restarted_by_the_poll(tmp_path: Path):
    """`_sync_event_tl_rings` runs on every 5-min poll. A capture runs for
    window_min (60 by default), so the sync must skip that camera or it
    would put a ring loop back on a camera the capture already owns."""
    svc = _Svc(tmp_path, cams=[_cam()])
    svc._event_tl_claim_capture("cam1")

    svc._sync_event_tl_rings([])

    assert "cam1" not in svc._event_tl_ring_state()["threads"]


# ── Failure modes ───────────────────────────────────────────────────────────


def test_a_camera_that_goes_offline_keeps_its_ring(tmp_path: Path):
    """The frames already captured are still valid pre-roll. Losing the
    camera must not tear the ring down — it retries on the next tick."""
    svc = _Svc(tmp_path, cams=[_cam()], runtimes={})
    ring = EventTLRing(tmp_path / "ring", capacity=5, max_bytes=10_000_000)
    ring.push(b"before-the-outage")
    stop = threading.Event()

    t = threading.Thread(target=svc._event_tl_ring_loop, args=("gone", ring, stop, 0.05))
    t.start()
    time.sleep(0.2)
    stop.set()
    t.join(timeout=2)

    assert not t.is_alive(), "the loop hung on a missing camera"
    assert len(ring) == 1, "an offline camera cost us the frames we already had"


def test_teardown_leaves_nothing_on_disk(tmp_path: Path):
    svc = _Svc(tmp_path, cams=[_cam()])
    svc._start_event_tl_ring("cam1", pre_min=15, interval_s=8)
    ring_dir = svc._event_tl_ring_dir("cam1")
    svc._event_tl_ring_state()["rings"]["cam1"].push(b"x")
    assert ring_dir.exists()

    svc._stop_event_tl_prebuffers()

    assert not ring_dir.exists(), "shutdown left a ring on disk — it accumulates forever"
    assert svc._event_tl_ring_state()["threads"] == {}


def test_a_camera_losing_its_opt_in_loses_its_ring(tmp_path: Path):
    svc = _Svc(tmp_path, cams=[_cam()])
    svc._sync_event_tl_rings([])
    ring_dir = svc._event_tl_ring_dir("cam1")
    assert "cam1" in svc._event_tl_ring_state()["threads"]

    svc.settings_store.data["cameras"] = [_cam(enabled=False)]
    svc._sync_event_tl_rings([])

    assert "cam1" not in svc._event_tl_ring_state()["threads"]
    assert not ring_dir.exists()


def test_boot_cleanup_sweeps_orphans_and_spares_real_clips(tmp_path: Path):
    """A container restart mid-ring / mid-encode leaves a ring dir, a
    capture scratch dir and a part-encoded mp4. All three are orphans by
    definition at boot; the finished clips next to them are not."""
    evt = tmp_path / "weather" / "cam1" / "event_timelapse"
    evt.mkdir(parents=True)
    (evt / ".prebuffer").mkdir()
    (evt / ".prebuffer" / "00000000.jpg").write_bytes(b"x")
    (evt / ".scratch_2026-08-28_120000_thunder_rising_cam1").mkdir()
    (evt / ".part_2026-08-28_120000_thunder_rising_cam1.mp4").write_bytes(b"truncated")
    (evt / "2026-08-27_100000_storm_front_cam1.mp4").write_bytes(b"real clip")
    (evt / "2026-08-27_100000_storm_front_cam1.json").write_text("{}")

    removed = purge_event_tl_scratch(tmp_path / "weather")

    assert removed == 3
    assert not (evt / ".prebuffer").exists()
    assert not (evt / ".scratch_2026-08-28_120000_thunder_rising_cam1").exists()
    assert not (evt / ".part_2026-08-28_120000_thunder_rising_cam1.mp4").exists()
    assert (evt / "2026-08-27_100000_storm_front_cam1.mp4").exists(), "ate a finished clip"
    assert (evt / "2026-08-27_100000_storm_front_cam1.json").exists()


def test_boot_cleanup_runs_once_per_service(tmp_path: Path):
    """`_sync_event_tl_rings` must never reach the sweep — it would
    delete a live ring out from under its own loop."""
    svc = _Svc(tmp_path, cams=[_cam()])
    svc._event_tl_boot_cleanup()
    svc._start_event_tl_ring("cam1", pre_min=15, interval_s=8)
    ring_dir = svc._event_tl_ring_dir("cam1")

    svc._event_tl_boot_cleanup()

    assert ring_dir.exists(), "the second sweep deleted a live ring"
    svc._stop_event_tl_prebuffers()


# ── Risk-armed mode ─────────────────────────────────────────────────────────


def _slices(**series):
    """Forecast slices at +15, +30, +45 min from now."""
    from datetime import datetime, timedelta

    now = datetime.now()
    out = []
    for i in range(3):
        slot = {"_dt": now + timedelta(minutes=15 * (i + 1)), "time": "t%d" % i}
        for k, values in series.items():
            slot[k] = values[i]
        out.append(slot)
    return out


def test_the_watch_arms_well_below_the_trigger_threshold(tmp_path: Path):
    """The whole case for `armed` over `always`: because the triggers read
    60–90 min of forecast, the watch predicate lights up long before the
    trigger can fire — so the ring is full when it matters without
    spinning 24/7."""
    svc = _Svc(tmp_path)
    evt_cfg = {"triggers": {"thunder_rising": True, "front_passing": False, "storm_front": False}}
    rising = _slices(lightning_potential=[600.0, 800.0, 900.0])

    active, reason = svc._event_tl_watch_active(rising, evt_cfg)

    assert active, "watch stayed dark on a lightning potential of 900 J/kg"
    assert "lightning_potential" in reason
    assert svc._detect_thunder_rising(rising) is None, (
        "the trigger itself must NOT have fired here — otherwise the watch "
        "buys no lead time and the ring is empty when it is needed"
    )


def test_the_watch_respects_the_per_camera_trigger_toggles(tmp_path: Path):
    """A camera that only wants thunder must not burn its ring on wind."""
    svc = _Svc(tmp_path)
    windy = _slices(wind_gusts_10m=[45.0, 50.0, 55.0], cloud_cover=[10.0, 10.0, 10.0])

    thunder_only = {
        "triggers": {"thunder_rising": True, "front_passing": False, "storm_front": False}
    }
    assert svc._event_tl_watch_active(windy, thunder_only)[0] is False

    storm_too = {"triggers": {"thunder_rising": True, "front_passing": False, "storm_front": True}}
    assert svc._event_tl_watch_active(windy, storm_too)[0] is True


def test_calm_weather_leaves_the_ring_off(tmp_path: Path):
    svc = _Svc(tmp_path)
    calm = _slices(
        lightning_potential=[0.0, 10.0, 5.0],
        wind_gusts_10m=[8.0, 9.0, 7.0],
        cloud_cover=[20.0, 22.0, 21.0],
    )

    assert svc._event_tl_watch_active(calm, {})[0] is False
    assert svc._event_tl_watch_active([], {})[0] is False


def test_the_grace_window_survives_a_flickering_forecast(tmp_path: Path):
    """One "elevated" poll keeps the ring alive for watch_grace_min. A
    forecast that dips for a single cycle must not wipe a half-full
    ring."""
    svc = _Svc(tmp_path)

    assert svc._event_tl_note_watch("cam1", True, "test") is True
    assert svc._event_tl_note_watch("cam1", False, "") is True, "grace window ignored"

    svc._event_tl_ring_state()["watch_until"]["cam1"] = time.time() - 1
    assert svc._event_tl_note_watch("cam1", False, "") is False, "grace never expires"


def test_armed_mode_only_rolls_inside_the_watch(tmp_path: Path):
    svc = _Svc(tmp_path, cams=[_cam(prebuffer_mode="armed")])
    calm = _slices(lightning_potential=[0.0, 0.0, 0.0], wind_gusts_10m=[5.0, 5.0, 5.0])

    svc._sync_event_tl_rings(calm)
    assert "cam1" not in svc._event_tl_ring_state()["threads"], "ring spun up on a calm forecast"

    svc._sync_event_tl_rings(_slices(lightning_potential=[900.0, 900.0, 900.0]))
    assert "cam1" in svc._event_tl_ring_state()["threads"], "ring stayed off through a watch"
    svc._stop_event_tl_prebuffers()


def test_prebuffer_mode_off_never_rolls(tmp_path: Path):
    svc = _Svc(tmp_path, cams=[_cam(prebuffer_mode="off")])

    svc._sync_event_tl_rings(_slices(lightning_potential=[9000.0, 9000.0, 9000.0]))

    assert svc._event_tl_ring_state()["threads"] == {}


# ── Config + schema ─────────────────────────────────────────────────────────


def test_the_shipped_defaults_carry_a_pre_roll_window():
    from app.settings._consts import EVENT_TL_DEFAULTS, WEATHER_DEFAULTS

    assert EVENT_TL_DEFAULTS["prebuffer_min"] == 15
    assert EVENT_TL_DEFAULTS["prebuffer_mode"] == "armed"
    assert WEATHER_DEFAULTS["event_timelapse"]["prebuffer_max_mb"] == 256
    assert WEATHER_DEFAULTS["event_timelapse"]["watch_grace_min"] == 30


def test_a_camera_predating_the_key_is_backfilled_additively():
    from app.settings.migrations import migrate_weather_defaults

    data = {
        "cameras": [
            {
                "id": "legacy",
                "weather": {
                    "enabled": True,
                    "event_timelapse": {"enabled": True, "window_min": 42, "interval_s": 20},
                },
            }
        ]
    }

    migrate_weather_defaults(data)
    evt = data["cameras"][0]["weather"]["event_timelapse"]

    assert evt["prebuffer_min"] == 15, "legacy camera left without a pre-roll window"
    assert evt["prebuffer_mode"] == "armed"
    assert evt["window_min"] == 42, "migration clobbered an operator value"
    assert evt["interval_s"] == 20


def test_the_camera_schema_type_checks_the_weather_block():
    from app.schema import CAMERA_SCHEMA, validate_and_coerce

    assert CAMERA_SCHEMA["weather"] == (dict, {})
    with pytest.raises(ValueError):
        validate_and_coerce({"id": "c", "name": "c", "weather": "yes"}, CAMERA_SCHEMA)


def test_the_event_tl_schema_coerces_a_hand_edited_settings_file(tmp_path: Path):
    """A settings.json edited by hand is the realistic source of
    `"prebuffer_min": "15"`. It must coerce, not kill the poll thread."""
    svc = _Svc(tmp_path)

    mode, pre_min, interval_s = svc._event_tl_prebuffer_cfg(
        {"prebuffer_min": "20", "prebuffer_mode": "ALWAYS", "interval_s": "10"}
    )

    assert (mode, pre_min, interval_s) == ("always", 20, 10)


@pytest.mark.parametrize(
    "block,expected",
    [
        ({}, ("armed", 15, 8)),
        ({"prebuffer_mode": "nonsense"}, ("armed", 15, 8)),
        ({"prebuffer_mode": "off"}, ("off", 15, 8)),
        ({"prebuffer_min": 0}, ("off", 0, 8)),
        ({"prebuffer_min": -5}, ("off", 0, 8)),
        ({"prebuffer_min": "not-a-number"}, ("off", 0, 8)),
    ],
)
def test_prebuffer_config_resolution(tmp_path: Path, block, expected):
    assert _Svc(tmp_path)._event_tl_prebuffer_cfg(block) == expected


def test_the_ring_capacity_is_the_window_divided_by_the_interval(tmp_path: Path):
    """15 min at the shipped 8 s interval is 113 frames — the number the
    disk budget in the module docstring is computed from."""
    svc = _Svc(tmp_path, cams=[_cam()])
    svc._start_event_tl_ring("cam1", pre_min=15, interval_s=8)

    assert svc._event_tl_ring_state()["rings"]["cam1"].capacity == 113
    svc._stop_event_tl_prebuffers()
