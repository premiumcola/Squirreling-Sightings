"""Retroactive bird-species classification for archived events.

Stub-based throughout — no real Coral hardware, no real tflite model.
`_FakeClassifier` stands in for BirdSpeciesClassifier the same way the
rest of this test suite fakes Coral-adjacent services (see
test_boot_coral_probe.py's own docstring).

Covers:
  * the offline classify-and-backfill function re-crops from an
    injected frame_loader and stamps species + the event-level
    aggregate, exactly matching the live path's own aggregate rule
    (camera_runtime/_motion.py::_build_event_meta).
  * idempotency: an event that already carries `bird_species` is never
    reconsidered, even with an unclassified bird detection still on it.
  * graceful degradation: no frame, an unusable/mismatched bbox, and a
    raising classifier all leave the event untouched instead of
    crashing.
  * the sweep is bounded per call (mirrors weather_episodes/_archive.py
    ::_stamp_footage's own budget test shape) and short-circuits
    cheaply when the classifier is unavailable.
  * the dossier hook fires once per newly-stamped species and reaches
    the store via the same read-modify-write EventStore.update_event
    path every other retroactive stamp in this codebase uses.
  * camera_runtime/_status.py's `bird_species_reason` reflects the
    real classifier state rather than being silently dropped (the gap
    that left camedit/index.js's warning line always dark).
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.bird_species_backfill import (
    MANUAL_BACKFILL_BUDGET,
    backfill_event_species,
    build_backfill_classifier,
    dossier_hook_for,
    dossier_lookup_for,
    find_backfill_candidates,
    sweep_bird_species_backfill,
)
from app.camera_runtime._status import StatusMixin
from app.storage import EventStore

assert MANUAL_BACKFILL_BUDGET > 0  # sanity: the manual trigger stays bounded too


# ── fakes ────────────────────────────────────────────────────────────────


class _FakeClassifier:
    def __init__(self, available=True, result=("Rotkehlchen", "Erithacus rubecula", 0.91)):
        self.available = available
        self._result = result
        self.calls = 0

    def classify_crop(self, crop):
        self.calls += 1
        return self._result


class _RaisingClassifier:
    available = True

    def classify_crop(self, crop):
        raise RuntimeError("model exploded")


class _QueueClassifier:
    """Returns one (species, species_latin, score) result per call, in
    order — stands in for a real classifier telling apart several
    different birds present in the same clip."""

    available = True

    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def classify_crop(self, crop):
        result = self._results[self.calls]
        self.calls += 1
        return result


def _bird_event(event_id="e1", bbox=None, species=None, bird_species=None):
    return {
        "event_id": event_id,
        "bird_species": bird_species,
        "detections": [
            {
                "label": "bird",
                "score": 0.8,
                "bbox": bbox or {"x1": 10, "y1": 10, "x2": 40, "y2": 40},
                "species": species,
                "species_latin": None,
                "species_score": None,
            }
        ],
    }


def _multi_bird_event(event_id="e1", n=3):
    """An event with `n` unclassified bird detections at distinct
    bboxes, so each can be re-cropped and classified independently."""
    dets = [
        {
            "label": "bird",
            "score": 0.8,
            "bbox": {"x1": i * 10, "y1": i * 10, "x2": i * 10 + 20, "y2": i * 10 + 20},
            "species": None,
            "species_latin": None,
            "species_score": None,
        }
        for i in range(n)
    ]
    return {"event_id": event_id, "bird_species": None, "detections": dets}


def _frame(w=200, h=200):
    return np.zeros((h, w, 3), dtype=np.uint8)


# ── backfill_event_species ──────────────────────────────────────────────


def test_backfill_stamps_species_and_the_event_aggregate():
    event = _bird_event()
    clf = _FakeClassifier()
    changed = backfill_event_species(event, clf, lambda ev: _frame())
    assert changed is True
    assert clf.calls == 1
    assert event["bird_species"] == "Rotkehlchen"
    det = event["detections"][0]
    assert det["species"] == "Rotkehlchen"
    assert det["species_latin"] == "Erithacus rubecula"
    assert det["species_score"] == 0.91


def test_backfill_is_idempotent_when_bird_species_already_set():
    event = _bird_event(species="Amsel", bird_species="Amsel")
    clf = _FakeClassifier()
    changed = backfill_event_species(event, clf, lambda ev: _frame())
    assert changed is False
    assert clf.calls == 0
    assert event["bird_species"] == "Amsel"


def test_backfill_skips_a_second_unclassified_bird_once_the_event_has_a_species():
    """The event-level field, not the per-detection one, is the gate —
    matches _needs_backfill's own docstring on why."""
    event = _bird_event(species="Amsel", bird_species="Amsel")
    event["detections"].append(
        {
            "label": "bird",
            "score": 0.5,
            "bbox": {"x1": 50, "y1": 50, "x2": 60, "y2": 60},
            "species": None,
        }
    )
    clf = _FakeClassifier()
    changed = backfill_event_species(event, clf, lambda ev: _frame())
    assert changed is False
    assert clf.calls == 0


def _dossier_lookup(counts: dict[str, int]):
    """dossier_lookup stub: `latin -> {"sighting_count": n}` for every
    key in `counts`, None (never recorded) for anything else."""

    def _fn(latin: str):
        return {"sighting_count": counts[latin]} if latin in counts else None

    return _fn


def test_backfill_aggregate_picks_the_rarest_species_not_first_in_order():
    """3 different bird species in one clip — the rarest one becomes
    the event's headline `bird_species`, even though it's the SECOND
    detection classified, not the first."""
    event = _multi_bird_event(n=3)
    clf = _QueueClassifier(
        [
            ("Amsel", "Turdus merula", 0.9),  # idx 0, common
            ("Rotkehlchen", "Erithacus rubecula", 0.9),  # idx 1, rarest
            ("Kohlmeise", "Parus major", 0.9),  # idx 2, mid
        ]
    )
    lookup = _dossier_lookup({"Turdus merula": 5, "Erithacus rubecula": 1, "Parus major": 10})
    changed = backfill_event_species(event, clf, lambda ev: _frame(), dossier_lookup=lookup)
    assert changed is True
    assert clf.calls == 3
    assert event["bird_species"] == "Rotkehlchen"


def test_backfill_aggregate_prefers_a_never_recorded_species():
    """A species with no dossier entry at all outranks an already-seen
    one, regardless of that species' sighting_count."""
    event = _multi_bird_event(n=2)
    clf = _QueueClassifier(
        [
            ("Amsel", "Turdus merula", 0.9),  # idx 0, seen once — very rare but recorded
            ("Seltener Gast", "Genus novus", 0.9),  # idx 1, never recorded
        ]
    )
    lookup = _dossier_lookup({"Turdus merula": 1})
    changed = backfill_event_species(event, clf, lambda ev: _frame(), dossier_lookup=lookup)
    assert changed is True
    assert event["bird_species"] == "Seltener Gast"


def test_backfill_aggregate_tie_break_keeps_stored_order():
    """Equal sighting_count resolves deterministically to whichever
    detection is first in stored order."""
    event = _multi_bird_event(n=2)
    clf = _QueueClassifier(
        [
            ("Kohlmeise", "Parus major", 0.9),
            ("Blaumeise", "Cyanistes caeruleus", 0.9),
        ]
    )
    lookup = _dossier_lookup({"Parus major": 3, "Cyanistes caeruleus": 3})
    changed = backfill_event_species(event, clf, lambda ev: _frame(), dossier_lookup=lookup)
    assert changed is True
    assert event["bird_species"] == "Kohlmeise"


def test_backfill_degrades_when_no_frame_is_available():
    event = _bird_event()
    clf = _FakeClassifier()
    changed = backfill_event_species(event, clf, lambda ev: None)
    assert changed is False
    assert clf.calls == 0
    assert event["bird_species"] is None


def test_backfill_degrades_when_frame_loader_raises():
    event = _bird_event()
    clf = _FakeClassifier()

    def _boom(ev):
        raise OSError("disk gone")

    changed = backfill_event_species(event, clf, _boom)
    assert changed is False
    assert event["bird_species"] is None


def test_backfill_degrades_when_the_classifier_raises():
    event = _bird_event()
    changed = backfill_event_species(event, _RaisingClassifier(), lambda ev: _frame())
    assert changed is False
    assert event["bird_species"] is None


def test_backfill_refuses_a_bbox_that_overshoots_the_loaded_frame():
    """The snapshot-downscale mismatch guard: a bbox in native-resolution
    space against a smaller loaded frame must not silently crop the
    wrong patch — see _crop_bbox's docstring."""
    event = _bird_event(bbox={"x1": 0, "y1": 0, "x2": 5000, "y2": 5000})
    clf = _FakeClassifier()
    changed = backfill_event_species(event, clf, lambda ev: _frame())
    assert changed is False
    assert clf.calls == 0


def test_backfill_ignores_a_non_bird_label():
    event = {
        "event_id": "e1",
        "bird_species": None,
        "detections": [
            {"label": "cat", "score": 0.9, "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5}}
        ],
    }
    clf = _FakeClassifier()
    changed = backfill_event_species(event, clf, lambda ev: _frame())
    assert changed is False
    assert clf.calls == 0


def test_backfill_noop_when_classifier_unavailable():
    event = _bird_event()
    clf = _FakeClassifier(available=False)
    changed = backfill_event_species(event, clf, lambda ev: _frame())
    assert changed is False
    assert clf.calls == 0


# ── build_backfill_classifier: does not force `enabled` ────────────────


def test_build_backfill_classifier_respects_enabled_false():
    """Unlike the coral test-panel's bird_eff override (routes/
    _coral_pipeline.py), a background sweep must not run inference the
    operator explicitly switched off."""
    cfg = {"processing": {"bird_species": {"enabled": False}}}
    clf = build_backfill_classifier(cfg)
    assert clf.available is False
    assert clf.enabled is False


def test_build_backfill_classifier_reflects_missing_model_reason():
    cfg = {
        "processing": {
            "bird_species": {"enabled": True, "model_path": "/nonexistent/inat_bird.tflite"}
        }
    }
    clf = build_backfill_classifier(cfg)
    assert clf.available is False
    assert "model file not found" in clf.reason


# ── dossier_hook_for ─────────────────────────────────────────────────────


def test_dossier_hook_for_is_none_without_a_service():
    assert dossier_hook_for(None) is None


def test_dossier_hook_for_binds_on_new_species():
    class _Svc:
        def __init__(self):
            self.calls = []

        def on_new_species(self, latin, common_de, event_id, camera_id):
            self.calls.append((latin, common_de, event_id, camera_id))

    svc = _Svc()
    hook = dossier_hook_for(svc)
    hook("Erithacus rubecula", "Rotkehlchen", "e1", "cam1")
    assert svc.calls == [("Erithacus rubecula", "Rotkehlchen", "e1", "cam1")]


# ── dossier_lookup_for ────────────────────────────────────────────────────


def test_dossier_lookup_for_is_none_without_a_service():
    assert dossier_lookup_for(None) is None


def test_dossier_lookup_for_binds_get_dossier():
    class _Svc:
        def get_dossier(self, latin):
            return {"sighting_count": 7} if latin == "Turdus merula" else None

    lookup = dossier_lookup_for(_Svc())
    assert lookup("Turdus merula") == {"sighting_count": 7}
    assert lookup("Genus novus") is None


# ── find_backfill_candidates / sweep: real EventStore, tmp_path ────────


def _write_snapshot(path: Path, w=100, h=100):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), _frame(w, h))
    assert ok


def test_find_backfill_candidates_only_yields_events_missing_a_species(tmp_path):
    store = EventStore(str(tmp_path))
    store.add_event("cam1", _bird_event(event_id="needs-it"))
    store.add_event(
        "cam1", _bird_event(event_id="already-done", species="Amsel", bird_species="Amsel")
    )
    store.add_event("cam1", {"event_id": "no-bird", "detections": [{"label": "cat"}]})

    found = {eid for _cam, eid, _ev in find_backfill_candidates(store, ["cam1"])}
    assert found == {"needs-it"}


def test_sweep_short_circuits_when_classifier_unavailable(tmp_path):
    store = EventStore(str(tmp_path))
    store.add_event("cam1", _bird_event())
    result = sweep_bird_species_backfill(
        store, tmp_path, _FakeClassifier(available=False), ["cam1"]
    )
    assert result == {"examined": 0, "changed": 0, "reason": "classifier_unavailable"}


def test_sweep_is_bounded_by_its_budget(tmp_path):
    """Never turns one maintenance tick into a full-archive scan —
    mirrors weather_episodes/_archive.py::_stamp_footage's own
    per-sweep cap and test_the_sweep_stamps_the_count_on_the_poll_
    thread's budget assertion in test_weather_episode_footage.py."""
    store = EventStore(str(tmp_path))
    for i in range(6):
        store.add_event("cam1", _bird_event(event_id=f"e{i}"))
    result = sweep_bird_species_backfill(store, tmp_path, _FakeClassifier(), ["cam1"], budget=2)
    assert result["examined"] == 2


def test_sweep_stamps_the_store_and_fires_the_dossier_hook_once(tmp_path):
    store = EventStore(str(tmp_path))
    snap_rel = "motion_detection/cam1/e1.jpg"
    _write_snapshot(tmp_path / snap_rel)
    store.add_event(
        "cam1",
        {
            "event_id": "e1",
            "bird_species": None,
            "snapshot_relpath": snap_rel,
            "detections": [
                {
                    "label": "bird",
                    "score": 0.8,
                    "bbox": {"x1": 10, "y1": 10, "x2": 40, "y2": 40},
                    "species": None,
                }
            ],
        },
    )
    hook_calls = []
    result = sweep_bird_species_backfill(
        store,
        tmp_path,
        _FakeClassifier(),
        ["cam1"],
        dossier_hook=lambda latin, common, eid, cid: hook_calls.append((latin, common, eid, cid)),
    )
    assert result == {"examined": 1, "changed": 1}
    stored = store.get_event("cam1", "e1")
    assert stored["bird_species"] == "Rotkehlchen"
    assert stored["detections"][0]["species_latin"] == "Erithacus rubecula"
    assert hook_calls == [("Erithacus rubecula", "Rotkehlchen", "e1", "cam1")]


def test_sweep_threads_dossier_lookup_through_to_pick_the_rarest_species(tmp_path):
    """End-to-end: dossier_lookup passed into sweep_bird_species_backfill
    reaches backfill_event_species and drives the rarity pick, not just
    the plain "first" fallback."""
    store = EventStore(str(tmp_path))
    snap_rel = "motion_detection/cam1/e1.jpg"
    _write_snapshot(tmp_path / snap_rel)
    store.add_event(
        "cam1",
        {
            "event_id": "e1",
            "bird_species": None,
            "snapshot_relpath": snap_rel,
            "detections": [
                {
                    "label": "bird",
                    "score": 0.8,
                    "bbox": {"x1": 10, "y1": 10, "x2": 40, "y2": 40},
                    "species": None,
                },
                {
                    "label": "bird",
                    "score": 0.7,
                    "bbox": {"x1": 50, "y1": 50, "x2": 80, "y2": 80},
                    "species": None,
                },
            ],
        },
    )
    clf = _QueueClassifier(
        [
            ("Amsel", "Turdus merula", 0.9),  # idx 0, common
            ("Rotkehlchen", "Erithacus rubecula", 0.9),  # idx 1, rarer
        ]
    )
    result = sweep_bird_species_backfill(
        store,
        tmp_path,
        clf,
        ["cam1"],
        dossier_lookup=_dossier_lookup({"Turdus merula": 9, "Erithacus rubecula": 1}),
    )
    assert result == {"examined": 1, "changed": 1}
    assert store.get_event("cam1", "e1")["bird_species"] == "Rotkehlchen"


def test_sweep_never_crashes_on_one_bad_event(tmp_path):
    """A missing snapshot file (frame_loader returns None for it) must
    not abort the batch — the next candidate still gets processed."""
    store = EventStore(str(tmp_path))
    store.add_event(
        "cam1",
        {
            "event_id": "broken",
            "bird_species": None,
            "snapshot_relpath": "motion_detection/cam1/does-not-exist.jpg",
            "detections": [
                {
                    "label": "bird",
                    "score": 0.8,
                    "bbox": {"x1": 0, "y1": 0, "x2": 5, "y2": 5},
                    "species": None,
                }
            ],
        },
    )
    snap_rel = "motion_detection/cam1/good.jpg"
    _write_snapshot(tmp_path / snap_rel)
    store.add_event(
        "cam1",
        {
            "event_id": "good",
            "bird_species": None,
            "snapshot_relpath": snap_rel,
            "detections": [
                {
                    "label": "bird",
                    "score": 0.8,
                    "bbox": {"x1": 10, "y1": 10, "x2": 40, "y2": 40},
                    "species": None,
                }
            ],
        },
    )
    result = sweep_bird_species_backfill(store, tmp_path, _FakeClassifier(), ["cam1"])
    assert result["examined"] == 2
    assert result["changed"] == 1
    assert store.get_event("cam1", "broken")["bird_species"] is None
    assert store.get_event("cam1", "good")["bird_species"] == "Rotkehlchen"


# ── camera_runtime/_status.py: bird_species_reason reflects reality ────


class _FakeDetector:
    mode = "coral"
    available = True
    reason = "ok"

    def timing_breakdown(self):
        return {}


class _FakeRuntimeStatus(StatusMixin):
    """Just enough of CameraRuntime for StatusMixin.status() to run
    without a live capture thread — no camera, no OpenCV stream."""

    def __init__(self, bird_classifier):
        self.cfg = {"name": "Testcam", "location": "", "enabled": True, "armed": True}
        self.camera_id = "cam1"
        self.frame_ts = 0.0
        self.frame = None
        self.last_error = None
        self.event_counter_today = 0
        self.detector = _FakeDetector()
        self.bird_classifier = bird_classifier
        self._det_state_warned = None
        self._error_streak = 0
        self._reconnect_count = 0
        self._stale_incidents = 0
        self._stale_streak = 0
        self._preview_fps = 0
        self._preview_resolution = None
        self._live_viewers = 0
        self._supervisor_restarts = 0
        self._inference_times_ms: list = []
        self._roi_rescue_attempts = 0
        self._roi_rescue_hits = 0
        self._roi_rescue_log = deque()
        self._reconnect_log = deque()


def test_status_surfaces_the_real_bird_species_reason():
    clf = _FakeClassifier(available=False)
    clf.reason = "model file not found: /app/models/inat_bird_quant.tflite"
    clf.mode = "none"
    rt = _FakeRuntimeStatus(clf)
    st = rt.status()
    assert st["bird_species_available"] is False
    assert st["bird_species_reason"] == "model file not found: /app/models/inat_bird_quant.tflite"


def test_status_bird_species_reason_is_not_hardcoded():
    """Two different classifier states must report two different
    reasons — otherwise camedit/index.js's warning line would always
    render the same text regardless of what actually broke."""
    ok_clf = _FakeClassifier()
    ok_clf.reason = "ok"
    ok_clf.mode = "coral"
    rt = _FakeRuntimeStatus(ok_clf)
    assert rt.status()["bird_species_reason"] == "ok"

    broken_clf = _FakeClassifier(available=False)
    broken_clf.reason = "classifier unavailable: prefer_cpu"
    broken_clf.mode = "none"
    rt.bird_classifier = broken_clf
    assert rt.status()["bird_species_reason"] == "classifier unavailable: prefer_cpu"


def test_status_defaults_the_reason_when_bird_classifier_is_none():
    """getattr's fallback — a runtime whose bird_classifier is None
    (never built, e.g. an early boot race) must not raise and must
    report the same "disabled" default coral_reason already uses."""
    rt = _FakeRuntimeStatus(None)
    assert rt.status()["bird_species_reason"] == "disabled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
