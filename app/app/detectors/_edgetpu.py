"""Shared EdgeTPU-delegate helper for the three detector tiers.

pycoral is the canonical Coral binding, but it only publishes wheels for
Python 3.7-3.9 and the image runs 3.11 — so tier 1 always fails here and
the stick sits idle while inference runs on CPU. The same silicon is
reachable from plain tflite-runtime by loading libedgetpu as an external
delegate, which needs no pycoral and therefore no second Python-3.9
image. Detectors use this as tier 1b, between pycoral and the CPU
fallback.

The delegated interpreter exposes the ordinary tflite Interpreter API
(set_tensor / invoke / get_tensor), so callers reuse their existing
tflite parse path unchanged — only the interpreter construction differs.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# libedgetpu ships under a different filename per platform. Linux is the
# only one that matters for the container; the others keep a dev machine
# from silently falling through to CPU.
_DELEGATE_LIBS = ("libedgetpu.so.1", "libedgetpu.1.dylib", "edgetpu.dll")


def make_delegate_interpreter(model_path: str, device: str | None = None):
    """Return an EdgeTPU-delegated tflite Interpreter, or None.

    Returns None rather than raising whenever the TPU route is
    unavailable — no compiled model, no libedgetpu, no stick plugged in —
    so every caller can fall through to its CPU tier unchanged.
    """
    if not model_path or "_edgetpu" not in model_path:
        # A delegate attached to a non-compiled model loads fine but runs
        # every op on CPU, which would report "TPU active" while
        # delivering CPU latency. Refuse rather than lie about the mode.
        return None
    try:
        import tflite_runtime.interpreter as tflite  # type: ignore
    except Exception as e:
        log.warning("[det] tflite-runtime nicht importierbar für EdgeTPU-Delegate: %s", e)
        return None
    options = {"device": device} if device else {}
    last_error: Exception | None = None
    for lib in _DELEGATE_LIBS:
        try:
            delegate = tflite.load_delegate(lib, options)
        except Exception as e:
            last_error = e
            continue
        try:
            interp = tflite.Interpreter(model_path=model_path, experimental_delegates=[delegate])
            interp.allocate_tensors()
            return interp
        except Exception as e:
            # Library resolved but the TPU refused the model — trying the
            # remaining names would hit the same device, so stop here.
            last_error = e
            break
    # Actionable: the model IS edgetpu-compiled, so the operator expects
    # the TPU. Surface why it did not engage instead of dropping to CPU
    # silently — that silence is what hid an idle stick for months.
    log.warning("[det] EdgeTPU-Delegate nicht verfügbar (%s): %s", model_path, last_error)
    return None
