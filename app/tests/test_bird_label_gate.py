"""The German-name gate on iNaturalist bird labels.

A species whose Latin binomial is absent from `config/inat_to_german.
json` is suppressed: `_pretty_bird_label` returns (None, latin) and the
detection stays a generic "bird". That is DELIBERATE — a region filter,
not a bug — and until this file existed nothing pinned it, so a future
refactor could have quietly reversed a decision that was made against
measurements.

The evidence, recorded in full in `_pretty_bird_label`'s docstring:
commit 639c2d6 introduced the suppression together with the top-3 walk,
scoring 50/60 (83%) correct German species and zero wrong-species hits
on a 60-image batch. The map is sourced from a Bavarian garden-bird
survey and doubles as the app's species vocabulary — the dossier
prebuild (maintenance.py) and the achievement set are both built from
it, so a species let through the gate would render with no dossier and
no icon.

These tests do not argue the trade is right. They make it VISIBLE, so
that changing it is a decision rather than an accident.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.detectors._label_loader import _extract_latin, _pretty_bird_label

MAP_PATH = Path(__file__).resolve().parents[1] / "config" / "inat_to_german.json"

MAPPING = {"Turdus merula": "Amsel", "Cyanistes caeruleus": "Blaumeise"}


class TestTheGate:
    def test_a_mapped_species_shows_its_german_name(self):
        assert _pretty_bird_label("Turdus merula (Common Blackbird)", MAPPING) == (
            "Amsel",
            "Turdus merula",
        )

    def test_an_unmapped_species_is_suppressed_but_keeps_its_binomial(self):
        """The load-bearing assertion. A recognised species outside the
        map yields no display name — the caller reads that None as
        "try the next top-k candidate", and if none map, the detection
        stays a generic bird rather than inventing a species line."""
        display, latin = _pretty_bird_label("Cardinalis cardinalis (Northern Cardinal)", MAPPING)
        assert display is None
        assert latin == "Cardinalis cardinalis"

    def test_the_binomial_survives_suppression_for_the_logs(self):
        """Suppression hides the name from the UI; it must not throw
        away what the model actually decided, or a later widening of
        the map could not be evaluated against real misses."""
        assert _pretty_bird_label("Genus novus", MAPPING)[1] == "Genus novus"


class TestLatinExtraction:
    def test_the_three_label_shapes_normalise_to_one_binomial(self):
        assert _extract_latin("Turdus merula (Common Blackbird)") == "Turdus merula"
        assert _extract_latin("PARUS MAJOR") == "Parus major"
        assert _extract_latin("Passer_domesticus") == "Passer domesticus"

    def test_a_single_word_label_is_returned_as_is(self):
        assert _extract_latin("Corvus") == "Corvus"

    def test_nothing_in_nothing_out(self):
        assert _extract_latin(None) is None
        assert _extract_latin("   ") is None


class TestTheShippedMap:
    """The map is data, and the gate's behaviour is a function of it.
    A change to its shape changes what the classifier can name."""

    def _entries(self):
        raw = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        return {k: v for k, v in raw.items() if not k.startswith("_")}

    def test_it_is_present_and_is_a_binomial_to_german_table(self):
        entries = self._entries()
        assert entries, "the gate suppresses everything without this file"
        for latin, german in entries.items():
            assert len(latin.split()) == 2, f"{latin!r} is not a Genus species binomial"
            assert german and german[0].isupper(), f"{german!r} is not a German noun"

    def test_metadata_keys_are_excluded_from_the_vocabulary(self):
        """`_`-prefixed keys carry provenance, not species. Letting one
        through would put "_source" in the dossier vocabulary."""
        raw = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        assert any(k.startswith("_") for k in raw), "provenance keys should be kept in the file"
        assert not any(k.startswith("_") for k in self._entries())

    def test_the_regional_scope_is_small_and_that_is_the_point(self):
        """~80 binomials against the iNat model's ~960 classes. The
        narrowness IS the filter; this test exists so a change in
        magnitude is noticed rather than absorbed."""
        assert 40 <= len(self._entries()) <= 200
