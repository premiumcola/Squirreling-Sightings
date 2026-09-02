"""BirdSpeciesClassifier — second-stage iNaturalist classifier for bird
crops. Same three-tier fallback as CoralObjectDetector.

Carved out of `_legacy_classes.py` during R02.2.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from ._edgetpu import make_delegate_interpreter
from ._label_loader import _load_bird_latin_to_de, _pretty_bird_label, load_label_map
from ._timing import InferenceTimingMixin
from ._types import STAGE_BIRD

log = logging.getLogger(__name__)

#: The detector label that earns a second-stage species pass. COCO has
#: exactly one bird class, so both callers of `stamp_species` test
#: against this rather than spelling the literal twice.
BIRD_LABEL = "bird"


def stamp_species(classifier, crop, det):
    """Classify one bird crop and stamp the result onto ``det``.

    THE one place a second-stage result becomes a detection's species.
    Both callers go through here — the live loop
    (``camera_runtime/_main_loop.py``) and the clip replay
    (``replay/_species.py``) — so "what a classified bird looks like
    afterwards" is defined once instead of drifting between the path
    that runs at capture time and the path that runs over the archive.

    Each caller keeps its OWN crop step and passes the pixels in. That
    split is deliberate rather than an oversight: the live loop slices
    the working frame it is already holding, while the archive-facing
    paths go through ``bird_species_backfill.crop_bbox``, which refuses
    a box that overshoots the frame handed to it (a downscaled snapshot
    against native-resolution coordinates). Sharing the stamping
    without sharing the cropping keeps the live pixel path bit-for-bit
    what it has always been.

    Returns the ``(display, latin, score)`` triple on a hit and None
    otherwise. None covers three different silences that the caller
    cannot tell apart and does not need to: an unavailable model, a
    crop that scored below ``min_score``, and a species whose Latin
    binomial carries no German name — the deliberate suppression
    documented in ``_label_loader._pretty_bird_label`` and introduced
    with evidence in commit 639c2d6. The replay uses the return value
    to tally species across a whole clip; the live loop ignores it and
    reads the detection it just mutated.
    """
    if classifier is None or not getattr(classifier, "available", False):
        return None
    species, species_latin, species_score = classifier.classify_crop(crop)
    if not species:
        return None
    det.species = species
    det.species_latin = species_latin
    det.species_score = float(species_score) if species_score is not None else None
    det.model = STAGE_BIRD
    return species, species_latin, det.species_score


class BirdSpeciesClassifier(InferenceTimingMixin):
    """Optional second stage classifier for bird crops.

    Tries pycoral (EdgeTPU) first, then tflite-runtime CPU fallback.
    Without a model file the system stays on generic 'bird'.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.enabled = bool(self.cfg.get("enabled"))
        self.available = False
        self.reason = "disabled"
        self.mode = "none"  # "coral" | "cpu" | "none"
        self.labels = load_label_map(self.cfg.get("labels_path"))
        self.min_score = float(self.cfg.get("min_score", 0.25))
        self.latin_to_de = _load_bird_latin_to_de(self.cfg.get("latin_to_de_path"))
        self.interpreter = None
        self.common = None
        self.classify = None
        self._cpu_mode = False
        # The model file the ACTIVE tier really loaded — the CPU tier
        # substitutes the non-EdgeTPU build, so the configured path is not
        # the running one.
        self.active_model_path: str | None = None
        # Second-stage classifiers default to CPU — see _CLASSIFIER_CPU_NOTE
        # in detectors/_edgetpu.py. Set prefer_cpu: false in the
        # processing.bird_species config to put this back on the TPU.
        self._prefer_cpu = bool(self.cfg.get("prefer_cpu", True))
        self._cpu_threads = self.cfg.get("cpu_threads")
        # Same four-bucket timing the object detector reports. Without it
        # the telemetry panel could show what device this stage runs on
        # but not what it costs — and "CPU" alone is not an answer to
        # "can I afford 3x3".
        self._init_timings()
        if not self.enabled:
            return
        model_path = self.cfg.get("model_path")
        if not model_path:
            self.reason = "missing model_path"
            return
        if not Path(model_path).exists():
            cpu_alt = self.cfg.get("cpu_model_path")
            if not (cpu_alt and Path(cpu_alt).exists()):
                self.reason = f"model file not found: {model_path}"
                log.warning("[det] Bird classifier: %s", self.reason)
                return

        coral_error = "prefer_cpu"
        if not self._prefer_cpu:
            # ── Tier 1: pycoral ───────────────────────────────────────────
            try:
                from pycoral.adapters import classify, common  # type: ignore
                from pycoral.utils.edgetpu import make_interpreter  # type: ignore

                self.common = common
                self.classify = classify
                self.interpreter = make_interpreter(model_path, device=self.cfg.get("device"))
                self.interpreter.allocate_tensors()
                self.available = True
                self.mode = "coral"
                self.reason = "ok"
                self.active_model_path = model_path
                log.info("[det] Bird classifier (Coral) aktiv: %s", model_path)
                return
            except Exception as e:
                log.warning("[det] Bird classifier pycoral unavailable (%s) – EdgeTPU-Delegate…", e)
                coral_error = str(e)

            # ── Tier 1b: EdgeTPU via tflite-runtime delegate ───────────────
            # See detectors/_edgetpu.py. _classify_cpu already dequantises
            # uint8/int8 output, so the compiled model parses unchanged.
            delegated = make_delegate_interpreter(model_path, self.cfg.get("device"))
            if delegated is not None:
                self.interpreter = delegated
                self._cpu_mode = True
                self.available = True
                self.mode = "coral"
                self.reason = "edgetpu_delegate"
                self.active_model_path = model_path
                log.info("[det] Bird classifier (EdgeTPU-Delegate) aktiv: %s", model_path)
                return

        # ── Tier 2: tflite-runtime ────────────────────────────────────────
        cpu_model = self.cfg.get("cpu_model_path")
        if not cpu_model:
            cpu_model = model_path.replace("_edgetpu.tflite", ".tflite")
            if cpu_model == model_path:
                cpu_model = None

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
                self.active_model_path = try_path
                log.info("[det] Bird classifier (CPU) aktiv: %s", try_path)
                return
            except Exception as e2:
                log.warning("[det] Bird classifier CPU fehlgeschlagen für %s: %s", try_path, e2)

        self.reason = f"classifier unavailable: {coral_error}"
        log.warning("[det] Bird species classifier nicht verfügbar")

    def classify_crop(self, crop: np.ndarray) -> tuple[str | None, str | None, float | None]:
        """Return (display_name, latin_binomial, score).

        display_name is the German common name when the species is in the
        latin_to_de map, otherwise the raw iNat label. latin_binomial is
        always the clean "Genus species" form.
        """
        if not self.available or crop is None or crop.size == 0:
            return None, None, None
        if self._cpu_mode:
            return self._classify_cpu(crop)
        return self._classify_coral(crop)

    def _classify_coral(self, crop: np.ndarray) -> tuple[str | None, str | None, float | None]:
        t_pre = time.perf_counter()
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        width, height = self.common.input_size(self.interpreter)
        resized = cv2.resize(rgb, (width, height))
        self.common.set_input(self.interpreter, resized)
        # This stage holds no inference lock (see _device_lock's "known
        # gap"), so the wait bucket is structurally zero here rather than
        # unmeasured — t_wait and t_invoke are deliberately the same mark.
        t_invoke = time.perf_counter()
        self.interpreter.invoke()
        t_post = time.perf_counter()
        self._record_timing(t_pre, t_invoke, t_invoke, t_post)
        classes = self.classify.get_classes(
            self.interpreter, top_k=3, score_threshold=self.min_score
        )
        if not classes:
            return None, None, None
        # Walk top-3 and return the first candidate that has a German mapping.
        # iNat's #1 is sometimes a North-American species while a European
        # cousin we know sits at #2/#3 — pick the one we can name.
        for c in classes:
            raw = self.labels.get(int(c.id), str(c.id))
            display, latin = _pretty_bird_label(raw, self.latin_to_de)
            if display:
                return display, latin, float(c.score)
        return None, None, None

    def _classify_cpu(self, crop: np.ndarray) -> tuple[str | None, str | None, float | None]:
        t_pre = time.perf_counter()
        input_details = self.interpreter.get_input_details()
        output_details = self.interpreter.get_output_details()
        in_h = input_details[0]['shape'][1]
        in_w = input_details[0]['shape'][2]
        in_dtype = input_details[0]['dtype']
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (in_w, in_h))
        inp = np.expand_dims(resized, axis=0)
        if in_dtype == np.float32:
            inp = inp.astype(np.float32) / 255.0
        else:
            inp = inp.astype(in_dtype)
        self.interpreter.set_tensor(input_details[0]['index'], inp)
        t_invoke = time.perf_counter()
        self.interpreter.invoke()
        t_post = time.perf_counter()
        self._record_timing(t_pre, t_invoke, t_invoke, t_post)
        scores = self.interpreter.get_tensor(output_details[0]['index'])[0]
        # Top-3 candidates, descending by score. Walk them and pick the first
        # one with a German mapping (iNat top-1 is often a North-American
        # species while a European cousin we know sits at #2/#3).
        out_dtype = output_details[0]['dtype']
        scale, zero_point = (
            output_details[0].get('quantization', (0.0, 0))
            if out_dtype in (np.uint8, np.int8)
            else (None, None)
        )

        def _to_prob(raw_score: float) -> float:
            if out_dtype in (np.uint8, np.int8):
                if scale:
                    return (raw_score - zero_point) * float(scale)
                return raw_score / 255.0
            return raw_score

        top_ids = np.argsort(scores)[::-1][:3]
        for cid in top_ids:
            cid = int(cid)
            prob = _to_prob(float(scores[cid]))
            if prob < self.min_score:
                continue
            raw = self.labels.get(cid, str(cid))
            display, latin = _pretty_bird_label(raw, self.latin_to_de)
            if display:
                return display, latin, prob
        return None, None, None
