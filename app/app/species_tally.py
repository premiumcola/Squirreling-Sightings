"""The one accumulator for "which species appear anywhere in one clip".

Two places now aggregate species across the frames of a single clip:
`replay/_species.py` (offline, walking an archived mp4) and
`camera_runtime/_clip_tally.py` (live, folding in each analysis tick
while the clip records). They must agree — a replay that contradicts
the event it re-examines is worse than no replay — so the merge rule
lives here once rather than twice.

Split into its own top-level module for exactly the reason
`bird_species_rank.py` was: the live detection path would otherwise
have to import `replay/`, dragging the offline sweep's cv2 frame-
loading machinery onto the hot loop, and the dependency would point
the wrong way (the live pipeline is not downstream of the replay that
re-examines it).

Species are keyed by LATIN BINOMIAL, not by display name. The German
name is what the operator reads, but the binomial is what the model
actually decided and what the dossier and achievement subsystems key
on (see `bird_species_rank.py`). Two iNat labels that map to one
German name are one species and must not be counted as two.

Keeping every classified crop rather than the first is the whole
point: one frame's crop is a blurred tail, the next one's is the same
bird in profile. Ranking the distinct species by their BEST score
means a clip holding a Blaumeise and an Amsel reports both, and one
poor crop cannot outvote a good one.
"""

from __future__ import annotations


class SpeciesTally:
    """Every species the second stage named anywhere in one clip.

    Counters are kept separately from results because they answer
    different questions: `result()` says WHAT was found, the counters
    say what it cost and whether the answer is complete.

    ``max_species`` bounds the number of DISTINCT species the tally
    will hold. The replay leaves it None — its spend is already bounded
    by `max_crops`, and an offline run writes its result into a
    `replays` entry that is itself capped. The live path sets it,
    because an event JSON that grows one row per species for the whole
    length of a busy clip is exactly the unbounded growth an event
    document must not have. Hitting it sets `truncated`, so a capped
    list is never mistaken for a complete one.
    """

    def __init__(self, *, max_crops: int, max_species: int | None = None):
        self.max_crops = int(max_crops)
        self.max_species = int(max_species) if max_species is not None else None
        #: Sampled frames on which at least one crop was classified.
        self.frames_classified = 0
        #: Classifier invocations actually spent. The budgeted number —
        #: a crop `crop_bbox` refused costs no inference and is not
        #: counted against it.
        self.crops_classified = 0
        #: Invocations that came back with a name. The gap between this
        #: and `crops_classified` is the classifier's own silence: below
        #: min_score, or a species with no German name.
        self.hits = 0
        #: True when a budget ran out before the clip did, so the
        #: species list is a floor rather than the whole answer.
        self.truncated = False
        self._by_key: dict[str, dict] = {}

    @property
    def exhausted(self) -> bool:
        return self.crops_classified >= self.max_crops

    def add(self, display: str, latin: str | None, score: float | None) -> None:
        """Fold one classified crop into the clip-level result."""
        key = (latin or display or "").strip()
        if not key:
            return
        value = float(score) if score is not None else 0.0
        row = self._by_key.get(key)
        if row is None:
            # A species already in the tally is always allowed to
            # improve its score — the cap bounds how many DISTINCT
            # species a clip can carry, not how well each is measured.
            if self.max_species is not None and len(self._by_key) >= self.max_species:
                self.truncated = True
                return
            self._by_key[key] = {
                "species": display,
                "species_latin": latin,
                "best_score": round(value, 4),
                "frames": 1,
            }
            return
        row["frames"] += 1
        if value > row["best_score"]:
            row["best_score"] = round(value, 4)
            row["species"] = display
            row["species_latin"] = latin

    def result(self) -> list[dict]:
        """Distinct species, best-scoring first."""
        return sorted(
            self._by_key.values(),
            key=lambda r: (-r["best_score"], r["species"] or ""),
        )

    def names(self) -> list[str]:
        """Just the display names, in the same order."""
        return [r["species"] for r in self.result() if r["species"]]

    def stats(self) -> dict:
        return {
            "frames_classified": self.frames_classified,
            "crops_classified": self.crops_classified,
            "species_hits": self.hits,
            "classify_truncated": self.truncated,
        }
