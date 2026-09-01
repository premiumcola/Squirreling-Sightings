"""What a detector / classifier instance IS, in words a JSON can carry.

Two readers need the same answer: the telemetry panel (live, per
request) and the event provenance snapshot (once per event). Both used
to derive "TPU or CPU, and through which API" from ``mode`` and
``_cpu_mode`` by hand; one function here means one place to be wrong.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path


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
