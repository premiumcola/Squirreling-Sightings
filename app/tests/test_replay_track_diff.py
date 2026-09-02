"""The track axis of a replay comparison, on the path production takes.

`build_comparison` had no direct test. `test_replay_route.py` covers the
two edge baselines — no sidecar at all, and a sidecar indexed to zero
tracks — but never the ordinary case: a clip that WAS indexed, replayed
with the same settings, which is what the operator does most.

That case was wrong. The before side puts the sidecar's tracks through
`track_to_detection` (label + score + bbox); the after side handed the
diff the COMPACT tracks meant for the event JSON, which carry neither a
`score` nor a `bbox`. `normalise_detection` read both as missing, so the
track axis of every replay of an indexed clip reported a score drop to
zero and the whole comparison came back "changed".
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.replay._diff import track_to_detection  # noqa: E402
from app.replay._report import build_comparison  # noqa: E402
from app.replay._run import compact_track  # noqa: E402

BBOX = {"x1": 100, "y1": 300, "x2": 160, "y2": 440}


def _sidecar_track(track_id: str = "t1", *, label: str = "person", score: float = 0.9) -> dict:
    """One track in the shape `tracking_worker` writes into tracks.json."""
    return {
        "track_id": track_id,
        "label": label,
        "color": "#22c55e",
        "best_score": score,
        "best_frame": 10,
        "first_frame": 0,
        "last_frame": 20,
        "end_reason": "ended_at_clip",
        "model": "coco",
        "samples": [
            {"f": 10, "t": 0.4, "bbox": dict(BBOX), "score": score, "source": "detect"},
        ],
    }


def _replay_result(tracks: list[dict]) -> dict:
    """Exactly what `replay_clip` returns for those tracks — both keys,
    built from the one list, the way the real function builds them."""
    return {
        "tracks": [compact_track(t) for t in tracks],
        "detections": [track_to_detection(t) for t in tracks],
        "species": [],
        "classified": False,
        "classifier": {"available": False, "mode": "none", "model": None, "reason": "disabled"},
    }


def _event(tracks: list[dict]) -> dict:
    """An archived event whose stored detections agree with the tracks."""
    return {
        "detections": [
            {"label": t["label"], "score": t["best_score"], "bbox": dict(BBOX)} for t in tracks
        ]
    }


def _compare(tracks, replay_tracks=None):
    tracks = list(tracks)
    replay_tracks = tracks if replay_tracks is None else list(replay_tracks)
    return build_comparison(
        event=_event(tracks),
        sidecar_tracks=tracks,
        replay=_replay_result(replay_tracks),
        alarm_profile=None,
    )


def test_replaying_an_indexed_clip_unchanged_reports_unchanged():
    """The everyday case: same clip, same settings, same answer."""
    cmp = _compare([_sidecar_track()])

    counts = cmp["diff"]["tracks"]["counts"]
    assert counts["unchanged"] == 1, cmp["diff"]["tracks"]
    assert counts["score_changed"] == 0
    assert counts["appeared"] == 0 and counts["disappeared"] == 0
    assert cmp["changed"] is False


def test_the_track_diff_sees_boxes_on_both_sides():
    """The root cause, stated directly: a missing box on the after side
    sent every pair into the label-only branch, so the spatial matching
    the diff exists for never ran."""
    cmp = _compare([_sidecar_track()])

    pairs = cmp["diff"]["tracks"].get("unchanged_pairs") or cmp["diff"]["tracks"]
    assert cmp["diff"]["tracks"]["counts"]["unchanged"] == 1, pairs


def test_the_track_count_still_counts_tracks():
    """The after side of the diff changed shape; the reported count must
    not — it is one entry per replayed track either way."""
    cmp = _compare([_sidecar_track("t1"), _sidecar_track("t2")])

    assert cmp["after"]["track_count"] == 2
    assert cmp["before"]["track_count"] == 2


def test_a_genuine_score_drop_is_still_reported():
    """The fix must not make the axis blind — a real change still shows."""
    before = [_sidecar_track(score=0.9)]
    after = [_sidecar_track(score=0.4)]
    cmp = _compare(before, replay_tracks=after)

    assert cmp["diff"]["tracks"]["counts"]["score_changed"] == 1
    assert cmp["changed"] is True


def test_a_vanished_track_is_still_reported():
    before = [_sidecar_track("t1"), _sidecar_track("t2")]
    after = [_sidecar_track("t1")]
    cmp = _compare(before, replay_tracks=after)

    assert cmp["diff"]["tracks"]["counts"]["disappeared"] == 1
    assert cmp["changed"] is True


def test_an_unindexed_clip_still_has_no_track_baseline():
    """Guard the edge `test_replay_route.py` already relies on."""
    tracks = [_sidecar_track()]
    cmp = build_comparison(
        event=_event(tracks),
        sidecar_tracks=None,
        replay=_replay_result(tracks),
        alarm_profile=None,
    )

    assert cmp["tracks_comparable"] is False
    assert cmp["diff"]["tracks"] is None
    assert cmp["changed"] is False
