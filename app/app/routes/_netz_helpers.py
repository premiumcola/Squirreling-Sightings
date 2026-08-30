"""Shared shapes for the ``/api/netz/*`` blueprint.

Everything here is read-only over the ladder or a pure projection of it.
The one rule that must not bend: the value this endpoint reports is the
EFFECTIVE value, resolved through ``resolve_effective``, together with
the layer that produced it. The operator's original complaint was that
the settings showed the wrong layer — a prettier wrong display would be
a failure, not a fix.
"""

from __future__ import annotations

import time

from .. import app_state
from ..detection_feedback import (
    MIN_JUDGED_PER_CLASS,
    MIN_JUDGED_PER_STRATUM,
    corpus_stats,
    resolve_stratum,
)
from ..thresholds import resolve_effective
from ..thresholds._apply import (
    AXIS_ORDER,
    E_FACTORY,
    adapted_layer,
    camera_role,
    clamp_e,
    clamp_manual_e,
    effective_e,
    manual_patch,
    provenance,
    rails,
    thresholds_for,
)
from ..thresholds._learner import axis_proposal, camera_axes


def push_cfg() -> dict:
    tele = (app_state.settings.data.get("telegram") if app_state.settings else None) or {}
    return tele.get("push") or {}


def camera(cam_id: str) -> dict | None:
    if not app_state.settings:
        return None
    return app_state.settings.get_camera(cam_id)


def camera_chips() -> list:
    """The camera switcher. No "alle Kameras" mode — three cameras with
    opposite jobs (Einbruchschutz, Futterstelle, Garten) cannot share one
    sensitivity, and an averaged net would be a lie."""
    cams = (app_state.settings.data.get("cameras") if app_state.settings else None) or []
    return [
        {"id": c.get("id"), "name": c.get("name") or c.get("id"), "role": camera_role(c)}
        for c in cams
        if isinstance(c, dict) and c.get("id")
    ]


def _axis(cam: dict, label: str, stratum: dict, proposal) -> dict:
    eff = resolve_effective(cam, push_cfg(), label, adapted=adapted_layer(cam, label))
    e = effective_e(cam, label)
    judged = int(stratum.get("n_total") or 0)
    return {
        "label": label,
        "E": e,
        "spawn": eff.spawn,
        "push": eff.push,
        "confirm_n": eff.confirm_n,
        "confirm_s": eff.confirm_seconds,
        "push_enabled": eff.push_enabled,
        # WHICH LAYER WON, per field. This is the answer to the
        # operator's actual complaint and it travels with every value.
        "source": dict(eff.source),
        "provenance": provenance(cam, label),
        "evidence": {
            "judged": judged,
            "true": int(stratum.get("n_true") or 0),
            "false": int(stratum.get("n_false") or 0),
            "answer_rate": stratum.get("answer_rate") or 0.0,
            "ready": bool(stratum.get("ready")),
            "scope": stratum.get("scope") or "stratum",
            "blockers": list(stratum.get("blockers") or []),
            "needed": MIN_JUDGED_PER_STRATUM,
            "needed_per_class": MIN_JUDGED_PER_CLASS,
        },
        "proposal": proposal,
    }


def _closest_to_ready(axes: list) -> dict | None:
    """The stratum the empty state prints a progress line for.

    One line, for the axis nearest the bar — not a table of zeros. No
    fake confidence, no spinner: day one is honest about having no
    evidence.
    """
    candidates = [a for a in axes if not a["evidence"]["ready"]]
    if not candidates:
        return None
    best = max(candidates, key=lambda a: a["evidence"]["judged"])
    return {
        "label": best["label"],
        "judged": best["evidence"]["judged"],
        "needed": MIN_JUDGED_PER_STRATUM,
    }


def net_state(cam_id: str) -> dict | None:
    """The whole panel payload for one camera."""
    cam = camera(cam_id)
    if cam is None:
        return None
    root = app_state.storage_root
    try:
        stats = corpus_stats(root)
    except Exception:
        stats = {"strata": [], "pooled": []}
    labels = camera_axes(cam)
    axes = []
    for label in labels:
        stratum = resolve_stratum(stats, cam_id, label)
        try:
            proposal = axis_proposal(root, cam, push_cfg(), label, stats)
        except Exception:
            proposal = None
        axes.append(_axis(cam, label, stratum, proposal))
    return {
        "cam_id": cam_id,
        "cam_name": cam.get("name") or cam_id,
        "role": camera_role(cam),
        "auto": cam.get("net_auto") is not False,
        "axis_order": list(AXIS_ORDER),
        "axes": axes,
        "rails": rails(),
        "e_factory": E_FACTORY,
        "cameras": camera_chips(),
        "progress": _closest_to_ready(axes),
        # Named, not merely "frozen" — the difference between frozen and
        # forgotten is whether the operator can read the list.
        "frozen": FROZEN_KEYS,
        # Kamera-Feinschliff — the camera-WIDE capture/motion/tracking loop
        # settings that used to live on the Erkennung tab. They can never
        # become radar axes (they run before the pipeline knows a class),
        # so they render as a plain fold below the net instead. Same
        # defaults as hydrateErkennungFields/discovery.js's collector.
        "tuning": {
            "frame_interval_ms": cam.get("frame_interval_ms", 350),
            "motion_sensitivity": cam.get("motion_sensitivity", 0.5),
            "post_motion_tail_s": cam.get("post_motion_tail_s") or 0,
            "track_miss_grace_seconds": cam.get("track_miss_grace_seconds") or 0,
            "track_iou_match_threshold": cam.get("track_iou_match_threshold") or 0,
            "track_spawn_min_score": cam.get("track_spawn_min_score") or 0,
            "track_block_contain": cam.get("track_block_contain") or 0,
            "track_filter_ghosts": cam.get("track_filter_ghosts") is not False,
            "roi_mode": cam.get("roi_mode") or "off",
            "wildlife_motion_sensitivity": cam.get("wildlife_motion_sensitivity") or 0,
            "roi_min_net_disp_frac": cam.get("roi_min_net_disp_frac") or 0,
        },
    }


#: Everything the net deliberately does NOT write, listed for the
#: „Werte, die fest bleiben" fold. One line each, no controls.
FROZEN_KEYS = [
    {"key": "confirmation_window", "de": "Bestätigungs-Fenster je Klasse (N von M Sekunden)"},
    {"key": "detection_min_score", "de": "Allgemeine Konfidenz-Schwelle der Kamera"},
    {"key": "processing.detection.min_score", "de": "Globale Detektor-Schwelle"},
    {"key": "processing.bird_species.min_score", "de": "Vogelarten-Klassifikator"},
    {"key": "wildlife.min_score", "de": "Wildtier-Kaskade"},
    {"key": "wildlife._inat_min_score", "de": "iNaturalist-Stufe der Wildtier-Kaskade"},
    {"key": "wildlife_min_score", "de": "Wildtier-Schwelle je Kamera"},
    {"key": "label_veto", "de": "Klassen-Veto je Kamera"},
    {"key": "hybrid_mode", "de": "TPU+CPU-Doppelpass"},
    {"key": "TRACK_FLOOR_SCORE", "de": "Roher Detektor-Boden (0,20)"},
    {"key": "calibration", "de": "Alle Kalibrier-Schranken (50 / 20 / 20 / 20 %)"},
]


def apply_axes(cam_id: str, axes: dict, *, pin: bool, confirmed: bool = False) -> dict:
    """Write dragged axes onto the CAMERA layer, additively.

    The same path the learner's proposal-adoption uses, so a drag and an
    adopted proposal can never disagree about where the number lives.
    ``label_thresholds`` and ``push_thresholds`` are the camera layer;
    ``net_pin`` records that a human put them there.

    ``confirmed`` is the operator's answer to the person-floor dialog and
    the ONLY thing that lets ``person`` on a security camera go below
    ``AUTO_E_FLOOR_PERSON_SECURITY``. It defaults to False so a path that
    forgets to ask cannot blind a camera by omission — the value is
    clamped to the floor and the caller is told which axes moved, in
    ``written[label]["clamped"]``.
    """
    cam = camera(cam_id)
    if cam is None:
        return {}
    merged = dict(cam)
    lt = dict(merged.get("label_thresholds") or {})
    pt = dict(merged.get("push_thresholds") or {})
    pins = dict(merged.get("net_pin") or {})
    adapted = dict(merged.get("net_adapted") or {})
    written = {}
    for label, raw in (axes or {}).items():
        e = clamp_manual_e(cam, label, raw, confirmed=confirmed)
        clamped = e != clamp_e(raw)
        patch = manual_patch(label, e)
        lt[label] = patch["label_thresholds"][label]
        pt[label] = patch["push_thresholds"][label]
        if pin:
            pins[label] = {"E": e, "ts": time.time(), "by": "manual"}
            # Adopting a proposal or dragging an axis UNPINS the
            # learner's own value for it: two forces writing one number
            # through two keys is exactly the drift this replaces.
            adapted.pop(label, None)
        written[label] = {"E": e, "clamped": clamped, **thresholds_for(label, e)}
    merged["label_thresholds"] = lt
    merged["push_thresholds"] = pt
    merged["net_pin"] = pins
    merged["net_adapted"] = adapted
    app_state.settings.upsert_camera(merged)
    return written


def reset_axes(cam_id: str, labels) -> list:
    """E = 50 and unpin — factory, exactly recoverable."""
    cam = camera(cam_id)
    if cam is None:
        return []
    merged = dict(cam)
    lt = dict(merged.get("label_thresholds") or {})
    pt = dict(merged.get("push_thresholds") or {})
    pins = dict(merged.get("net_pin") or {})
    adapted = dict(merged.get("net_adapted") or {})
    targets = list(labels) if labels else camera_axes(cam)
    for label in targets:
        lt.pop(label, None)
        pt.pop(label, None)
        pins.pop(label, None)
        adapted.pop(label, None)
    merged["label_thresholds"] = lt
    merged["push_thresholds"] = pt
    merged["net_pin"] = pins
    merged["net_adapted"] = adapted
    app_state.settings.upsert_camera(merged)
    return targets
