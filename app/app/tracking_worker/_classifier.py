"""The worker's CPU-pinned second-stage bird classifier.

The tracking worker owns one `BirdSpeciesClassifier` for the same two
reasons it owns one detector (see ``__init__.py::detector``): a second
instance would double the model memory, and — the sharper problem — it
could take the single Edge TPU that the live camera runtimes own.

WHY THE PINNING IS NOT REDUNDANT
--------------------------------
`BirdSpeciesClassifier` already defaults to CPU on its own:
`prefer_cpu` defaults to True in detectors/bird_species.py, per the
_CLASSIFIER_CPU_NOTE in detectors/_edgetpu.py. But that default is a
CONFIG value the operator can flip — `processing.bird_species.
prefer_cpu: false` deliberately puts the LIVE second stage on the TPU,
and that is a legitimate thing to want. A post-clip pass that inherited
the setting would then contend for the device with live capture, and a
batch replay walking hundreds of archived clips is precisely the
workload that would starve it.

So the forcing below is what makes this instance's pinning independent
of what the operator chose for live detection, rather than a restating
of a default that could move underneath it.
"""

from __future__ import annotations


def build_cpu_classifier(bird_cfg: dict):
    """Build a `BirdSpeciesClassifier` that cannot acquire the TPU.

    Mirrors ``__init__.py::_ensure_detector``'s `worker_cfg` forcing,
    and for the same non-obvious reason: nulling `device` alone does
    NOT keep a model off the TPU, because the EdgeTPU delegate
    (detectors tier 1b) takes the default device when handed none.
    Both keys are required.
    """
    from ..detectors import BirdSpeciesClassifier

    cfg = dict(bird_cfg or {})
    cfg["device"] = None
    cfg["prefer_cpu"] = True
    return BirdSpeciesClassifier(cfg)


def classifier_signature(cfg: dict) -> tuple:
    """The cfg fields that materially change what this classifier
    produces.

    Mirrors ``__init__.py::_detector_signature``: `export_effective_
    config` returns a fresh dict on every call, so identity is useless
    as a cache key and the signature has to be derived from content or
    the model would reload on every single clip of a batch.
    """
    cfg = cfg or {}
    return (
        bool(cfg.get("enabled")),
        cfg.get("model_path"),
        cfg.get("cpu_model_path"),
        cfg.get("labels_path"),
        cfg.get("latin_to_de_path"),
        float(cfg.get("min_score") or 0.0),
    )
