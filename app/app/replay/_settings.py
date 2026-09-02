"""Which settings a replay or a simulation runs with, and how to name
that set.

Five sources, one shape: the set on record, the camera's current
profile, the shipped factory profile, an explicit override dict, and an
archived profile revision. Everything downstream — ``resolve_object_
filter``, ``resolve_track_thresholds``, ``precision_for``, the ghost
prune — reads a per-camera config dict through a getter, so a replay is
the production pipeline handed a DIFFERENT getter. Nothing here knows
about videos or detectors; it only decides what dict that getter returns.

All five sources are projected onto the SAME key set (the one
``build_provenance`` captures). Without that projection a "current"
config would carry fifty keys a stored snapshot never had, and the
"are these two sets identical?" check the UI relies on could never
answer yes.
"""

from __future__ import annotations

from ..camera_runtime._recording._provenance import project_settings, settings_hash
from ..settings.defaults import default_camera

# Defined next to PROVENANCE_TUNING_KEYS, which they are written in
# terms of, and re-exported here because this is where callers look for
# them. See that module's header for why the direction is that way.
__all__ = ["project_settings", "resolve_replay_settings", "settings_hash"]

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


def _set(cfg: dict, source: str, basis: str, *, note=None, overridden=(), revision=None) -> dict:
    """One settings descriptor. Every arm below returns this shape.

    Extracted so a new source costs two lines rather than eight — the
    resolver grew a factory and a revision arm and would otherwise have
    gone past the function ceiling by repeating the same six keys.
    """
    out = {
        "cfg": cfg,
        "source": source,
        "basis": basis,
        "hash": settings_hash(cfg),
        "note": note,
        "overridden": sorted(overridden),
    }
    if revision is not None:
        out["revision"] = revision
    return out


def _revision_set(current_cfg: dict, revision_id: str, revisions) -> dict:
    """One archived profile revision, laid over the current profile.

    ``revisions`` is the lookup seam — a callable taking a revision id
    and returning its tuning overrides, or None. It is injected rather
    than imported so this module keeps knowing nothing about where an
    archive lives; see ``replay/_revisions.py`` for the one that reads
    the Erkennungsnetz archive.
    """
    overrides = revisions(revision_id) if callable(revisions) else None
    if not overrides:
        raise ValueError(f"Unbekannter Profil-Stand: {revision_id}")
    projected = project_settings(overrides)
    cfg = project_settings(current_cfg)
    cfg.update(projected)
    return _set(
        cfg,
        "revision",
        f"archiv:{revision_id}",
        overridden=projected.keys(),
        revision=revision_id,
    )


def resolve_replay_settings(event: dict, current_cfg: dict, spec, *, revisions=None) -> dict:
    """Turn the request's ``settings`` field into the set to replay with.

    ``spec`` is ``"stored"``, ``"current"``, ``"factory"``, a dict of
    overrides (``{"tuning": {...}}`` or the bare override dict), or
    ``{"revision": <archive id>}``. Returns a descriptor carrying the
    resolved ``cfg`` plus enough provenance of its own that the stored
    replay entry can say what it ran with.

    The simulation reaches the archive through exactly this vocabulary —
    one settings-selection mechanism, two callers.
    """
    if isinstance(spec, dict) and spec.get("revision"):
        return _revision_set(current_cfg, str(spec["revision"]), revisions)

    if isinstance(spec, dict):
        overrides = spec.get("tuning") if isinstance(spec.get("tuning"), dict) else spec
        projected = project_settings(overrides)
        cfg = project_settings(current_cfg)
        cfg.update(projected)
        return _set(cfg, "custom", "current+overrides", overridden=projected.keys())

    if spec == "factory":
        # The shipped profile, built from the same defaults a new camera
        # is seeded with — not a remembered copy of them.
        return _set(project_settings(default_camera({})), "factory", "factory")

    if spec == "current":
        return _set(project_settings(current_cfg), "current", "current")

    provenance = event.get("provenance") or {}
    tuning = provenance.get("tuning")
    if isinstance(tuning, dict) and tuning:
        return _set(project_settings(tuning), "stored", "provenance")

    legacy = event.get("recording_settings")
    if isinstance(legacy, dict) and legacy:
        return _set(
            _from_legacy(legacy),
            "stored",
            "recording_settings",
            note=(
                "Diese Aufnahme ist älter als der Settings-Schnappschuss — "
                "nachsimuliert mit den überlieferten Aufnahme-Settings "
                "(Schwellen und Objektfilter); die übrigen Regler stammen "
                "aus dem aktuellen Profil."
            ),
        )

    return _set(
        project_settings(current_cfg),
        "stored",
        "current",
        note=(
            "Für diese Aufnahme sind keine Settings hinterlegt — "
            "nachsimuliert mit dem aktuellen Profil."
        ),
    )
