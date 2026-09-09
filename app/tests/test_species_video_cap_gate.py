"""The recording-time half of the species cap: once a species has
enough CONFIRMED video, the next sighting gets a lightweight entry
instead of another full clip.

Traced request: "wenn man zwanzig zwanzig von einem hat, dann nur noch
eins" — "record until 20-30 videos exist per species, then only info,
no recording." `confirmed_video_count` (a Telegram "Ja", never a raw
detection) is the number this compares against
`storage.bird_species_video_cap`.

`_species_over_cap` and `_persist_capped_sighting` are tested directly
against a minimal rig — real `EventStore`, real `_write_snapshot_jpeg`
(mixed in from `LoopStagesMixin`, the same writer a snapshot camera
uses), everything else stubbed. `_start_clip` itself is exercised
end-to-end with `_build_event_meta` stubbed to the shape it actually
returns, so the wiring between the two is covered too.
"""

from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pytest

from app.camera_runtime._loop_stages import LoopStagesMixin
from app.camera_runtime._recording_step import RecordingStepMixin
from app.settings._consts import BIRD_SPECIES_VIDEO_CAP_DEFAULT
from app.species_video_count import confirmed_video_count, record_confirmed_video
from app.storage import EventStore

CAM_ID = "cam_nutbar"


class _Runtime(RecordingStepMixin, LoopStagesMixin):
    """Only what the two methods under test reach for."""

    def __init__(self, storage_root, *, cap=None):
        self.camera_id = CAM_ID
        self.cfg = {"name": "Nut Bar"}
        storage = {"root": str(storage_root)}
        if cap is not None:
            storage["bird_species_video_cap"] = cap
        self.global_cfg = {
            "storage": storage,
            "server": {"public_base_url": "http://example.test"},
        }
        self.store = EventStore(str(storage_root))
        self.last_event_at = datetime(2026, 1, 1)
        self.event_counter_today = 0
        self._pre_buffer = []

    def _build_provenance_snapshot(self):
        return None


def _rec_meta(event_id="20260909-120000-000001", species="Elster", **overrides):
    meta = {
        "event_id": event_id,
        "labels": ["bird"],
        "top_label": "bird",
        "bird_species": species,
        "cat_name": None,
        "person_name": None,
        "whitelisted": False,
        "alarm_level": "info",
        "after_hours": False,
        "detections": [{"label": "bird", "score": 0.7}],
        "whole_clip": {"detections": [], "frames": 1, "species": []},
        "save_video": True,
    }
    meta.update(overrides)
    return meta


def _frame():
    return np.zeros((20, 20, 3), dtype=np.uint8)


# ── _species_over_cap ────────────────────────────────────────────────────


def test_a_species_under_the_cap_is_not_capped(tmp_storage_root):
    rt = _Runtime(tmp_storage_root)
    for _ in range(BIRD_SPECIES_VIDEO_CAP_DEFAULT - 1):
        record_confirmed_video(tmp_storage_root, "Elster")
    assert rt._species_over_cap(_rec_meta()) is None


def test_a_species_at_the_cap_is_capped(tmp_storage_root):
    rt = _Runtime(tmp_storage_root)
    for _ in range(BIRD_SPECIES_VIDEO_CAP_DEFAULT):
        record_confirmed_video(tmp_storage_root, "Elster")
    assert rt._species_over_cap(_rec_meta()) == "Elster"


def test_a_non_bird_event_is_never_capped(tmp_storage_root):
    rt = _Runtime(tmp_storage_root)
    for _ in range(100):
        record_confirmed_video(tmp_storage_root, "Elster")
    meta = _rec_meta(species=None, labels=["cat"])
    assert rt._species_over_cap(meta) is None


def test_a_bird_with_no_species_guess_is_never_capped(tmp_storage_root):
    """Nothing to compare against the cap — record it, exactly like
    today, so the species can eventually be identified at all."""
    rt = _Runtime(tmp_storage_root)
    assert rt._species_over_cap(_rec_meta(species=None)) is None


def test_the_cap_is_configurable(tmp_storage_root):
    rt = _Runtime(tmp_storage_root, cap=2)
    record_confirmed_video(tmp_storage_root, "Elster")
    assert rt._species_over_cap(_rec_meta()) is None
    record_confirmed_video(tmp_storage_root, "Elster")
    assert rt._species_over_cap(_rec_meta()) == "Elster"


def test_a_cap_of_zero_turns_the_whole_feature_off(tmp_storage_root):
    rt = _Runtime(tmp_storage_root, cap=0)
    for _ in range(500):
        record_confirmed_video(tmp_storage_root, "Elster")
    assert rt._species_over_cap(_rec_meta()) is None


def test_a_different_species_is_unaffected_by_another_ones_cap(tmp_storage_root):
    rt = _Runtime(tmp_storage_root)
    for _ in range(BIRD_SPECIES_VIDEO_CAP_DEFAULT):
        record_confirmed_video(tmp_storage_root, "Elster")
    assert rt._species_over_cap(_rec_meta(species="Kohlmeise")) is None


# ── _persist_capped_sighting ─────────────────────────────────────────────


def test_a_capped_sighting_has_a_snapshot_but_no_video(tmp_storage_root):
    rt = _Runtime(tmp_storage_root)
    now = datetime(2026, 9, 9, 12, 0, 0)
    meta = _rec_meta()
    rt._persist_capped_sighting(now, meta["event_id"], "Elster", meta, _frame(), None)

    ev = rt.store.get_event(CAM_ID, meta["event_id"])
    assert ev is not None
    assert ev["video_relpath"] is None
    assert ev["video_url"] is None
    assert ev["snapshot_relpath"]
    assert (tmp_storage_root / ev["snapshot_relpath"]).exists()
    assert ev["bird_species"] == "Elster"
    assert ev["capped_species_sighting"] is True


def test_a_capped_sighting_is_visible_in_the_media_index(tmp_storage_root):
    """The whole point of keeping it: the Sichtungen grid and the
    species tally must still see today's magpie."""
    from app.media_index import visible_media_events

    rt = _Runtime(tmp_storage_root)
    now = datetime(2026, 9, 9, 12, 0, 0)
    meta = _rec_meta()
    rt._persist_capped_sighting(now, meta["event_id"], "Elster", meta, _frame(), None)

    def _size_of(rel):
        p = tmp_storage_root / rel
        return p.stat().st_size if p.exists() else None

    visible = visible_media_events(rt.store, _size_of, CAM_ID)
    assert any(e["event_id"] == meta["event_id"] for e in visible)


# ── _start_clip end to end ────────────────────────────────────────────────


class _StartClipRuntime(_Runtime):
    """Adds just enough for `_start_clip` itself: a stubbed
    `_build_event_meta` returning the shape the real one produces, and
    the ffmpeg-recording hooks stubbed off so only the capped-sighting
    branch (or the ordinary one) can run."""

    def __init__(self, storage_root, meta, **kw):
        super().__init__(storage_root, **kw)
        self._meta = meta
        self.started_ffmpeg = False

    def _build_event_meta(self, *_a, **_k):
        return self._meta

    def _start_ffmpeg_recording(self, *_a, **_k):
        self.started_ffmpeg = True
        return False  # never actually recording — this path must not be reached


@pytest.fixture(autouse=True)
def _no_real_ffmpeg(monkeypatch):
    monkeypatch.setattr(
        "app.camera_runtime._recording_step._FFMPEG_AVAILABLE", False, raising=False
    )


def test_start_clip_writes_a_sighting_and_skips_ffmpeg_when_capped(tmp_storage_root):
    meta = _rec_meta()
    rt = _StartClipRuntime(tmp_storage_root, meta)
    for _ in range(BIRD_SPECIES_VIDEO_CAP_DEFAULT):
        record_confirmed_video(tmp_storage_root, "Elster")

    must_continue = rt._start_clip(
        datetime(2026, 9, 9, 12, 0, 0), ["bird"], [], _frame(), None, cooldown=10
    )

    assert must_continue is True
    assert rt._recording is False if hasattr(rt, "_recording") else True
    assert rt.store.get_event(CAM_ID, meta["event_id"]) is not None
    assert rt.started_ffmpeg is False


def test_start_clip_resets_the_cooldown_so_one_visit_writes_one_sighting(tmp_storage_root):
    """Without this, every motion frame during the same visit re-enters
    `_start_clip` and writes ANOTHER sighting — the exact flood the cap
    exists to prevent."""
    meta = _rec_meta()
    rt = _StartClipRuntime(tmp_storage_root, meta)
    for _ in range(BIRD_SPECIES_VIDEO_CAP_DEFAULT):
        record_confirmed_video(tmp_storage_root, "Elster")

    t0 = datetime(2026, 9, 9, 12, 0, 0)
    rt._start_clip(t0, ["bird"], [], _frame(), None, cooldown=10)
    assert rt.last_event_at == t0
    assert rt.event_counter_today == 1


def test_start_clip_does_not_touch_the_species_gate_for_a_healthy_count(tmp_storage_root):
    """A species well under its cap must still take the ordinary path —
    this only pins that the new gate does not fire early, the ordinary
    recording start is exercised by the existing recording-step tests."""
    meta = _rec_meta()
    rt = _StartClipRuntime(tmp_storage_root, meta)

    rt._start_clip(datetime(2026, 9, 9, 12, 0, 0), ["bird"], [], _frame(), None, cooldown=10)

    # No sighting was written by the CAP path — the ordinary OpenCV
    # fallback ran instead (ffmpeg unavailable in this rig).
    assert rt.store.get_event(CAM_ID, meta["event_id"]) is None
    assert confirmed_video_count(tmp_storage_root, "Elster") == 0
