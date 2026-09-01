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


def pick_headline_species(
    candidates: list[tuple[str, str | None]],
    dossier_lookup: DossierLookup | None,
) -> str | None:
    """Pick the ONE display name to stamp as `event["bird_species"]`.

    `candidates` is every bird detection's (display_name, species_latin)
    pair, in stored order — display_name is what gets returned (it's
    what `event["bird_species"]` has always held), species_latin is
    only the dossier lookup key.

    Ranking, rarest/newest first:
      1. no dossier entry at all for that latin name — never recorded,
         a genuine new discovery, always wins regardless of any other
         species' count.
      2. an existing dossier — lower `sighting_count` wins.
      3. no `species_latin` to look up — can't be ranked at all, sinks
         below every rankable candidate.

    Ties (equal rank, including when `dossier_lookup` is None because
    no dossier service is wired up) resolve to stored order — the
    historic "first bird detection" rule, kept as the deterministic
    fallback rather than replaced by it.
    """
    if not candidates:
        return None
    if dossier_lookup is None:
        return candidates[0][0]

    def _rank(indexed: tuple[int, tuple[str, str | None]]) -> tuple[int, int, int]:
        idx, (_display, latin) = indexed
        latin = (latin or "").strip()
        if not latin:
            return (2, 0, idx)
        dossier = dossier_lookup(latin)
        if not dossier:
            return (0, 0, idx)
        count = int(dossier.get("sighting_count") or 0)
        return (1, count, idx)

    _best_idx, (display, _latin) = min(enumerate(candidates), key=_rank)
    return display
