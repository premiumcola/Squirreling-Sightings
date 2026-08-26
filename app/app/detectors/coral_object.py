"""CoralObjectDetector — three-tier (pycoral / tflite-runtime CPU /
motion-only) COCO-style object detector.

Carved out of `_legacy_classes.py` during R02.2.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time

import cv2
import numpy as np

from ._decision_log import log_decision
from ._device_lock import inference_lock
from ._edgetpu import make_delegate_interpreter
from ._label_loader import load_label_map
from ._preprocess import letterbox
from ._timing import InferenceTimingMixin
from ._types import Detection, _apply_region_filter

log = logging.getLogger(__name__)

# Size of the throwaway warmup frame. 4:3 rather than square so the
# warmup exercises the letterbox padding branch as well, and small
# enough that the resize itself costs nothing next to the invoke.
_WARMUP_W, _WARMUP_H = 320, 240


class CoralObjectDetector(InferenceTimingMixin):
    """Object detector with three-tier fallback:
    1. pycoral + EdgeTPU  → mode="coral"
    2. tflite-runtime CPU → mode="cpu"
    3. No detection       → mode="motion_only"
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = self.cfg.get("mode", "none") in {"coral", "future_coral"}
        self.available = False
        self.reason = "disabled"
        self.mode = "motion_only"  # "coral" | "cpu" | "motion_only"
        self.labels = load_label_map(self.cfg.get("labels_path"))
        self.min_score = float(self.cfg.get("min_score", 0.55))
        # Region filter: drop implausible COCO labels (elephant, zebra, …)
        # after detection. On by default. See IMPOSSIBLE_LABELS for the set.
        self._region_filter = bool(self.cfg.get("region_filter_enabled", True))
        self.interpreter = None
        self.common = None
        self.detect = None
        self._cpu_mode = False  # True when using tflite-runtime instead of pycoral
        self.device = self.cfg.get("device")
        # Explicit "stay off the TPU" switch. Setting device=None is NOT
        # enough: the EdgeTPU delegate takes the default device when no
        # device option is given, so a caller that only nulled the device
        # still lands on the TPU. Callers that must not contend for it —
        # the post-clip tracking worker, and the CPU half of a hybrid
        # CPU+TPU split — set prefer_cpu and go straight to tier 2.
        self._prefer_cpu = bool(self.cfg.get("prefer_cpu"))
        # Thread count for CPU interpreters. None = tflite's
        # implementation-dependent default. Worth capping on a box that
        # also software-decodes several RTSP streams.
        self._cpu_threads = self.cfg.get("cpu_threads")
        # Serialise set_tensor → invoke → get_tensor. The interpreter is
        # NOT thread-safe — when the runtime loop and the simulate-now
        # endpoint hit it concurrently, two effects collide:
        #   1. tflite raises "There is at least 1 reference to internal
        #      data in the interpreter …" because a numpy view from a
        #      previous get_tensor() is still live when set_tensor() runs.
        #   2. EdgeTPU invokes can produce inconsistent output if a
        #      second invoke starts before the previous one's output
        #      tensors are read.
        # The lock covers the entire read-from-output phase so callers
        # always observe a consistent snapshot.
        #
        # Provisional: WHICH lock is right depends on the tier this
        # detector ends up on, which is not known yet. `_activate_tier`
        # rebinds it once that is decided — process-wide for the TPU,
        # per-instance for CPU. See `_device_lock`.
        self._infer_lock = threading.Lock()
        # Rolling per-stage inference timings — see _record_timing.
        self._init_timings()
        if not self.enabled:
            return
        # Startup diagnostic: log the label file path + first 25 entries so
        # label-mapping mistakes surface immediately instead of showing up as
        # "crow detected as elephant" weeks later.
        lp = self.cfg.get("labels_path")
        sample = {k: self.labels[k] for k in sorted(self.labels)[:25]}
        log.info(
            "CoralObjectDetector labels: %s — %d entries, head=%s", lp, len(self.labels), sample
        )
        model_path = self.cfg.get("model_path")
        if not model_path:
            self.reason = "missing model_path"
            return

        coral_error = "prefer_cpu"
        if not self._prefer_cpu:
            # ── Tier 1: pycoral + Coral TPU ────────────────────────────────
            try:
                from pycoral.adapters import common, detect  # type: ignore
                from pycoral.utils.edgetpu import make_interpreter  # type: ignore

                self.common = common
                self.detect = detect
                self.interpreter = make_interpreter(model_path, device=self.device)
                self.interpreter.allocate_tensors()
                self.available = True
                self.mode = "coral"
                self.reason = "ok"
                log.info("[det] Coral TPU aktiv: %s", model_path)
                self._activate_tier()
                return
            except Exception as e:
                log.warning("[det] pycoral nicht verfügbar (%s) – versuche EdgeTPU-Delegate…", e)
                coral_error = str(e)

            # ── Tier 1b: EdgeTPU via tflite-runtime delegate ───────────────
            # Same silicon as tier 1, reached without pycoral. Output is
            # plain SSD, so the tflite parse path handles it — only the
            # interpreter construction differs, hence _cpu_mode (= "uses
            # the tflite API") is True while mode stays "coral" (= "runs
            # on the TPU").
            delegated = make_delegate_interpreter(model_path, self.device)
            if delegated is not None:
                self.interpreter = delegated
                self._cpu_mode = True
                self.available = True
                self.mode = "coral"
                self.reason = "edgetpu_delegate"
                log.info("[det] Coral TPU aktiv (EdgeTPU-Delegate): %s", model_path)
                self._activate_tier()
                return

        # ── Tier 2: tflite-runtime CPU fallback ────────────────────────────
        # For EdgeTPU models (*_edgetpu.tflite) try the non-EdgeTPU variant.
        cpu_model = self.cfg.get("cpu_model_path")
        if not cpu_model:
            cpu_model = model_path.replace("_edgetpu.tflite", ".tflite")
            if cpu_model == model_path:
                cpu_model = None  # same path → no CPU variant available

        for try_path in filter(None, [cpu_model, model_path]):
            try:
                import tflite_runtime.interpreter as tflite  # type: ignore

                kwargs = {"model_path": try_path}
                if self._cpu_threads:
                    kwargs["num_threads"] = int(self._cpu_threads)
                interp = tflite.Interpreter(**kwargs)
                interp.allocate_tensors()
                self.interpreter = interp
                self._cpu_mode = True
                self.available = True
                self.mode = "cpu"
                self.reason = (
                    "cpu_requested" if self._prefer_cpu else f"cpu_fallback (coral: {coral_error})"
                )
                log.info(
                    "[det] CPU-Inferenz aktiv: %s (threads=%s, %s)",
                    try_path,
                    self._cpu_threads or "default",
                    "angefordert" if self._prefer_cpu else "Fallback",
                )
                self._activate_tier()
                return
            except Exception as e2:
                log.warning("[det] CPU-Inferenz fehlgeschlagen für %s: %s", try_path, e2)

        # Every tier failed. Name the tier that was actually tried —
        # blaming pycoral when the caller asked for CPU sends whoever
        # reads this log looking in the wrong place.
        self.reason = (
            "cpu requested but no usable CPU model"
            if self._prefer_cpu
            else f"pycoral: {coral_error}"
        )
        log.warning(
            "[det] Kein Detektor verfügbar (%s) – nur Bewegungserkennung aktiv", self.reason
        )

    def _activate_tier(self) -> None:
        """Wiring that can only happen once the tier is known.

        Called from every successful tier, never from the failure path —
        an unavailable detector runs no inference and needs neither.
        """
        self._infer_lock = inference_lock(self.mode, self.device)
        self._warmup()

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
            log.warning("[det] Warmup fehlgeschlagen (%s) – Detektor bleibt verfügbar", e)
            return
        finally:
            self._warming = False
        log.info(
            "[det] Warmup abgeschlossen (%s): %.0f ms",
            self.mode,
            (time.perf_counter() - started) * 1000.0,
        )

    # Per-label minimum bounding-box constraints. Surveillance cameras at
    # fixed positions almost never see a real person at <15% frame height
    # or <2% frame area — a small "person" box is overwhelmingly a false
    # positive (wood grain, shadow, distant silhouette). Keys are COCO
    # labels; values are (min_height_frac, min_area_frac).
    _LABEL_MIN_BBOX: dict[str, tuple[float, float]] = {
        "person": (0.15, 0.02),
    }

    def detect_frame(
        self,
        frame: np.ndarray,
        min_score: float | None = None,
        label_thresholds: dict[str, float] | None = None,
        *,
        cam_id: str | None = None,
    ) -> list[Detection]:
        """Run detection.

        `min_score` is the global confidence floor (defaults to cfg).
        `label_thresholds` is an optional per-label override applied as a
        post-filter — any detection whose label appears in the dict is
        kept only if its score >= the dict value. Lets the user crank up
        the bar for "person" without sacrificing recall on cat/bird.
        `cam_id` is purely for diagnostic logging — when provided AND the
        ``app.app.detectors`` logger is at INFO or below, the detector
        emits a one-line "[det][cam:<id>] kept/dropped" trace.
        """
        if not self.available:
            return []
        threshold = (
            float(min_score) if (min_score is not None and min_score > 0) else self.min_score
        )
        if self._cpu_mode:
            dets = self._detect_cpu(frame, threshold)
        else:
            dets = self._detect_coral(frame, threshold)
        kept, drops = self._apply_label_filters_with_reasons(
            dets,
            frame,
            label_thresholds,
            threshold,
        )
        if cam_id:
            with contextlib.suppress(Exception):
                log_decision(cam_id, kept, drops)
        return kept

    def _apply_label_filters_with_reasons(
        self,
        dets: list[Detection],
        frame: np.ndarray,
        label_thresholds: dict[str, float] | None,
        global_threshold: float,
    ) -> tuple[list[Detection], list[tuple[Detection, str]]]:
        """Same gates as _apply_label_filters but also returns a parallel
        list of (detection, drop_reason) for the diagnostic logger. Hot
        path: the reason-string formatting only happens for dropped
        detections — the kept-list path is one append per kept det."""
        out: list[Detection] = []
        drops: list[tuple[Detection, str]] = []
        if not dets:
            return out, drops
        h, w = frame.shape[:2]
        frame_area = float(max(1, h * w))
        for d in dets:
            # Per-label confidence override.
            if label_thresholds:
                t = label_thresholds.get(d.label)
                if t is not None and d.score < float(t):
                    drops.append((d, f"label_threshold({d.label})={t} (got {d.score:.2f})"))
                    continue
            # Per-label size floor (currently only "person").
            min_h_frac, min_area_frac = self._LABEL_MIN_BBOX.get(d.label, (0.0, 0.0))
            if min_h_frac > 0.0 or min_area_frac > 0.0:
                x1, y1, x2, y2 = d.bbox
                bb_h = max(0, y2 - y1)
                bb_area = max(0, (x2 - x1) * (y2 - y1))
                if bb_h < min_h_frac * h:
                    drops.append((d, f"size_floor (h_frac={bb_h / h:.2f} < {min_h_frac:.2f})"))
                    continue
                if bb_area < min_area_frac * frame_area:
                    drops.append(
                        (
                            d,
                            f"size_floor (area_frac={bb_area / frame_area:.3f} < {min_area_frac:.3f})",
                        )
                    )
                    continue
            out.append(d)
        return out, drops

    # Back-compat alias — anything that historically called
    # _apply_label_filters keeps the old single-return-value semantics.
    def _apply_label_filters(self, dets, frame, label_thresholds):
        kept, _ = self._apply_label_filters_with_reasons(
            dets,
            frame,
            label_thresholds,
            self.min_score,
        )
        return kept

    def detect_frame_raw(self, frame: np.ndarray, threshold: float = 0.20) -> list[Detection]:
        """Run inference and return the raw model output BEFORE label
        filters / size floors / per-label thresholds. Used by the
        cam-edit "Erkennung jetzt simulieren" endpoint so the user can
        see what Coral actually found before filters narrow it down —
        each detection then gets a verdict (pass / below threshold /
        filtered by class) computed against the camera's current config.
        Threshold is intentionally low (0.20 default) so even
        almost-rejected hits show up in the simulation; the caller
        applies the user's actual thresholds afterwards.
        """
        if not self.available:
            return []
        if self._cpu_mode:
            return self._detect_cpu(frame, threshold)
        return self._detect_coral(frame, threshold)

    def _detect_coral(self, frame: np.ndarray, threshold: float | None = None) -> list[Detection]:
        """Inference via pycoral + EdgeTPU.

        Wrapped in ``_infer_lock`` so a concurrent simulate-now call
        can't start a second invoke while an outstanding get_objects()
        view is still tied to the previous run — and, on the TPU tier,
        so the cameras queue for the one device explicitly instead of
        inside libedgetpu.

        Colour conversion and letterboxing stay OUTSIDE the lock. That
        prep is pure CPU work on a private frame, and now that the lock
        is shared by every camera, holding it across the prep would
        serialise their letterboxing too — throughput given away for
        nothing.
        """
        score_threshold = threshold if threshold is not None else self.min_score
        _t_pre = time.perf_counter()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        width, height = self.common.input_size(self.interpreter)
        # Aspect-preserving letterbox — see letterbox() for the why.
        # pycoral returns bbox in model-pixel space, so the inverse
        # transform below subtracts pad before dividing by scale.
        canvas, scale, pad_x, pad_y = letterbox(rgb, width, height)
        _t_wait = time.perf_counter()
        with self._infer_lock:
            _t_invoke = time.perf_counter()
            self.common.set_input(self.interpreter, canvas)
            self.interpreter.invoke()
            _t_post = time.perf_counter()
            # Materialise pycoral results into a plain list of (id, score, bbox)
            # tuples while still inside the lock so the underlying tensor
            # references are released before the next caller can run set_input.
            objs = self.detect.get_objects(self.interpreter, score_threshold=score_threshold)
            snapshot = [
                (
                    int(o.id),
                    float(o.score),
                    (
                        float(o.bbox.xmin),
                        float(o.bbox.ymin),
                        float(o.bbox.xmax),
                        float(o.bbox.ymax),
                    ),
                )
                for o in objs
            ]
        self._record_timing(_t_pre, _t_wait, _t_invoke, _t_post)
        h, w = frame.shape[:2]
        inv_scale = 1.0 / scale if scale > 0 else 1.0
        out: list[Detection] = []
        for cid, score, (xmin, ymin, xmax, ymax) in snapshot:
            x1 = max(0, min(w, int(round((xmin - pad_x) * inv_scale))))
            y1 = max(0, min(h, int(round((ymin - pad_y) * inv_scale))))
            x2 = max(0, min(w, int(round((xmax - pad_x) * inv_scale))))
            y2 = max(0, min(h, int(round((ymax - pad_y) * inv_scale))))
            label = self.labels.get(cid, str(cid))
            out.append(Detection(label=label, score=score, bbox=(x1, y1, x2, y2), raw_cls_id=cid))
        return _apply_region_filter(out, self._region_filter)

    def _detect_cpu(self, frame: np.ndarray, threshold: float | None = None) -> list[Detection]:
        """Inference via tflite-runtime on CPU (SSD MobileNet layout).

        Both the lock AND ``np.copy()`` on the output tensors are
        required:
          • the lock prevents a parallel ``set_tensor`` call (from the
            simulate-now endpoint) from clashing with this thread's
            outstanding numpy views;
          • the copy detaches our return values from the interpreter's
            internal buffer so a downstream consumer can hold the
            arrays past the lock release without keeping the
            interpreter pinned.
        """
        score_threshold = threshold if threshold is not None else self.min_score
        _t_pre = time.perf_counter()
        input_details = self.interpreter.get_input_details()
        output_details = self.interpreter.get_output_details()
        in_h = input_details[0]['shape'][1]
        in_w = input_details[0]['shape'][2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        # Aspect-preserving letterbox — same rationale as _detect_coral.
        # SSD-MobileNet emits normalised bbox coords (0..1) in the
        # padded model square, so the inverse transform multiplies by
        # the model dim first, then subtracts pad, then divides by
        # scale to land back in original frame pixels.
        canvas, scale, pad_x, pad_y = letterbox(rgb, in_w, in_h)
        inp = np.expand_dims(canvas, axis=0)
        if input_details[0]['dtype'] == np.float32:
            inp = (inp.astype(np.float32) - 127.5) / 127.5
        _t_wait = time.perf_counter()
        with self._infer_lock:
            _t_invoke = time.perf_counter()
            self.interpreter.set_tensor(input_details[0]['index'], inp)
            self.interpreter.invoke()
            _t_post = time.perf_counter()
            # Standard SSD output order: boxes [N,4], classes [N], scores [N], count
            boxes = np.copy(self.interpreter.get_tensor(output_details[0]['index'])[0])
            classes = np.copy(self.interpreter.get_tensor(output_details[1]['index'])[0])
            scores = np.copy(self.interpreter.get_tensor(output_details[2]['index'])[0])
        self._record_timing(_t_pre, _t_wait, _t_invoke, _t_post)
        h, w = frame.shape[:2]
        inv_scale = 1.0 / scale if scale > 0 else 1.0
        out: list[Detection] = []
        for i in range(len(scores)):
            score = float(scores[i])
            if score < score_threshold:
                continue
            ymin, xmin, ymax, xmax = boxes[i]
            x1 = max(0, min(w, int(round((xmin * in_w - pad_x) * inv_scale))))
            y1 = max(0, min(h, int(round((ymin * in_h - pad_y) * inv_scale))))
            x2 = max(0, min(w, int(round((xmax * in_w - pad_x) * inv_scale))))
            y2 = max(0, min(h, int(round((ymax * in_h - pad_y) * inv_scale))))
            cls_id = int(classes[i])
            label = self.labels.get(cls_id, str(cls_id))
            out.append(
                Detection(label=label, score=score, bbox=(x1, y1, x2, y2), raw_cls_id=cls_id)
            )
        return _apply_region_filter(out, self._region_filter)
