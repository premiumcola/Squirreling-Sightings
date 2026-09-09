"""The Telegram caption shows the species, not just "Vogel".

Traced request: "die Abfrage der Spezies in Telegram kommt gar nicht
für Vögel" — `bird_species` was already computed and sitting on the
event before either caption function ran; neither one read it.
"""

from __future__ import annotations

from app.telegram_bot._outbound._event_alert import _event_caption
from app.telegram_bot._outbound._question import _caption
from app.telegram_helpers import species_caption_label


def test_species_caption_label_prefers_the_species_for_a_bird():
    assert species_caption_label("bird", {"bird_species": "Elster"}) == "Elster"


def test_species_caption_label_falls_back_to_the_class_without_a_species():
    assert species_caption_label("bird", {}) == "Vogel"
    assert species_caption_label("bird", {"bird_species": "  "}) == "Vogel"


def test_species_caption_label_is_unchanged_for_every_other_class():
    assert species_caption_label("person", {"bird_species": "Elster"}) == "Person"
    assert species_caption_label("cat", {}) == "Katze"


def test_the_question_caption_names_the_species():
    text = _caption("Nut Bar", "bird", 0.72, {"bird_species": "Elster"})
    assert "Elster" in text
    assert "Vogel" not in text
    assert "72 %" in text


def test_the_question_caption_falls_back_without_a_species():
    text = _caption("Nut Bar", "bird", 0.72, {})
    assert "Vogel" in text


def test_the_event_alert_caption_names_the_species():
    text = _event_caption({"bird_species": "Elster"}, "bird", "Nut Bar", 91)
    assert "Elster" in text
    assert "Vogel" not in text


def test_the_first_since_headline_also_names_the_species():
    meta = {
        "bird_species": "Elster",
        "first_since": {"label": "bird", "gap_hours": 5.0},
    }
    text = _event_caption(meta, "bird", "Nut Bar", 91)
    assert "Erstes Elster seit" in text


def test_a_non_bird_event_alert_caption_is_unchanged():
    text = _event_caption({}, "person", "Nut Bar", 88)
    assert "Person" in text
