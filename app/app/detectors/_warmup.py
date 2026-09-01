"""Warmup + tier activation for ``CoralObjectDetector``.

Mixin: every attribute it touches (``mode``, ``device``, ``cfg``,
``interpreter``, ``_infer_lock``, ``_try_cpu``) lives on the concrete
detector. Split out of ``coral_object.py`` at the file ceiling — the
warmup is one concern (prove the chosen tier can actually run an
inference, off the constructing thread) and reads as one.
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from ._device_lock import inference_lock

log = logging.getLogger(__name__)

# Size of the throwaway warmup frame. 4:3 rather than square so the
# warmup exercises the letterbox padding branch as well, and small
# enough that the resize itself costs nothing next to the invoke.
_WARMUP_W, _WARMUP_H = 320, 240


class WarmupMixin:
    def _on_warmup_failed(self, exc: Exception) -> None:
        """Treat a failed warmup as a failed TIER, not a slow first frame.

        The warmup started life as a latency optimisation. It turned out
        to be the only thing that ever checks whether the chosen tier can
        actually run an inference — and on a real box it caught exactly
        that:

            Encountered an unresolved custom op … Node number 8
            (EdgeTpuDelegateForCustomOp) failed to invoke.

        The delegate had loaded, so `_try_delegate` reported success and
        the detector advertised `mode="coral"`, `available=True`. Every
        real frame then raised the same error, no detection ever
        survived, no motion event was ever built, and nothing downstream
        could tell the difference between "nothing moved" and "the
        detector is dead". `load_delegate` succeeding proves a device is
        present; it proves nothing about the compiled model matching the
        installed libedgetpu.

        So on the TPU path a failed warmup drops to the CPU tier, which
        runs the non-compiled twin of the same model. Slower, and
        correct — the opposite trade of staying fast and blind. On the
        CPU tier there is nowhere left to fall, so the failure is logged
        and the detector stays up: a synthetic black frame is a weak
        reason to refuse real ones.
        """
        if self.mode != "coral":
            log.warning("[det] Warmup fehlgeschlagen (%s) – Detektor bleibt verfügbar", exc)
            return
        log.error(
            "[det] TPU-Warmup fehlgeschlagen (%s) – der Delegate lädt, kann aber "
            "nicht rechnen. Fallback auf CPU, sonst bliebe die Erkennung stumm.",
            exc,
        )
        model_path = self.cfg.get("model_path") or ""
        with self._infer_lock:
            self._coral_error = f"warmup failed: {exc}"
            self.interpreter = None
            self.available = False
            self.mode = "motion_only"
            self._cpu_mode = False
            recovered = self._try_cpu(model_path)
        if recovered:
            # The lock identity depends on the tier — a CPU detector must
            # not keep holding the process-wide TPU lock, or it would
            # serialise itself against the other cameras for no reason.
            self._infer_lock = inference_lock(self.mode, self.device)
            log.info("[det] Nach fehlgeschlagenem TPU-Warmup auf CPU umgestellt")
        else:
            self.reason = f"tpu warmup failed, no CPU fallback: {exc}"
            log.error("[det] Kein CPU-Modell als Rückfall vorhanden – nur Bewegungserkennung aktiv")

    def _activate_tier(self) -> None:
        """Wiring that can only happen once the tier is known.

        Called from every successful tier, never from the failure path —
        an unavailable detector runs no inference and needs neither.
        """
        self._infer_lock = inference_lock(self.mode, self.device)
        # Warm up OFF the constructing thread. A detector is not built in
        # the background: rebuild_runtimes / restart_single_camera reach
        # here from Flask request threads (camera save, wizard, settings
        # import, /api/reload) and from the Telegram bot thread, and the
        # Coral test panel builds one per HTTP request. Since the device
        # lock is now process-wide, a synchronous warmup would park those
        # threads behind whatever is currently on the TPU — including the
        # model-switch route, which is precisely the escape hatch from a
        # wedged stick. A daemon thread keeps the latency win (the first
        # real frame still finds a warm interpreter) without ever holding
        # a request hostage.
        self._warmup_thread = threading.Thread(
            target=self._warmup,
            name=f"det-warmup-{self.mode}",
            daemon=True,
        )
        self._warmup_thread.start()

    def wait_for_warmup(self, timeout: float = 30.0) -> bool:
        """Block until the warmup finishes. Returns False on timeout.

        Production never needs this — the warmup races the first frame
        and losing that race merely costs one slow frame. It exists so
        tests can assert on warmup deterministically instead of sleeping,
        and so a future diagnostic endpoint can report readiness.
        """
        thread = getattr(self, "_warmup_thread", None)
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _warmup(self) -> None:
        """Run one throwaway inference so the first real frame is warm.

        On the TPU the first invoke pushes the model parameters across
        USB into the device's on-chip cache; on CPU it triggers the
        first-call allocations. Either way the cost lands on whichever
        frame happens to be first — which, after a restart or a settings
        save, is the first motion event, the one frame we would least
        like to be slow.

        Failure is deliberately non-fatal. Warmup is a latency
        optimisation, and a detector that stumbles on a synthetic black
        frame may well be fine on a real one; refusing to come up would
        convert a slow first frame into no detection at all. The reason
        is logged rather than swallowed silently — on the real box it
        would be the first sign the model and the delegate disagree.
        """
        frame = np.zeros((_WARMUP_H, _WARMUP_W, 3), dtype=np.uint8)
        started = time.perf_counter()
        # Keep the cold sample out of the rolling window — see
        # _record_timing. It is not a measurement of steady state.
        self._warming = True
        try:
            # threshold=1.0: run the full path but keep the post-filter
            # work at zero. We want the invoke, not the detections.
            self.detect_frame_raw(frame, threshold=1.0)
        except Exception as e:
            self._warming = False
            self._on_warmup_failed(e)
            return
        finally:
            self._warming = False
        log.info(
            "[det] Warmup abgeschlossen (%s): %.0f ms",
            self.mode,
            (time.perf_counter() - started) * 1000.0,
        )
