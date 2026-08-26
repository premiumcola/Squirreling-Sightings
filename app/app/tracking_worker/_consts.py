"""Tuning constants + the tracks.json schema history.

Everything here is a literal the rest of the package reads; no logic,
no imports from siblings. The tracking ALGORITHM's own constants
(IOU_MATCH_THRESHOLD, TRACK_FLOOR_SCORE, TRACK_SPAWN_SCORE,
TRACK_MISS_WINDOWS, SAMPLE_BBOX_DELTA_PX) live in :mod:`tracker_core`
and are imported from there at each use site — they are shared with
the live camera path and must not fork.
"""

from __future__ import annotations

# Schema version of the tracks.json file. Bump when the shape changes;
# the reindex-all endpoint uses schema mismatch as the trigger to re-queue
# stale sidecars.
#
#   v1 — initial release (schema, video_path, fps, frame_count, duration_s,
#        best_frame, tracks, built_at).
#   v2 — adds top-level "filter_applied": list[str] | None recording the
#        camera's object_filter at write time. Detections with labels
#        outside the filter are dropped BEFORE track association, so the
#        sidecar only carries tracks the camera would have notified on.
#        None means "no filter, all classes accepted" (distinct from an
#        empty list).
#   v3 — ByteTrack-style two-tier association. The worker now pulls
#        detections at the raw model floor (TRACK_FLOOR_SCORE = 0.20)
#        and treats anything < TRACK_SPAWN_SCORE (0.50) as a tentative
#        sample that can only EXTEND an existing track via IoU — never
#        spawn. Combined with linear-velocity bbox prediction and a
#        wider miss window (TRACK_MISS_WINDOWS bumped from 2 to 4),
#        this keeps a single moving subject on ONE track id across
#        short low-confidence dips. Sample dicts gain no new fields;
#        the score history already lets the lightbox distinguish
#        confirmed vs. tentative frames.
#   v4 — K3 · adds top-level "gates" block recording the per-camera
#        TRACK_SPAWN_SCORE / TRACK_FLOOR_SCORE / miss-grace values
#        the worker actually applied. The Mediathek timeline panel
#        renders these inline when an indexed clip ends up with
#        tracks=[] so the user sees "Indexierung fertig · keine
#        Spuren bestätigt — kurze Sichtungen unter X % werden
#        gefiltert" instead of the ambiguous "Keine Track-Daten —
#        erscheinen sobald die Indexierung fertig ist" (which read
#        as "still running" when the indexer had in fact finished
#        and found nothing trackable).
TRACKS_SCHEMA = 4

# Detection-job timing target. A 30-second clip should finish in
# under ~10 s on CPU; anything slower triggers a one-line WARN so the
# operator notices a degraded run without losing frames.
SLOW_JOB_RATIO = 1.0 / 3.0  # processing time / clip duration

# Bounded ring of recent per-event failures the UI polls so it can tell
# the user *why* a re-index didn't produce a fresh sidecar. 32 is plenty
# for the polling interval to find a failure before it ages out.
RECENT_FAILURES_CAP = 32

# Confirmation-window fallbacks. Used when a camera carries no
# ``confirmation_window.global`` block — same numbers the wizard seeds.
DEFAULT_CONFIRM_N = 3
DEFAULT_CONFIRM_SECONDS = 5.0

# Global fallback for the per-label spawn threshold when neither the
# camera's label_thresholds nor its detection_min_score is set.
DEFAULT_MIN_SCORE = 0.55

# K1 · gates for the static-false-positive sweep. A tracklet is
# DROPPED at payload build when ALL of these hold:
#   * has at least STATIC_FP_MIN_DETECTS detect samples (so the
#     stats are meaningful — a 2-sample blip is left alone),
#   * MEDIAN of its detect-source scores < the clip's spawn
#     threshold (the model never had real confidence in this
#     subject — best_score sometimes spikes once just above spawn
#     for a chair/pole, but the median stays low),
#   * net centroid displacement from first to last detect sample
#     is < STATIC_FP_DISP_FRAC × min(median_bw, median_bh) (it
#     didn't move enough to be a person walking),
#   * max single-frame centroid step is also < the same fraction
#     (no momentary motion in the middle either — fully static).
# Real persons standing still consistently score ≥ spawn, so the
# score gate alone protects them. Real persons who walk fail the
# displacement gate.
STATIC_FP_MIN_DETECTS = 3
STATIC_FP_DISP_FRAC = 0.5

# K3 · global offline tracklet stitching parameters.
#
# Sequential stitch: tracklet A ends at time t_a_end, tracklet B
# starts at t_b_start. Linkable iff (same label) AND
# (gap ≤ STITCH_MAX_GAP_S) AND (centroid distance ≤
# STITCH_DIST_FACTOR × max(last_bw, last_bh, first_bw, first_bh))
# AND (size ratio between A.last and B.first ≤ STITCH_SIZE_RATIO).
#
# Parallel/overlap merge: two tracklets co-existing in time whose
# detect samples in the OVERLAP window have IoU ≥ STITCH_OVERLAP_IOU
# on every shared frame. Same label only.
STITCH_MAX_GAP_S = 6.0
STITCH_DIST_FACTOR = 1.6
STITCH_SIZE_RATIO = 1.8
STITCH_OVERLAP_IOU = 0.55
