"""Cross-dimension facet counts for the unified library feed.

``count_library_facets`` backs ``GET /api/library/facets``
(``routes/library.py``) — the counts the merged filter bar
(``library/_filter-bar.js``) needs to prune irrelevant chips and badge
the rest, mirroring what the legacy per-domain pill bars already did
from their own stats endpoints (``mediathek/filters.js``'s
``_aggregateMediaCounts``, the old ``weather/sightings.js`` pill row).
``/api/library`` never had an equivalent because it never needed one
until the filter bar grew per-chip counts — see this module's git
history for the operator ask that lifted that scope boundary.

Faceted semantics, the standard "pick a value in dimension A, the
OTHER dimensions' counts adjust, A's own counts don't self-zero"
pattern: each returned dimension (``cameras``/``labels``/
``categories``) is counted against the OTHER two dimensions' currently
active filters, deliberately ignoring its OWN — so a chip already
toggled on keeps an honest count instead of collapsing to its own
selection. ``total`` is the one number that DOES apply every dimension
together, matching an unpaginated ``list_library_items`` call's full
eligible-count for the same filters.

Implementation shape: fetch ONE broadest candidate superset — every
camera (never narrowed by an active ``camera_ids`` filter, since the
``cameras`` facet has to see what every camera would contribute),
kinds/since/until exactly as requested (those aren't per-dimension
facets, they scope the whole request the same way they scope
``/api/library`` itself), no label/category filtering at the read
layer — then tally each dimension from that one superset in memory,
applying only the OTHER two dimensions' filters per facet. This reuses
``_flat_candidates``/``_widen_matches`` for the actual candidate
gathering (one full-exhaustion widen, see ``_widen_matches``'s own
docstring) and ``_cam_scoped_ok``/``_matches_categories``/
``_category_of`` for the post-fetch filtering, rather than re-running
the widen loop once per dimension.
"""

from __future__ import annotations

from datetime import datetime

from ._feed import (
    _cam_scoped_ok,
    _category_of,
    _flat_candidates,
    _matches_categories,
    _resolve_cameras,
    _resolve_want,
    _widen_matches,
)


def _label_set_of(item: dict) -> set:
    """The set of label-filter values ``item`` would match — mirrors
    ``_motion_reader._matches_label``'s own match set bit-for-bit (an
    event's ``labels`` list, plus the two single-value fields a
    species/identity classifier stamps instead of, or in addition to,
    ``labels``): the two must stay in lockstep or a facet count would
    disagree with what the actual ``labels`` filter matches."""
    extra = item.get("extra") or {}
    evt_labels = set(extra.get("labels") or [])
    extras = {extra.get("cat_name"), extra.get("bird_species")} - {None}
    return evt_labels | extras


def _matches_labels(item: dict, labels) -> bool:
    if not labels:
        return True
    return bool(set(labels) & _label_set_of(item))


def count_library_facets(
    *,
    store=None,
    weather_service=None,
    storage_root=None,
    cameras=None,
    kinds=None,
    camera_ids=None,
    labels=None,
    categories=None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Per-dimension counts + the true total for the current filters.

    Returns ``{"cameras": {cam_id: n}, "labels": {label: n},
    "categories": {category: n}, "total": n}`` — see the module
    docstring for the faceted-counting rule each dimension follows.
    ``cameras`` only ever contains kinds that carry a real ``cam_id``
    (motion/sighting/timelapse); ``labels`` only motion items;
    ``categories`` only sighting/manual/episode items.
    """
    want = _resolve_want(kinds, None, labels)
    cam_ids, cam_names = _resolve_cameras(cameras, None)
    hi = until if until is not None else datetime.now()

    degraded: list = []
    flat = _flat_candidates(want, weather_service, storage_root, cam_names, None, None)
    matched = _widen_matches(
        want=want,
        store=store,
        weather_service=weather_service,
        cam_ids=cam_ids,
        cam_names=cam_names,
        camera_ids=None,
        label=None,
        labels=None,
        categories=None,
        flat=flat,
        hi=hi,
        since=since,
        degraded=degraded,
        keep_widening=lambda _matched: True,
    )
    return _tally_facets(matched.values(), camera_ids, labels, categories)


def _tally_facets(items, camera_ids, labels, categories) -> dict:
    cam_active = set(camera_ids) if camera_ids else None
    label_active = set(labels) if labels else None
    cat_active = set(categories) if categories else None

    cameras_out: dict[str, int] = {}
    labels_out: dict[str, int] = {}
    categories_out: dict[str, int] = {}
    total = 0

    for it in items:
        cam_ok = _cam_scoped_ok(it, cam_active)
        label_ok = _matches_labels(it, label_active)
        cat_ok = _matches_categories(it, cat_active)

        if label_ok and cat_ok:
            cid = it.get("cam_id") or ""
            if cid:
                cameras_out[cid] = cameras_out.get(cid, 0) + 1

        if it["kind"] == "motion" and cam_ok and cat_ok:
            for lbl in _label_set_of(it):
                labels_out[lbl] = labels_out.get(lbl, 0) + 1

        if it["kind"] in ("sighting", "manual", "episode") and cam_ok and label_ok:
            for cat in _category_of(it):
                categories_out[cat] = categories_out.get(cat, 0) + 1

        if cam_ok and label_ok and cat_ok:
            total += 1

    return {
        "cameras": cameras_out,
        "labels": labels_out,
        "categories": categories_out,
        "total": total,
    }
