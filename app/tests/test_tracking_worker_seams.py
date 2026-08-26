"""The post-clip tracking seams, each exercised on its own.

These behaviours all existed before the package split, buried inside a
1203-line module where the only way to reach them was to run a whole
clip through `TrackingWorker._run_one` with a video file and a
detector. Nothing here starts the worker thread, opens a video, or
loads a model.

The rules pinned below are the ones a future edit is most likely to
get subtly wrong:

  * the confirmation window is DETECT-sourced only — counting the
    tracker's own IoU continuations would confirm a subject the model
    saw once;
  * the ghost prune's threshold ladder (per-label → per-camera →
    global) with `track_spawn_min_score` as a FLOOR on top, not a
    replacement;
  * the static-FP sweep protecting a confident subject regardless of
    motion, and a moving subject regardless of confidence;
  * stitching staying same-label and inside its gap/size/distance
    gates;
  * the achievement merge being strictly additive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tracker_core import Track, TrackerState
from app.tracking_worker._achievement import aggregate_track_stats, update_event_achievement
from app.tracking_worker._detect import detect_and_filter, resolve_object_filter
from app.tracking_worker._ghosts import prune_ghost_tracks, spawn_threshold_fn
from app.tracking_worker._job import safe_relpath, tracks_path_for
from app.tracking_worker._payload import build_payload
from app.tracking_worker._samples import confirmed_in_window, observed_samples
from app.tracking_worker._static_fp import is_static_false_positive
from app.tracking_worker._stitch import absorb, can_stitch_sequential, overlap_iou_sustained
from app.tracking_worker._video import precision_for


# ── builders ────────────────────────────────────────────────────────────
def _sample(f, t, x, y, w=60, h=140, score=0.8, source="detect"):
    return {
        "f": f,
        "t": t,
        "bbox": {"x1": x, "y1": y, "x2": x + w, "y2": y + h},
        "score": score,
        "source": source,
    }


def _track(label="person", samples=(), track_id="t1", best_score=None):
    tr = Track(track_id, label, samples[0]["f"] if samples else 0)
    tr.samples = list(samples)
    if samples:
        tr.first_frame = samples[0]["f"]
        tr.last_frame = samples[-1]["f"]
    tr.best_score = (
        best_score
        if best_score is not None
        else max((float(s.get("score") or 0.0) for s in samples), default=0.0)
    )
    return tr


def _walk(n, *, score=0.8, dx=40, t0=0.0, dt=1.0, source="detect"):
    return [
        _sample(i * 25, t0 + i * dt, 100 + i * dx, 300, score=score, source=source)
        for i in range(n)
    ]


# ── sample primitives ───────────────────────────────────────────────────
class TestConfirmationWindow:
    def test_dense_enough_run_confirms(self):
        # three detect samples one second apart, window 5 s / n=3
        assert confirmed_in_window(_walk(3), 3, 5.0) is True

    def test_sparse_run_does_not_confirm(self):
        # three detect samples six seconds apart — no 5 s window holds 3
        assert confirmed_in_window(_walk(3, dt=6.0), 3, 5.0) is False

    def test_iou_continuations_do_not_count(self):
        """A "track"-source sample is the tracker extrapolating, not the
        model seeing something. Counting it would confirm a subject the
        detector found exactly once."""
        samples = _walk(1) + _walk(2, t0=1.0, source="track")
        assert observed_samples(_track(samples=samples)) == samples  # all observed…
        assert confirmed_in_window(samples, 2, 5.0) is False  # …but only one detect

    def test_window_is_sliding_not_anchored_at_the_start(self):
        early = _walk(1, t0=0.0)
        late = _walk(3, t0=20.0)
        assert confirmed_in_window(early + late, 3, 5.0) is True


# ── object filter + detector pass ───────────────────────────────────────
class _Det:
    def __init__(self, label, score):
        self.label = label
        self.score = score


class _Detector:
    def __init__(self, dets, available=True):
        self.available = available
        self.dets = dets
        self.thresholds = []

    def detect_frame_raw(self, frame, threshold):
        self.thresholds.append(threshold)
        return [d for d in self.dets if d.score >= threshold]


class TestObjectFilter:
    def test_empty_list_means_no_filter(self):
        """An empty object_filter is "not configured", not "allow nothing"
        — the live path treats it the same way."""
        assert resolve_object_filter(lambda _c: {"object_filter": []}, "cam") is None

    def test_populated_list_becomes_the_allowed_set(self):
        got = resolve_object_filter(lambda _c: {"object_filter": ["person", "cat"]}, "cam")
        assert got == {"person", "cat"}

    def test_a_raising_getter_degrades_to_no_filter(self):
        def _boom(_cam):
            raise RuntimeError("settings store is mid-reload")

        assert resolve_object_filter(_boom, "cam") is None

    def test_filter_is_applied_after_the_raw_pass(self):
        det = _Detector([_Det("person", 0.9), _Det("cat", 0.4)])
        out = detect_and_filter(det, object(), {"person"}, floor_score=0.2)
        assert [d.label for d in out] == ["person"]
        # the model was still asked at the low floor — the tentative tier
        # depends on seeing sub-spawn detections
        assert det.thresholds == [0.2]

    def test_unavailable_detector_yields_no_detections(self):
        det = _Detector([_Det("person", 0.9)], available=False)
        assert detect_and_filter(det, object(), None, floor_score=0.2) == []
        assert det.thresholds == []


# ── sampling cadence ────────────────────────────────────────────────────
class TestPrecision:
    @pytest.mark.parametrize(
        "cfg, expected",
        [
            ({}, "standard"),
            ({"track_postclip_precision": "precise"}, "precise"),
            ({"track_postclip_precision": "  PRECISE "}, "precise"),
            ({"track_postclip_precision": "standard"}, "standard"),
            ({"track_postclip_precision": None}, "standard"),
            ({"track_postclip_precision": "nonsense"}, "standard"),
        ],
    )
    def test_only_precise_switches_cadence(self, cfg, expected):
        assert precision_for(lambda _c: cfg, "cam") == expected

    def test_missing_getter_is_standard(self):
        assert precision_for(None, "cam") == "standard"


# ── ghost prune ─────────────────────────────────────────────────────────
class TestSpawnThresholdLadder:
    def test_label_threshold_wins(self):
        fn = spawn_threshold_fn(
            {"label_thresholds": {"person": 0.7}, "detection_min_score": 0.4},
            {"min_score": 0.55},
        )
        assert fn("person") == 0.7

    def test_camera_default_covers_unlisted_labels(self):
        fn = spawn_threshold_fn(
            {"label_thresholds": {"person": 0.7}, "detection_min_score": 0.4},
            {"min_score": 0.55},
        )
        assert fn("cat") == 0.4

    def test_global_default_is_the_last_resort(self):
        assert spawn_threshold_fn({}, {"min_score": 0.62})("cat") == 0.62

    def test_missing_global_falls_back_to_the_module_default(self):
        assert spawn_threshold_fn({}, {})("cat") == 0.55

    def test_zero_is_the_use_the_default_sentinel(self):
        fn = spawn_threshold_fn(
            {"label_thresholds": {"person": 0}, "detection_min_score": 0},
            {"min_score": 0.55},
        )
        assert fn("person") == 0.55

    def test_track_spawn_min_score_is_a_floor_not_a_replacement(self):
        """It raises a permissive per-label threshold and leaves a
        stricter one alone — a camera-wide floor, same as
        resolve_track_thresholds applies to the matcher."""
        cfg = {"label_thresholds": {"person": 0.3, "cat": 0.9}, "track_spawn_min_score": 0.6}
        fn = spawn_threshold_fn(cfg, {"min_score": 0.55})
        assert fn("person") == 0.6
        assert fn("cat") == 0.9

    def test_garbage_values_do_not_raise(self):
        fn = spawn_threshold_fn(
            {"label_thresholds": {"person": "n/a"}, "detection_min_score": "x"},
            {"min_score": "y"},
        )
        assert fn("person") == 0.55


class TestGhostPrune:
    def _state(self, *tracks):
        st = TrackerState()
        st.closed = list(tracks)
        return st

    def test_confident_track_survives(self):
        st = self._state(_track(samples=_walk(4, score=0.8)))
        assert (
            prune_ghost_tracks(
                st, cam_cfg={"detection_min_score": 0.6}, detection_cfg={}, camera_id="cam"
            )
            == 0
        )
        assert len(st.closed) == 1

    def test_faint_and_sparse_track_is_dropped(self):
        st = self._state(_track(samples=_walk(3, score=0.25, dt=9.0)))
        dropped = prune_ghost_tracks(
            st, cam_cfg={"detection_min_score": 0.6}, detection_cfg={}, camera_id="cam"
        )
        assert dropped == 1
        assert st.closed == []

    def test_faint_but_persistent_track_is_rescued_by_the_window(self):
        """The dusk squirrel: never confident, but seen often enough that
        the live confirmer would have promoted it."""
        st = self._state(_track(samples=_walk(5, score=0.25, dt=1.0)))
        assert (
            prune_ghost_tracks(
                st, cam_cfg={"detection_min_score": 0.6}, detection_cfg={}, camera_id="cam"
            )
            == 0
        )
        assert len(st.closed) == 1

    def test_per_label_window_overrides_the_global_one(self):
        cam_cfg = {
            "detection_min_score": 0.6,
            "confirmation_window": {
                "global": {"n": 2, "seconds": 5},
                "person": {"n": 99, "seconds": 1},
            },
        }
        faint = _track(samples=_walk(5, score=0.25), track_id="p")
        cat = _track(label="cat", samples=_walk(5, score=0.25), track_id="c")
        st = self._state(faint, cat)
        assert prune_ghost_tracks(st, cam_cfg=cam_cfg, detection_cfg={}, camera_id="cam") == 1
        assert [t.label for t in st.closed] == ["cat"]

    def test_empty_state_is_a_no_op(self):
        st = TrackerState()
        assert prune_ghost_tracks(st, cam_cfg={}, detection_cfg={}, camera_id="cam") == 0


# ── static false positives ──────────────────────────────────────────────
class TestStaticFalsePositive:
    def test_a_motionless_low_score_blob_is_dropped(self):
        samples = [_sample(i * 25, float(i), 800, 500, 90, 200, score=0.31) for i in range(6)]
        drop, reason = is_static_false_positive(_track(samples=samples), 0.5)
        assert drop is True
        assert "static-fp" in reason

    def test_confidence_alone_protects_a_motionless_subject(self):
        """A person standing still still scores above spawn — the score
        gate must save her before the motion gate is even consulted."""
        samples = [_sample(i * 25, float(i), 800, 500, 90, 200, score=0.72) for i in range(6)]
        assert is_static_false_positive(_track(samples=samples), 0.5)[0] is False

    def test_motion_alone_protects_a_faint_subject(self):
        samples = [
            _sample(i * 25, float(i), 800 + i * 60, 500, 90, 200, score=0.31) for i in range(6)
        ]
        assert is_static_false_positive(_track(samples=samples), 0.5)[0] is False

    def test_one_mid_clip_step_is_enough_to_keep_it(self):
        """Net displacement can be zero for someone who walks out and
        back; the max-step gate is what catches that."""
        xs = [800, 800, 1400, 1400, 800, 800]
        samples = [_sample(i * 25, float(i), x, 500, 90, 200, score=0.31) for i, x in enumerate(xs)]
        assert is_static_false_positive(_track(samples=samples), 0.5)[0] is False

    def test_a_two_sample_blip_is_left_alone(self):
        samples = [_sample(i * 25, float(i), 800, 500, 90, 200, score=0.20) for i in range(2)]
        assert is_static_false_positive(_track(samples=samples), 0.5)[0] is False

    def test_a_degenerate_zero_size_box_is_left_alone(self):
        samples = [_sample(i * 25, float(i), 800, 500, 0, 0, score=0.2) for i in range(4)]
        assert is_static_false_positive(_track(samples=samples), 0.5)[0] is False


# ── stitching ───────────────────────────────────────────────────────────
class TestSequentialStitch:
    def _pair(self, *, gap=2.0, dx=40, label_b="person", w2=60, h2=140):
        a = _track(samples=_walk(3), track_id="a")
        b_t0 = 2.0 + gap
        b = _track(
            label=label_b,
            samples=[
                _sample(200 + i * 25, b_t0 + i, 220 + dx + i * 40, 300, w2, h2) for i in range(3)
            ],
            track_id="b",
        )
        return a, b

    def test_a_short_gap_close_by_links(self):
        a, b = self._pair(gap=2.0, dx=0)
        ok, why = can_stitch_sequential(a, b)
        assert ok is True, why

    def test_a_different_label_never_links(self):
        a, b = self._pair(gap=1.0, dx=0, label_b="cat")
        assert can_stitch_sequential(a, b) == (False, "label-mismatch")

    def test_too_long_a_gap_does_not_link(self):
        a, b = self._pair(gap=9.0, dx=0)
        ok, why = can_stitch_sequential(a, b)
        assert ok is False and why.startswith("gap=")

    def test_a_size_jump_does_not_link(self):
        a, b = self._pair(gap=1.0, dx=0, w2=400, h2=900)
        ok, why = can_stitch_sequential(a, b)
        assert ok is False and why.startswith("size-ratio=")

    def test_a_distant_endpoint_does_not_link(self):
        a, b = self._pair(gap=1.0, dx=1500)
        ok, why = can_stitch_sequential(a, b)
        assert ok is False and why.startswith("dist=")

    def test_overlapping_in_time_is_not_a_sequential_link(self):
        a = _track(samples=_walk(4), track_id="a")
        b = _track(samples=_walk(4, t0=1.0), track_id="b")
        assert can_stitch_sequential(a, b) == (False, "b-starts-before-a-ends")

    def test_a_track_without_observed_samples_cannot_link(self):
        a = _track(samples=_walk(3), track_id="a")
        empty = _track(samples=(), track_id="e")
        assert can_stitch_sequential(a, empty) == (False, "no-detect-samples")


class TestOverlapMerge:
    def test_co_located_tracks_report_high_iou(self):
        a = _track(samples=_walk(4), track_id="a")
        b = _track(
            samples=[_sample(i * 25, float(i), 104 + i * 40, 302) for i in range(4)],
            track_id="b",
        )
        assert overlap_iou_sustained(a, b) > 0.55

    def test_tracks_that_share_no_frame_report_zero(self):
        a = _track(samples=_walk(3), track_id="a")
        b = _track(samples=[_sample(1000 + i * 25, 40.0 + i, 100, 300) for i in range(3)])
        assert overlap_iou_sustained(a, b) == 0.0

    def test_separate_subjects_in_the_same_frames_report_low_iou(self):
        a = _track(samples=_walk(4), track_id="a")
        b = _track(
            samples=[_sample(i * 25, float(i), 1400, 300) for i in range(4)],
            track_id="b",
        )
        assert overlap_iou_sustained(a, b) == 0.0


class TestAbsorb:
    def test_donor_samples_are_merged_deduped_and_resorted(self):
        a = _track(samples=_walk(2), track_id="a")
        b = _track(samples=_walk(4, score=0.95)[2:], track_id="b")
        b.samples.append(a.samples[0])  # a duplicate frame index
        absorb(a, b)
        frames = [s["f"] for s in a.samples]
        assert frames == sorted(frames)
        assert len(frames) == len(set(frames)) == 4

    def test_best_score_is_recomputed_over_the_union(self):
        a = _track(samples=_walk(2, score=0.4), track_id="a")
        b = _track(samples=_walk(2, score=0.9, t0=5.0), track_id="b")
        b.samples = [dict(s, f=s["f"] + 500) for s in b.samples]
        absorb(a, b)
        assert a.best_score == pytest.approx(0.9)
        assert a.best_frame_idx == 500

    def test_the_donor_is_emptied_and_marked(self):
        a = _track(samples=_walk(2), track_id="a")
        b = _track(samples=[dict(s, f=s["f"] + 500) for s in _walk(2)], track_id="b")
        absorb(a, b)
        assert b.samples == []
        assert b.active is False
        assert b.end_reason == "stitched"


# ── payload ─────────────────────────────────────────────────────────────
class TestPayload:
    def _payload(self, **kw):
        st = TrackerState()
        st.closed = [_track(samples=_walk(3))]
        return build_payload(
            st,
            25.0,
            250,
            10.0,
            kw.pop("allowed", None),
            Path("/srv/storage/motion_detection/cam/2026-08-26/ev.mp4"),
            Path("/srv/storage"),
            **kw,
        )

    def test_video_path_is_relative_to_the_storage_root(self):
        assert self._payload()["video_path"] == "motion_detection/cam/2026-08-26/ev.mp4"

    def test_no_filter_and_an_empty_filter_are_distinguishable(self):
        assert self._payload(allowed=None)["filter_applied"] is None
        assert self._payload(allowed=set())["filter_applied"] == []
        assert self._payload(allowed={"cat", "person"})["filter_applied"] == ["cat", "person"]

    def test_the_gates_block_records_what_was_applied(self):
        gates = self._payload(spawn_score=0.5, floor_score=0.2, grace_s=4.0)["gates"]
        assert gates == {"min_confidence": 0.5, "raw_floor": 0.2, "miss_grace_s": 4.0}

    def test_a_path_outside_the_storage_root_stays_absolute(self):
        assert safe_relpath(Path("/mnt/other/x.mp4"), Path("/srv/storage")) == "/mnt/other/x.mp4"

    def test_the_sidecar_sits_next_to_the_clip(self):
        assert tracks_path_for(Path("/s/a/b/ev_1.mp4")) == Path("/s/a/b/ev_1.tracks.json")


# ── achievement merge ───────────────────────────────────────────────────
class _Store:
    def __init__(self, event):
        self.event = event
        self.written = None

    def get_event(self, _cam, _eid):
        return dict(self.event)

    def update_event(self, _cam, _eid, ev):
        self.written = ev


class TestAchievement:
    def _tracks(self):
        return [
            {"track_id": "a", "label": "person", "best_score": 0.83, "samples": _walk(4)},
            {
                "track_id": "b",
                "label": "person",
                "best_score": 0.41,
                "samples": _walk(2, dt=30.0, score=0.41),
            },
            {"track_id": "c", "label": "cat", "best_score": 0.6, "samples": _walk(3)},
        ]

    def test_counts_and_peaks_are_per_class(self):
        got = aggregate_track_stats(self._tracks(), {})
        assert got["tracks_by_class"] == {"person": 2, "cat": 1}
        assert got["peak_score_by_class"] == {"person": 0.83, "cat": 0.6}

    def test_confirmation_matches_the_sample_stream(self):
        hits = {
            h["track_id"]: h
            for h in aggregate_track_stats(self._tracks(), {})["confirm_hits_by_track"]
        }
        assert hits["a"]["confirmed"] is True
        assert hits["b"]["confirmed"] is False  # two samples 30 s apart
        assert hits["a"]["hit_count"] == 4
        assert hits["a"]["span_seconds"] == 3.0

    def test_no_tracks_produces_no_keys(self):
        assert aggregate_track_stats([], {}) == {}

    def test_the_merge_is_additive(self):
        """inference_avg_ms is written synchronously at finalize; the
        tracks pass must never clear it."""
        store = _Store({"id": "ev", "achievement": {"inference_avg_ms": 12.5}})
        update_event_achievement(store, "cam", "ev", self._tracks(), {})
        ach = store.written["achievement"]
        assert ach["inference_avg_ms"] == 12.5
        assert ach["tracks_by_class"] == {"person": 2, "cat": 1}

    def test_a_missing_event_is_not_written_back(self):
        store = _Store({})
        update_event_achievement(store, "cam", "ev", self._tracks(), {})
        assert store.written is None

    def test_a_broken_store_does_not_raise(self):
        class _Broken:
            def get_event(self, _cam, _eid):
                raise OSError("event json unreadable")

        update_event_achievement(_Broken(), "cam", "ev", self._tracks(), {})
