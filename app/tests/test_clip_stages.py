"""Clip-production stage vocabulary — the contract the library renders.

Two things are pinned here and both have teeth:

1. ``status`` keeps its four legacy values. ``stage`` is the *new*,
   finer field; the moment ``STAGE_STATUS`` starts emitting something
   else, every pre-existing consumer of ``status`` (the Mediaview
   pending message, the poll predicate) silently stops matching.

2. Staleness is derived, not stored. A container restart mid-encode
   leaves an event frozen in ``encoding`` forever with no process
   behind it and nothing that would ever write a "stalled" flag — so
   the tile would spin for eternity pretending to work. The age check
   is the only thing standing between that event and a permanent lie.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.camera_runtime._recording._stages import (
    PENDING_STAGES,
    STAGE_ENCODING,
    STAGE_FAILED,
    STAGE_PROCESSING,
    STAGE_QUEUED,
    STAGE_READY,
    STAGE_RECORDING,
    STAGE_STATUS,
    annotate_stage,
    is_pending,
    set_clip_stage,
    stage_age_s,
    stage_of,
    stall_ceiling_s,
)

NOW = datetime(2026, 8, 27, 12, 0, 0)


def _ev(**kw) -> dict:
    base = {"event_id": "20260827-115900-000000", "time": "2026-08-27T11:59:00"}
    base.update(kw)
    return base


# ── the coarse status field may never drift ────────────────────────────────
@pytest.mark.parametrize(
    ("stage", "status"),
    [
        (STAGE_RECORDING, "recording"),
        (STAGE_QUEUED, "processing"),
        (STAGE_ENCODING, "processing"),
        (STAGE_PROCESSING, "processing"),
        (STAGE_READY, "ready"),
        (STAGE_FAILED, "error"),
    ],
)
def test_every_stage_maps_onto_a_legacy_status(stage, status):
    assert STAGE_STATUS[stage] == status


def test_pending_stages_are_exactly_the_non_terminal_ones():
    assert set(PENDING_STAGES) == {
        STAGE_RECORDING,
        STAGE_QUEUED,
        STAGE_ENCODING,
        STAGE_PROCESSING,
    }
    assert STAGE_READY not in PENDING_STAGES
    assert STAGE_FAILED not in PENDING_STAGES


# ── events written before `stage` existed must still resolve ───────────────
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("recording", STAGE_RECORDING),
        ("processing", STAGE_PROCESSING),
        ("ready", STAGE_READY),
        ("error", STAGE_FAILED),
    ],
)
def test_legacy_events_derive_their_stage_from_status(status, expected):
    assert stage_of(_ev(status=status)) == expected


def test_an_event_with_no_status_at_all_is_finished():
    """The OpenCV fallback path writes its event only once, at the end,
    and never sets `status`. Those are done, not stuck."""
    assert stage_of(_ev()) == STAGE_READY
    assert is_pending(_ev()) is False


def test_recorded_stage_wins_over_status():
    assert stage_of(_ev(status="processing", stage=STAGE_ENCODING)) == STAGE_ENCODING


def test_an_unknown_stage_falls_back_to_status_rather_than_crashing():
    assert stage_of(_ev(status="recording", stage="teleporting")) == STAGE_RECORDING


# ── age ────────────────────────────────────────────────────────────────────
def test_age_counts_from_stage_since_when_present():
    ev = _ev(stage=STAGE_ENCODING, stage_since="2026-08-27T11:59:30")
    assert stage_age_s(ev, NOW) == 30


def test_age_falls_back_to_the_event_start_time():
    assert stage_age_s(_ev(stage=STAGE_ENCODING), NOW) == 60


def test_an_unparseable_timestamp_yields_no_age_instead_of_an_exception():
    assert stage_age_s(_ev(time="not a date"), NOW) is None


# ── stall ceilings ─────────────────────────────────────────────────────────
def test_recording_ceiling_follows_the_configured_clip_length():
    assert stall_ceiling_s(STAGE_RECORDING, 120) == 240
    assert stall_ceiling_s(STAGE_RECORDING, 600) == 720


def test_encoding_ceiling_clears_the_ffmpeg_subprocess_timeout():
    """`_reencode_motion_clip` runs ffmpeg with timeout=300. A clip that
    legitimately takes 299 s must not be branded stuck at 240."""
    assert stall_ceiling_s(STAGE_ENCODING) > 300


def test_terminal_stages_have_no_ceiling():
    assert stall_ceiling_s(STAGE_READY) == 0
    assert stall_ceiling_s(STAGE_FAILED) == 0


# ── annotate_stage ─────────────────────────────────────────────────────────
def test_finished_events_get_no_stage_chatter():
    """Every fact once. A ready clip shows its duration and size; it has
    no business also carrying stage fields."""
    ev = annotate_stage(_ev(status="ready"), NOW)
    assert "stage_age_s" not in ev
    assert "stage_stalled" not in ev


def test_a_fresh_recording_is_busy_not_stalled():
    ev = annotate_stage(_ev(stage=STAGE_RECORDING, stage_since="2026-08-27T11:59:50"), NOW)
    assert ev["stage"] == STAGE_RECORDING
    assert ev["stage_age_s"] == 10
    assert ev["stage_stalled"] is False


def test_a_recording_stub_outliving_its_clip_ceiling_is_stalled():
    """The exact shape a container restart leaves behind: the stub is on
    disk, the ffmpeg subprocess that would have advanced it is gone."""
    since = (NOW - timedelta(seconds=241)).isoformat(timespec="seconds")
    ev = annotate_stage(_ev(stage=STAGE_RECORDING, stage_since=since), NOW, 120)
    assert ev["stage_stalled"] is True


def test_an_encode_still_inside_the_ffmpeg_timeout_is_not_stalled():
    since = (NOW - timedelta(seconds=280)).isoformat(timespec="seconds")
    ev = annotate_stage(_ev(stage=STAGE_ENCODING, stage_since=since), NOW)
    assert ev["stage_stalled"] is False


def test_an_encode_past_the_ffmpeg_timeout_is_stalled():
    since = (NOW - timedelta(seconds=600)).isoformat(timespec="seconds")
    ev = annotate_stage(_ev(stage=STAGE_ENCODING, stage_since=since), NOW)
    assert ev["stage_stalled"] is True


def test_a_legacy_pending_event_gets_one_clip_length_of_grace():
    """Without `stage_since` the only clock is the clip's start time,
    which includes the recording itself. Charging that to the encode
    would call healthy clips stuck."""
    ev = _ev(status="processing", time=(NOW - timedelta(seconds=440)).isoformat())
    assert annotate_stage(dict(ev), NOW, 120)["stage_stalled"] is False
    old = _ev(status="processing", time=(NOW - timedelta(seconds=1000)).isoformat())
    assert annotate_stage(old, NOW, 120)["stage_stalled"] is True


# ── set_clip_stage ─────────────────────────────────────────────────────────
class _FakeStore:
    def __init__(self, event=None):
        self.event = event
        self.writes = []

    def get_event(self, _cam, _eid):
        return dict(self.event) if self.event is not None else None

    def update_event(self, cam, eid, payload):
        self.writes.append((cam, eid, payload))
        self.event = payload
        return True


def test_setting_a_stage_writes_stage_status_and_timestamp():
    store = _FakeStore({"event_id": "e", "status": "recording"})
    set_clip_stage(store, "cam", "e", STAGE_ENCODING)
    (_cam, _eid, payload) = store.writes[0]
    assert payload["stage"] == STAGE_ENCODING
    assert payload["status"] == "processing", "the legacy coarse field must follow along"
    assert stage_age_s(payload, datetime.now()) is not None


def test_a_store_that_blows_up_does_not_take_the_encode_down():
    """The stage announcement is decoration. Losing it must never cost
    the clip."""

    class _Broken:
        def get_event(self, *_a):
            raise OSError("disk gone")

    set_clip_stage(_Broken(), "cam", "e", STAGE_ENCODING)  # must not raise


def test_the_recorder_announces_every_transition():
    """Three call sites, one per stage change. A dropped one leaves the
    tile stuck on the previous phase for the rest of the clip.

    Lives in _ffmpeg_clip.py — the ffmpeg stream-copy lifecycle was split
    out of _recording/__init__.py to keep that file under CLAUDE.md's
    500-line ceiling once the pre-roll splice landed there too."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parent.parent
        / "app"
        / "camera_runtime"
        / "_recording"
        / "_ffmpeg_clip.py"
    ).read_text(encoding="utf-8")
    assert '"stage": STAGE_RECORDING' in src, "the stub must be born knowing its stage"
    assert "_set_clip_stage(event_id, STAGE_QUEUED)" in src
    assert "_set_clip_stage(event_id, STAGE_ENCODING)" in src
    assert "STAGE_READY if video_url else STAGE_FAILED" in src


def test_no_progress_percentage_is_ever_invented():
    """A bar moving at a made-up rate is worse than an honest spinner.
    If a `progress`/`percent` field ever appears it must come from a
    real ffmpeg frame counter — and then this assertion is the place to
    have that argument."""
    ev = annotate_stage(_ev(stage=STAGE_ENCODING), NOW)
    assert not [k for k in ev if "progress" in k or "percent" in k]
