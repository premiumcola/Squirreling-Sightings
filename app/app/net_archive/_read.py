"""The browse side: a filtered page of records, and the header stat.

Records are read newest-first straight off the month folders, so the
common case (the first page) touches only the current month.
"""

from __future__ import annotations

from ._consts import CHANGE_KINDS, PAGE_SIZE, STATE_CHANGED, STATE_BADGE, STATE_PENDING
from ._io import iter_record_paths, load_record, read_record


def _row(rec: dict) -> dict:
    """The list-row projection — everything a 92 px row needs, nothing more."""
    det = rec.get("detection") or {}
    cons = rec.get("consequence") or {}
    verdict = rec.get("verdict") or {}
    state = cons.get("state") or STATE_PENDING
    return {
        "event_id": rec.get("event_id"),
        "ts": rec.get("ts"),
        "cam_id": rec.get("cam_id"),
        "cam_name": rec.get("cam_name"),
        "kind": rec.get("kind"),
        "label": det.get("label"),
        "score": det.get("score"),
        "asked": bool(rec.get("asked")),
        "verdict": verdict.get("value"),
        "corrected_label": verdict.get("corrected_label"),
        "state": state,
        "badge": STATE_BADGE.get(state, "⏳"),
        "reason_de": cons.get("reason_de") or "",
        # A camera-wide change has no class; the field name is what the
        # row shows in the chip's place.
        "field_de": cons.get("field_de"),
        "has_frame": rec.get("kind") not in CHANGE_KINDS,
    }


def _sort_key(row: dict):
    """Newest first, by the record's OWN timestamp.

    Not by file order: ``iter_record_paths`` walks month folders, and
    every manual change written before this landed in ``unknown`` (its
    event_id starts with ``netz-``, so ``_month_of`` cannot date it).
    Reverse-sorted, ``unknown`` comes before every real month — which put
    the whole change history above the whole question history regardless
    of when anything happened. The operator asked for "der Reihe nach".
    """
    return str(row.get("ts") or "")


def _matches(rec: dict, cam: str | None, label: str | None, only_open: bool) -> bool:
    if cam and rec.get("cam_id") != cam:
        return False
    if label and (rec.get("detection") or {}).get("label") != label:
        return False
    if only_open and rec.get("verdict"):
        return False
    return True


def list_records(
    storage_root,
    *,
    cam: str | None = None,
    label: str | None = None,
    only_open: bool = False,
    offset: int = 0,
    limit: int = PAGE_SIZE,
) -> dict:
    """A page of rows, newest first, plus the counts the header prints.

    The header stat — "Von 84 Antworten haben 11 einen Wert bewegt" — is
    computed over the whole FILTERED set, not over the page: it is the
    audit sentence the feature exists to be able to print, and a page-
    local version of it would be meaningless.
    """
    rows = []
    answered = 0
    moved = 0
    unjudged = 0
    cams: dict = {}
    labels: dict = {}
    for path in iter_record_paths(storage_root):
        rec = read_record(path)
        if rec is None:
            continue
        cam_id = rec.get("cam_id")
        lab = (rec.get("detection") or {}).get("label")
        if cam_id:
            cams[cam_id] = rec.get("cam_name") or cam_id
        if lab:
            labels[lab] = labels.get(lab, 0) + 1
        if not _matches(rec, cam, label, only_open):
            continue
        if rec.get("verdict"):
            answered += 1
            if (rec.get("consequence") or {}).get("state") == STATE_CHANGED:
                moved += 1
        else:
            unjudged += 1
        rows.append(_row(rec))
    rows.sort(key=_sort_key, reverse=True)
    page = rows[offset : offset + limit]
    return {
        "items": page,
        "total": len(rows),
        "offset": offset,
        "answered": answered,
        "moved": moved,
        "unjudged": unjudged,
        "cameras": [{"id": k, "name": v} for k, v in sorted(cams.items(), key=lambda kv: kv[1])],
        "labels": [k for k, _ in sorted(labels.items(), key=lambda kv: -kv[1])],
    }


def get_record(storage_root, event_id: str) -> dict | None:
    return load_record(storage_root, event_id)


def find_event_context(storage_root, event_id: str) -> dict | None:
    """``{cam_id, label, score}`` for one event, from the archive.

    The durable fallback for ``runtime.alert_index``, whose LRU drops an
    entry after ~200 pushes. A verdict tapped after that still books
    correctly — ``_stats.judged_alerts`` joins on ``event_id`` — but the
    callbacks that need the camera and the class (``:m1h``, ``:siren``)
    used to bail out with "Daten zur Erkennung fehlen." This outlives
    the LRU by design, and it is also where a compaction-orphaned
    verdict gets its score back.
    """
    rec = load_record(storage_root, event_id)
    if rec is None:
        return None
    det = rec.get("detection") or {}
    return {
        "cam": rec.get("cam_id"),
        "label": det.get("label"),
        "score": det.get("score"),
        "cam_name": rec.get("cam_name"),
    }
