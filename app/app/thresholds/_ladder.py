"""THR-1 · resolving the threshold ladder. Public via ``thresholds``.

Four independent gates decide whether a sighting ever reaches the user,
and until now every one of them was read at its own call site with its
own fallback chain:

    detect  — raw model floor the detector is asked for
              (``tracker_core._consts.TRACK_FLOOR_SCORE``, 0.20)
    spawn   — minimum confidence to START a track / feed the
              confirmation window (``label_thresholds``, 0.45-0.55)
    confirm — N-of-M sliding window (``confirmation_window``)
    push    — minimum confidence for a Telegram push
              (``telegram.push.labels[*].threshold``, 0.80-0.90)

Reading them separately is how the shipped config ended up with a dead
zone: ``person`` confirms at 0.45 but pushes at 0.85, so every sighting
between the two is recorded and silently never sent. ``resolve_effective``
puts all four side by side for one camera and one label, and reports for
each value WHERE it came from — so a diagnostic (DIAG-2) or the UI can
show the ladder without re-implementing the lookup order.

Precedence — highest wins, and it is the same for every field:

    camera  > adapted > global > default

* ``camera``  — the operator set this by hand on THIS camera.
* ``adapted`` — a value some later automatic calibration proposes
  (THR-2 / THR-3). It sits BELOW the manual layer on purpose: an
  automatic adaptation must never be able to silently overwrite a
  number the user typed. It is passed in per call — nothing here
  reads or writes an adapted value on its own.
* ``global``  — the system-wide setting in ``telegram.push``.
* ``default`` — the shipped constant.

Pure functions, no I/O, no app state. Consumers pass in the camera dict
and the ``telegram.push`` dict they already hold.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..settings._consts import (
    CONFIRMATION_WINDOW_DEFAULTS,
    LABEL_THRESHOLD_DEFAULTS,
    TELEGRAM_PUSH_DEFAULTS,
)
from ..tracker_core._consts import TRACK_FLOOR_SCORE, TRACK_SPAWN_SCORE

SOURCE_CAMERA = "camera"
SOURCE_ADAPTED = "adapted"
SOURCE_GLOBAL = "global"
SOURCE_DEFAULT = "default"

# Ordered highest-precedence-first. Documented as data so a caller can
# render / sort by it instead of hard-coding the order a second time.
SOURCE_PRECEDENCE: tuple[str, ...] = (
    SOURCE_CAMERA,
    SOURCE_ADAPTED,
    SOURCE_GLOBAL,
    SOURCE_DEFAULT,
)

# Fallbacks for a label that carries no per-class confirmation entry —
# mirrors DetectionConfirmer.check()'s own signature defaults.
CONFIRM_N_FALLBACK = 3
CONFIRM_SECONDS_FALLBACK = 5.0


@dataclass(frozen=True)
class EffectiveThresholds:
    """Every gate one (camera, label) pair passes, plus its origin.

    ``source`` maps field name → one of :data:`SOURCE_PRECEDENCE`.
    """

    label: str
    detect: float
    spawn: float
    confirm_n: int
    confirm_seconds: float
    push: float
    push_enabled: bool
    source: dict[str, str]

    @property
    def dead_zone(self) -> bool:
        """True when a sighting can be confirmed but never pushed.

        ``push > spawn`` means every score in between triggers a
        recording and no notification — the shipped ``person`` config
        (spawn 0.45 / push 0.85) is exactly this case.
        """
        return self.push > self.spawn


def _as_float(val) -> float | None:
    """Numeric value or None when the entry is absent / unusable.

    0.0 survives — it is a legitimate push threshold (``motion``).
    """
    if val is None or isinstance(val, bool):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _positive(val) -> float | None:
    """Like :func:`_as_float` but treats 0.0 as "unset".

    The per-camera ``track_*`` overrides use 0.0 as "keep the module
    default" — see ``tracker_core.resolve_track_thresholds``.
    """
    num = _as_float(val)
    return num if num is not None and num > 0.0 else None


def _pick(candidates: list[tuple[str, float | None]], fallback: float) -> tuple[float, str]:
    """First candidate with a value, in the order given by the caller.

    Callers build the list in :data:`SOURCE_PRECEDENCE` order.
    """
    for source, value in candidates:
        if value is not None:
            return value, source
    return fallback, SOURCE_DEFAULT


def _sub(cfg, key: str) -> dict:
    """A dict-valued sub-config, or {} when absent / the wrong shape."""
    val = (cfg or {}).get(key)
    return val if isinstance(val, dict) else {}


def _resolve_detect(cam_cfg: dict, adapted: dict) -> tuple[float, str]:
    return _pick(
        [
            (SOURCE_CAMERA, _positive(cam_cfg.get("track_continue_min_score"))),
            (SOURCE_ADAPTED, _positive(adapted.get("detect"))),
        ],
        TRACK_FLOOR_SCORE,
    )


def _resolve_spawn(cam_cfg: dict, label: str, adapted: dict) -> tuple[float, str]:
    """Per-label camera value, then the learner, then the camera-wide one.

    ``track_spawn_min_score`` sits BELOW ``adapted`` on purpose, and that
    is the one place the precedence table bends — for a reason that is
    about what the two keys mean, not about who wrote them.
    ``label_thresholds[label]`` is a statement about THIS class;
    ``track_spawn_min_score`` is a single camera-wide tracker knob with
    no class in it at all, written four at a time by the „Vorsichtig /
    Ausgewogen / Robust" preset buttons on the Erkennung tab.

    Ranked above ``adapted`` it was a silent global veto: one
    „Vorsichtig" click posted ``track_spawn_min_score: 0.55`` to
    ``/api/settings/cameras`` and every axis the learner had moved — every
    label without its own ``label_thresholds`` entry — reverted to 0.55
    with no control anywhere showing it. A per-class decision still wins;
    a camera-wide default no longer overrides a per-class one.
    """
    return _pick(
        [
            (SOURCE_CAMERA, _as_float(_sub(cam_cfg, "label_thresholds").get(label))),
            (SOURCE_ADAPTED, _as_float(adapted.get("spawn"))),
            (SOURCE_CAMERA, _positive(cam_cfg.get("track_spawn_min_score"))),
            (SOURCE_DEFAULT, _as_float(LABEL_THRESHOLD_DEFAULTS.get(label))),
        ],
        TRACK_SPAWN_SCORE,
    )


def _resolve_confirm(cam_cfg: dict, label: str) -> tuple[int, float, str]:
    cam_win = _sub(_sub(cam_cfg, "confirmation_window"), label)
    default_win = CONFIRMATION_WINDOW_DEFAULTS.get(label) or {}
    win, source = (cam_win, SOURCE_CAMERA) if cam_win else (default_win, SOURCE_DEFAULT)
    n = _as_float(win.get("n"))
    secs = _as_float(win.get("seconds"))
    if n is None and secs is None:
        source = SOURCE_DEFAULT
    return (
        max(1, int(n if n is not None else CONFIRM_N_FALLBACK)),
        max(0.5, secs if secs is not None else CONFIRM_SECONDS_FALLBACK),
        source,
    )


def _resolve_push(cam_cfg: dict, push_cfg: dict, label: str, adapted: dict) -> tuple[float, str]:
    return _pick(
        [
            (SOURCE_CAMERA, _as_float(_sub(cam_cfg, "push_thresholds").get(label))),
            (SOURCE_ADAPTED, _as_float(adapted.get("push"))),
            (SOURCE_GLOBAL, _as_float(_sub(_sub(push_cfg, "labels"), label).get("threshold"))),
            (
                SOURCE_DEFAULT,
                _as_float(_sub(_sub(TELEGRAM_PUSH_DEFAULTS, "labels"), label).get("threshold")),
            ),
        ],
        0.0,
    )


def _resolve_push_enabled(cam_cfg: dict, push_cfg: dict, label: str) -> tuple[bool, str]:
    """Whether the label pushes at all.

    ``class_severity`` is the per-camera, per-label matrix and — per its
    own definition in the cam-edit panel — the source of truth that
    replaced ``alarm_profile``. It therefore OUTRANKS the global switch.

    The contradiction this fixes: the shipped global config has
    ``cat: {push: False}``, so a camera whose matrix said ``cat = info``
    detected cats, recorded cats, listed cats as active — and never once
    reported one. Two settings, opposite meanings, no warning. The
    operator had answered the question ("info") and was overruled by a
    default they never saw.

    ``off`` in the matrix still means off: a camera that mutes a class
    mutes it, whatever the global says.
    """
    severity = _sub(cam_cfg, "class_severity").get(label)
    if isinstance(severity, str) and severity:
        return severity != "off", SOURCE_CAMERA
    cfg_label = _sub(_sub(push_cfg, "labels"), label)
    if "push" in cfg_label:
        return bool(cfg_label.get("push")), SOURCE_GLOBAL
    shipped = _sub(_sub(TELEGRAM_PUSH_DEFAULTS, "labels"), label)
    return bool(shipped.get("push", False)), SOURCE_DEFAULT


def resolve_effective(
    cam_cfg: dict | None,
    push_cfg: dict | None,
    label: str,
    adapted: dict | None = None,
) -> EffectiveThresholds:
    """Resolve every gate for one camera + one label.

    ``cam_cfg``  — a camera dict from ``settings.cameras``.
    ``push_cfg`` — the ``telegram.push`` dict.
    ``adapted``  — optional proposal from an automatic calibration,
                   keys ``detect`` / ``spawn`` / ``push``. Ranks BELOW
                   anything the operator set on the camera.
    """
    cam_cfg = cam_cfg or {}
    push_cfg = push_cfg or {}
    adapted = adapted or {}
    detect, detect_src = _resolve_detect(cam_cfg, adapted)
    spawn, spawn_src = _resolve_spawn(cam_cfg, label, adapted)
    confirm_n, confirm_seconds, confirm_src = _resolve_confirm(cam_cfg, label)
    push, push_src = _resolve_push(cam_cfg, push_cfg, label, adapted)
    push_enabled, push_enabled_src = _resolve_push_enabled(cam_cfg, push_cfg, label)
    # The detector floor can never sit above the spawn gate — a spawn
    # the detector never reports is unreachable. Same clamp
    # tracker_core.resolve_track_thresholds applies; when it bites, the
    # spawn value IS the detect value, so it carries spawn's origin.
    if detect > spawn:
        detect, detect_src = spawn, spawn_src
    return EffectiveThresholds(
        label=label,
        detect=detect,
        spawn=spawn,
        confirm_n=confirm_n,
        confirm_seconds=confirm_seconds,
        push=push,
        push_enabled=push_enabled,
        source={
            "detect": detect_src,
            "spawn": spawn_src,
            "confirm_n": confirm_src,
            "confirm_seconds": confirm_src,
            "push": push_src,
            "push_enabled": push_enabled_src,
        },
    )
