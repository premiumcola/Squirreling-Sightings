"""`TrackerState.closed` used to grow for as long as the instance lived.

The live runtime's instance lives the whole camera session — potentially
days — while its only reader (`_adopt.try_reidentify`) ever looks at
`closed[-TRACK_REID_SCAN_DEPTH:]`. At ~630 B per closed track, a camera
with even a modest event rate accumulates roughly 1 GB/month of tracks
nothing will ever read again — the one confirmed memory leak this
project's resource audit found.

The post-clip worker's OWN TrackerState (tracking_worker/_video.py)
must stay unbounded: it genuinely needs every track from the one clip
it processes for stitching/ghost-filtering, not a bounded tail of it.
"""

from __future__ import annotations

from app.tracker_core import LiveTracker, TrackerState
from app.tracker_core._consts import LIVE_CLOSED_CAP, TRACK_REID_SCAN_DEPTH


def test_the_cap_covers_what_try_reidentify_actually_scans():
    """If these ever drift apart, re-id would look for a track the cap
    already evicted — pin the invariant, not just today's numbers."""
    assert LIVE_CLOSED_CAP >= TRACK_REID_SCAN_DEPTH


def test_uncapped_state_grows_without_bound():
    """The post-clip worker's contract — closed_cap defaults to None."""
    st = TrackerState()
    assert st.closed_cap is None
    for i in range(500):
        st.close_track(f"track-{i}")
    assert len(st.closed) == 500


def test_capped_state_trims_to_the_configured_size():
    st = TrackerState(closed_cap=10)
    for i in range(37):
        st.close_track(f"track-{i}")
    assert len(st.closed) == 10


def test_the_cap_keeps_the_MOST_RECENT_tracks_not_the_oldest():
    """A re-id scan reads the tail — trimming from the front, not the
    back, is the whole point."""
    st = TrackerState(closed_cap=5)
    for i in range(12):
        st.close_track(i)
    assert st.closed == [7, 8, 9, 10, 11]


def test_close_tracks_extends_and_trims_in_one_call():
    st = TrackerState(closed_cap=5)
    st.close_tracks(list(range(20)))
    assert st.closed == [15, 16, 17, 18, 19]


def test_a_cap_larger_than_the_current_length_is_a_no_op():
    st = TrackerState(closed_cap=100)
    st.close_tracks(list(range(3)))
    assert st.closed == [0, 1, 2]


def test_the_live_tracker_constructs_a_capped_state():
    """THE regression test — this is the actual production call site."""
    lt = LiveTracker("cam_test")
    assert lt.state.closed_cap == LIVE_CLOSED_CAP
    for i in range(LIVE_CLOSED_CAP * 3):
        lt.state.close_track(i)
    assert len(lt.state.closed) == LIVE_CLOSED_CAP
    # And it kept the tail, so re-id can still find anything the scan
    # depth is allowed to look at.
    assert lt.state.closed[-TRACK_REID_SCAN_DEPTH:] == list(
        range(LIVE_CLOSED_CAP * 3 - TRACK_REID_SCAN_DEPTH, LIVE_CLOSED_CAP * 3)
    )
