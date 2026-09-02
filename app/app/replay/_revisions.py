"""Which PROFILE REVISIONS a camera can be simulated against.

The Erkennungsnetz already archives every question it asked and every
axis the operator moved (:mod:`app.net_archive`). Each of those records
carries the net as it stood at that moment — ``net_state``, one entry
per class. That is a profile revision in all but name, and until now
only the archive page could reach it: the simulation could run the
camera's current profile and nothing else.

This module is the catalogue and the projection, and NOTHING ELSE. It
never writes. A revision picked for a simulation is materialised into a
throwaway dict and handed to the same ``cam_cfg_getter`` seam a replay
uses, so the camera's stored settings are not reachable from here even
by accident — ``routes/netz.py``'s restore endpoint stays the one and
only path that puts an archived net back onto a camera. The difference
matters: restoring is a decision, simulating is a question, and the
whole point of asking is to be able to ask without deciding.

The projection deliberately goes through ``thresholds.manual_patch``,
the same function ``_netz_helpers.apply_axes`` uses to WRITE a restore.
One computation, two callers, so "what the simulation shows" and "what
restoring would give you" cannot drift apart.
"""

from __future__ import annotations

from ..net_archive import KIND_ALARM, KIND_FRAGE, KIND_NETZ, get_record, list_records
from ..thresholds._apply import manual_patch

#: The two revisions every camera has, archive or no archive.
REVISION_CURRENT = "current"
REVISION_FACTORY = "factory"

#: Archive kinds whose records carry a ``net_state`` worth replaying. A
#: ``kamera_aenderung`` records one camera-wide field's before/after and
#: carries no net at all, so it cannot describe a whole revision.
_NET_KINDS = (KIND_FRAGE, KIND_ALARM, KIND_NETZ)

#: How many archived revisions the chip offers. The archive holds up to
#: 400 records; a picker with 400 entries is not a picker.
MAX_REVISIONS = 20


def list_revisions(storage_root, cam_id: str, *, limit: int = MAX_REVISIONS) -> list[dict]:
    """The revisions a simulation can be pointed at, newest first.

    The two synthetic ones lead because they are the two an operator
    reaches for: what the camera is doing now, and what it shipped with.
    Archived revisions follow in the archive's own order.
    """
    out = [
        {
            "id": REVISION_CURRENT,
            "kind": REVISION_CURRENT,
            "label": "Aktuelles Profil",
            "ts": None,
        },
        {
            "id": REVISION_FACTORY,
            "kind": REVISION_FACTORY,
            "label": "Werkseinstellung",
            "ts": None,
        },
    ]
    page = list_records(storage_root, cam=cam_id, limit=min(200, max(1, int(limit) * 4)))
    for row in page.get("items") or []:
        if row.get("kind") not in _NET_KINDS:
            continue
        out.append(
            {
                "id": row.get("event_id"),
                "kind": row.get("kind"),
                "label": _archive_label(row),
                "ts": row.get("ts"),
            }
        )
        if len(out) >= int(limit) + 2:
            break
    return out


def _archive_label(row: dict) -> str:
    """A revision's name in the picker.

    The class is what distinguishes two records from the same minute, so
    it leads; the timestamp is rendered by the frontend, which knows the
    viewer's locale and how much width the chip has.
    """
    label = row.get("label") or row.get("field_de")
    return str(label) if label else "Netz-Stand"


def revision_overrides(storage_root, cam_id: str, revision_id: str, current_cfg: dict):
    """The tuning overrides that reproduce one archived revision.

    Mirrors what ``_netz_helpers.apply_axes`` computes for a restore —
    through the same ``manual_patch`` — but RETURNS the patch instead of
    writing it anywhere.

    Returns ``None`` when the record is unknown, belongs to a different
    camera, or carries no net. The caller turns that into an error
    rather than a silent fall back to the live profile: a simulation
    that quietly ran something other than what the chip claims is worse
    than one that refuses.
    """
    rec = get_record(storage_root, revision_id)
    if not rec or rec.get("cam_id") != cam_id:
        return None
    axes = {
        label: info.get("E")
        for label, info in (rec.get("net_state") or {}).items()
        if isinstance(info, dict) and info.get("E") is not None
    }
    if not axes:
        return None

    cfg = current_cfg or {}
    label_thresholds = dict(cfg.get("label_thresholds") or {})
    push_thresholds = dict(cfg.get("push_thresholds") or {})
    pins: dict = {}
    for label, e in axes.items():
        patch = manual_patch(label, e)
        label_thresholds.update(patch["label_thresholds"])
        push_thresholds.update(patch["push_thresholds"])
        pins.update(patch["net_pin"])
    return {
        "label_thresholds": label_thresholds,
        "push_thresholds": push_thresholds,
        "net_pin": pins,
        # A historic revision is authoritative for every axis it names.
        # Leaving the learner's CURRENT proposals in place would blend
        # today's adaptation into a picture of the past.
        "net_adapted": {},
    }


def spec_for(revision_id: str):
    """The ``resolve_replay_settings`` spec for one revision id.

    Revisions ride the replay's existing settings vocabulary rather than
    a second one: ``current`` and ``factory`` are bare tokens, and an
    archived revision is ``{"revision": <event_id>}``.
    """
    if revision_id == REVISION_CURRENT:
        return REVISION_CURRENT
    if revision_id == REVISION_FACTORY:
        return REVISION_FACTORY
    return {"revision": revision_id}


def simulation_cfg(storage_root, cam_id: str, cam_cfg: dict, revision_id):
    """``(cfg, descriptor)`` for one simulation tick.

    ``cfg`` is what the tick's gates, thresholds and tracker should read.
    For the live profile that is the caller's own dict, unchanged. For a
    revision it is a NEW dict — the camera's real identity, geometry,
    zones and masks with the revision's tuning laid over the top. The
    caller's ``cam_cfg`` is the running camera's live config and is
    never mutated, which is the property that keeps a simulated revision
    out of the camera's stored settings.

    Raises ``ValueError`` when the revision cannot be resolved.
    """
    from ._settings import resolve_replay_settings

    if not revision_id or revision_id == REVISION_CURRENT:
        return cam_cfg, None
    settings = resolve_replay_settings(
        {},
        cam_cfg,
        spec_for(revision_id),
        revisions=lambda rid: revision_overrides(storage_root, cam_id, rid, cam_cfg),
    )
    descriptor = {k: v for k, v in settings.items() if k != "cfg"}
    return {**(cam_cfg or {}), **settings["cfg"]}, descriptor
