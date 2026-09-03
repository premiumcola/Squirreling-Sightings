"""Model loading for the wildlife cascade.

Two independent three-tier ladders — pycoral, then the EdgeTPU delegate,
then plain tflite-runtime on the CPU — one for the primary MobileNet and
one for the optional iNaturalist second opinion. Split out of
`wildlife.py` so the file that decides WHAT an animal is does not also
carry ninety lines about where its weights came from.

The attribute names this mixin writes are read elsewhere by name
(`detectors/_describe.py`, `detectors/_utilisation.py`), so they are a
contract, not private bookkeeping: `interpreter`, `mode`, `reason`,
`available`, `active_model_path`, `_cpu_mode`, and the `_inat_*` set.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ._edgetpu import make_delegate_interpreter
from ._label_loader import load_label_map
from ._timing import InferenceTimingMixin
from .discovery import discover_wildlife_paths

log = logging.getLogger(__name__)

# Threshold the classifier runs at when `processing.wildlife.min_score`
# is absent from the effective config — which is the live case on any
# install whose config.yaml predates the `processing.wildlife` block.
# Named rather than inlined so the debug panel can report the value that
# is genuinely in effect instead of "not configured": the setting IS
# read, it just resolves to this.
WILDLIFE_MIN_SCORE_DEFAULT = 0.35

# The iNat backend's own default threshold, independent of the wildlife
# one — it is a different model answering a different question.
INAT_MIN_SCORE_DEFAULT = 0.25


class _InatTiming(InferenceTimingMixin):
    """Timing holder for the iNat second-opinion interpreter.

    WildlifeClassifier drives TWO interpreters (MobileNet + iNat) and the
    mixin keeps one rolling window per object, so the second interpreter
    gets its own holder rather than a second copy of the bucket logic.
    They are genuinely separate models on possibly different devices —
    averaging them into one number would hide exactly the case the panel
    exists to show."""

    def __init__(self) -> None:
        self._init_timings()


class WildlifeLoadMixin:
    """Everything `WildlifeClassifier.__init__` does before it can
    classify anything. Kept as a mixin rather than free functions
    because each tier writes half a dozen fields on the instance, and
    threading those back out through a result object would be more
    moving parts than the ladder itself."""

    # ── configuration ──────────────────────────────────────────────────
    def _resolve_paths(self) -> None:
        """Auto-discovery: locate a MobileNet ImageNet model + its labels
        file in /app/models. Lets users drop a model in without editing
        yaml. Always runs (cheap glob) so partial configs — common case:
        model_path set but labels_path missing — still get the labels
        filled in. setdefault only — never overwrite a user-supplied
        value, even when the file is missing on disk. A non-existent
        configured path is more often a transient mount issue at boot
        than a bad config; silently swapping in the discovery default
        would erase the operator's intent."""
        for k, v in discover_wildlife_paths().items():
            if not self.cfg.get(k):
                self.cfg[k] = v
                continue
            if not Path(self.cfg[k]).exists():
                log.warning(
                    "[det] Wildlife classifier: configured %s=%s does not exist; "
                    "leaving config as-is. Discovered alternative was %s.",
                    k,
                    self.cfg[k],
                    v,
                )

    def _init_backend_fields(self, inat_cfg: dict | None) -> None:
        """Every field the two ladders write, in their unloaded state."""
        self.labels = load_label_map(self.cfg.get("labels_path"))
        self.min_score = float(self.cfg.get("min_score", WILDLIFE_MIN_SCORE_DEFAULT))
        self.interpreter = None
        self.common = None
        self.classify = None
        self._cpu_mode = False
        # ── Optional iNaturalist second-stage backend ──────────────────
        # When inat_cfg is supplied (typically the bird_species block,
        # since the user can re-use that path), we load a parallel TFLite
        # interpreter and run it on the wildlife crop. Stays None when no
        # path is configured or loading fails.
        self._inat_interpreter = None
        self._inat_labels: dict[int, str] = {}
        self._inat_common = None
        self._inat_classify = None
        self._inat_cpu_mode = False
        # Own rolling window — the iNat model is a different model on a
        # possibly different device than MobileNet above.
        self._inat_timing = _InatTiming()
        self._inat_min_score = INAT_MIN_SCORE_DEFAULT
        self._inat_cfg = dict(inat_cfg) if inat_cfg else {}
        self._init_timings()
        # The model file the ACTIVE tier really loaded — the CPU tier
        # substitutes the non-EdgeTPU build, so the configured path is
        # not the running one.
        self.active_model_path: str | None = None
        self.active_inat_model_path: str | None = None
        # Second-stage classifiers default to CPU — see
        # _CLASSIFIER_CPU_NOTE in detectors/_edgetpu.py. Set
        # prefer_cpu: false in the processing.wildlife config to put this
        # back on the TPU.
        self._prefer_cpu = bool(self.cfg.get("prefer_cpu", True))
        self._cpu_threads = self.cfg.get("cpu_threads")
        # Some ImageNet label files include an extra "background" entry
        # at index 0 (1001 labels total). The model output then has 1001
        # bins too, so no offset is required. When the labels file has
        # exactly 1000 entries and the model emits 1001, we shift by 1.
        self._label_offset = 0

    def _model_file_reachable(self, model_path: str) -> bool:
        """True when either the configured model or its CPU twin exists."""
        if Path(model_path).exists():
            return True
        cpu_alt = self.cfg.get("cpu_model_path")
        if cpu_alt and Path(cpu_alt).exists():
            return True
        self.reason = f"model file not found: {model_path}"
        log.warning("[det] Wildlife classifier: %s", self.reason)
        return False

    # ── the primary MobileNet ladder ───────────────────────────────────
    def _load_primary(self, model_path: str) -> None:
        """Tier 1 pycoral → tier 1b EdgeTPU delegate → tier 2 CPU."""
        coral_error = "prefer_cpu"
        if not self._prefer_cpu:
            coral_error = self._try_pycoral(model_path)
            if coral_error is None:
                return
            if self._try_delegate(model_path):
                return
        if self._try_cpu(model_path, coral_error):
            return
        self.reason = (
            f"classifier unavailable: {coral_error}" if coral_error else "classifier unavailable"
        )
        log.warning("[det] Wildlife classifier nicht verfügbar")

    def _try_pycoral(self, model_path: str) -> str | None:
        """None when the TPU tier loaded; otherwise the error to report."""
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
            log.info(
                "[det] Wildlife classifier (Coral) aktiv: %s — %d labels",
                model_path,
                len(self.labels),
            )
            self._load_inat_backend()
            return None
        except Exception as e:
            log.warning("[det] Wildlife classifier pycoral unavailable (%s) – EdgeTPU-Delegate…", e)
            return str(e)

    def _try_delegate(self, model_path: str) -> bool:
        """Tier 1b: EdgeTPU through the tflite-runtime delegate. See
        detectors/_edgetpu.py."""
        delegated = make_delegate_interpreter(model_path, self.cfg.get("device"))
        if delegated is None:
            return False
        self.interpreter = delegated
        self._cpu_mode = True
        self.available = True
        self.mode = "coral"
        self.reason = "edgetpu_delegate"
        self.active_model_path = model_path
        log.info(
            "[det] Wildlife classifier (EdgeTPU-Delegate) aktiv: %s — %d labels",
            model_path,
            len(self.labels),
        )
        self._load_inat_backend()
        return True

    def _try_cpu(self, model_path: str, coral_error: str) -> bool:
        """Tier 2: plain tflite-runtime. Prefers the uncompiled twin of
        an `*_edgetpu.tflite` — running the compiled one on the CPU works
        but wastes the compilation."""
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
                log.info(
                    "[det] Wildlife classifier (CPU) aktiv: %s — %d labels",
                    try_path,
                    len(self.labels),
                )
                self._load_inat_backend()
                return True
            except Exception as e2:
                log.warning("[det] Wildlife classifier CPU fehlgeschlagen für %s: %s", try_path, e2)
        return False

    # ── the iNaturalist second opinion ─────────────────────────────────
    def _load_inat_backend(self) -> None:
        """Try to load the iNaturalist tflite second-stage classifier from
        self._inat_cfg. No-op when the cfg is empty, the model file doesn't
        exist, or both Coral/CPU loaders fail. Logged outcome so the user
        sees a single line in the startup banner."""
        cfg = self._inat_cfg or {}
        model_path = cfg.get("model_path")
        if not model_path or not Path(model_path).exists():
            cpu_alt = cfg.get("cpu_model_path")
            if not (cpu_alt and Path(cpu_alt).exists()):
                return
            model_path = cpu_alt
        self._inat_min_score = float(cfg.get("min_score", INAT_MIN_SCORE_DEFAULT))
        self._inat_labels = load_label_map(cfg.get("labels_path"))
        # Same prefer_cpu contract as the wildlife stage above, and for the
        # same reason (see detectors/_edgetpu.py): the Edge TPU caches model
        # parameters in ~8 MB of SRAM, the shipped models do not fit there
        # together, and every switch rewrites that cache across USB. The
        # object detector runs on EVERY frame and owns the stick; this
        # backend runs only on a wildlife-gated crop.
        #
        # This guard was missing, which stayed invisible for as long as the
        # image ran Python 3.11 — pycoral had no wheel there, so tier 1
        # always raised and the backend silently landed on CPU anyway. The
        # moment the :coral image made pycoral importable (2026-08-28) this
        # started claiming the TPU and evicting the detector on every bird.
        # Absence of a symptom was never evidence the guard was present.
        if bool(cfg.get("prefer_cpu", self._prefer_cpu)):
            self._load_inat_cpu(model_path)
            return
        # Tier 1: pycoral
        try:
            from pycoral.adapters import classify, common  # type: ignore
            from pycoral.utils.edgetpu import make_interpreter  # type: ignore

            self._inat_common = common
            self._inat_classify = classify
            self._inat_interpreter = make_interpreter(model_path, device=cfg.get("device"))
            self._inat_interpreter.allocate_tensors()
            self.active_inat_model_path = model_path
            log.info(
                "[det] Wildlife · iNat-Backend (Coral) aktiv: %s — %d labels",
                model_path,
                len(self._inat_labels),
            )
            return
        except Exception:
            pass
        # Tier 2: tflite-runtime
        self._load_inat_cpu(model_path)

    def _load_inat_cpu(self, model_path: str) -> None:
        """Load the iNat backend on the CPU via plain tflite-runtime.

        Reached both as the deliberate default (prefer_cpu) and as the
        fallback after a failed pycoral load, so it must not assume which
        path got here. `cpu_model_path` points at the uncompiled twin of an
        `*_edgetpu.tflite`; running the compiled one on the CPU works but
        wastes the compilation, hence the preference order.
        """
        cfg = self._inat_cfg or {}
        try:
            import tflite_runtime.interpreter as tflite  # type: ignore

            cpu_path = cfg.get("cpu_model_path") or model_path
            self._inat_interpreter = tflite.Interpreter(model_path=cpu_path)
            self._inat_interpreter.allocate_tensors()
            self._inat_cpu_mode = True
            self.active_inat_model_path = cpu_path
            log.info(
                "[det] Wildlife · iNat-Backend (CPU) aktiv: %s — %d labels",
                cpu_path,
                len(self._inat_labels),
            )
        except Exception as e:
            log.info("[det] Wildlife · iNat-Backend nicht geladen: %s", e)
            self._inat_interpreter = None
