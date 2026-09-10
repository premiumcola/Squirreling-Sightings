"""bird_species_rank.py::pick_headline_species — the one rule shared by
the live path (camera_runtime/_motion.py::_build_event_meta) and the
offline backfill sweep (bird_species_backfill.py) for picking which
species becomes an event's headline `bird_species` when a clip holds
several.

Rarest/never-recorded-first: a species with no dossier entry always
outranks an already-seen one, regardless of count; among already-seen
species the lowest `sighting_count` wins; ties fall back to stored
order, the historic "first bird detection" rule.
"""

from __future__ import annotations

from app.bird_species_rank import pick_headline_species


def _lookup(counts: dict[str, int]):
    """Build a dossier_lookup stub: `latin -> {"sighting_count": n}` for
    every key in `counts`, `None` (no dossier) for anything else."""

    def _fn(latin: str):
        if latin not in counts:
            return None
        return {"sighting_count": counts[latin]}

    return _fn


def test_no_candidates_returns_none():
    assert pick_headline_species([], _lookup({})) is None


def test_no_dossier_lookup_falls_back_to_stored_order():
    candidates = [("Amsel", "Turdus merula"), ("Rotkehlchen", "Erithacus rubecula")]
    assert pick_headline_species(candidates, None) == "Amsel"


def test_rarest_wins_even_when_not_first_in_order():
    """The core ask: a clip with 3 species picks the rarest one, not
    whichever detection happened to fire first."""
    candidates = [
        ("Amsel", "Turdus merula"),  # idx 0, common
        ("Rotkehlchen", "Erithacus rubecula"),  # idx 1, rarest
        ("Kohlmeise", "Parus major"),  # idx 2, mid
    ]
    lookup = _lookup(
        {
            "Turdus merula": 5,
            "Erithacus rubecula": 1,
            "Parus major": 10,
        }
    )
    assert pick_headline_species(candidates, lookup) == "Rotkehlchen"


def test_never_recorded_species_always_wins_regardless_of_count():
    """A species with NO dossier entry outranks every already-seen
    species, even one with a very low sighting_count."""
    candidates = [
        ("Amsel", "Turdus merula"),  # idx 0, seen once — very rare but recorded
        ("Seltener Gast", "Genus novus"),  # idx 1, never recorded at all
    ]
    lookup = _lookup({"Turdus merula": 1})
    assert pick_headline_species(candidates, lookup) == "Seltener Gast"


def test_tie_break_keeps_stored_order():
    """Equal rank (here: both never recorded) resolves deterministically
    to the earliest candidate in stored order."""
    candidates = [
        ("Kohlmeise", "Parus major"),
        ("Blaumeise", "Cyanistes caeruleus"),
    ]
    assert pick_headline_species(candidates, _lookup({})) == "Kohlmeise"


def test_tie_break_on_equal_sighting_counts():
    candidates = [
        ("Kohlmeise", "Parus major"),
        ("Blaumeise", "Cyanistes caeruleus"),
    ]
    lookup = _lookup({"Parus major": 3, "Cyanistes caeruleus": 3})
    assert pick_headline_species(candidates, lookup) == "Kohlmeise"


def test_candidate_missing_a_latin_name_sinks_below_rankable_ones():
    candidates = [
        ("Unbekannt", None),
        ("Amsel", "Turdus merula"),
    ]
    lookup = _lookup({"Turdus merula": 100})
    assert pick_headline_species(candidates, lookup) == "Amsel"


def test_duplicate_species_in_candidates_keeps_first_occurrence():
    candidates = [
        ("Amsel", "Turdus merula"),
        ("Amsel", "Turdus merula"),
    ]
    lookup = _lookup({"Turdus merula": 2})
    assert pick_headline_species(candidates, lookup) == "Amsel"


# ── Evidence gates the rarity promotion ─────────────────────────────────
# Rarity alone was defensible when this saw ONE frame's detections. Fed a
# whole clip's tally it stopped being so, and a real archive clip
# (20260907-103617) proved it: filed under a bird that has never been in
# this garden, on one 29 % frame, against 110 frames of Elster at 70 %.
# „wie ist der da überhaupt draufgekommen?"


def test_a_single_stray_frame_never_takes_the_headline():
    """THE ARCHIVE CASE, with its real numbers."""
    candidates = [
        ("Elster", "Pica pica", 110 * 0.6992),
        ("Graureiher", "Ardea cinerea", 1 * 0.2891),  # never recorded — used to win
    ]
    assert pick_headline_species(candidates, _lookup({"Pica pica": 19})) == "Elster"


def test_a_rare_bird_that_really_shared_the_clip_still_wins():
    """The rule this protects must survive: a genuine second visitor,
    present in comparable measure, still takes the headline."""
    candidates = [
        ("Elster", "Pica pica", 100 * 0.70),
        ("Graureiher", "Ardea cinerea", 80 * 0.68),  # never recorded, well supported
    ]
    assert pick_headline_species(candidates, _lookup({"Pica pica": 19})) == "Graureiher"


def test_the_promotion_line_is_half_the_leader():
    from app.bird_species_rank import RARITY_PROMOTION_SHARE

    lead = 100.0
    lookup = _lookup({"Pica pica": 19})
    just_over = [("Elster", "Pica pica", lead), ("Graureiher", "Ardea cinerea", lead * 0.51)]
    just_under = [("Elster", "Pica pica", lead), ("Graureiher", "Ardea cinerea", lead * 0.49)]
    assert RARITY_PROMOTION_SHARE == 0.5
    assert pick_headline_species(just_over, lookup) == "Graureiher"
    assert pick_headline_species(just_under, lookup) == "Elster"


def test_without_evidence_the_historic_rarity_rule_is_untouched():
    """Plain (display, latin) pairs carry no evidence — every candidate
    scores 0, no promotion line exists, and rarity decides as it always
    did. That is what keeps every caller that has not been taught to
    measure working exactly as before."""
    candidates = [("Amsel", "Turdus merula"), ("Graureiher", "Ardea cinerea")]
    assert pick_headline_species(candidates, _lookup({"Turdus merula": 40})) == "Graureiher"


def test_with_no_dossier_service_the_best_supported_candidate_wins():
    """No history to be rare against, so the only defensible answer is
    what the clip actually saw most of — not whichever fired first."""
    candidates = [("Graureiher", "Ardea cinerea", 0.3), ("Elster", "Pica pica", 77.0)]
    assert pick_headline_species(candidates, None) == "Elster"


def test_two_thin_candidates_still_rank_by_rarity_between_themselves():
    """The line is relative to the leader, so a clip that saw little of
    anything has no leader to sink below — rarity decides as usual."""
    candidates = [("Amsel", "Turdus merula", 0.4), ("Graureiher", "Ardea cinerea", 0.38)]
    assert pick_headline_species(candidates, _lookup({"Turdus merula": 40})) == "Graureiher"
