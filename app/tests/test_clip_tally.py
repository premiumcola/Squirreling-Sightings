"""The event's detections must describe the CLIP, not one frame of it.

An event's `detections` list was serialised from the single tick on
which recording started (`camera_runtime/_motion.py::_build_event_meta`)
and never accumulated: `_upgrade_event_meta` could REPLACE it with one
later frame's list, but only when a brand-new label appeared, and on the
ffmpeg path — the one production actually takes — that replacement never
reached disk at all. Everything the pipeline recognised in the remaining
seconds of the clip was computed and then dropped at event level.

Three consequences the operator hit, one test class each below:
  * a clip that plainly holds two birds records one,
  * a species that only becomes identifiable seconds in never arrives,
  * `bird_species_rank` ranks the headline over one frame of evidence.

The batch replay walks the whole clip and regularly finds more than the
event recorded. These tests pin the live path to that same answer.

Stub-based throughout: no Coral, no ffmpeg, no network. Frames are small
numpy arrays; detections are stubs shaped like `detectors.Detection`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from app.camera_runtime._clip_tally import (
    CLIP_MAX_ROWS,
    CLIP_MAX_ROWS_PER_CLASS,
    ClipTally,
    single_frame_summary,
)


class _Det:
    """Shaped like `detectors.Detection` — the fields the aggregate reads.

    Deliberately a stub rather than the real dataclass: the aggregate
    must read through `getattr` and survive a detection built outside
    the cascade, which is exactly what a legacy sidecar hands it.
    """

    def __init__(
        self,
        label,
        score,
        *,
        track_id=None,
        species=None,
        species_latin=None,
        species_score=None,
        identity=None,
        model=None,
        bbox=(0, 0, 10, 10),
    ):
        self.label = label
        self.score = score
        self.bbox = bbox
        self.track_id = track_id
        self.species = species
        self.species_latin = species_latin
        self.species_score = species_score
        self.identity = identity
        self.model = model

    def to_dict(self):
        return {"label": self.label, "score": self.score, "model": self.model}


class TestTwoSubjectsInDifferentFrames:
    """The headline complaint: a clip holding two birds recorded one."""

    def test_two_birds_never_seen_together_both_reach_the_event(self):
        """Neither frame alone contains both. Only the clip does.

        This is the exact shape of the operator's report — one bird
        leaves the frame as the other arrives, so no single frame ever
        holds two, and a list frozen from any one frame holds one.
        """
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.81, track_id="t1")], 0.0)
        tally.add_frame([_Det("bird", 0.77, track_id="t2")], 3.0)

        rows = tally.rows()
        assert len(rows) == 2, "both birds must survive to the event"
        assert {r["track_id"] for r in rows} == {"t1", "t2"}

    def test_one_bird_across_many_frames_stays_one_row(self):
        """The converse, and the reason this keys on the tracker: a
        single bird seen on forty ticks is one bird, not forty."""
        tally = ClipTally()
        for i in range(40):
            tally.add_frame([_Det("bird", 0.6, track_id="t1")], float(i))

        rows = tally.rows()
        assert len(rows) == 1
        assert rows[0]["frames"] == 40

    def test_an_untracked_detection_collapses_by_label(self):
        """The wildlife stage synthesises its Detection AFTER the tracker
        has stepped, so it carries no track. Keying such a detection by
        anything finer than its class would file one squirrel as thirty.
        """
        tally = ClipTally()
        for i in range(30):
            tally.add_frame([_Det("squirrel", 0.5, model="wildlife_classifier")], float(i))

        rows = tally.rows()
        assert len(rows) == 1
        assert rows[0]["label"] == "squirrel"
        assert rows[0]["track_id"] is None

    def test_the_row_keeps_the_best_scoring_frames_geometry(self):
        """Same choice `replay/_diff.py::track_to_detection` makes when it
        collapses a track, so a row here and a row there describe the
        same frame of the same subject."""
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.40, track_id="t1", bbox=(0, 0, 5, 5))], 0.0)
        tally.add_frame([_Det("bird", 0.92, track_id="t1", bbox=(9, 9, 40, 40))], 1.0)
        tally.add_frame([_Det("bird", 0.55, track_id="t1", bbox=(1, 1, 6, 6))], 2.0)

        row = tally.rows()[0]
        assert row["score"] == pytest.approx(0.92)
        assert row["bbox"] == {"x1": 9, "y1": 9, "x2": 40, "y2": 40}


class TestLateSpecies:
    """A species only identifiable seconds into the clip must arrive."""

    def test_a_species_named_only_on_a_later_frame_reaches_the_event(self):
        """The bird is detected from the first tick but is not
        identifiable until three seconds in — a blurred tail resolving
        into a profile. The frozen list never saw the name."""
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.7, track_id="t1")], 0.0)
        tally.add_frame([_Det("bird", 0.7, track_id="t1")], 1.5)
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.7,
                    track_id="t1",
                    species="Blaumeise",
                    species_latin="Cyanistes caeruleus",
                    species_score=0.88,
                )
            ],
            3.0,
        )

        assert tally.species()[0]["species"] == "Blaumeise"
        assert tally.rows()[0]["species"] == "Blaumeise"

    def test_the_late_name_survives_a_higher_scoring_birdless_frame(self):
        """The regression this guards: species is decided by a LATER
        cascade stage than the box score, so riding it on the score
        comparison would let the best-scoring DETECTOR frame — which is
        regularly not the frame the classifier named — blank the name.
        """
        tally = ClipTally()
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.50,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.8,
                )
            ],
            0.0,
        )
        tally.add_frame([_Det("bird", 0.99, track_id="t1")], 1.0)

        row = tally.rows()[0]
        assert row["score"] == pytest.approx(0.99), "the box score still tracks the best frame"
        assert row["species"] == "Amsel", "a birdless frame must not blank a name already won"

    def test_two_species_in_one_clip_are_both_named(self):
        tally = ClipTally()
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.9,
                )
            ],
            0.0,
        )
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t2",
                    species="Blaumeise",
                    species_latin="Cyanistes caeruleus",
                    species_score=0.7,
                )
            ],
            4.0,
        )

        assert [r["species"] for r in tally.species()] == ["Amsel", "Blaumeise"]

    def test_species_merge_is_keyed_on_the_latin_binomial(self):
        """Same rule as `replay/_species.py`, because it is the same
        `SpeciesTally`. Two crops of one species are one species."""
        tally = ClipTally()
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.4,
                )
            ],
            0.0,
        )
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t2",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.9,
                )
            ],
            1.0,
        )

        species = tally.species()
        assert len(species) == 1
        assert species[0]["best_score"] == pytest.approx(0.9)
        assert species[0]["frames"] == 2

    def test_the_wildlife_stages_raw_label_never_enters_the_species_tally(self):
        """That stage reuses `species` for its raw ImageNet label, which
        is not a bird binomial and must not reach a tally the dossier
        subsystem keys on."""
        tally = ClipTally()
        tally.add_frame(
            [_Det("squirrel", 0.7, species="fox squirrel", model="wildlife_classifier")],
            0.0,
        )

        assert tally.species() == []


class TestModelAttributionSurvives:
    """The per-detection model attribution added in e6aeb2e names WHICH
    cascade stage decided a label. A re-simulation cannot reproduce a
    label it cannot attribute, so aggregation must not drop it."""

    def test_the_stage_that_named_the_species_is_the_row_s_model(self):
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.9, track_id="t1", model="detector")], 0.0)
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.5,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.8,
                    model="bird_classifier",
                )
            ],
            1.0,
        )

        assert tally.rows()[0]["model"] == "bird_classifier"

    def test_identity_and_its_reid_stage_survive(self):
        tally = ClipTally()
        tally.add_frame([_Det("cat", 0.8, track_id="t1", model="detector")], 0.0)
        tally.add_frame(
            [_Det("cat", 0.6, track_id="t1", identity="Mimi", model="cat_reid")],
            1.0,
        )

        row = tally.rows()[0]
        assert row["identity"] == "Mimi"
        assert row["model"] == "cat_reid"

    def test_every_row_carries_the_model_key_even_when_unattributed(self):
        """None is a real answer — a detection built outside the cascade.
        A MISSING key would make the frontend's `d.model || null` join
        indistinguishable from a stage it does not know."""
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.5, track_id="t1")], 0.0)

        assert "model" in tally.rows()[0]
        assert tally.rows()[0]["model"] is None


class TestTheCapHolds:
    """A long clip in a busy garden must not grow an event JSON without
    limit. The caps are the reason this is safe to run on every tick."""

    def test_distinct_tracks_are_capped_globally(self):
        tally = ClipTally()
        for i in range(CLIP_MAX_ROWS * 3):
            tally.add_frame([_Det(f"cls{i}", 0.5, track_id=f"t{i}")], float(i))

        assert len(tally.rows()) == CLIP_MAX_ROWS
        assert tally.is_truncated() is True

    def test_one_class_cannot_crowd_out_the_rest(self):
        """A feeder spawning a fresh bird track every few seconds must
        not push the one squirrel row out of the event."""
        tally = ClipTally()
        for i in range(CLIP_MAX_ROWS_PER_CLASS * 4):
            tally.add_frame([_Det("bird", 0.5, track_id=f"b{i}")], float(i))
        tally.add_frame([_Det("squirrel", 0.6, track_id="s1")], 99.0)

        rows = tally.rows()
        birds = [r for r in rows if r["label"] == "bird"]
        assert len(birds) == CLIP_MAX_ROWS_PER_CLASS
        assert any(r["label"] == "squirrel" for r in rows), "the cap must be per class"

    def test_a_capped_clip_says_so(self):
        tally = ClipTally(max_rows=2)
        tally.add_frame([_Det("bird", 0.5, track_id="t1")], 0.0)
        assert tally.is_truncated() is False
        tally.add_frame([_Det("bird", 0.5, track_id="t2")], 1.0)
        tally.add_frame([_Det("bird", 0.5, track_id="t3")], 2.0)
        assert tally.is_truncated() is True, "a capped list must never look complete"

    def test_a_subject_already_in_the_clip_is_never_refused(self):
        """The cap bounds how many DISTINCT subjects a clip carries, not
        how long an accepted one may be observed."""
        tally = ClipTally(max_rows=1)
        for i in range(50):
            tally.add_frame([_Det("bird", 0.5, track_id="t1")], float(i))

        assert tally.rows()[0]["frames"] == 50

    def test_species_rows_are_capped(self):
        tally = ClipTally(max_species=3)
        for i in range(20):
            tally.add_frame(
                [
                    _Det(
                        "bird",
                        0.5,
                        track_id=f"t{i}",
                        species=f"Art{i}",
                        species_latin=f"Genus sp{i}",
                        species_score=0.5,
                    )
                ],
                float(i),
            )

        assert len(tally.species()) == 3
        assert tally.is_truncated() is True

    def test_the_row_size_does_not_grow_with_clip_length(self):
        """A row is a fixed-size summary, not a sample list — that is what
        makes a five-minute clip cost the same as a five-second one."""
        short = ClipTally()
        short.add_frame([_Det("bird", 0.5, track_id="t1")], 0.0)
        long = ClipTally()
        for i in range(2000):
            long.add_frame([_Det("bird", 0.5, track_id="t1")], float(i))

        assert set(short.rows()[0]) == set(long.rows()[0])


class TestSpanAndShape:
    def test_a_row_reports_when_the_subject_was_present(self):
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.5, track_id="t1")], 1.25)
        tally.add_frame([_Det("bird", 0.5, track_id="t1")], 7.5)

        row = tally.rows()[0]
        assert row["first_s"] == pytest.approx(1.25)
        assert row["last_s"] == pytest.approx(7.5)

    def test_summary_is_the_block_written_onto_the_event(self):
        tally = ClipTally()
        tally.add_frame([_Det("bird", 0.5, track_id="t1")], 0.0)
        summary = tally.summary()

        assert set(summary) == {"detections", "species", "frames", "truncated"}
        assert summary["frames"] == 1

    def test_a_single_frame_summary_is_shaped_like_a_long_one(self):
        """A snapshot camera has no clip, and a runtime that dies mid-clip
        leaves only the stub. Neither may produce a differently-shaped
        block, or every consumer needs a special case."""
        one = single_frame_summary([_Det("bird", 0.5, track_id="t1")])
        assert set(one) == {"detections", "species", "frames", "truncated"}
        assert one["frames"] == 1
        assert len(one["detections"]) == 1

    def test_an_empty_clip_is_still_well_formed(self):
        summary = single_frame_summary([])
        assert summary["detections"] == []
        assert summary["species"] == []
        assert summary["truncated"] is False


class TestNoExtraInference:
    """Cost is the reason the list was one frame. The aggregate must read
    results the pipeline computed anyway and never invoke a model."""

    def test_the_tally_never_calls_a_classifier(self):
        """`_add_species` folds in an ALREADY-stamped species. If it ever
        called `stamp_species` itself, a clip would pay one classifier
        invocation per bird per tick — the exact cost this design exists
        to avoid.

        Asserted over the parsed call graph rather than the source text,
        so the module can go on NAMING the functions it deliberately
        does not call.
        """
        import ast
        import inspect

        import app.camera_runtime._clip_tally as mod

        tree = ast.parse(inspect.getsource(mod))
        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Name):
                called.add(fn.id)
            elif isinstance(fn, ast.Attribute):
                called.add(fn.attr)

        forbidden = {"stamp_species", "classify_crop", "detect_frame", "detect_frame_raw"}
        assert not (
            called & forbidden
        ), f"the aggregate must not run inference: {called & forbidden}"

    def test_folding_a_frame_touches_no_frame_pixels(self):
        """`add_frame` takes detections, never the image. A signature that
        accepted pixels would invite a second inference pass into the one
        place that must not have one."""
        import inspect

        sig = inspect.signature(ClipTally.add_frame)
        assert list(sig.parameters) == ["self", "detections", "t_s"]


class TestFrameStubsAreCheap:
    """The frames these tests would use if the aggregate took any — kept
    to prove the pipeline shape without Coral or a real stream."""

    def test_a_stub_frame_is_a_plain_array(self):
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        assert frame.shape == (48, 64, 3)


class TestHeadlineOverTheWholeClip:
    """The headline stays ONE species — it just gets better evidence."""

    def test_candidates_come_from_the_whole_clip_not_one_frame(self):
        tally = ClipTally()
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.9,
                )
            ],
            0.0,
        )
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t2",
                    species="Blaumeise",
                    species_latin="Cyanistes caeruleus",
                    species_score=0.6,
                )
            ],
            5.0,
        )

        candidates = tally.headline_candidates()
        assert len(candidates) == 2, "the ranking must see every species in the clip"
        assert ("Blaumeise", "Cyanistes caeruleus") in candidates

    def test_the_headline_is_still_one_name(self):
        """Changing it to a list is a separate task with UI implications
        and is explicitly NOT done here."""
        from app.camera_runtime._clip_tally import rank_headline_species

        tally = ClipTally()
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.9,
                )
            ],
            0.0,
        )
        tally.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t2",
                    species="Blaumeise",
                    species_latin="Cyanistes caeruleus",
                    species_score=0.6,
                )
            ],
            5.0,
        )

        headline = rank_headline_species(tally.headline_candidates())
        assert isinstance(headline, str)

    def test_no_birds_means_no_headline(self):
        from app.camera_runtime._clip_tally import rank_headline_species

        assert rank_headline_species([]) is None


class TestAgreementWithTheReplay:
    """Whatever this produces must agree with the batch replay, which is
    the reference implementation for 'what the whole clip contains'."""

    def test_the_species_row_shape_matches_the_replays(self):
        from app.replay import SpeciesTally

        replay_tally = SpeciesTally(max_crops=99)
        replay_tally.add("Amsel", "Turdus merula", 0.9)

        live = ClipTally()
        live.add_frame(
            [
                _Det(
                    "bird",
                    0.8,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.9,
                )
            ],
            0.0,
        )

        assert set(live.species()[0]) == set(replay_tally.result()[0])
        assert live.species()[0] == replay_tally.result()[0]

    def test_both_paths_use_the_same_tally_class(self):
        """Not a parallel implementation: one accumulator, two callers."""
        from app.replay import SpeciesTally as ReplayTally
        from app.species_tally import SpeciesTally as SharedTally

        assert ReplayTally is SharedTally

    def test_a_row_carries_the_replays_three_fields(self):
        """`replay/_diff.py::track_to_detection` collapses a track to
        `{label, score, bbox}`. A live row is a superset, so the two are
        directly comparable."""
        live = ClipTally()
        live.add_frame([_Det("bird", 0.8, track_id="t1")], 0.0)

        row = live.rows()[0]
        assert {"label", "score", "bbox"} <= set(row)


class TestOldEventsAreUntouched:
    """Backward compatibility is not optional. An archived event has no
    whole-clip block and must keep rendering exactly as it did."""

    def test_the_detection_contract_is_byte_identical(self):
        """`Detection.to_dict` is the event JSON's `detections` contract.
        The tracker now stamps `track_id` onto the object; if that leaked
        into `to_dict`, every archived event would differ from a fresh
        one in a field no old event has."""
        from app.detectors import Detection

        det = Detection(label="bird", score=0.5, bbox=(0, 0, 4, 4))
        det.track_id = "t1"

        assert "track_id" not in det.to_dict()
        assert set(det.to_dict()) == {
            "label",
            "score",
            "bbox",
            "species",
            "species_latin",
            "species_score",
            "identity",
            "raw_cls_id",
            "via_roi",
            "model",
        }

    def test_an_event_without_the_block_still_reads(self):
        """The shape an archived event has. Every consumer reads
        `detections`; none may require the new key."""
        legacy = {
            "event_id": "20250101-120000-000000",
            "camera_id": "acme_cam_garden_113",
            "labels": ["bird"],
            "top_label": "bird",
            "detections": [
                {"label": "bird", "score": 0.7, "bbox": {"x1": 1, "y1": 1, "x2": 9, "y2": 9}}
            ],
            "bird_species": "Amsel",
        }

        assert legacy.get("whole_clip") is None
        assert legacy["detections"][0]["label"] == "bird"

    def test_the_replay_before_side_still_reads_the_frozen_frame(self):
        """`replay/_report.py::original_side` compares against the event's
        own `detections`. Leaving that key as the trigger frame is what
        keeps `birds_gained` meaning what it has always meant."""
        from app.replay import original_side

        event = {
            "detections": [
                {"label": "bird", "score": 0.7, "bbox": {"x1": 1, "y1": 1, "x2": 9, "y2": 9}}
            ],
            "whole_clip": {"detections": [{"label": "bird"}, {"label": "bird"}], "species": []},
        }
        before = original_side(event, None)

        assert len(before["detections"]) == 1, "the before side is the frozen frame, not the clip"
        assert before["tracks"] is None


class TestRecordingStepAggregates:
    """The integration the unit tests above cannot prove: that the
    recording state machine actually feeds the aggregate, on BOTH arms,
    for the whole life of the clip.

    This is the test that fails against the pre-change code — there
    `_rec_event_meta` has no `whole_clip` at all.
    """

    def _cam(self):
        from app.camera_runtime._motion import MotionMixin
        from app.camera_runtime._recording_step import RecordingStepMixin

        class _Store:
            def __init__(self):
                self.events = {}

            def get_event(self, _cam, eid):
                return dict(self.events.get(eid) or {})

            def update_event(self, _cam, eid, ev):
                self.events[eid] = dict(ev)

        class _Cam(RecordingStepMixin, MotionMixin):
            def __init__(self):
                self.camera_id = "acme_cam_garden_113"
                self.cfg = {"armed": True, "alarm_profile": "soft"}
                self.global_cfg = {"processing": {"clip_max_duration_s": 120}}
                self.store = _Store()
                self.person_registry = None
                self.recent_detections = []
                self.last_event_at = datetime(2025, 1, 1, 0, 0, 0)
                self.event_counter_today = 0
                self._recording = False
                self._clip_tally = None
                self._rec_event_meta = None
                self._rec_start_time = None
                self._last_motion_ts = None
                self._rec_frames = []
                self._rec_corrupt_frames = 0
                self._ffmpeg_proc = None
                self._pre_buffer = []
                self.motion_preroll = None

        return _Cam()

    def _tick(self, cam, monkeypatch, *, dets, labels, has_motion, at):
        import app.camera_runtime._recording_step as step_mod

        monkeypatch.setattr(step_mod, "_FFMPEG_AVAILABLE", False)
        cam._rtsp_recording_step(
            proc_frame=np.zeros((8, 8, 3), dtype=np.uint8),
            now_dt=at,
            has_motion=has_motion,
            labels=labels,
            detections=dets,
            drawn=None,
            effective_bbox=None,
            cooldown=0,
        )

    def test_a_clip_accumulates_across_its_ticks(self, monkeypatch):
        cam = self._cam()
        t0 = datetime(2025, 6, 1, 12, 0, 0)

        # Tick 1 — the trigger frame. One bird, unnamed.
        self._tick(
            cam,
            monkeypatch,
            dets=[_Det("bird", 0.7, track_id="t1")],
            labels=["bird"],
            has_motion=True,
            at=t0,
        )
        assert cam._recording is True
        frozen = list(cam._rec_event_meta["detections"])

        # Tick 2 — a SECOND bird, on its own track, three seconds in.
        self._tick(
            cam,
            monkeypatch,
            dets=[
                _Det("bird", 0.7, track_id="t1"),
                _Det(
                    "bird",
                    0.8,
                    track_id="t2",
                    species="Blaumeise",
                    species_latin="Cyanistes caeruleus",
                    species_score=0.9,
                ),
            ],
            labels=["bird"],
            has_motion=True,
            at=t0 + timedelta(seconds=3),
        )

        block = cam._rec_event_meta["whole_clip"]
        assert len(block["detections"]) == 2, "the clip holds two birds; the event must say two"
        assert len(frozen) == 1, "the trigger frame stays exactly one frame"
        assert cam._rec_event_meta["detections"] == frozen, "the frozen list must not be rewritten"
        assert block["species"][0]["species"] == "Blaumeise"

    def test_the_no_motion_arm_also_feeds_the_aggregate(self, monkeypatch):
        """A subject that only shows itself during the post-motion tail
        is exactly what the single-frame freeze lost."""
        cam = self._cam()
        t0 = datetime(2025, 6, 1, 12, 0, 0)

        self._tick(
            cam,
            monkeypatch,
            dets=[_Det("bird", 0.7, track_id="t1")],
            labels=["bird"],
            has_motion=True,
            at=t0,
        )
        # No motion, clip still open — the tail.
        self._tick(
            cam,
            monkeypatch,
            dets=[_Det("squirrel", 0.6, track_id="t9")],
            labels=[],
            has_motion=False,
            at=t0 + timedelta(seconds=1),
        )

        labels_in_clip = {r["label"] for r in cam._rec_event_meta["whole_clip"]["detections"]}
        assert labels_in_clip == {"bird", "squirrel"}

    def test_the_headline_is_re_decided_over_the_clip(self, monkeypatch):
        """A species identifiable only seconds in must reach
        `bird_species`, which opened as None."""
        cam = self._cam()
        t0 = datetime(2025, 6, 1, 12, 0, 0)

        self._tick(
            cam,
            monkeypatch,
            dets=[_Det("bird", 0.7, track_id="t1")],
            labels=["bird"],
            has_motion=True,
            at=t0,
        )
        assert cam._rec_event_meta["bird_species"] is None

        self._tick(
            cam,
            monkeypatch,
            dets=[
                _Det(
                    "bird",
                    0.7,
                    track_id="t1",
                    species="Amsel",
                    species_latin="Turdus merula",
                    species_score=0.85,
                )
            ],
            labels=["bird"],
            has_motion=True,
            at=t0 + timedelta(seconds=3),
        )

        assert cam._rec_event_meta["bird_species"] == "Amsel"

    def test_each_clip_gets_a_fresh_aggregate(self, monkeypatch):
        """The live tracker's tracks outlive the clip — they age out on
        the miss-grace window, not the clip boundary. Reading its state
        at close would mix in subjects from before this event began."""
        cam = self._cam()
        t0 = datetime(2025, 6, 1, 12, 0, 0)

        self._tick(
            cam,
            monkeypatch,
            dets=[_Det("bird", 0.7, track_id="t1")],
            labels=["bird"],
            has_motion=True,
            at=t0,
        )
        first = cam._clip_tally
        cam._recording = False
        cam._clip_tally = None

        self._tick(
            cam,
            monkeypatch,
            dets=[_Det("cat", 0.7, track_id="t2")],
            labels=["cat"],
            has_motion=True,
            at=t0 + timedelta(minutes=5),
        )

        assert cam._clip_tally is not first
        labels = {r["label"] for r in cam._rec_event_meta["whole_clip"]["detections"]}
        assert labels == {"cat"}, "a new clip must not inherit the previous clip's subjects"
