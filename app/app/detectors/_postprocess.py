"""Model-space boxes → frame-space ``Detection`` list.

The tail both detector tiers share: undo the letterbox, clamp to the
frame, map the class id to its label, stamp the stage, drop the
impossible classes. Pure — no interpreter, no lock — so the pycoral and
the tflite tier cannot drift apart here, and the arithmetic has a test
that needs no model file.

Both tiers first reduce their raw output to the same tuple shape,
``(class_id, score, (xmin, ymin, xmax, ymax))`` in MODEL-pixel space:
``pycoral_snapshot`` for pycoral's object views (materialised inside the
inference lock — see ``CoralObjectDetector._detect_coral``), and
``ssd_snapshot`` for the SSD-MobileNet tensors, whose coordinates arrive
normalised to 0..1 and are scaled up to the model square here.
"""

from __future__ import annotations

from ._types import STAGE_DETECTOR, Detection, _apply_region_filter

Snapshot = list[tuple[int, float, tuple[float, float, float, float]]]


def pycoral_snapshot(objs) -> Snapshot:
    """Plain tuples from pycoral's ``get_objects`` result, so the tensor
    views are released before the next caller runs ``set_input``."""
    return [
        (
            int(o.id),
            float(o.score),
            (float(o.bbox.xmin), float(o.bbox.ymin), float(o.bbox.xmax), float(o.bbox.ymax)),
        )
        for o in objs
    ]


def ssd_snapshot(boxes, classes, scores, *, in_w: int, in_h: int, threshold: float) -> Snapshot:
    """SSD output order is boxes ``[N,4]`` as ``(ymin, xmin, ymax, xmax)``,
    classes ``[N]``, scores ``[N]``; rows under ``threshold`` are dropped
    here, the way pycoral's ``score_threshold`` drops them on the TPU."""
    out: Snapshot = []
    for i in range(len(scores)):
        score = float(scores[i])
        if score < threshold:
            continue
        ymin, xmin, ymax, xmax = boxes[i]
        out.append((int(classes[i]), score, (xmin * in_w, ymin * in_h, xmax * in_w, ymax * in_h)))
    return out


def to_detections(
    snapshot: Snapshot,
    *,
    frame_hw: tuple[int, int],
    scale: float,
    pad_x: float,
    pad_y: float,
    labels: dict,
    region_filter: bool,
) -> list[Detection]:
    """Inverse letterbox: subtract the pad, divide by the scale, clamp to
    the frame. ``scale``/``pad_*`` are what ``letterbox`` returned."""
    h, w = frame_hw
    inv_scale = 1.0 / scale if scale > 0 else 1.0
    out: list[Detection] = []
    for cid, score, (xmin, ymin, xmax, ymax) in snapshot:
        x1 = max(0, min(w, int(round((xmin - pad_x) * inv_scale))))
        y1 = max(0, min(h, int(round((ymin - pad_y) * inv_scale))))
        x2 = max(0, min(w, int(round((xmax - pad_x) * inv_scale))))
        y2 = max(0, min(h, int(round((ymax - pad_y) * inv_scale))))
        out.append(
            Detection(
                label=labels.get(cid, str(cid)),
                score=score,
                bbox=(x1, y1, x2, y2),
                raw_cls_id=cid,
                model=STAGE_DETECTOR,
            )
        )
    return _apply_region_filter(out, region_filter)
