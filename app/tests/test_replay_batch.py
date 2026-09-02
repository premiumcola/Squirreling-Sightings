"""The batch replay's selection, aggregation, persistence and job state.

Everything here is the pure half — no Flask, no detector, no video. The
endpoint itself is covered by test_replay_batch_route.py.

The guarantee this file exists to hold: every species number the
aggregate publishes is one the replay actually earned. The replay now
DOES classify (replay/_species.py runs the live loop's own second stage
over every sampled frame), so `species_named_events` means "the replay
put a name on this clip that the event did not have" — and a clip whose
classifier never ran must never be counted as one where the search came
up empty. That last distinction is what `classified_events` exists for
and what the tests below pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.replay_batch import (
    count_birds,
    event_day,
    find_bird_events,
    fold,
    in_range,
    is_bird_event,
    load_report,
    movers_from,
    report_path,
    save_report,
    summarise_event,
)
from app.storage import EventStore

CAM = "cam_a"


def _event(event_id, **kw):
    base = {"event_id": event_id, "camera_id": CAM, "labels": [], "detections": []}
    base.update(kw)
    return base


def _track_diff(before_tracks, *, gone=()):
    """A tracks diff shaped the way `build_comparison` publishes one:
    the original side lives in the buckets, never as its own list."""
    return {
        "appeared": [],
        "disappeared": list(gone),
        "class_changed": [],
        "score_changed": [],
        "unchanged": [{"before": t, "after": t} for t in before_tracks],
        "counts": {},
    }


def _species_block(gained=(), kept=(), before=()):
    """The species block `build_comparison` publishes, in miniature."""
    return {
        "before": list(before),
        "after": list(gained) + list(kept),
        "gained": list(gained),
        "kept": list(kept),
        "detail": [{"species": n, "species_latin": None, "best_score": 0.9, "frames": 1}
                   for n in list(gained) + list(kept)],
    }


def _comparison(*, before_dets=(), after_dets=(), before_tracks=None, changed=True, **kw):
    diff = kw.pop("diff", None) or {"counts": {}}
    gone = kw.pop("gone", ())
    gained = kw.pop("species_gained", ())
    kept = kw.pop("species_kept", ())
    classified = kw.pop("classified", True)
    return {
        "species": _species_block(gained, kept),
        "classified": classified,
        "before": {
            "detections": list(before_dets),
            "detection_count": len(before_dets),
            "track_count": None if before_tracks is None else len(before_tracks),
            "alert": {},
        },
        "after": {
            "detections": list(after_dets),
            "detection_count": len(after_dets),
            "track_count": len(after_dets),
            "alert": {},
        },
        "diff": {
            "detections": diff,
            "tracks": None if before_tracks is None else _track_diff(before_tracks, gone=gone),
        },
        "tracks_comparable": before_tracks is not None,
        "alert_changed": kw.get("alert_changed", False),
        "changed": changed,
    }


def _bird(score=0.8):
    return {"label": "bird", "score": score, "bbox": (0, 0, 10, 10)}


# ── selection ─────────────────────────────────────────────────────────


class TestIsBirdEvent:
    def test_labels_name_a_bird(self):
        assert is_bird_event(_event("e", labels=["bird"]))

    def test_top_label_names_a_bird_even_when_labels_say_motion(self):
        """The case _upgrade_event_meta creates: labels froze at motion
        while top_label already knew better."""
        assert is_bird_event(_event("e", labels=["motion"], top_label="bird"))

    def test_a_bird_detection_alone_is_enough(self):
        assert is_bird_event(_event("e", labels=["motion"], detections=[_bird()]))

    def test_a_clip_with_no_bird_anywhere_is_not_selected(self):
        ev = _event("e", labels=["person"], top_label="person", detections=[{"label": "person"}])
        assert not is_bird_event(ev)

    def test_an_empty_event_is_not_a_bird(self):
        assert not is_bird_event({})


class TestDateWindow:
    def test_day_comes_from_the_event_id(self):
        assert event_day({"event_id": "20260522-120000-123456"}) == "20260522"

    def test_day_falls_back_to_the_filename_stem(self):
        assert event_day({}, "20260101-000000-0") == "20260101"

    def test_an_undateable_event_yields_empty(self):
        assert event_day({"event_id": "not-a-date"}) == ""

    def test_bounds_are_inclusive(self):
        assert in_range("20260522", "20260522", "20260522")

    def test_before_the_window_is_out(self):
        assert not in_range("20260501", "20260522", None)

    def test_after_the_window_is_out(self):
        assert not in_range("20260601", None, "20260522")

    def test_no_bounds_accepts_anything(self):
        assert in_range("20260522", None, None)

    def test_an_undateable_event_is_kept_only_when_unbounded(self):
        assert in_range("", None, None)
        assert not in_range("", "20260101", None)


class TestFindBirdEvents:
    @pytest.fixture
    def store(self, tmp_storage_root: Path) -> EventStore:
        st = EventStore(str(tmp_storage_root))
        st.add_event(CAM, _event("20260522-120000-1", labels=["bird"]))
        st.add_event(CAM, _event("20260601-120000-2", labels=["bird"]))
        st.add_event(CAM, _event("20260522-130000-3", labels=["person"]))
        st.add_event("cam_b", _event("20260522-140000-4", labels=["bird"]))
        return st

    def test_only_bird_events_are_yielded(self, store):
        ids = {eid for _c, eid, _e in find_bird_events(store)}
        assert ids == {"20260522-120000-1", "20260601-120000-2", "20260522-140000-4"}

    def test_camera_narrows_the_walk(self, store):
        cams = {c for c, _e, _d in find_bird_events(store, ["cam_b"])}
        assert cams == {"cam_b"}

    def test_date_range_narrows_the_walk(self, store):
        ids = {eid for _c, eid, _e in find_bird_events(store, since="20260601")}
        assert ids == {"20260601-120000-2"}

    def test_a_malformed_document_is_skipped_not_fatal(self, store, tmp_storage_root: Path):
        bad = tmp_storage_root / "motion_detection" / CAM / "broken.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{not json", encoding="utf-8")
        assert len(list(find_bird_events(store))) == 3

    def test_tracks_sidecars_are_never_read_as_events(self, store, tmp_storage_root: Path):
        side = tmp_storage_root / "motion_detection" / CAM / "x.tracks.json"
        side.write_text(json.dumps({"labels": ["bird"]}), encoding="utf-8")
        assert len(list(find_bird_events(store))) == 3


# ── aggregation ───────────────────────────────────────────────────────


class TestCountBirds:
    def test_counts_only_birds(self):
        assert count_birds([_bird(), {"label": "person"}, _bird()]) == 2

    def test_empty_and_none_are_zero(self):
        assert count_birds([]) == 0
        assert count_birds(None) == 0


class TestSummariseEvent:
    def test_a_second_bird_is_reported_as_gained(self):
        """The operator's case: the clip holds two birds, the event
        recorded one."""
        comp = _comparison(before_tracks=[_bird()], after_dets=[_bird(), _bird()])
        row = summarise_event(CAM, "e1", _event("e1"), comp)
        assert row["birds_before"] == 1
        assert row["birds_after"] == 2
        assert row["birds_gained"] == 1
        assert row["birds_lost"] == 0

    def test_a_sidecar_baseline_is_marked_as_track_basis(self):
        comp = _comparison(before_tracks=[_bird()], after_dets=[_bird()])
        assert summarise_event(CAM, "e", _event("e"), comp)["basis"] == "tracks"

    def test_without_a_sidecar_the_basis_is_the_frozen_detections(self):
        comp = _comparison(before_dets=[_bird()], after_dets=[_bird(), _bird()])
        row = summarise_event(CAM, "e", _event("e"), comp)
        assert row["basis"] == "detections"
        assert row["birds_gained"] == 1

    def test_losing_a_bird_is_reported(self):
        comp = _comparison(before_tracks=[_bird(), _bird()], after_dets=[_bird()])
        row = summarise_event(CAM, "e", _event("e"), comp)
        assert row["birds_lost"] == 1
        assert row["birds_gained"] == 0

    def test_a_bird_only_in_the_disappeared_bucket_still_counts_as_before(self):
        """Every original-side track lands in exactly one bucket, and a
        bird that vanished entirely lands in `disappeared` — counting
        only the paired buckets would under-count the baseline."""
        comp = _comparison(before_tracks=[], gone=[_bird()], after_dets=[])
        row = summarise_event(CAM, "e", _event("e"), comp)
        assert row["basis"] == "tracks"
        assert row["birds_before"] == 1
        assert row["birds_lost"] == 1

    def test_a_gained_name_is_reported_with_the_name_itself(self):
        """The whole point of classifying during replay: not "a name is
        now possible" but which name was actually produced."""
        comp = _comparison(after_dets=[_bird()], species_gained=["Amsel"])
        row = summarise_event(CAM, "e", _event("e"), comp)
        assert row["species_named"] is True
        assert row["species_gained"] == ["Amsel"]

    def test_a_name_the_event_already_had_is_a_confirmation_not_a_gain(self):
        """Re-reaching a stored name is evidence the stored name was
        right. Counting it as a gain would inflate the headline with
        clips where nothing was learned."""
        comp = _comparison(after_dets=[_bird()], species_kept=["Blaumeise"])
        ev = _event("e", bird_species="Blaumeise")
        row = summarise_event(CAM, "e", ev, comp)
        assert row["species_before"] == "Blaumeise"
        assert row["species_named"] is False
        assert row["species_confirmed"] == ["Blaumeise"]

    def test_finding_no_species_is_not_the_same_as_not_looking(self):
        """A detector-only run reports zero names; so does a classified
        run that found none. `classified` is the only field that tells
        them apart, and the report leans on it."""
        looked = summarise_event(CAM, "e", _event("e"), _comparison(after_dets=[_bird()]))
        did_not = summarise_event(
            CAM, "e", _event("e"), _comparison(after_dets=[_bird()], classified=False)
        )
        assert looked["species_gained"] == [] and did_not["species_gained"] == []
        assert looked["classified"] is True
        assert did_not["classified"] is False

    def test_the_biggest_score_move_is_reported(self):
        diff = {
            "counts": {},
            "score_changed": [
                {"before": {"score": 0.5}, "after": {"score": 0.6}, "delta": 0.1},
                {"before": {"score": 0.9}, "after": {"score": 0.5}, "delta": -0.4},
            ],
        }
        row = summarise_event(CAM, "e", _event("e"), _comparison(diff=diff))
        assert row["top_move"] == 0.4

    def test_no_moves_means_zero(self):
        assert summarise_event(CAM, "e", _event("e"), _comparison())["top_move"] == 0.0


class TestMoversFrom:
    def test_each_move_becomes_a_row(self):
        diff = {
            "counts": {},
            "score_changed": [
                {"before": {"score": 0.4, "label": "bird"}, "after": {"score": 0.7}, "delta": 0.3}
            ],
        }
        rows = movers_from(CAM, "e", _comparison(diff=diff))
        assert rows == [
            {
                "camera_id": CAM,
                "event_id": "e",
                "label": "bird",
                "before": 0.4,
                "after": 0.7,
                "delta": 0.3,
            }
        ]

    def test_no_moves_yields_nothing(self):
        assert movers_from(CAM, "e", _comparison()) == []


class TestFold:
    def _rows(self):
        return [
            summarise_event(
                CAM,
                "a",
                _event("a"),
                _comparison(before_tracks=[_bird()], after_dets=[_bird()] * 2),
            ),
            summarise_event(
                CAM, "b", _event("b"), _comparison(before_dets=[_bird()], after_dets=[_bird()] * 2)
            ),
            summarise_event(CAM, "c", _event("c"), _comparison(after_dets=[], changed=False)),
        ]

    def test_examined_counts_every_row(self):
        assert fold(self._rows(), [])["examined"] == 3

    def test_changed_and_unchanged_partition_the_rows(self):
        agg = fold(self._rows(), [])
        assert agg["changed"] == 2
        assert agg["unchanged"] == 1

    def test_strict_gain_counts_only_the_track_baseline(self):
        """Both a and b gained a bird, but only a had a whole-clip
        baseline to gain it against — the honest headline is 1."""
        agg = fold(self._rows(), [])
        assert agg["birds_gained_events"] == 2
        assert agg["birds_gained_strict"] == 1

    def test_named_clips_are_counted_and_the_names_ranked(self):
        """The aggregate answers "which species" in words, not just
        "how many clips". Amsel appears in two clips, Blaumeise in one,
        so the ranking leads with Amsel."""
        rows = [
            summarise_event(CAM, "a", _event("a"), _comparison(species_gained=["Amsel"])),
            summarise_event(
                CAM, "b", _event("b"), _comparison(species_gained=["Amsel", "Blaumeise"])
            ),
            summarise_event(CAM, "c", _event("c"), _comparison(changed=False)),
        ]
        agg = fold(rows, [])
        assert agg["species_named_events"] == 2
        assert agg["species_names"] == [
            {"species": "Amsel", "events": 2},
            {"species": "Blaumeise", "events": 1},
        ]

    def test_clips_that_never_ran_the_classifier_are_counted_apart(self):
        """`classified_events` is the denominator for every species
        number — without it, a run made with classification off reads
        as a run that found nothing."""
        rows = [
            summarise_event(CAM, "a", _event("a"), _comparison(species_gained=["Amsel"])),
            summarise_event(CAM, "b", _event("b"), _comparison(classified=False)),
        ]
        agg = fold(rows, [])
        assert agg["classified_events"] == 1
        assert agg["species_named_events"] == 1

    def test_movers_are_ranked_by_absolute_delta(self):
        movers = [
            {
                "camera_id": CAM,
                "event_id": "a",
                "label": "bird",
                "before": 0,
                "after": 0,
                "delta": 0.1,
            },
            {
                "camera_id": CAM,
                "event_id": "b",
                "label": "bird",
                "before": 0,
                "after": 0,
                "delta": -0.6,
            },
        ]
        assert [m["event_id"] for m in fold([], movers)["movers"]] == ["b", "a"]

    def test_errors_are_carried_through(self):
        assert fold([], [], errors=4)["errors"] == 4

    def test_the_detail_list_is_capped_and_flagged(self):
        from app.replay_batch import MAX_DETAIL_ROWS

        rows = self._rows() * (MAX_DETAIL_ROWS)
        agg = fold(rows, [])
        assert len(agg["detail"]) == MAX_DETAIL_ROWS
        assert agg["detail_truncated"] is True
        assert agg["examined"] == len(rows)


# ── persistence ───────────────────────────────────────────────────────


class TestPersistence:
    def test_a_saved_report_reads_back_identically(self, tmp_storage_root: Path):
        report = {"schema": 1, "examined": 7, "movers": []}
        assert save_report(tmp_storage_root, report) is True
        assert load_report(tmp_storage_root) == report

    def test_no_report_yet_reads_as_none(self, tmp_storage_root: Path):
        assert load_report(tmp_storage_root) is None

    def test_an_unreadable_report_is_absent_not_fatal(self, tmp_storage_root: Path):
        report_path(tmp_storage_root).write_text("{ truncated", encoding="utf-8")
        assert load_report(tmp_storage_root) is None

    def test_a_second_run_supersedes_the_first(self, tmp_storage_root: Path):
        save_report(tmp_storage_root, {"examined": 1})
        save_report(tmp_storage_root, {"examined": 2})
        assert load_report(tmp_storage_root)["examined"] == 2
