"""D1 · light cross-frame motion-blob tracker for the wind-tolerant gate.

Associates RAW motion blobs (not Coral detections) across recent frames by
IoU / nearest-centroid and measures each track's NET DISPLACEMENT and
trajectory straightness. Per the B4 inventory (storage/_diag/motion_gate_*.md)
this is the ONLY cheap feature that separates a real animal (which translates
across the scene — dog 527 px / 21 % width, cat 286 px / 11 %) from wind in
foliage (which oscillates in place ≈ 0 net displacement). Per-blob solidity is
carried as a cheap support signal.

A blob track is "coherent" — and a wildlife-low motion event escalates to the
D2 ROI/tiling re-detection — only when it has persisted for ``min_age`` frames
AND its net displacement clears ``required_net_px``: ``min_net_frac`` of the
frame width as an upper bound, lowered towards the track's OWN size by
``size_coupling`` (SMALL-3), so the test scales with the subject rather than
with the frame. Conservative defaults ship until a real wind corpus exists
(prompt E); they are per-camera tunable (D3).

Pure logic, no OpenCV/Coral state — unit-testable in isolation.
"""

from __future__ import annotations

import math

from .bbox_utils import iou

# Conservative defaults (no wind corpus yet — see prompt E). The dog/cat
# samples translate 11–21 % of frame width; in-place shimmer is ~0 %. 4 % is
# comfortably above shimmer and well below either animal.
DEFAULT_MIN_NET_FRAC = 0.04
DEFAULT_MIN_AGE = 3

# SMALL-3 · how far a blob must travel measured in its OWN size. The
# `min_net_frac` bound above is absolute (4 % of 2560 px = 102 px) and so
# asks the same 102 px of a 400 px dog and of a 40 px squirrel. A squirrel
# working a feeder moves a body length or two and never reaches 102 px, so
# it was classified as in-place shimmer and the D2 rescue was never even
# offered it — the exact "small object" failure this package is about.
#
# k = 1.0 means "a subject must have moved by its own largest dimension".
# That is the scale-free version of the same intuition the absolute bound
# encodes, and it is what separates translation from shimmer at ANY size:
# vegetation oscillating in place returns to where it started regardless of
# how big the swaying patch is, so its net displacement stays near zero and
# it fails the coupled bound just as it failed the absolute one.
# 0 disables the coupling and restores purely absolute behaviour.
DEFAULT_SIZE_COUPLING = 1.0
_IOU_MATCH = 0.10  # blobs jump frame-to-frame; nearest-centroid backs up IoU
_MAX_MISSES = 4


class _BlobTrack:
    __slots__ = ("track_id", "centroids", "bboxes", "solidities", "last_frame", "misses")

    def __init__(self, track_id: int, bbox, centroid, solidity, frame_idx):
        self.track_id = track_id
        self.centroids = [centroid]
        self.bboxes = [bbox]
        self.solidities = [solidity]
        self.last_frame = frame_idx
        self.misses = 0

    def extend(self, bbox, centroid, solidity, frame_idx):
        self.centroids.append(centroid)
        self.bboxes.append(bbox)
        self.solidities.append(solidity)
        self.last_frame = frame_idx
        self.misses = 0

    @property
    def age(self) -> int:
        return len(self.centroids)

    @property
    def net_displacement(self) -> float:
        a, b = self.centroids[0], self.centroids[-1]
        return math.hypot(b[0] - a[0], b[1] - a[1])

    @property
    def path_length(self) -> float:
        total = 0.0
        for i in range(1, len(self.centroids)):
            x0, y0 = self.centroids[i - 1]
            x1, y1 = self.centroids[i]
            total += math.hypot(x1 - x0, y1 - y0)
        return total

    @property
    def straightness(self) -> float:
        p = self.path_length
        return self.net_displacement / p if p > 0 else 0.0

    @property
    def median_solidity(self) -> float:
        s = sorted(self.solidities)
        return s[len(s) // 2] if s else 0.0

    @property
    def median_dim(self) -> float:
        """Median of max(width, height) over the track's bboxes.

        The median rather than `last_bbox`: a frame-differenced blob's
        extent flickers frame to frame as parts of the subject stop and
        start moving, and the size-coupled displacement bound below would
        inherit that jitter — a track could qualify and disqualify on
        alternating frames purely from bbox noise.
        """
        d = sorted(float(max(b[2], b[3])) for b in self.bboxes)
        return d[len(d) // 2] if d else 0.0

    @property
    def last_bbox(self):
        return self.bboxes[-1]


def _centroid(bbox):
    x, y, w, h = bbox
    return (x + w / 2.0, y + h / 2.0)


def _to_xyxy(bbox):
    x, y, w, h = bbox
    return (x, y, x + w, y + h)


class MotionBlobTracker:
    """One instance per camera. Feed it the per-frame wildlife-low motion
    blobs; ask it whether any track shows coherent translation."""

    def __init__(self, iou_match: float = _IOU_MATCH, max_misses: int = _MAX_MISSES):
        self._tracks: list[_BlobTrack] = []
        self._next_id = 0
        self._frame_idx = 0
        self._iou_match = iou_match
        self._max_misses = max_misses

    def update(self, blobs):
        """blobs: list of dicts {bbox:(x,y,w,h), solidity:float}. Associates to
        existing tracks (IoU first, then nearest centroid), spawns new tracks
        for the unmatched, ages out stale ones. Returns the active tracks."""
        self._frame_idx += 1
        unmatched_tracks = set(range(len(self._tracks)))
        for b in blobs:
            bbox = b["bbox"]
            cen = _centroid(bbox)
            sol = float(b.get("solidity", 0.0))
            best_i, best_score = -1, 0.0
            bx = _to_xyxy(bbox)
            for ti in unmatched_tracks:
                tr = self._tracks[ti]
                ov = iou(bx, _to_xyxy(tr.last_bbox))
                # IoU when boxes overlap; otherwise a proximity score that
                # falls off with centroid distance (blobs can jump between
                # frames so pure IoU under-associates).
                if ov >= self._iou_match:
                    score = 1.0 + ov
                else:
                    lc = tr.centroids[-1]
                    dist = math.hypot(cen[0] - lc[0], cen[1] - lc[1])
                    diag = math.hypot(bbox[2], bbox[3]) + 1.0
                    score = max(0.0, 1.0 - dist / (4.0 * diag))
                if score > best_score:
                    best_score, best_i = score, ti
            if best_i >= 0 and best_score > 0.25:
                self._tracks[best_i].extend(bbox, cen, sol, self._frame_idx)
                unmatched_tracks.discard(best_i)
            else:
                self._tracks.append(_BlobTrack(self._next_id, bbox, cen, sol, self._frame_idx))
                self._next_id += 1
        # Age out tracks not matched this frame.
        for ti in unmatched_tracks:
            self._tracks[ti].misses += 1
        self._tracks = [t for t in self._tracks if t.misses <= self._max_misses]
        return self._tracks

    def required_net_px(self, track, frame_w, min_net_frac, size_coupling):
        """Net displacement this track must show to count as coherent.

        ``min_net_frac · frame_w`` is the CAP: the absolute bound is never
        exceeded, so `roi_min_net_disp_frac` keeps its meaning as the upper
        limit an operator can set. Under that cap the requirement falls to
        the track's own size, so a small subject qualifies by moving its own
        length while a large one still has to cross a real distance.
        """
        cap = max(1.0, float(min_net_frac) * float(frame_w))
        if size_coupling <= 0:
            return cap
        return max(1.0, min(cap, float(size_coupling) * track.median_dim))

    def coherent_track(
        self,
        frame_w,
        min_net_frac=DEFAULT_MIN_NET_FRAC,
        min_age=DEFAULT_MIN_AGE,
        size_coupling=DEFAULT_SIZE_COUPLING,
    ):
        """Return the strongest track showing coherent net translation, or
        None. 'Coherent' = persisted ≥ min_age frames AND net displacement ≥
        `required_net_px` (a real subject crossing, not in-place vegetation
        shimmer) — an absolute bound capped from below by the track's own
        size, so the test scales with the subject instead of the frame."""
        best = None
        for t in self._tracks:
            if t.age < min_age:
                continue
            if t.net_displacement < self.required_net_px(t, frame_w, min_net_frac, size_coupling):
                continue
            if best is None or t.net_displacement > best.net_displacement:
                best = t
        return best

    def reset(self):
        self._tracks = []
