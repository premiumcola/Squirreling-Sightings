"""Species classification during a clip replay — with a stubbed
classifier, no model file, no TPU and no video decoder.

What this file exists to hold, in one line each:

  * a species is aggregated over the WHOLE clip, not one frame — the
    only advantage a replay has over the event it re-examines;
  * naming goes through the live loop's own stamping function, so a
    detection named by a replay is shaped exactly like one named at
    capture time;
  * the expensive half is bounded and says what it spent;
  * "found no species" and "never looked" stay distinguishable.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.detectors import STAGE_BIRD, stamp_species
from app.detectors._types import Detection
from app.replay import SpeciesTally, event_species, make_sample_hook, species_diff
from app.replay._run import classifier_for, describe_classifier
from app.tracking_worker._video import sample_clip

CAM = "cam_test"


# ── stubs ─────────────────────────────────────────────────────────────


class _Classifier:
    """Stands in for BirdSpeciesClassifier. Returns queued answers in
    order, then repeats the last one — so a test can say "frame 1 is a
    blurred miss, every frame after is an Amsel" without scripting
    every sample."""

    available = True
    mode = "cpu"
    reason = "cpu_requested"
    active_model_path = "/models/inat_bird_quant.tflite"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def classify_crop(self, crop):
        self.calls += 1
        idx = min(self.calls - 1, len(self.answers) - 1)
        return self.answers[idx]


def _bird(x=0, score=0.8):
    return Detection(label="bird", score=score, bbox=(x, 0, x + 20, 20))


def _frame():
    return np.zeros((60, 60, 3), dtype=np.uint8)


# ── the stamping seam, shared with the live loop ──────────────────────


class TestStampSpecies:
    def test_a_hit_stamps_every_field_the_live_loop_stamps(self):
        det = _bird()
        got = stamp_species(_Classifier([("Amsel", "Turdus merula", 0.91)]), _frame(), det)
        assert got == ("Amsel", "Turdus merula", 0.91)
        assert det.species == "Amsel"
        assert det.species_latin == "Turdus merula"
        assert det.species_score == pytest.approx(0.91)
        assert det.model == STAGE_BIRD

    def test_a_silent_classifier_leaves_the_detection_generic(self):
        """No name is the classifier's answer in three different
        situations — below min_score, no German mapping, no model. The
        detection must stay a plain bird in all of them rather than
        acquire a half-filled species."""
        det = _bird()
        assert stamp_species(_Classifier([(None, "Genus novus", None)]), _frame(), det) is None
        assert det.species is None
        assert det.model is None

    def test_an_unavailable_classifier_is_not_called(self):
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        clf.available = False
        assert stamp_species(clf, _frame(), _bird()) is None
        assert clf.calls == 0

    def test_a_missing_score_does_not_become_a_zero(self):
        det = _bird()
        stamp_species(_Classifier([("Amsel", "Turdus merula", None)]), _frame(), det)
        assert det.species == "Amsel"
        assert det.species_score is None


# ── whole-clip aggregation ────────────────────────────────────────────


class TestSpeciesTally:
    def test_the_best_frame_wins_not_the_first(self):
        """The reason to classify a whole clip: an early blurred crop
        must not fix the answer when a later frame sees the bird
        properly."""
        tally = SpeciesTally(max_crops=10)
        tally.add("Amsel", "Turdus merula", 0.31)
        tally.add("Amsel", "Turdus merula", 0.88)
        tally.add("Amsel", "Turdus merula", 0.42)
        assert tally.result() == [
            {
                "species": "Amsel",
                "species_latin": "Turdus merula",
                "best_score": 0.88,
                "frames": 3,
            }
        ]

    def test_two_species_in_one_clip_are_both_reported(self):
        tally = SpeciesTally(max_crops=10)
        tally.add("Amsel", "Turdus merula", 0.6)
        tally.add("Blaumeise", "Cyanistes caeruleus", 0.9)
        assert tally.names() == ["Blaumeise", "Amsel"]

    def test_species_are_keyed_by_binomial_not_display_name(self):
        """Two iNat labels can carry one German name. Keying on the
        display name would count one bird as two species."""
        tally = SpeciesTally(max_crops=10)
        tally.add("Blaumeise", "Cyanistes caeruleus", 0.7)
        tally.add("Blaumeise", "Parus caeruleus", 0.8)
        assert len(tally.result()) == 2
        tally2 = SpeciesTally(max_crops=10)
        tally2.add("Blaumeise", "Cyanistes caeruleus", 0.7)
        tally2.add("Blaumeise", "Cyanistes caeruleus", 0.8)
        assert len(tally2.result()) == 1

    def test_a_nameless_result_is_ignored(self):
        tally = SpeciesTally(max_crops=10)
        tally.add("", None, 0.9)
        assert tally.result() == []


# ── the per-frame hook ────────────────────────────────────────────────


class TestSampleHook:
    def test_only_bird_boxes_are_classified(self):
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        tally = SpeciesTally(max_crops=10)
        dets = [_bird(), Detection(label="cat", score=0.9, bbox=(0, 0, 20, 20))]
        make_sample_hook(clf, tally)(_frame(), dets)
        assert clf.calls == 1
        assert dets[1].species is None

    def test_every_bird_in_a_frame_is_classified(self):
        """Two birds in one frame are two crops — the flock case that
        makes the crop budget a different number from the frame cap."""
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        tally = SpeciesTally(max_crops=10)
        make_sample_hook(clf, tally)(_frame(), [_bird(0), _bird(30)])
        assert clf.calls == 2
        assert tally.crops_classified == 2
        assert tally.frames_classified == 1

    def test_the_crop_budget_stops_the_spend_and_says_so(self):
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        tally = SpeciesTally(max_crops=2)
        hook = make_sample_hook(clf, tally)
        hook(_frame(), [_bird(0), _bird(25)])
        hook(_frame(), [_bird(0), _bird(25)])
        assert clf.calls == 2
        assert tally.crops_classified == 2
        assert tally.truncated is True

    def test_a_box_outside_the_frame_costs_no_inference(self):
        """`crop_bbox` refuses a box that overshoots the frame. A
        refusal is not a classification and must not be billed against
        the budget."""
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        tally = SpeciesTally(max_crops=10)
        huge = Detection(label="bird", score=0.9, bbox=(0, 0, 9000, 9000))
        make_sample_hook(clf, tally)(_frame(), [huge])
        assert clf.calls == 0
        assert tally.crops_classified == 0
        assert tally.frames_classified == 0

    def test_no_classifier_means_no_hook_at_all(self):
        """`sample_clip` skips the hook entirely when there is nothing
        to classify with, rather than calling a no-op per frame."""
        assert make_sample_hook(None, SpeciesTally(max_crops=10)) is None
        unavailable = _Classifier([])
        unavailable.available = False
        assert make_sample_hook(unavailable, SpeciesTally(max_crops=10)) is None

    def test_the_hook_stamps_the_detection_it_was_handed(self):
        """The detections the hook mutates are the ones association is
        about to consume — the species has to land on the real object,
        not on a copy."""
        tally = SpeciesTally(max_crops=10)
        dets = [_bird()]
        make_sample_hook(_Classifier([("Amsel", "Turdus merula", 0.9)]), tally)(_frame(), dets)
        assert dets[0].species == "Amsel"
        assert dets[0].model == STAGE_BIRD


# ── what the event already knew, and what the replay added ────────────


class TestSpeciesDiff:
    def test_both_places_a_stored_name_can_live_are_read(self):
        event = {
            "bird_species": "Amsel",
            "detections": [
                {"label": "bird", "species": "Blaumeise"},
                {"label": "bird", "species": "Amsel"},
                {"label": "cat"},
            ],
        }
        assert event_species(event) == ["Amsel", "Blaumeise"]

    def test_a_new_name_is_a_gain_and_a_known_one_is_not(self):
        out = species_diff(
            ["Amsel"],
            [
                {"species": "Amsel", "species_latin": "Turdus merula", "best_score": 0.9},
                {"species": "Blaumeise", "species_latin": "Cyanistes caeruleus", "best_score": 0.8},
            ],
        )
        assert out["gained"] == ["Blaumeise"]
        assert out["kept"] == ["Amsel"]

    def test_an_event_with_no_name_gains_everything_found(self):
        out = species_diff([], [{"species": "Amsel", "best_score": 0.9}])
        assert out["gained"] == ["Amsel"]
        assert out["before"] == []


# ── how the run reports what it ran on ────────────────────────────────


class TestClassifierReporting:
    def test_a_detector_only_run_is_not_a_failed_lookup(self):
        assert describe_classifier(None, requested=False)["reason"] == "not_requested"
        assert describe_classifier(None, requested=True)["reason"] == "unavailable"

    def test_the_device_is_reported_so_a_tpu_grab_would_be_visible(self):
        """A replay's classifier is pinned to CPU. If this ever reads
        "coral", the pinning broke and an archive sweep is sharing the
        accelerator with live capture."""
        assert describe_classifier(_Classifier([]), requested=True)["mode"] == "cpu"

    def test_a_worker_without_the_accessor_degrades_to_detector_only(self):
        """The replay accepts any object exposing the worker's
        accessors. One that predates the second stage must still get
        its box counts rather than an exception."""

        class _Old:
            def detector(self):
                return None

        assert classifier_for(_Old(), True) is None

    def test_classification_can_be_switched_off(self):
        class _New:
            def bird_classifier(self):
                raise AssertionError("must not be built for a detector-only run")

        assert classifier_for(_New(), False) is None


# ── through the real sampling loop ────────────────────────────────────


class _Cap:
    """The capture handle `sample_clip` seeks and reads. Every position
    yields a frame, so the walk is driven purely by the cadence."""

    def __init__(self):
        self.reads = 0

    def set(self, _prop, _idx):
        return True

    def read(self):
        self.reads += 1
        return True, _frame()


class _WalkDetector:
    """Returns a fresh detection list per sample — fresh because the
    hook mutates what it is handed, and a shared object would let one
    frame's species leak into the next."""

    available = True

    def __init__(self, per_sample):
        self.per_sample = per_sample
        self.calls = 0

    def detect_frame_raw(self, frame, threshold):
        spec = self.per_sample[min(self.calls, len(self.per_sample) - 1)]
        self.calls += 1
        return [_bird(x, score) for x, score in spec]


class TestThroughTheRealWalk:
    """`sample_clip` with the hook attached — the wiring the replay
    actually runs, minus cv2's decoder."""

    META = {
        "fps": 25.0,
        "frame_count": 75,
        "duration_s": 3.0,
        "sample_interval": 25,
        "frame_w": 60,
        "frame_h": 60,
    }

    def _walk(self, detector, hook, **kw):
        return sample_clip(
            _Cap(),
            dict(self.META),
            detector,
            None,
            floor_score=0.2,
            spawn_score=0.5,
            iou_threshold=0.3,
            sample_hook=hook,
            **kw,
        )

    def test_a_species_is_accumulated_across_the_whole_clip(self):
        """Three sampled frames, the middle one the good look at the
        bird. The clip's answer is the best of the three — which is the
        entire advantage a replay has over the single frame the event
        froze at recording start."""
        clf = _Classifier(
            [
                ("Amsel", "Turdus merula", 0.30),
                ("Amsel", "Turdus merula", 0.94),
                ("Amsel", "Turdus merula", 0.55),
            ]
        )
        tally = SpeciesTally(max_crops=99)
        detector = _WalkDetector([[(0, 0.8)]])
        self._walk(detector, make_sample_hook(clf, tally))
        assert detector.calls == 3
        assert tally.frames_classified == 3
        assert tally.crops_classified == 3
        assert tally.result()[0]["best_score"] == 0.94
        assert tally.result()[0]["frames"] == 3

    def test_frames_classified_never_exceeds_frames_decoded(self):
        """The number the report leans on: how much of the clip was
        NAMED versus merely decoded. A frame holding no bird is decoded
        and detected but never classified."""
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        tally = SpeciesTally(max_crops=99)
        # Only the first sample holds a bird; the rest are empty.
        detector = _WalkDetector([[(0, 0.8)], [], []])
        self._walk(detector, make_sample_hook(clf, tally))
        assert detector.calls == 3
        assert tally.frames_classified == 1

    def test_the_budget_bounds_a_flock_across_frames(self):
        """Three frames of four birds is twelve crops; the budget stops
        it at five and the run says it was truncated."""
        clf = _Classifier([("Amsel", "Turdus merula", 0.9)])
        tally = SpeciesTally(max_crops=5)
        detector = _WalkDetector([[(0, 0.8), (25, 0.8), (0, 0.7), (25, 0.7)]])
        self._walk(detector, make_sample_hook(clf, tally))
        assert tally.crops_classified == 5
        assert tally.truncated is True
        # Detection is unaffected — the clip is still fully walked, so
        # the BIRD COUNT stays a whole-clip answer even when the
        # species search ran out of budget.
        assert detector.calls == 3

    def test_the_queued_sidecar_walk_is_unchanged_without_a_hook(self):
        """`sample_hook` defaults to None so the tracking worker's own
        jobs walk exactly as they did before this existed."""
        detector = _WalkDetector([[(0, 0.8)]])
        state = self._walk(detector, None)
        assert detector.calls == 3
        assert state.active == []
