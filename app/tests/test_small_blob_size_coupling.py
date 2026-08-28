"""SMALL-3 · the coherence bound was absolute, the problem is relative.

`coherent_track` demanded `min_net_frac * frame_w` of net displacement —
4 % of 2560 px = 102 px — from every track regardless of the size of the
thing moving. A dog crossing a garden clears that trivially. A squirrel at
a feeder moves a body length or two, never reaches 102 px, and was filed as
in-place vegetation shimmer. The coherent blob is the precondition for the
whole D2 rescue, so the small-subject case was rejected before any of the
small-subject machinery downstream could look at it.

The bound now falls to the track's own size, capped by the absolute one.

Acceptance criteria are BACKLOG SMALL-3's, verbatim: a 40 px blob that
moved 60 px on a 2560 px frame counts as coherent (today: 60 < 102, no);
a 400 px blob that moved 60 px does not.

NOTE: BACKLOG SMALL-3 writes the formula as
``max(min_net_frac * frame_w, k * max(bw, bh))``. That is a typo — `max`
fails both of the acceptance tests the same package specifies (the 40 px
blob would still face a 102 px bound) and contradicts its own prose,
"für große Blobs bleibt die alte Schranke wirksam, für kleine sinkt sie"
and "roi_min_net_disp_frac bleibt als Obergrenze erhalten". `min` is what
the prose, the cap statement and both acceptance tests all describe, and
is what is implemented.
"""

from __future__ import annotations

from app.motion_blob_tracker import (
    DEFAULT_MIN_NET_FRAC,
    MotionBlobTracker,
)

FRAME_W = 2560


def _walk(tracker, dim, step, frames=4):
    """Drive one blob of `dim` px square `step` px per frame along x."""
    for i in range(frames):
        tracker.update([{"bbox": (100 + i * step, 500, dim, dim), "solidity": 0.8}])
    return tracker


def test_a_small_blob_moving_its_own_length_is_coherent():
    """THE acceptance case. 40 px blob, 60 px net, 2560 px frame.

    Against the old absolute-only bound the requirement is 102 px, 60 < 102,
    `coherent_track` returns None and the rescue is never offered the
    squirrel at all.
    """
    t = _walk(MotionBlobTracker(), dim=40, step=20)

    track = t.coherent_track(FRAME_W)

    assert track is not None
    assert track.net_displacement == 60.0


def test_a_large_blob_with_the_same_displacement_stays_incoherent():
    """BACKLOG's counter-test. The absolute bound must keep its teeth on
    anything big enough for it to be a fair question — 60 px is not a dog
    crossing a garden, it is a dog shifting its weight."""
    t = _walk(MotionBlobTracker(), dim=400, step=20)

    assert t.coherent_track(FRAME_W) is None


def test_the_absolute_bound_remains_the_upper_limit():
    """`roi_min_net_disp_frac` keeps its documented meaning: coupling can
    only ever LOWER the requirement, never raise it above the operator's
    configured cap. A 900 px blob must not suddenly need 900 px."""
    t = _walk(MotionBlobTracker(), dim=900, step=40)
    track = t._tracks[0]

    cap = DEFAULT_MIN_NET_FRAC * FRAME_W
    required = t.required_net_px(track, FRAME_W, DEFAULT_MIN_NET_FRAC, size_coupling=1.0)

    assert required == cap


def test_in_place_shimmer_is_still_rejected_at_every_size():
    """The reason the coupling is safe. Wind does not translate — a swaying
    patch returns to where it started, so its NET displacement is ~0 and it
    fails a size-coupled bound exactly as it failed an absolute one. The
    coupling relaxes the distance, never the requirement to have gone
    somewhere."""
    for dim in (20, 40, 200):
        t = MotionBlobTracker()
        for i in range(8):
            x = 100 + (5 if i % 2 else 0)
            t.update([{"bbox": (x, 500, dim, dim), "solidity": 0.8}])

        assert t.coherent_track(FRAME_W) is None, dim


def test_coupling_can_be_switched_off_to_restore_the_absolute_bound():
    """The escape hatch: a camera that wants the old, deafer behaviour."""
    t = _walk(MotionBlobTracker(), dim=40, step=20)

    assert t.coherent_track(FRAME_W, size_coupling=0) is None


def test_min_age_is_untouched_by_the_coupling():
    """A blob seen twice is not a trajectory however far it jumped —
    persistence stays an independent precondition."""
    t = _walk(MotionBlobTracker(), dim=40, step=60, frames=2)

    assert t.coherent_track(FRAME_W) is None


def test_the_size_used_is_the_median_not_the_last_frame():
    """A frame-differenced blob's extent flickers. If the bound read
    `last_bbox` a track would qualify and disqualify on alternating frames
    from bbox noise alone, and the rescue would stutter with it."""
    t = MotionBlobTracker()
    for i, dim in enumerate((40, 40, 40, 600)):
        t.update([{"bbox": (100 + i * 20, 500, dim, dim), "solidity": 0.8}])
    track = t._tracks[0]

    assert track.median_dim == 40.0
    assert track.last_bbox[2] == 600
