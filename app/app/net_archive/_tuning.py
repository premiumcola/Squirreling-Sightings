"""Camera-WIDE tuning changes, in the same Verlauf as the class drags.

The gap this closes: ``PATCH /api/netz/<cam>/axes`` has written an
archive record for every per-class threshold drag since the archive
existed, while ``PATCH /api/cameras/<id>/detection-tuning`` — the route
behind Analyse-Intervall, Nachlauf, Gnadenfrist, IoU-Schwelle,
ROI-Modus, Spur-Start, Doppel-Sperre, the tracker presets and the
Ghost-Spuren switch — wrote nothing at all. Half of what the operator
changed on the Erkennungsprofil had no history, and the half that did
looked complete. „Ich brauch eine Historie für die Kamera, wie die
Einstellungen der Reihe nach geändert wurden … welcher Wert wie
verändert wurde."

One record per CHANGED field, not one per request: „welcher Wert" is the
question, and a request that touches four fields answers it four times.
A field whose value did not actually move writes nothing — a history
full of "350 ms → 350 ms" is a history nobody reads.

Two mirrors live here and both are deliberate:

* :data:`TUNING_LABELS_DE` mirrors ``TUNE_LABELS_DE`` in
  ``netz/_settings_axes.js``. Pinned by test_netz_tuning_archive.py, the
  same way ``_mapping.js`` is pinned against ``thresholds/_apply.py``.
* the value formatting mirrors each spec's ``fmt``. It renders the
  sentence stored ON the record, so the browser never re-formats a
  number it did not compute — the record has to stay readable months
  later, when the JS that wrote the value has changed twice.
"""

from __future__ import annotations

import logging
from datetime import datetime

from ._consts import KIND_TUNING, STATE_CHANGED
from ._io import save_record

log = logging.getLogger(__name__)

#: German name per field. Mirror of TUNE_LABELS_DE in
#: web/static/js/netz/_settings_axes.js, plus the two fields that are
#: never a spoke of their own (the ghost switch and the tracker presets'
#: continue score).
TUNING_LABELS_DE = {
    "frame_interval_ms": "Analyse-Intervall",
    "motion_sensitivity": "Bewegungs-Vortrigger",
    "post_motion_tail_s": "Nachlauf",
    "track_miss_grace_seconds": "Gnadenfrist",
    "track_iou_match_threshold": "IoU-Schwelle",
    "roi_mode": "ROI-Modus",
    "wildlife_motion_sensitivity": "Wildtier-Empfindlichkeit",
    "roi_min_net_disp_frac": "Min.-Strecke",
    "track_spawn_min_score": "Spur-Start",
    "track_block_contain": "Doppel-Sperre",
    "track_continue_min_score": "Spur-Fortsetzung",
    "track_filter_ghosts": "Ghost-Spuren ausblenden",
}

#: What an ABSENT key means. 0.0 is the "use the system default" sentinel
#: for almost every field here, so a first-ever save of 0.0 is not a
#: change; these two carry a real default instead and would otherwise log
#: a phantom "0 ms → 350 ms" the first time anything else is saved.
#: Same numbers as ``routes/_netz_helpers.net_state``'s tuning dict.
_UNSET = {"frame_interval_ms": 350, "motion_sensitivity": 0.5}

_BOOL_FIELDS = ("track_filter_ghosts",)
_ENUM_DE = {"roi_mode": {"off": "Aus", "roi": "Motion-ROI", "2x2": "2×2", "3x3": "3×3"}}


def _norm(field: str, raw):
    """The comparable value of a field — absent and "system default" are
    the same thing, and 0 vs 0.0 vs "0" must never read as a change."""
    if field in _BOOL_FIELDS:
        return raw is not False
    if field in _ENUM_DE:
        return str(raw or "off").lower()
    if raw is None:
        raw = _UNSET.get(field, 0.0)
    try:
        return round(float(raw), 4)
    except (TypeError, ValueError):
        return 0.0


def _fmt_number(field: str, value: float) -> str:
    if field == "frame_interval_ms":
        return f"{int(round(value))} ms"
    if field == "motion_sensitivity":
        return f"{round(value * 100)} %"
    if value <= 0:
        return {
            "track_block_contain": "Standard (70 %)",
            "wildlife_motion_sensitivity": "auto",
            "roi_min_net_disp_frac": "auto (4 %)",
        }.get(field, "Standard")
    if field == "post_motion_tail_s":
        return f"{value:g} s"
    if field == "track_miss_grace_seconds":
        return f"{value:.1f} s"
    if field == "wildlife_motion_sensitivity":
        return f"{value:.1f}×"
    if field in ("track_block_contain", "roi_min_net_disp_frac"):
        return f"{round(value * 100)} %"
    return f"{value:.2f}"


def format_tuning_value(field: str, raw) -> str:
    """The value as the panel prints it — mirror of the spec's ``fmt``."""
    value = _norm(field, raw)
    if field in _BOOL_FIELDS:
        return "an" if value else "aus"
    if field in _ENUM_DE:
        return _ENUM_DE[field].get(value, value)
    return _fmt_number(field, value)


def tuning_changes(before: dict, after: dict) -> list:
    """``[(field, before_raw, after_raw)]`` for the fields that MOVED.

    Only fields present in ``before`` are considered: that dict is the
    snapshot the route took of exactly the keys the request carried, so a
    field nobody touched can never appear here.
    """
    return [
        (field, raw, after.get(field))
        for field, raw in before.items()
        if field in TUNING_LABELS_DE and _norm(field, raw) != _norm(field, after.get(field))
    ]


def record_tuning_changes(storage_root, *, cam_id: str, cam_name: str, changes: list) -> int:
    """One archive record per changed field. Returns how many were written.

    No image and no ``net_state``: there is no moment to show, and the
    per-class ladder is untouched by these fields. The detail sheet reads
    the kind and leaves both out rather than printing an empty net.
    """
    # Microseconds, matching ``_motion._build_event_meta``'s event_id
    # shape — and DATE-LEADING so ``_io._month_of`` files it in the right
    # month folder instead of the ``unknown`` bucket.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    written = 0
    for i, (field, before_raw, after_raw) in enumerate(changes):
        name = TUNING_LABELS_DE.get(field, field)
        before_text = format_tuning_value(field, before_raw)
        after_text = format_tuning_value(field, after_raw)
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event_id": f"{stamp}-cam-{i:02d}-{field}",
            "cam_id": cam_id,
            "cam_name": cam_name,
            "kind": KIND_TUNING,
            "detection": {"label": None, "score": None, "all": []},
            "asked": False,
            "asked_via": "web",
            "asked_ts": None,
            "net_state": {},
            "rails": {},
            "consequence": {
                "state": STATE_CHANGED,
                "label": None,
                "cam_id": cam_id,
                "field": field,
                "field_de": name,
                "before": {"value": before_raw, "text": before_text},
                "after": {"value": after_raw, "text": after_text},
                "reason_de": (
                    f"Du hast {name} auf {cam_name} von {before_text} auf {after_text} geändert."
                ),
            },
        }
        if save_record(storage_root, payload["event_id"], payload):
            written += 1
    if written:
        log.info("[det] Kamera-Einstellung archiviert: cam=%s %d Werte", cam_id, written)
    return written
