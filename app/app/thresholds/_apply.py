"""NETZ · the E ↔ Schwelle mapping, and the nightly run that applies it.

One integer per (camera, class) — ``E ∈ [0, 100]``, "Empfindlichkeit".
Bigger radius on the net = bigger E = more sensitive = more Meldungen.
``E = 50`` is exactly the shipped factory behaviour for that class, which
is why the mapping is ANCHORED rather than absolute: an absolute scale
would have to reproduce both the shipped spawn (person .45) and the
shipped push (person .85) from one number, and no single number does
both. Anchoring makes ``E = 50`` mean "Werkseinstellung für diese
Klasse" and the polygon's shape mean "wie weit ich vom Werk abgewichen
bin".

    STEP          = 0.006                    # 1 E-Punkt = 0.6 Prozentpunkte
    delta(E)      = (50 - E) * STEP          # E=0 → +0.30 strenger
    spawn(l, E)   = clamp(SPAWN_ANCHOR[l] + delta, 0.25, 0.90)
    push (l, E)   = clamp(PUSH_ANCHOR [l] + delta, 0.45, 0.98)
    if push < spawn + 0.10: push = spawn + 0.10

``web/static/js/netz/_mapping.js`` is a bit-for-bit mirror of the four
functions below — the same rule that binds ``camera_id.build_camera_id``
to ``buildCameraId``. ``tests/test_netz_mapping.py`` asserts the two
agree on all 101 E values × every class, through a JSON fixture both
sides read.

The net writes exactly two keys per camera, and nothing else:

    label_thresholds[label] = spawn(label, E)
    push_thresholds [label] = push (label, E)

``confirmation_window`` is deliberately NOT written: confirm is
anti-flicker tied to how long a class stays in frame (a bird 2 s, a
person 20 s), not to risk appetite. Conflating the two makes the mapping
unexplainable.
"""

from __future__ import annotations

import logging
import math

from ..settings._consts import LABEL_THRESHOLD_DEFAULTS, TELEGRAM_PUSH_DEFAULTS
from ..tracker_core._consts import TRACK_SPAWN_SCORE

log = logging.getLogger(__name__)

# ── the mapping constants ─────────────────────────────────────────────
STEP = 0.006
E_FACTORY = 50
E_MIN = 0
E_MAX = 100

# Hard rails. Both paths — a manual drag and the nightly learner — are
# clamped by these; nothing writes a threshold outside them.
SPAWN_FLOOR = 0.25
SPAWN_CEIL = 0.90
PUSH_FLOOR = 0.45
PUSH_CEIL = 0.98
MIN_GAP = 0.10

# AUTOMATIC PATH ONLY. `person` on a security camera is what an intruder
# trips; a corpus dominated by the operator's own comings and goings
# would otherwise learn its way to blindness. A manual drag may cross
# this, behind a blocking confirm in the UI. The learner never can.
AUTO_E_FLOOR_PERSON_SECURITY = 35
# Movement budget per nightly run, in E points (≈ 3 pp of threshold).
MAX_LEARNER_STEP_E = 5
# One run per 24 h per (camera, class).
LEARNER_MIN_INTERVAL_S = 24 * 3600.0

ROLE_SECURITY = "security"
ROLE_WILDLIFE = "wildlife"

# Fixed, global axis order. NEVER sorted by value — a polygon whose
# spokes reorder between two cameras is unreadable.
AXIS_ORDER: tuple[str, ...] = (
    "person",
    "cat",
    "dog",
    "bird",
    "squirrel",
    "fox",
    "hedgehog",
    "marten",
    "deer",
    "car",
    "motion",
)

PROVENANCE_WERK = "werk"
PROVENANCE_MANUAL = "manuell"
PROVENANCE_AUTO = "automatisch"


def _q(x: float) -> float:
    """Quantise to 4 decimals, half-up.

    Not ``round()``: Python's banker's rounding and JavaScript's
    ``Math.round`` disagree on exact ties, and this value has to come out
    bit-for-bit identical on both sides of the mirror. ``floor(x*1e4 +
    0.5)/1e4`` is the same IEEE-754 sequence in both languages.
    """
    return math.floor(x * 10000.0 + 0.5) / 10000.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def clamp_e(value) -> int:
    """Coerce anything to a valid E. Garbage becomes factory, not zero —
    zero is the strictest setting there is and a parse failure must never
    silently mean "report nothing"."""
    try:
        e = int(round(float(value)))
    except (TypeError, ValueError):
        return E_FACTORY
    return int(_clamp(e, E_MIN, E_MAX))


def spawn_anchor(label: str) -> float:
    """The shipped spawn for a class — what E = 50 reproduces."""
    val = LABEL_THRESHOLD_DEFAULTS.get(label)
    return float(val) if val is not None else float(TRACK_SPAWN_SCORE)


def push_anchor(label: str) -> float:
    """The shipped push for a class — what E = 50 reproduces.

    A label with no ``TELEGRAM_PUSH_DEFAULTS`` entry (``fox``,
    ``hedgehog``, ``marten``, ``deer``) gets spawn + 0.35, the same
    distance the shipped classes carry. Before THR-3 those labels
    resolved to 0.0 at the live gate; the net axis is the only thing
    that will ever give them a per-camera value.
    """
    entry = (TELEGRAM_PUSH_DEFAULTS.get("labels") or {}).get(label) or {}
    val = entry.get("threshold")
    if val is None:
        return spawn_anchor(label) + 0.35
    return float(val)


def delta_for(e: int) -> float:
    """Threshold offset for one E. Positive = stricter."""
    return (E_FACTORY - e) * STEP


def spawn_for(label: str, e) -> float:
    return _q(_clamp(spawn_anchor(label) + delta_for(clamp_e(e)), SPAWN_FLOOR, SPAWN_CEIL))


def push_for(label: str, e) -> float:
    ev = clamp_e(e)
    raw = _clamp(push_anchor(label) + delta_for(ev), PUSH_FLOOR, PUSH_CEIL)
    spawn = spawn_for(label, ev)
    # Only reachable AFTER clamping — the two anchors are always at least
    # 0.10 apart, so the gap can only close when one of them hits a rail.
    if raw < spawn + MIN_GAP:
        raw = spawn + MIN_GAP
    return _q(raw)


def thresholds_for(label: str, e) -> dict:
    """Both written keys for one (class, E)."""
    return {"spawn": spawn_for(label, e), "push": push_for(label, e)}


def e_from_push(label: str, push_value: float) -> int:
    """The E whose push threshold is closest to ``push_value``.

    The inverse the learner needs: ``recommend_push`` proposes a push
    threshold, and the net stores an E. Derived from the push anchor
    because push is the value the corpus can actually speak about.
    """
    try:
        target = float(push_value)
    except (TypeError, ValueError):
        return E_FACTORY
    return clamp_e(E_FACTORY - (target - push_anchor(label)) / STEP)


def camera_role(cam_cfg: dict | None) -> str:
    """``security`` (the safe direction) unless the camera says wildlife."""
    role = str((cam_cfg or {}).get("role") or "").strip().lower()
    return ROLE_WILDLIFE if role == ROLE_WILDLIFE else ROLE_SECURITY


def person_floor_applies(cam_cfg: dict | None, label: str) -> bool:
    return label == "person" and camera_role(cam_cfg) == ROLE_SECURITY


def clamp_manual_e(cam_cfg: dict | None, label: str, e, *, confirmed: bool) -> int:
    """The MANUAL path's E, after the one rail it has.

    A drag may cross the person floor — that is the difference between
    the manual and the automatic path — but only when the caller carries
    the operator's explicit confirmation. ``confirmed`` is not a default
    and not an inference: the blocking dialog lives in the UI, and the
    three writers that never show it (the API called directly, the
    „Rückgängig" toast, „Netz zu diesem Zeitpunkt wiederherstellen")
    pass False and are clamped up to the floor instead.

    Without this the floor was decoration: ``AUTO_E_FLOOR_PERSON_SECURITY``
    guarded ``clamp_learner_e`` alone, so a single PATCH with ``E: 0``
    put ``person`` on a security camera at a 0.75 spawn — an intruder
    under 75 % confidence produces no track, no clip and no alert.
    """
    ev = clamp_e(e)
    if confirmed or not person_floor_applies(cam_cfg, label):
        return ev
    return max(ev, AUTO_E_FLOOR_PERSON_SECURITY)


def clamp_learner_e(cam_cfg: dict | None, label: str, current_e: int, proposed_e: int) -> int:
    """The automatic path's E, after both of its own rails.

    Movement budget first, then the person safety floor — in that order,
    so the floor is the last word and a 30-point proposal cannot slip
    under it through the budget.
    """
    cur = clamp_e(current_e)
    want = clamp_e(proposed_e)
    step = int(_clamp(want - cur, -MAX_LEARNER_STEP_E, MAX_LEARNER_STEP_E))
    out = clamp_e(cur + step)
    if person_floor_applies(cam_cfg, label) and out < AUTO_E_FLOOR_PERSON_SECURITY:
        out = AUTO_E_FLOOR_PERSON_SECURITY
    return out


# ── the two per-camera net maps ───────────────────────────────────────


def _net_map(cam_cfg: dict | None, key: str) -> dict:
    val = (cam_cfg or {}).get(key)
    return val if isinstance(val, dict) else {}


def pinned_e(cam_cfg: dict | None, label: str):
    """E of a manually pinned axis, or None when the axis is free.

    A manual drag pins that axis PERMANENTLY — no timeout. A value that
    silently reverts after 30 days is precisely the thing that destroys
    trust.
    """
    entry = _net_map(cam_cfg, "net_pin").get(label)
    if not isinstance(entry, dict) or "E" not in entry:
        return None
    return clamp_e(entry.get("E"))


def adapted_e(cam_cfg: dict | None, label: str):
    """E the nightly learner last wrote for this axis, or None."""
    entry = _net_map(cam_cfg, "net_adapted").get(label)
    if not isinstance(entry, dict) or "E" not in entry:
        return None
    return clamp_e(entry.get("E"))


def adapted_layer(cam_cfg: dict | None, label: str) -> dict:
    """The ``adapted`` argument ``resolve_effective`` takes.

    This is the first writer the ladder's ``adapted`` layer has ever had
    — it has been sitting there with no producer since THR-1. Ranking it
    below ``camera`` is what makes the precedence question answer itself:
    a pinned axis writes the camera layer and the learner physically
    cannot outrank it.
    """
    e = adapted_e(cam_cfg, label)
    if e is None:
        return {}
    return thresholds_for(label, e)


def effective_e(cam_cfg: dict | None, label: str) -> int:
    """The E the chart draws for this axis, and where it came from.

    Manual pin wins, then the learner's value, then Werk.
    """
    pin = pinned_e(cam_cfg, label)
    if pin is not None:
        return pin
    auto = adapted_e(cam_cfg, label)
    return E_FACTORY if auto is None else auto


def provenance(cam_cfg: dict | None, label: str) -> str:
    if pinned_e(cam_cfg, label) is not None:
        return PROVENANCE_MANUAL
    if adapted_e(cam_cfg, label) is not None:
        return PROVENANCE_AUTO
    return PROVENANCE_WERK


def rails() -> dict:
    """The guard-rail bounds every consumer reports rather than restates."""
    return {
        "spawn": [SPAWN_FLOOR, SPAWN_CEIL],
        "push": [PUSH_FLOOR, PUSH_CEIL],
        "min_gap": MIN_GAP,
        "person_auto_floor_e": AUTO_E_FLOOR_PERSON_SECURITY,
        "max_learner_step_e": MAX_LEARNER_STEP_E,
        "step": STEP,
        "e_factory": E_FACTORY,
    }


def manual_patch(label: str, e) -> dict:
    """The camera-dict fragment a manual drag writes for one axis.

    Deliberately shaped as a nested patch so the caller hands it straight
    to ``SettingsStore.update_section`` / a ``setdefault`` merge. The net
    never writes ``settings.json`` wholesale.
    """
    ev = clamp_e(e)
    thr = thresholds_for(label, ev)
    return {
        "label_thresholds": {label: thr["spawn"]},
        "push_thresholds": {label: thr["push"]},
        "net_pin": {label: {"E": ev, "by": "manual"}},
    }


def clamp_person_label_threshold(cam_cfg: dict | None, label_thresholds: dict) -> dict:
    """Cap `label_thresholds["person"]` at the security-camera floor.

    `clamp_manual_e` guards the NET's writes. It does not guard the two
    routes that write `label_thresholds` directly — `POST
    /api/settings/cameras` (the whole camera dict) and `PATCH
    /api/cameras/<id>/detection-tuning`. Both accepted `person: 0.95`,
    which on Werkstatt or Garten means a person has to be recognised
    with 95 % confidence before a track even starts: the camera is
    blind and nothing says so.

    `AUTO_E_FLOOR_PERSON_SECURITY` (E 35) maps to a person spawn of
    0.54, so that is the ceiling. Wildlife-role cameras are untouched —
    a bird feeder has no intruder to miss.

    Returns a new dict; never mutates the caller's.
    """
    out = dict(label_thresholds or {})
    if "person" not in out or not person_floor_applies(cam_cfg, "person"):
        return out
    ceiling = spawn_for("person", AUTO_E_FLOOR_PERSON_SECURITY)
    try:
        wanted = float(out["person"])
    except (TypeError, ValueError):
        return out
    if wanted > ceiling:
        log.warning(
            "[det] person-Schwelle %.2f über dem Sicherheits-Limit – auf %.2f begrenzt",
            wanted,
            ceiling,
        )
        out["person"] = ceiling
    return out
