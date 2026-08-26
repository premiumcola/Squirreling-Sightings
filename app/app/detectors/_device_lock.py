"""One lock per physical Edge TPU, shared by every interpreter in the
process.

An Edge TPU is owned by a single process and serves one invoke at a
time; a second process trying to claim the stick aborts outright. Inside
the one process that owns it, though, nothing stopped several threads
from calling invoke() concurrently — `camera_runtime/runtime.py` builds
ONE detector per camera, and the lock each detector created for itself
only ever protected that detector against its own re-entry.

The queueing still happened, down in libedgetpu, where it is invisible.
That is what makes it worth fixing even though the driver was "handling"
it: the per-stage timing split (`_timing.InferenceTimingMixin`) attributes
time to `invoke` when a thread is stuck inside the driver, and to `wait`
when it is stuck on our lock. Contention that hides in `invoke` is
indistinguishable from a genuinely slow model, and those two call for
opposite fixes. Taking the lock ourselves moves the cost into the bucket
that names it.

Which tier gets which lock is the whole design:

  * TPU tier  (``mode == "coral"``) — the process-wide lock for that
    device. All cameras queue on it.
  * CPU tier  (``mode == "cpu"``)   — a fresh per-instance lock. CPU
    interpreters must run in PARALLEL; serialising them is precisely the
    throughput the second-stage classifiers were moved off the TPU to
    gain (see `_CLASSIFIER_CPU_NOTE` in `_edgetpu.py`). The instance lock
    still does its original job of stopping one interpreter being
    re-entered by the simulate-now endpoint mid-inference.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

# Guards the registry itself, not the devices — held only long enough to
# hand back a lock, never across an inference.
_REGISTRY_GUARD = threading.Lock()
_DEVICE_LOCKS: dict[str, threading.Lock] = {}

# Key used when no device is named. `load_delegate` with no device option
# takes the default stick, so every caller that leaves `device` unset is
# talking to the SAME piece of silicon and must share one lock.
_DEFAULT_DEVICE = "default"


def _device_key(device: str | None) -> str:
    """Normalise a device hint to a registry key.

    Known limit: an explicit ``"usb:0"`` and an unset device may well be
    the same stick, and this keying would then hand out two locks for one
    device. Nothing can resolve that from the hint alone — libedgetpu
    does not tell us which device it picked. On a one-stick box (this
    deployment) the config either names the device everywhere or nowhere,
    so the keys agree; the split only exists so a genuine two-stick setup
    is not needlessly serialised.
    """
    return (device or "").strip().lower() or _DEFAULT_DEVICE


def tpu_device_lock(device: str | None) -> threading.Lock:
    """Return the process-wide lock for one Edge TPU device."""
    key = _device_key(device)
    with _REGISTRY_GUARD:
        lock = _DEVICE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _DEVICE_LOCKS[key] = lock
            log.info("[det] TPU-Lock angelegt für Gerät '%s'", key)
        return lock


def inference_lock(mode: str, device: str | None) -> threading.Lock:
    """The lock an interpreter running in `mode` must hold around invoke.

    Call this once the tier is decided, not before — the whole point is
    that the answer differs per tier. See the module docstring.
    """
    if mode == "coral":
        return tpu_device_lock(device)
    return threading.Lock()
