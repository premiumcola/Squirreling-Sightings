"""Which settings a replay runs with, and how to name that set.

Three sources, one shape. Everything downstream — ``resolve_object_
filter``, ``resolve_track_thresholds``, ``precision_for``, the ghost
prune — reads a per-camera config dict through a getter, so a replay is
the production pipeline handed a DIFFERENT getter. Nothing here knows
about videos or detectors; it only decides what dict that getter returns.

All three sources are projected onto the SAME key set (the one
``build_provenance`` captures). Without that projection a "current"
config would carry fifty keys a stored snapshot never had, and the
"are these two sets identical?" check the UI relies on could never
answer yes.
"""

from __future__ import annotations

import hashlib
import json

from ..camera_runtime._recording._provenance import PROVENANCE_TUNING_KEYS

# recording_settings (the pre-provenance snapshot) under its own key
# names -> the camera-config names the pipeline actually reads. Only
# the keys that survive the round trip; confirm_n / confirm_seconds are
# handled separately because they nest.
_LEGACY_KEY_MAP = {
    "conf_thresh_general": "detection_min_score",
    "conf_thresh_per_class": "label_thresholds",
    "object_filter": "object_filter",
    "sample_interval_ms": "frame_interval_ms",
    "motion_pretrigger_sensitivity": "motion_sensitivity",
    "pre_motion_seconds": "pre_motion_seconds",
}


def project_settings(cfg: dict | None) -> dict:
    """Keep only the keys a replay can meaningfully vary, dropping the
    ones that are absent. Absent and explicitly-null mean the same thing
    to every consumer (they all use ``.get`` with a fallback), so
    dropping nulls keeps the hash stable across snapshots that recorded
    an unset key and ones that omitted it."""
    src = cfg or {}
    out = {}
    for key in PROVENANCE_TUNING_KEYS:
        if key in src and src[key] is not None:
            out[key] = src[key]
    return out


def settings_hash(cfg: dict) -> str:
    """Short, stable fingerprint of one settings set.

    Twelve hex chars, matching the polygon signatures ``build_
    provenance`` already writes. Sorted keys and ``default=str`` so a
    set carrying a stray non-JSON value still hashes instead of
    exploding mid-replay.
    """
    blob = json.dumps(cfg, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _from_legacy(recording_settings: dict) -> dict:
    """Best-effort camera config from a pre-provenance event.

    ``recording_settings`` predates the full snapshot and carries a
    third of the knobs under different names. What it does carry is the
    part that moves detections — the confidence floor, the per-class
    thresholds and the object filter — so a replay off it is still worth
    running. The caller tells the operator it is a partial basis.
    """
    out = {}
    for legacy_key, cfg_key in _LEGACY_KEY_MAP.items():
        val = recording_settings.get(legacy_key)
        if val is not None:
            out[cfg_key] = val
    n, secs = recording_settings.get("confirm_n"), recording_settings.get("confirm_seconds")
    if n is not None or secs is not None:
        window = {}
        if n is not None:
            window["n"] = n
        if secs is not None:
            window["seconds"] = secs
        out["confirmation_window"] = {"global": window}
    return project_settings(out)


def resolve_replay_settings(event: dict, current_cfg: dict, spec) -> dict:
    """Turn the request's ``settings`` field into the set to replay with.

    ``spec`` is ``"stored"``, ``"current"``, or a dict of overrides
    (``{"tuning": {...}}`` or the bare override dict). Returns a
    descriptor carrying the resolved ``cfg`` plus enough provenance of
    its own that the stored replay entry can say what it ran with.
    """
    if isinstance(spec, dict):
        overrides = spec.get("tuning") if isinstance(spec.get("tuning"), dict) else spec
        cfg = project_settings(current_cfg)
        cfg.update(project_settings(overrides))
        return {
            "cfg": cfg,
            "source": "custom",
            "basis": "current+overrides",
            "hash": settings_hash(cfg),
            "note": None,
            "overridden": sorted(project_settings(overrides).keys()),
        }

    if spec == "current":
        cfg = project_settings(current_cfg)
        return {
            "cfg": cfg,
            "source": "current",
            "basis": "current",
            "hash": settings_hash(cfg),
            "note": None,
            "overridden": [],
        }

    provenance = event.get("provenance") or {}
    tuning = provenance.get("tuning")
    if isinstance(tuning, dict) and tuning:
        cfg = project_settings(tuning)
        return {
            "cfg": cfg,
            "source": "stored",
            "basis": "provenance",
            "hash": settings_hash(cfg),
            "note": None,
            "overridden": [],
        }

    legacy = event.get("recording_settings")
    if isinstance(legacy, dict) and legacy:
        cfg = _from_legacy(legacy)
        return {
            "cfg": cfg,
            "source": "stored",
            "basis": "recording_settings",
            "hash": settings_hash(cfg),
            "note": (
                "Diese Aufnahme ist älter als der Settings-Schnappschuss — "
                "nachsimuliert mit den überlieferten Aufnahme-Settings "
                "(Schwellen und Objektfilter); die übrigen Regler stammen "
                "aus dem aktuellen Profil."
            ),
            "overridden": [],
        }

    cfg = project_settings(current_cfg)
    return {
        "cfg": cfg,
        "source": "stored",
        "basis": "current",
        "hash": settings_hash(cfg),
        "note": (
            "Für diese Aufnahme sind keine Settings hinterlegt — "
            "nachsimuliert mit dem aktuellen Profil."
        ),
        "overridden": [],
    }
