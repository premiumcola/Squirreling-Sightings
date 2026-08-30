from __future__ import annotations

import time

from ..detect_setup import apply_object_filter
from ..detection_tiling import normalise_mode, tiled_detect
from ..motion_samples import record_sample as record_motion_sample
from ._consts import log

_UNSET = object()


# How much of the coherent motion blob a detection must cover before that
# detection counts as "this box explains the thing that moved". This is
# CONTAINMENT of the blob in the box, not IoU — see `_blob_containment`.
_RESCUE_BLOB_CONTAINMENT = 0.5

# Minimum seconds between two magnified re-detects on the same camera.
# The rescue's precondition (a coherent blob with no confirmable detection
# on it) persists for the whole time a subject crosses the scene, so without
# a brake the rescue fires on EVERY frame of that crossing — at a 150 ms
# frame interval that is ~400 extra region inferences per minute, on a CPU
# that is already the bottleneck because the TPU does not compute.
#
# 1.5 s is chosen against the confirmation contract downstream, not picked
# round: `_loop` confirms a label at n=3 hits within seconds=5.0 by default,
# and a 1.5 s spacing still delivers 4 attempts inside any 5 s window. A 2 s
# cooldown would deliver exactly 3 and leave no margin — one missed frame
# would then cost the confirmation entirely.
_RESCUE_MIN_INTERVAL_S = 1.5

_UNSET = object()


def _blob_containment(det_box, blob_box):
    """Fraction of ``blob_box`` that lies inside ``det_box``. Both ``x1y1x2y2``.

    NOT IoU. IoU is the wrong question here and was the original mistake.
    A motion blob comes from frame differencing, so it covers only the part
    of the subject that actually MOVED — it is a subset of the mover, and
    routinely a small and off-centre one. A person standing still and moving
    an arm produces a blob over the arm; IoU between that blob and the full
    person box is ``arm_area / person_area`` ≈ 0.08, under any sane
    threshold, so the gate concluded "nothing explains this motion" while a
    0.90 person box sat directly on top of it and fired the rescue anyway.

    Containment asks the question the gate actually means: is the thing that
    moved accounted for by this box? For the arm-in-person case it is 1.0.

    Containment is >= IoU for every pair of boxes (the union in the
    denominator is never smaller than the blob alone). That is true, and
    an earlier version of this comment drew a false conclusion from it:
    that the gate could therefore only ever fire LESS often. It cannot,
    because the threshold moved too — IoU >= 0.30 became containment
    >= 0.50, so the two gates are not comparable term by term.

    A worked counterexample, both boxes 50 px^2 with a 24 px^2 overlap:
    IoU = 24/76 = 0.32 cleared the old bar, containment = 24/50 = 0.48
    misses the new one. There the rescue now fires where it previously
    did not. The band is narrow, but it is not empty, and the cost of
    the change is bounded by the cooldown below rather than by this
    inequality.

    The honest degenerate case: a detection box covering most of the frame
    contains every blob and would suppress the rescue wholesale. That box
    still has to clear its spawn floor to get here, and a detection that
    confident is one worth believing, so it is left as-is rather than
    guarded with an area ratio — an area ratio is exactly what would
    re-break the arm-in-person case above.

    Belongs in `bbox_utils` next to `iou` as the second primitive; kept
    local only because that module is outside this change's file scope.
    """
    ax1, ay1, ax2, ay2 = det_box
    bx1, by1, bx2, by2 = blob_box
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    blob_area = max(0, bx2 - bx1) * max(0, by2 - by1)
    if inter <= 0 or blob_area <= 0:
        return 0.0
    return inter / blob_area


def _confirmable_on_blob(detections, blob, spawn_for, min_containment=_RESCUE_BLOB_CONTAINMENT):
    """Does any surviving detection both clear its spawn floor AND explain the blob?

    The D2 rescue used to be skipped whenever ``detections`` was non-empty.
    One weak, wrong box — COCO reading a distant squirrel as "cat" at 0.30,
    far below any spawn threshold — was therefore enough to suppress the
    magnified re-detect entirely. That is exactly the case small and distant
    subjects produce: the detector sees *something*, names it wrong and
    weakly, and the suppression fires because of it.

    What matters is not whether the detector returned anything, but whether
    anything it returned is confirmable and actually explains the blob that
    moved. Everything else leaves the rescue's reason to run intact.
    """
    if blob is None:
        return False
    bx, by, bw, bh = blob.last_bbox
    blob_box = (bx, by, bx + bw, by + bh)
    for d in detections:
        if float(d.score) < float(spawn_for(d.label)):
            continue
        if _blob_containment(tuple(d.bbox), blob_box) >= min_containment:
            return True
    return False


class RescueMixin:
    """D1/D2 · the magnified re-detect around a coherent motion blob.

    Split out of ``_main_loop`` because that file was 1040 lines before
    this commit and CLAUDE.md caps a Python file at 500: extract first,
    then edit. The rescue is the natural seam — it is the only part of the
    loop with its own gate (``_confirmable_on_blob``), its own brake
    (``_RESCUE_MIN_INTERVAL_S``) and its own tests
    (``test_small_rescue_*``, ``test_roi_rescue_counters``).

    Mixin for CameraRuntime. Methods access shared state via `self.*`
    (detector, tracker, config) which live on the concrete class.
    """

    def _effective_roi_mode(self) -> str:
        """The camera's roi_mode, warning once per distinct bad value.

        `normalise_mode` logs when it has to fall back; calling it from the
        frame loop would emit that warning several times a second. The last
        raw value is remembered so a typo is reported when it appears and
        when it changes, and stays quiet in between.
        """
        raw = self.cfg.get("roi_mode")
        if raw == getattr(self, "_roi_mode_raw", _UNSET):
            return self._roi_mode_effective
        mode = normalise_mode(raw)
        self._roi_mode_raw = raw
        self._roi_mode_effective = mode
        return mode

    def _rescue_cooldown_ready(self, now):
        """Has enough time passed since the last magnified re-detect?

        Split out of `_loop` so the brake can be tested without standing up
        a camera. Read-only: the timestamp is stamped by the caller once it
        has decided to actually spend the inference, so a frame that clears
        the cooldown but is then found to have a confirmable detection does
        not restart the clock.
        """
        return (now - getattr(self, "_roi_rescue_last_ts", 0.0)) >= _RESCUE_MIN_INTERVAL_S

    def _roi_rescue(self, proc_frame, raw_detections, blob, det_mode, allowed, excluded):
        """D2 · magnified re-detect around a coherent motion blob.

        Returns the detection list the rest of the frame should work with.
        The full-frame pass the loop already ran is handed to `tiled_detect`
        instead of being repeated, so an attempt costs the region inferences
        only — on CPU, with the TPU down, that saved invoke is the single
        largest cost item in this path.
        """
        # M2 · count every attempt, not just the successes. "How often did
        # the rescue fire, and how often did it actually save something" is
        # unanswerable from the log alone if only hits are recorded.
        self._roi_rescue_attempts += 1
        self._roi_rescue_log.append(time.time())
        mbox = blob.last_bbox if det_mode == "roi" else None
        roi_dets, _sahi = tiled_detect(
            self.detector,
            proc_frame,
            det_mode,
            threshold=self._tracker.floor,
            motion_box=mbox,
            full_dets=raw_detections,
        )
        # Same gate order as the full-frame path: class filter, then mask,
        # then zones. Both halves of the class gate travel together — a
        # magnified re-detect that resurrected an excluded class would be
        # the exclusion's only leak.
        roi_dets, _ = apply_object_filter(roi_dets, allowed, excluded)
        roi_dets = self._filter_masked_detections(proc_frame, roi_dets)
        roi_dets = self._filter_zoned_detections(proc_frame, roi_dets)
        # Only boxes that came out of a magnified region are "via roi" — the
        # full-frame boxes travelled through the merge unchanged and marking
        # them too would make the D4 provenance flag meaningless, and would
        # let a pre-existing weak box count as a rescue hit.
        seen = {id(d) for d in raw_detections}
        gained = [d for d in roi_dets if id(d) not in seen]
        for d in gained:
            d.via_roi = True
        if gained:
            self._roi_rescue_hits += 1
            log.info(
                "[%s] D2 ROI rescue (%s): %d hit(s) on coherent blob "
                "net=%.0fpx straight=%.2f zoom=%s → %s",
                self.camera_id,
                det_mode,
                len(gained),
                blob.net_displacement,
                blob.straightness,
                _sahi.get("magnification"),
                ",".join(sorted({d.label for d in gained})),
            )
        # E1 · persist a labeled motion sample (kept ≈ animal, empty ≈
        # wind/noise) for offline threshold calibration.
        record_motion_sample(
            self.global_cfg.get("storage", {}).get("root"),
            self.camera_id,
            blob,
            bool(gained),
            det_mode,
            time.time(),
            proc_frame.shape[1],
        )
        return roi_dets
