"""What a detector / classifier instance IS, in words a JSON can carry.

Two readers need the same answer: the telemetry panel (live, per
request) and the event provenance snapshot (once per event). Both used
to derive "TPU or CPU, and through which API" from ``mode`` and
``_cpu_mode`` by hand; one function here means one place to be wrong.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ._types import STAGE_BIRD, STAGE_DETECTOR, STAGE_WILDLIFE


def describe_backend(obj) -> dict:
    """``{"device", "api", "mode", "reason"}`` for one interpreter holder.

    ``device`` and ``api`` are two fields on purpose. ``mode == "coral"``
    with ``_cpu_mode == True`` means "TPU, reached through the tflite
    delegate instead of pycoral" — collapsing that into one badge is how
    a working delegate ends up reported as a CPU fallback.
    """
    mode = getattr(obj, "mode", "none")
    cpu_api = bool(getattr(obj, "_cpu_mode", False))
    reason = getattr(obj, "reason", "disabled")
    if mode == "coral":
        device, api = "tpu", ("tflite-delegate" if cpu_api else "pycoral")
    elif mode == "cpu":
        device, api = "cpu", "tflite-cpu"
    else:
        device, api = "off", None
    return {"device": device, "api": api, "mode": mode, "reason": reason}


@lru_cache(maxsize=32)
def _sha256_prefix(path: str, size: int, mtime_ns: int) -> str | None:
    # size + mtime are part of the key so a swapped model file with the
    # same name is re-hashed instead of served from the cache.
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]
    except OSError:
        return None


def model_fingerprint(path) -> str | None:
    """First 12 hex chars of the model file's sha256; None when the file
    is missing. Cached per (path, size, mtime) — model files are tens of
    MB and an event must not re-read one."""
    if not path:
        return None
    try:
        st = Path(str(path)).stat()
    except OSError:
        return None
    return _sha256_prefix(str(path), st.st_size, st.st_mtime_ns)


def describe_model(obj, path_attr: str = "active_model_path") -> dict:
    """Backend + model file name + fingerprint for one interpreter holder."""
    path = getattr(obj, path_attr, None)
    out = describe_backend(obj)
    out["file"] = Path(str(path)).name if path else None
    out["sha256"] = model_fingerprint(path)
    return out


def describe_models(detector=None, bird=None, wildlife=None) -> dict:
    """The stage → model table a payload carries ONCE.

    Keyed by the ``detectors.STAGE_*`` tokens that a detection's ``model``
    field holds, so a reader joins a box to the model file that labelled
    it through that token instead of the file name being repeated on
    every box. ``event["provenance"]["models"]`` and the live /
    simulation payload are the same table built by the same function —
    two surfaces naming one model the same way is the whole point.
    """
    out = {
        STAGE_DETECTOR: describe_model(detector),
        STAGE_BIRD: describe_model(bird),
        STAGE_WILDLIFE: describe_model(wildlife),
    }
    if getattr(wildlife, "_inat_interpreter", None) is not None:
        inat = describe_model(wildlife, "active_inat_model_path")
        inat.update(inat_backend(wildlife))
        out["wildlife_inat"] = inat
    out["tpu_active"] = any(m.get("device") == "tpu" for m in out.values())
    return out


def inat_backend(wild) -> dict:
    """The iNat second-opinion interpreter has no ``mode`` of its own —
    only a CPU flag next to its parent classifier."""
    cpu = bool(getattr(wild, "_inat_cpu_mode", True))
    return {"device": "cpu" if cpu else "tpu", "api": "tflite-cpu" if cpu else "pycoral"}


@dataclass(frozen=True)
class Stage:
    """One interpreter a camera runtime owns.

    ``holder`` is the object that carries ``mode`` / model path;
    ``timing`` the one that carries the timing mixin — the same object
    except for the iNat stage, which has a separate timing holder.
    """

    name: str
    holder: object
    timing: object
    backend: dict
    model_path: str | None


def iter_stages(rt) -> Iterator[Stage]:
    """Every interpreter of one runtime, in cascade order — the detector,
    the bird classifier, the wildlife classifier and its iNat stage."""
    for name, attr in (("detector", "detector"), ("bird", "bird_classifier")):
        obj = getattr(rt, attr, None)
        if obj is not None:
            yield Stage(
                name, obj, obj, describe_backend(obj), getattr(obj, "active_model_path", None)
            )
    wild = getattr(rt, "wildlife_classifier", None)
    if wild is None:
        return
    yield Stage(
        "wildlife", wild, wild, describe_backend(wild), getattr(wild, "active_model_path", None)
    )
    if getattr(wild, "_inat_interpreter", None) is not None:
        backend = {**describe_backend(wild), **inat_backend(wild)}
        yield Stage(
            "wildlife_inat",
            wild,
            getattr(wild, "_inat_timing", None),
            backend,
            getattr(wild, "active_inat_model_path", None),
        )
