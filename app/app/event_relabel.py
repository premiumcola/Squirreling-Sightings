"""Applying an operator's "this label is wrong" verdict to the event's
OWN record — not just the diagnostic / threshold-tuning ledgers.

Two surfaces let an operator say a label is wrong: the web lightbox's
label-bubble toggle (``routes.events.api_event_labels`` — tapping an
already-active bubble turns it off) and the Telegram "❌ Nein" / "war
etwas anderes" buttons (``telegram_bot._inbound_event``). Both need the
same two things done, atomically, to ``event`` — keep ``top_label`` in
sync with ``labels``, and drop ``cat_name`` / ``bird_species`` when the
label they pin (``cat`` / ``bird``) is the one leaving the list.

Before this module existed, only the labels list itself was kept in
sync (web) — ``cat_name``/``bird_species`` stayed stamped even after
the class left ``labels``, so a label FILTER still matched the event
through ``extras`` (see ``storage._filter_events``) even though its
badge no longer showed the class. On the Telegram side nothing at all
was synced: a "Nein" on a cat alert left ``labels: ["cat"]`` standing,
and the badge, the filters and the achievement counters all read that
straight off the event, so nothing downstream ever saw the correction.

One function, both callers — CLAUDE.md forbids a second copy of this.
"""

from __future__ import annotations

#: label -> event field a species/identity classifier stamps IN
#: ADDITION to (or instead of) `labels`. Mirrors the match set
#: `library._motion_reader._matches_label` / `storage._filter_events`
#: use, so a filter can never match on a field this module left stale.
IDENTITY_FIELDS: dict[str, str] = {"cat": "cat_name", "bird": "bird_species"}


def sync_top_label(event: dict, labels: list) -> str:
    """The `top_label` `labels` implies — the rule this project has used
    since the web label editor first shipped: keep the previous
    top_label if it survived the edit, else the new first label, else
    the residual "motion" bucket (this codebase's stand-in for "no
    recognized class" — see `labels.primary_label`)."""
    prev_top = event.get("top_label")
    if not labels:
        return "motion"
    if prev_top in labels:
        return prev_top
    return labels[0]


#: Detection lists this module also walks, keyed by where they live on
#: the event. `whole_clip.detections` is the one the player's object
#: list actually prefers (`vplayer/_data/_map.js::objectRowsFor` reads
#: it before the tracks.json sidecar or the trigger frame) — without
#: this, "Person raus editieren" left every per-object heading still
#: reading "Person" forever, on this load AND every one after, because
#: nothing had ever corrected the ONE place that heading is drawn from.
_DETECTION_LIST_PATHS: tuple[tuple[str, ...], ...] = (
    ("whole_clip", "detections"),
    ("detections",),
)


def _neutralize_disproven_detections(event: dict, removed: set) -> None:
    """A detection entry whose label just left `labels` is disproven —
    same verdict as the identity fields above, applied to the per-
    object rows instead of the event-level badge.

    Relabelled to "motion", not dropped: the entry's timing/bbox/track
    still describes something real that moved in frame, only the CLASS
    guess was wrong — exactly the residual bucket `sync_top_label`
    already falls back to for the event itself. Species/identity on the
    same entry go stale together with the label that pinned them, for
    the same reason `IDENTITY_FIELDS` clears them at the event level.
    """
    if not removed:
        return
    for path in _DETECTION_LIST_PATHS:
        node = event
        for key in path[:-1]:
            node = node.get(key) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                node = None
                break
        dets = node.get(path[-1]) if isinstance(node, dict) else None
        if not isinstance(dets, list):
            continue
        for d in dets:
            if isinstance(d, dict) and d.get("label") in removed:
                d["label"] = "motion"
                d["species"] = None
                d["species_latin"] = None
                d["species_score"] = None
                d["identity"] = None


def apply_label_change(event: dict, labels: list) -> dict:
    """Mutate `event` in place for a new `labels` list. Returns `event`.

    Keeps `top_label` in sync, clears any identity field (`cat_name`,
    `bird_species`) whose label just left the list, and neutralizes any
    per-detection row that carried it — a disproven "cat" must not
    leave a cat identity name standing (the badge/filters would still
    match it through `extras`), and a disproven "person" detection must
    not keep telling the object-list panel it is still a person.
    """
    removed = set(event.get("labels") or []) - set(labels)
    event["top_label"] = sync_top_label(event, labels)
    event["labels"] = labels
    for label, field in IDENTITY_FIELDS.items():
        if label in removed and event.get(field):
            event[field] = None
    _neutralize_disproven_detections(event, removed)
    return event


def labels_after_correction(
    labels_before: list, wrong_label: str, corrected_label: str | None
) -> list:
    """The new `labels` list for a "this was wrong" verdict.

    Plain "no" (`corrected_label=None`): `wrong_label` just comes off —
    `apply_label_change`'s top_label sync then falls back to "motion",
    this codebase's existing residual/unrecognized bucket and the
    closest first-class concept to the "unbekannt" an operator asks
    for (see `labels.primary_label`'s docstring). There is no separate
    "unknown" label to invent here without duplicating that concept.

    A replacement label goes to the FRONT: `primary_label` /
    `sync_top_label` both pick the first recognized label, and a named
    correction should become the new primary — not a secondary tag
    trailing whatever else fired on the same event.
    """
    out = [lab for lab in (labels_before or []) if lab not in (wrong_label, corrected_label)]
    if corrected_label:
        out.insert(0, corrected_label)
    return out
