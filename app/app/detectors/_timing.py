"""Per-stage inference timing, shared by every detector tier.

Split out of `coral_object.py` so the detector module stays under the
500-line ceiling and so a second stage can pick the mixin up without
copying the bucket definitions.
"""

from __future__ import annotations

import math
import time
from collections import deque

from ._utilisation import RollingUtilisation

# 60 samples ≈ 20 s of one camera's inference at ~3 Hz. Long enough to
# average out a single slow frame, short enough that the numbers still
# describe "now" rather than the last ten minutes.
_TIMING_WINDOW = 60

_BUCKETS = ("pre", "wait", "invoke", "post")


class InferenceTimingMixin:
    """Rolling per-stage timings for one interpreter.

    Consumers call `_init_timings()` from their `__init__`, then
    `_record_timing()` around each inference and `timing_breakdown()`
    to read the rolling averages back out.
    """

    # Set while a throwaway warmup inference is running. The cold first
    # invoke costs a multiple of the steady-state one, so counting it as
    # a sample would misreport the model as slow for the next 60 frames.
    _warming = False

    def _init_timings(self) -> None:
        self._timings: deque = deque(maxlen=_TIMING_WINDOW)
        # Same perf_counter timeline as the t_* arguments below, so the
        # invoke end-time recorded per sample is the one measured.
        self._utilisation = RollingUtilisation(clock=time.perf_counter)

    def _record_timing(self, t_pre: float, t_wait: float, t_invoke: float, t_post: float) -> None:
        """Store one inference split into its four real cost centres.

        The single `inference_avg_ms` the status bubble used to show
        wrapped all four together, which made it useless for deciding
        anything: a slow number could mean the TPU is loaded, or that
        another camera holds the lock, or merely that a 4-MP frame is
        expensive to letterbox on the CPU. Those call for opposite fixes.

          pre    — colour convert + letterbox + tensor prep (CPU, per frame)
          wait   — blocked on the inference lock (contention with another
                   caller — on the TPU tier, with every other camera)
          invoke — the actual inference (TPU or CPU compute)
          post   — reading output tensors back out
        """
        if self._warming:
            return
        now = time.perf_counter()
        self._utilisation.record(t_post - t_invoke, at=t_post)
        self._timings.append(
            {
                "pre": (t_wait - t_pre) * 1000.0,
                "wait": (t_invoke - t_wait) * 1000.0,
                "invoke": (t_post - t_invoke) * 1000.0,
                "post": (now - t_post) * 1000.0,
            }
        )

    def utilisation(self) -> dict:
        """Rolling ~10 s load of this interpreter — see ``_utilisation``."""
        return self._utilisation.snapshot()

    def timing_breakdown(self) -> dict:
        """Rolling averages in ms, or an empty dict before the first run.

        `wait_p95` is reported alongside the mean because contention is
        bursty by nature: three cameras whose inference intervals drift
        into phase stall each other for a few frames and then separate
        again. An average over 60 samples smears that into a number that
        looks harmless, while the stall is what actually drops a frame.
        """
        samples = list(self._timings)
        if not samples:
            return {}
        n = len(samples)
        out = {k: round(sum(s[k] for s in samples) / n, 1) for k in _BUCKETS}
        out["total"] = round(sum(out[k] for k in _BUCKETS), 1)
        out["wait_p95"] = round(_percentile([s["wait"] for s in samples], 0.95), 1)
        out["samples"] = n
        return out


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile. Exact on the small windows we keep, and
    it always returns a value that was really observed — an interpolated
    latency nobody measured is a poor thing to tune against."""
    ordered = sorted(values)
    idx = math.ceil(q * len(ordered)) - 1
    return ordered[max(0, min(len(ordered) - 1, idx))]
