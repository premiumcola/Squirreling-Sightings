"""Whole-clip detection aggregate for one recording session.

WHAT THIS CLOSES
----------------
An event's `detections` list is one frame's worth of evidence:
`_motion.py::_build_event_meta` serialises the detections of the single
tick on which recording started, and `_upgrade_event_meta` can REPLACE
that list with a single later frame's, but never accumulates. So a clip
that plainly holds two birds files one; a species that only becomes
identifiable three seconds in never reaches the event; and
`bird_species_rank.py` ranks the headline over one frame's worth of
candidates. The batch replay (`replay_batch/`) walks the whole clip and
regularly finds more than the event recorded — that gap is what this
closes, at record time, for the clip that is recording now.

DERIVED FROM THE TRACKER, NOT COLLECTED A SECOND TIME
-----------------------------------------------------
The cross-frame identity this needs already exists.
`tracker_core.LiveTracker.step_matches` returns `(detection, track)`
pairs and `step()` is literally that call with the tracks dropped one
line later — the live loop was computing the association and throwing
it away. So this keys on the tracker's own `track_id`: one row per
tracked subject, not one row per frame-detection. A second accumulator
alongside the tracker would be the parallel implementation CLAUDE.md
forbids, and it would disagree with the tracker the first time an IoU
association went one way and the copy went the other.

Detections the tracker never saw — the wildlife stage synthesises its
`Detection` AFTER association (`_wildlife_stage.py`) — have no track to
key on and collapse by LABEL instead. That stage appends at most one
detection per frame, so "one row per label" is exactly right there and
is not a guess.

COST
----
Zero extra inference. The detector already runs on every analysis tick
of a recording clip (`_main_loop.py`, `detect_frame_raw`), the bird
classifier has already stamped its species onto the very objects handed
here (`stamp_species`), and the re-id stages have already written their
identities. This reads results that are computed either way and folds
them together; it never calls a model.

BOUNDED BY CONSTRUCTION
-----------------------
An event document must not grow with the length of the clip. Rows are
capped globally and per class, species rows are capped, and each row is
a fixed-size summary rather than a sample list — a five-minute clip in a
busy garden costs the same as a five-second one. `truncated` says a cap
bit, so a capped list is never mistaken for a complete one.
"""

from __future__ import annotations

from ..bird_species_rank import pick_headline_species
from ..species_tally import SpeciesTally

#: Rows one event may carry, across every class. A garden clip with
#: forty distinct tracked subjects is already far past the point where
#: a per-subject list tells the operator anything; the cap is here so
#: the JSON cannot grow without bound, not because 40 is meaningful.
CLIP_MAX_ROWS = 40

#: Rows one event may carry for a SINGLE label. Bounds the failure mode
#: the global cap alone would not: a feeder that spawns a fresh bird
#: track every few seconds must not crowd out the one squirrel row that
#: is the interesting half of the clip.
CLIP_MAX_ROWS_PER_CLASS = 12

#: Distinct species one event may carry. Matches
#: `replay_batch/_consts.py::MAX_SPECIES_ROWS` so the live aggregate and
#: the batch report truncate at the same place.
CLIP_MAX_SPECIES = 25

#: `SpeciesTally.max_crops` is a spend budget for the offline sweep,
#: which pays one classifier invocation per crop it decides to examine.
#: The live path pays nothing here — the classification already
#: happened — so the budget is not the mechanism that bounds this and
#: is set out of the way. `CLIP_MAX_SPECIES` is the live bound.
_UNBUDGETED = 1 << 30


def rank_headline_species(candidates: list[tuple[str, str | None]]) -> str | None:
    """The ONE display name to stamp as `event["bird_species"]`.

    The rule itself is `bird_species_rank.pick_headline_species` and is
    unchanged — rarest-or-never-recorded first. What changes is only how
    many candidates reach it: a whole clip's worth instead of the single
    frame `_build_event_meta` saw.

    Looks up dossier counts via the live BirdDossierService the same way
    `_recording/_publish.py::_publish_dossiers` already reads it — one
    in-memory dict lookup behind a lock, no network I/O, so there is no
    latency concern that would keep this off the detection path.
    Degrades to the historic "first in stored order" fallback (via
    `pick_headline_species`'s own None-handling) when the service is not
    wired up yet or anything about reaching it fails: naming a bird must
    never be able to take event creation down.
    """
    if not candidates:
        return None
    lookup = None
    try:
        from .. import app_state as _app_state

        svc = getattr(_app_state, "bird_dossiers", None)
        lookup = svc.get_dossier if svc is not None else None
    except Exception:
        lookup = None
    return pick_headline_species(candidates, lookup)


def _bbox_dict(bbox) -> dict | None:
    """`Detection.bbox` is a 4-tuple; the event JSON speaks the
    x1/y1/x2/y2 dict that `Detection.to_dict` writes. Rows live on the
    event document beside `detections`, so they use the document's own
    convention and a renderer needs no second code path."""
    try:
        x1, y1, x2, y2 = bbox
    except (TypeError, ValueError):
        return None
    return {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}


class ClipTally:
    """Every subject seen anywhere in ONE recording session.

    Fed one analysis tick at a time via `add_frame`; `rows()` and
    `species()` are the whole-clip answer at any point, so a clip that
    is still recording can be asked what it holds so far.
    """

    def __init__(
        self,
        *,
        max_rows: int = CLIP_MAX_ROWS,
        max_per_class: int = CLIP_MAX_ROWS_PER_CLASS,
        max_species: int = CLIP_MAX_SPECIES,
    ):
        self.max_rows = int(max_rows)
        self.max_per_class = int(max_per_class)
        #: True when any cap refused a row or a species.
        self.truncated = False
        #: Analysis ticks folded in, whether or not they held anything.
        self.frames = 0
        self._rows: dict[str, dict] = {}
        self._per_class: dict[str, int] = {}
        self._tally = SpeciesTally(max_crops=_UNBUDGETED, max_species=max_species)

    # ── ingest ──────────────────────────────────────────────────────
    def add_frame(self, detections, t_s: float) -> None:
        """Fold one analysis tick's surviving detections into the clip.

        `t_s` is seconds since the clip opened. Called on every tick of
        a recording session — including the ticks with no motion, which
        is where a subject that arrives late in the clip is found.
        """
        self.frames += 1
        for det in detections or []:
            self._add_detection(det, t_s)

    def _key_for(self, det) -> str | None:
        """The identity this detection folds into.

        The tracker's `track_id` when it has one. Otherwise the label —
        a detection with no track has no identity finer than its class,
        and pretending otherwise would file one squirrel as thirty.
        """
        track_id = getattr(det, "track_id", None)
        if track_id:
            return f"track:{track_id}"
        label = (getattr(det, "label", "") or "").strip()
        return f"class:{label}" if label else None

    def _add_detection(self, det, t_s: float) -> None:
        key = self._key_for(det)
        if key is None:
            return
        row = self._rows.get(key)
        if row is None:
            row = self._open_row(key, det, t_s)
            if row is None:
                return
        else:
            self._extend_row(row, det, t_s)
        self._add_species(det)

    def _open_row(self, key: str, det, t_s: float) -> dict | None:
        """Start a row for a subject not seen before in this clip, or
        return None when a cap refuses it."""
        label = (getattr(det, "label", "") or "").strip()
        if len(self._rows) >= self.max_rows:
            self.truncated = True
            return None
        if self._per_class.get(label, 0) >= self.max_per_class:
            self.truncated = True
            return None
        self._per_class[label] = self._per_class.get(label, 0) + 1
        track_id = getattr(det, "track_id", None)
        row = {
            "track_id": track_id or None,
            "label": label,
            "score": round(float(getattr(det, "score", 0.0) or 0.0), 4),
            "bbox": _bbox_dict(getattr(det, "bbox", None)),
            "species": getattr(det, "species", None),
            "species_latin": getattr(det, "species_latin", None),
            "species_score": _round_opt(getattr(det, "species_score", None)),
            "identity": getattr(det, "identity", None),
            "model": getattr(det, "model", None),
            "frames": 1,
            "first_s": round(float(t_s), 3),
            "last_s": round(float(t_s), 3),
        }
        self._rows[key] = row
        return row

    def _extend_row(self, row: dict, det, t_s: float) -> None:
        """Fold a repeat sighting of a subject already in the clip.

        The row keeps the BEST-scoring frame's geometry and label, which
        is the same choice `replay/_diff.py::track_to_detection` makes
        when it collapses a whole track to one detection — so a row here
        and a row there describe the same frame of the same subject.
        """
        row["frames"] += 1
        row["last_s"] = round(float(t_s), 3)
        score = float(getattr(det, "score", 0.0) or 0.0)
        if score > row["score"]:
            row["score"] = round(score, 4)
            row["bbox"] = _bbox_dict(getattr(det, "bbox", None))
            row["label"] = (getattr(det, "label", "") or "").strip() or row["label"]
            row["model"] = getattr(det, "model", None) or row["model"]
        # Species and identity are decided by a LATER cascade stage than
        # the box score, so they must not ride on the score comparison
        # above: the best-scoring detector frame is regularly not the
        # frame on which the classifier finally named the bird. That is
        # the whole "identifiable only three seconds in" case.
        species_score = getattr(det, "species_score", None)
        if getattr(det, "species", None) and _beats(species_score, row.get("species_score")):
            row["species"] = det.species
            row["species_latin"] = getattr(det, "species_latin", None)
            row["species_score"] = _round_opt(species_score)
            row["model"] = getattr(det, "model", None) or row["model"]
        if getattr(det, "identity", None) and not row.get("identity"):
            row["identity"] = det.identity

    def _add_species(self, det) -> None:
        """Fold an already-classified bird into the species tally.

        `stamp_species` ran in the main loop; this only reads what it
        wrote. Nothing here invokes a classifier.
        """
        species = getattr(det, "species", None)
        if not species:
            return
        if (getattr(det, "label", "") or "") != "bird":
            # The wildlife stage reuses `species` for its raw ImageNet
            # label, which is not a bird binomial and must not enter a
            # tally the dossier subsystem keys on.
            return
        self._tally.crops_classified += 1
        self._tally.hits += 1
        self._tally.add(
            species, getattr(det, "species_latin", None), getattr(det, "species_score", None)
        )

    # ── read ────────────────────────────────────────────────────────
    def rows(self) -> list[dict]:
        """One row per subject, best-scoring first.

        Ordering matches `SpeciesTally.result()`'s rule — score
        descending, then label — so the two lists on an event read the
        same way round.
        """
        return sorted(
            self._rows.values(),
            key=lambda r: (-float(r["score"] or 0.0), r["label"] or ""),
        )

    def species(self) -> list[dict]:
        """Distinct species anywhere in the clip, best-scoring first."""
        return self._tally.result()

    def headline_candidates(self) -> list[tuple[str, str | None]]:
        """`(display, latin)` pairs for `bird_species_rank`.

        Order is the tally's — best-classified first — which is what
        `pick_headline_species` falls back on when two candidates rank
        equally, and when no dossier service is wired up at all. The
        rarest-first rule itself is unchanged; it just gets the whole
        clip's candidates instead of one frame's.
        """
        return [(r["species"], r["species_latin"]) for r in self.species() if r["species"]]

    def is_truncated(self) -> bool:
        return bool(self.truncated or self._tally.truncated)

    def summary(self) -> dict:
        """The block written onto the event document."""
        return {
            "detections": self.rows(),
            "species": self.species(),
            "frames": self.frames,
            "truncated": self.is_truncated(),
        }


def single_frame_summary(detections) -> dict:
    """The whole-clip block for an event that has exactly one frame.

    Two callers need this. A snapshot camera has no clip at all, so its
    one frame IS the whole answer. And a recording event must carry a
    well-formed block from the instant the stub is written, because the
    stub can be the last thing written if the runtime dies mid-clip —
    an event whose `whole_clip` is missing and one whose clip genuinely
    held one thing must not look the same.

    Built through `ClipTally` rather than hand-rolled so a one-frame
    block is shaped by the same code as a thousand-frame one.
    """
    tally = ClipTally()
    tally.add_frame(detections, 0.0)
    return tally.summary()


def _round_opt(value) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _beats(candidate, current) -> bool:
    """Whether `candidate` is a better species score than `current`.

    An unscored name still beats no name at all — some classifier paths
    return a species without a confidence — but never displaces a scored
    one.
    """
    if current is None:
        return True
    if candidate is None:
        return False
    try:
        return float(candidate) > float(current)
    except (TypeError, ValueError):
        return False
