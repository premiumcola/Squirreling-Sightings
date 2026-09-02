"""``/api/coral/models`` and ``/api/coral/models/select``."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import jsonify, request

from ... import app_state
from .._coral_helpers import (
    _MODELS_DIR,
    _categorize_tflite,
    _describe_tflite,
    _labels_for_model,
    _nickname_tflite,
)
from ._blueprint import bp

log = logging.getLogger(__name__)


@bp.get('/api/coral/models')
def api_coral_models():
    """List every .tflite model present in /app/models/, annotated with size,
    a filename-derived description, a purpose category, and the matching
    labels-file (if any). Flags which one is currently loaded per category."""
    eff = app_state.get_effective_config()
    proc = eff.get("processing") or {}
    active_by_category = {
        "detection": (proc.get("detection") or {}).get("model_path"),
        "bird_species": (proc.get("bird_species") or {}).get("model_path"),
        "wildlife": (proc.get("wildlife") or {}).get("model_path"),
    }
    # Current (legacy field) kept for backward compat
    current = active_by_category.get("detection")
    items: list = []
    if _MODELS_DIR.exists():
        for p in sorted(_MODELS_DIR.glob("*.tflite")):
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            category = _categorize_tflite(p.name)
            active_path = active_by_category.get(category)
            items.append(
                {
                    "filename": p.name,
                    "path": str(p),
                    "size_bytes": size,
                    "size_mb": round(size / 1048576, 2),
                    "description": _describe_tflite(p.name),
                    "nickname": _nickname_tflite(p.name),
                    "edgetpu": "_edgetpu" in p.name.lower(),
                    "model_category": category,
                    "labels": _labels_for_model(p.name),
                    "active": str(p) == current,  # legacy: detection only
                    "active_in_category": str(p) == active_path,  # per-category flag
                }
            )
    return jsonify(
        {
            "ok": True,
            "models": items,
            "current": current,
            "active_by_category": active_by_category,
            "models_dir": str(_MODELS_DIR),
        }
    )


@bp.post('/api/coral/models/select')
def api_coral_models_select():
    """Switch the active model for ONE category. Routing is driven by
    the filename's category (_categorize_tflite); writing a wildlife or
    bird-species model into processing.detection.model_path would
    clobber the COCO detector, which is the bug this guard fixes.

    Path traversal protection: target must resolve inside /app/models/.
    """
    settings = app_state.settings
    payload = request.get_json(silent=True) or {}
    raw_path = (payload.get("path") or "").strip()
    if not raw_path:
        return jsonify({"ok": False, "error": "path required"}), 400
    try:
        target = Path(raw_path).resolve()
        target.relative_to(_MODELS_DIR.resolve())
    except Exception:
        return jsonify({"ok": False, "error": "path must be inside /app/models"}), 400
    if not target.exists() or target.suffix.lower() != ".tflite":
        return jsonify({"ok": False, "error": "model not found"}), 404

    category = _categorize_tflite(target.name)
    if category == "other":
        return jsonify(
            {
                "ok": False,
                "error": "Modell-Kategorie unbekannt — bitte Dateinamen prüfen",
            }
        ), 400

    # Map category → settings.processing.<bucket> so each model writes
    # into its own bucket. cpu_model_path mirrors the EdgeTPU pick to
    # the non-edgetpu variant so the CPU fallback (or a no-Coral host)
    # loads the matching tflite without further config.
    bucket_by_cat = {
        "detection": "detection",
        "bird_species": "bird_species",
        "wildlife": "wildlife",
    }
    bucket_name = bucket_by_cat[category]
    proc = settings.data.setdefault("processing", {})
    bucket = proc.setdefault(bucket_name, {})
    bucket["model_path"] = str(target)
    cpu_candidate = str(target).replace("_edgetpu.tflite", ".tflite")
    if cpu_candidate != str(target) and Path(cpu_candidate).exists():
        bucket["cpu_model_path"] = cpu_candidate
    else:
        bucket.pop("cpu_model_path", None)
    # Detection always runs (it's the first stage); the second-stage
    # classifiers ship disabled-by-default so flipping enabled=True on
    # selection makes the model actually take effect. Mode flag mirrors
    # the legacy "coral" string so the runtime picks up the new path
    # via either branch.
    if category == "detection":
        bucket["mode"] = "coral"
    else:
        bucket["enabled"] = True
    settings.save()
    try:
        app_state.rebuild_runtimes()
    except Exception as e:
        log.warning("[coral] model switch: rebuild_runtimes failed: %s", e)
    return jsonify({"ok": True, "path": str(target), "category": category})
