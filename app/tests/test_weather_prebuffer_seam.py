"""The pre/post seam: what the encoder actually receives.

``_run_event_tl_capture`` hands ``sorted(frames_dir.glob("*.jpg"))`` to
the encoder, so the pre-roll and the forward capture have to agree on a
single, monotonically increasing filename sequence. Get that wrong by one
digit and the finished mp4 replays the storm before its own build-up —
the failure mode is silent, because every individual frame is fine.

These tests drive the real ``_run_event_tl_capture`` with a stubbed frame
source and a stubbed encoder, then assert on the exact image list the
encoder was handed.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.weather_service._event_tl import EventTimelapseMixin

# One "minute" of window_min at the sub-second scale the tests run at.
_WINDOW_MIN = 0.04  # ~2.4 s of forward capture
_INTERVAL_S = 0.5


class _Profile:
    name = "day"


class _RT:
    """Camera runtime stub: every hires grab returns an identifiable byte
    string, so the encoder's image list can be read back as a sequence."""

    def __init__(self):
        self.n = 0

    def snapshot_jpeg_hires(self, quality=92):
        self.n += 1
        return b"post-%04d" % self.n


class _Store:
    def __init__(self, storage_root):
        self.data = {"cameras": [{"id": "cam1", "name": "cam1"}]}
        self.base_config = {"storage": {"root": str(storage_root)}}


class _Svc(EventTimelapseMixin):
    def __init__(self, storage_root: Path):
        self.cfg = {}
        self.runtimes = {"cam1": _RT()}
        self._storage_root = Path(storage_root)
        self.settings_store = _Store(storage_root)
        self.encoded: list = []
        self.pushed: list = []

    # ── WeatherService collaborators ────────────────────────────────────
    def _sightings_dir(self) -> Path:
        return self._storage_root / "weather"

    def _cam_name(self, cam_id: str) -> str:
        return cam_id

    def _cfg_cameras(self) -> list:
        return list(self.settings_store.data.get("cameras") or [])

    @staticmethod
    def _cleanup_sun_scratch(scratch: Path):
        shutil.rmtree(scratch, ignore_errors=True)

    def _maybe_push_telegram(self, manifest: dict, mp4_path: Path):
        self.pushed.append(manifest)

    # ── Encoder stand-in ────────────────────────────────────────────────
    def _encode_event_tl_clip(self, images, out_dir, stem, fps, qa_ctx):
        # Record the byte content in the order the encoder would consume
        # it — that IS the timeline of the finished clip.
        self.encoded = [Path(p).read_bytes() for p in images]
        mp4_path = out_dir / f"{stem}.mp4"
        mp4_path.write_bytes(b"fake-mp4")
        return mp4_path


@pytest.fixture
def svc(tmp_path: Path, monkeypatch):
    import app.frame_helpers as fh

    monkeypatch.setattr(fh, "grab_valid_frame", lambda grab_fn, **kw: (grab_fn(), 0, ""))
    monkeypatch.setattr(fh, "pick_profile_from_baseline", lambda samples: _Profile())
    return _Svc(tmp_path)


def _seed_ring(svc, n: int):
    """Register a ring holding ``n`` identifiable pre-roll frames.

    Built directly rather than through ``_start_event_tl_ring`` so the
    rolling loop never runs here — the loop has its own coverage in
    ``test_weather_prebuffer.py`` and would otherwise push its own frames
    into the ring mid-test.
    """
    from app.weather_service._event_tl_ring import EventTLRing

    ring = EventTLRing(svc._event_tl_ring_dir("cam1"), capacity=max(1, n), max_bytes=10_000_000)
    for i in range(n):
        ring.push(b"pre-%04d" % i)
    svc._event_tl_ring_state()["rings"]["cam1"] = ring
    return ring


def _run(svc, fps=1):
    svc._run_event_tl_capture(
        "cam1",
        "thunder_rising",
        0.8,
        {},
        {},
        _WINDOW_MIN,
        _INTERVAL_S,
        fps,
    )


def test_the_clip_runs_pre_roll_then_event_in_capture_order(svc, tmp_path: Path):
    """The whole point of the feature: the build-up comes first."""
    _seed_ring(svc, 3)

    _run(svc)

    assert svc.encoded[:3] == [b"pre-0000", b"pre-0001", b"pre-0002"], (
        "the clip does not start with the pre-roll — either the ring was "
        "never retained, or the forward capture overwrote 00000.jpg"
    )
    assert len(svc.encoded) > 3, "no forward frames after the trigger"
    assert all(b.startswith(b"post-") for b in svc.encoded[3:])
    posts = [int(b.split(b"-")[1]) for b in svc.encoded[3:]]
    assert posts == sorted(posts), "forward frames landed out of order"


def test_the_manifest_records_how_much_of_the_clip_predates_the_trigger(svc):
    _seed_ring(svc, 4)

    _run(svc)

    assert svc.pushed, "clip never reached the push pipeline"
    assert svc.pushed[0]["prebuffer_frames"] == 4
    assert svc.pushed[0]["prebuffer_min"] == round(4 * _INTERVAL_S / 60.0, 1)


def test_an_empty_ring_still_yields_the_forward_clip(svc):
    """A trigger can arrive before the ring has anything in it. That must
    degrade to exactly the behaviour the system had before the ring
    existed — a forward-only clip — not to a crash."""
    _run(svc)

    assert svc.encoded, "no clip at all — the empty ring took the capture down with it"
    assert all(b.startswith(b"post-") for b in svc.encoded)
    assert svc.pushed[0]["prebuffer_frames"] == 0


def test_no_scratch_or_ring_survives_the_capture(svc, tmp_path: Path):
    _seed_ring(svc, 1)
    svc._event_tl_claim_capture("cam1")

    _run(svc)

    evt_dir = tmp_path / "weather" / "cam1" / "event_timelapse"
    leftovers = [p.name for p in evt_dir.iterdir() if p.name.startswith(".")]
    assert leftovers == [], f"capture left scratch behind: {leftovers}"
    assert svc._event_tl_ring_state()["threads"] == {}
    assert svc._event_tl_ring_state()["inflight"] == {}, "claim leaked — camera is now frozen"


def test_a_camera_that_vanished_releases_its_claim(svc):
    """Bail-out path: the runtime is gone by the time the capture thread
    starts. The claim must not leak, or the camera never captures again."""
    svc._event_tl_claim_capture("cam1")
    svc.runtimes.clear()

    _run(svc)

    assert svc.encoded == []
    assert svc._event_tl_ring_state()["inflight"] == {}


def test_too_few_frames_skips_the_encode_but_still_cleans_up(svc, tmp_path: Path):
    """fps*2 is the existing floor. Below it there is no clip — and there
    must be no scratch dir either."""
    _run(svc, fps=1000)

    assert svc.encoded == []
    evt_dir = tmp_path / "weather" / "cam1" / "event_timelapse"
    assert [p.name for p in evt_dir.iterdir() if p.name.startswith(".")] == []
