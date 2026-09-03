"""Tensor plumbing for the wildlife cascade's two interpreters.

`WildlifeClassifier` drives two models — MobileNet on ImageNet labels and
an optional iNaturalist second opinion — and used to carry a private copy
of the same forty lines for each: resize, normalise, invoke, argsort,
dequantise, cut at a floor. The two copies had already drifted (only one
of them knew about the 1000/1001 label offset), which is the usual end
state for a duplicated inference path.

One set of functions here, called twice. They are deliberately free
functions rather than methods: neither model's plumbing depends on any
classifier state beyond what is passed in, and keeping them stateless is
what lets a test drive them with a fake interpreter.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

# Nothing below the collector floor is worth a label — a floor derived
# from a very small configured threshold still must not admit noise.
MIN_COLLECT_FLOOR = 0.05


def collect_floor(min_score: float) -> float:
    """The score below which a candidate is not even collected.

    HALF the configured threshold on purpose: `classify_crop`'s
    cross-validation step needs to see weak evidence from both models
    (a "squirrel-likely" label at 0.40 still counts when the iNat model
    independently confirms a Sciuridae genus), so the collector is more
    permissive than the operator's knob.
    """
    return max(MIN_COLLECT_FLOOR, float(min_score) * 0.5)


def _dequantise(raw, output_detail) -> np.ndarray:
    """Per-class probabilities from one output tensor.

    A quantised model emits uint8/int8 bins that mean nothing until the
    model's own scale and zero point are applied; a float model is
    already probabilities. Converted to float64 FIRST — subtracting the
    zero point from a uint8 array in place would wrap around, which is
    the bug the "sort the array, don't argsort the negation" comment in
    the original path was working around.
    """
    arr = np.asarray(raw, dtype=np.float64)
    if output_detail["dtype"] not in (np.uint8, np.int8):
        return arr
    q = output_detail.get("quantization", (0.0, 0))
    scale = float(q[0]) if q and q[0] else 0.0
    zero_point = int(q[1]) if q else 0
    if scale:
        return (arr - zero_point) * scale
    # No scale published: the best available reading of a uint8 bin.
    return arr / 255.0


def run_tflite(interpreter, crop: np.ndarray) -> tuple[np.ndarray, tuple]:
    """One plain tflite-runtime inference on ``crop``.

    Returns ``(probabilities, marks)`` where ``marks`` is the
    ``(t_pre, t_wait, t_invoke, t_post)`` quadruple ``_record_timing``
    takes. There is no inference lock on this stage (see `_device_lock`'s
    "known gap"), so wait is structurally zero and the same mark serves
    for both.
    """
    t_pre = time.perf_counter()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    in_h = input_details[0]["shape"][1]
    in_w = input_details[0]["shape"][2]
    in_dtype = input_details[0]["dtype"]
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (in_w, in_h))
    inp = np.expand_dims(resized, axis=0)
    if in_dtype == np.float32:
        inp = (inp.astype(np.float32) - 127.5) / 127.5
    else:
        inp = inp.astype(in_dtype)
    interpreter.set_tensor(input_details[0]["index"], inp)
    t_invoke = time.perf_counter()
    interpreter.invoke()
    t_post = time.perf_counter()
    raw = interpreter.get_tensor(output_details[0]["index"])[0]
    return _dequantise(raw, output_details[0]), (t_pre, t_invoke, t_invoke, t_post)


def top_k_labels(
    probs: np.ndarray,
    labels: dict,
    *,
    floor: float,
    label_offset: int = 0,
    top_k: int = 3,
) -> list[tuple[str, float]]:
    """The ``top_k`` highest-scoring classes above ``floor``, named.

    Stops at the first candidate under the floor rather than filtering:
    the list is already score-descending, so everything after it is too.
    An id with no label degrades to its own index — a mislabelled model
    should still be diagnosable from the logs.
    """
    out: list[tuple[str, float]] = []
    for idx in np.argsort(probs)[::-1][:top_k]:
        i = int(idx)
        score = float(probs[i])
        if score < floor:
            break
        out.append((labels.get(i - label_offset, str(i)), score))
    return out


def run_coral(common, classify, interpreter, crop: np.ndarray, labels: dict, *, floor: float):
    """One pycoral inference, already reduced to ``(label, score)`` pairs.

    pycoral does its own top-k and thresholding on the device, so there
    is no probability array to rank here — the split between "run" and
    "rank" that the tflite path needs does not exist on this one.
    """
    t_pre = time.perf_counter()
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
    width, height = common.input_size(interpreter)
    resized = cv2.resize(rgb, (width, height))
    common.set_input(interpreter, resized)
    t_invoke = time.perf_counter()
    interpreter.invoke()
    t_post = time.perf_counter()
    classes = classify.get_classes(interpreter, top_k=3, score_threshold=floor)
    named = [(labels.get(int(c.id), str(c.id)), float(c.score)) for c in classes]
    return named, (t_pre, t_invoke, t_invoke, t_post)
