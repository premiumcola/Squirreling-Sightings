"""The one rule for "which species gets the headline label" when an
event carries multiple bird detections.

Two places compute `event["bird_species"]` — camera_runtime/_motion.py
::_build_event_meta (live, at clip-start) and bird_species_backfill.py
::backfill_event_species (retroactive sweep over the archive). Both
used to pick "whichever bird detection is first in stored order",
which is an accident of NMS/detection ordering, not a meaningful
choice. The operator's ask: when several species share one clip, the
headline should be whichever is RAREST by the operator's own sighting
history — or a species never recorded at all, which always outranks
an already-seen one no matter how low its count is.

Split into its own module (rather than living in bird_species_backfill
.py, which the live path would then have to import) so both call
sites share one implementation per CLAUDE.md's no-parallel-
implementations rule, without coupling the hot live-detection path to
the backfill sweep's cv2/frame-loading machinery.
"""

from __future__ import annotations

from collections.abc import Callable

#: `latin_name -> dossier dict | None`. `bird_dossiers.py::
#: BirdDossierService.get_dossier` already has this exact shape; a
#: retroactive-sweep caller adapts one via `bird_species_backfill.py::
#: dossier_lookup_for`.
DossierLookup = Callable[[str], "dict | None"]


#: How much of the best-supported candidate's evidence a rarer species
#: must ALSO carry before rarity is allowed to promote it over the
#: leader. Half: a genuine second visitor that shared the clip clears
#: this easily, a stray frame never does.
RARITY_PROMOTION_SHARE = 0.5


def _evidence(cand) -> float:
    """How much this clip actually saw of a candidate — `frames ×
    best_score` where the caller knows both, 0 where it does not.

    Zero is the historic shape: a plain ``(display, latin)`` pair carries
    no evidence, every candidate then scores 0, and the ranking below
    falls through to the pure rarity rule it has always applied.
    """
    try:
        return max(0.0, float(cand[2]))
    except (IndexError, TypeError, ValueError):
        return 0.0


def pick_headline_species(candidates, dossier_lookup: DossierLookup | None) -> str | None:
    """Pick the ONE display name to stamp as `event["bird_species"]`.

    `candidates` is every bird detection's ``(display_name,
    species_latin)`` pair — optionally with a third element, the evidence
    behind it (see `_evidence`). display_name is what gets returned,
    species_latin is only the dossier lookup key.

    EVIDENCE FIRST, THEN RARITY. The rule used to be rarity alone:
    a species with no dossier entry was a genuine new discovery and won
    outright, whatever else the clip held. Fed one frame's detections
    that was defensible. Fed a WHOLE CLIP's tally it stopped being so —
    a real archive clip carried

        Elster      best 0.70   110 frames
        Graureiher  best 0.29     1 frame

    and was filed under Graureiher, a bird that has never been in this
    garden, on the strength of a single 29 % frame. „wie ist der da
    überhaupt draufgekommen?"

    So rarity now decides only among candidates the clip actually
    supports: a rarer species must carry at least
    `RARITY_PROMOTION_SHARE` of the leader's evidence to be promoted over
    it. Everything below that line is ordered by evidence and can never
    take the headline from something the clip saw a hundred times.

    Ranking among the supported, rarest/newest first — unchanged:
      1. no dossier entry at all for that latin name — never recorded,
         a genuine new discovery, always wins;
      2. an existing dossier — lower `sighting_count` wins;
      3. no `species_latin` to look up — can't be ranked at all, sinks
         below every rankable candidate.

    Ties (equal rank, including when `dossier_lookup` is None because no
    dossier service is wired up) resolve to stored order — the historic
    "first bird detection" rule, kept as the deterministic fallback.
    """
    if not candidates:
        return None
    best_evidence = max((_evidence(c) for c in candidates), default=0.0)
    floor = best_evidence * RARITY_PROMOTION_SHARE
    if dossier_lookup is None:
        # No history to be rare against — the best-supported candidate is
        # the only defensible answer, and stored order breaks a tie.
        return max(candidates, key=lambda c: _evidence(c))[0] if best_evidence else candidates[0][0]

    def _rank(indexed: tuple[int, tuple]) -> tuple:
        idx, cand = indexed
        display, latin = cand[0], cand[1]
        del display
        ev = _evidence(cand)
        # Under the line: ranked purely by how much the clip saw, and
        # always below everything above the line.
        if best_evidence > 0 and ev < floor:
            return (1, -ev, 0, idx)
        latin = (latin or "").strip()
        if not latin:
            return (0, 2, 0, idx)
        dossier = dossier_lookup(latin)
        if not dossier:
            return (0, 0, 0, idx)
        return (0, 1, int(dossier.get("sighting_count") or 0), idx)

    _best_idx, best = min(enumerate(candidates), key=_rank)
    return best[0]
