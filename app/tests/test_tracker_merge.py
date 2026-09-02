"""J3 · the duplicate-fold pass, which had no test at all.

`merge_active_duplicates` is the last line of defence against the
"4 boxes stacked on one person" symptom, and it was the only module in
`tracker_core` with zero coverage — `grep -rl merge_active_duplicates
app/tests/` found nothing before this file.

The case that matters is three duplicates in one frame, because the
pass folds pairwise and the loser of one pair is still sitting in the
list when the next pair is considered.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tracker_core import Track, TrackerState  # noqa: E402
from app.tracker_core._consts import MERGE_SUSTAIN  # noqa: E402
from app.tracker_core._merge import merge_active_duplicates  # noqa: E402

# One box the tails all share, so pairwise IoU is 1.0 at every position
# and the sustained-overlap gate is satisfied for every pair. The merge
# decision then rests purely on track_quality_score, which is what this
# file is about.
BOX = {"x1": 100, "y1": 100, "x2": 200, "y2": 300}


def _track(track_id: str, frames: list[int], *, label: str = "person") -> Track:
    tr = Track(track_id, label, frames[0])
    for f in frames:
        tr.add_sample(f, float(f), dict(BOX), 0.9, "detect", label)
    return tr


def _samples_of(track) -> set[int]:
    return {int(s["f"]) for s in track.samples}


def test_three_duplicates_all_fold_into_the_single_survivor():
    """A loses to B, then A must not go on to absorb C.

    `absorbed.add(i)` happens inside the inner `for j` loop while only
    the OUTER loop tests `if i in absorbed`. So after A lost to B, A —
    already `active=False`, `end_reason="merged"` — stayed the reference
    for the rest of the inner loop and could still win a later pair on
    quality. C's samples then landed in a track that is on its way to
    `state.closed`, and never reached the surviving track at all.
    """
    a = _track("AAA", [0, 1, 2, 3])  # 4 observed samples
    b = _track("BBB", [0, 1, 2, 3, 4])  # 5 — the canonical survivor
    c = _track("CCC", [50, 51, 52])  # 3, on frames nobody else holds
    state = TrackerState(active=[a, b, c])

    merge_active_duplicates(state)

    survivors = [t.track_id for t in state.active]
    assert survivors == ["BBB"], f"expected one survivor, got {survivors}"
    # The whole point of a fold: no observation is dropped on the floor.
    assert _samples_of(b) >= {0, 1, 2, 3, 4, 50, 51, 52}
    assert all(t.end_reason == "merged" for t in state.closed)


def test_a_track_that_lost_a_merge_never_wins_a_later_one():
    """The narrow invariant behind the case above, stated directly."""
    a = _track("AAA", [0, 1, 2, 3])
    b = _track("BBB", [0, 1, 2, 3, 4])
    c = _track("CCC", [50, 51, 52])
    state = TrackerState(active=[a, b, c])

    merge_active_duplicates(state)

    assert a.active is False and a.end_reason == "merged"
    # A absorbed nothing on its way out — its own four frames, no more.
    assert _samples_of(a) == {0, 1, 2, 3}


def test_two_duplicates_still_fold_the_shorter_into_the_longer():
    """Guard the ordinary two-track case the pass was written for."""
    a = _track("AAA", [0, 1, 2])
    b = _track("BBB", [0, 1, 2, 3, 4])
    state = TrackerState(active=[a, b])

    merge_active_duplicates(state)

    assert [t.track_id for t in state.active] == ["BBB"]
    assert a.end_reason == "merged"


def test_different_labels_are_never_folded():
    a = _track("AAA", [0, 1, 2, 3], label="person")
    b = _track("BBB", [0, 1, 2, 3, 4], label="cat")
    state = TrackerState(active=[a, b])

    merge_active_duplicates(state)

    assert sorted(t.track_id for t in state.active) == ["AAA", "BBB"]
    assert state.closed == []


def test_a_track_below_the_sustain_window_is_left_alone():
    short = _track("SHORT", list(range(MERGE_SUSTAIN - 1)))
    long = _track("LONG", [0, 1, 2, 3, 4])
    state = TrackerState(active=[short, long])

    merge_active_duplicates(state)

    assert sorted(t.track_id for t in state.active) == ["LONG", "SHORT"]
