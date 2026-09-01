"""event_relabel · the shared "this label is wrong" mutation.

Both the web lightbox's label toggle (routes/events.py) and the
Telegram "Nein"/"war etwas anderes" buttons (telegram_bot/
_inbound_event.py) go through apply_label_change +
labels_after_correction. These tests pin the pure logic directly —
the Telegram end-to-end path is covered separately in
test_telegram_verdict_corrects_event.py.
"""

from __future__ import annotations

from app.event_relabel import apply_label_change, labels_after_correction


def _event(**overrides):
    base = {
        "event_id": "evt1",
        "labels": ["cat"],
        "top_label": "cat",
        "cat_name": "Whiskers",
        "bird_species": None,
    }
    base.update(overrides)
    return base


# ── apply_label_change ──────────────────────────────────────────────────


def test_removing_the_only_label_falls_back_to_motion():
    ev = _event()
    apply_label_change(ev, [])
    assert ev["labels"] == []
    assert ev["top_label"] == "motion"


def test_removing_cat_clears_cat_name():
    """The bug: a disproven cat_name used to survive the label edit and
    kept matching a `label=cat` filter via `_filter_events`'s `extras`."""
    ev = _event()
    apply_label_change(ev, [])
    assert ev.get("cat_name") is None


def test_removing_bird_clears_bird_species():
    ev = _event(labels=["bird"], top_label="bird", cat_name=None, bird_species="Amsel")
    apply_label_change(ev, [])
    assert ev.get("bird_species") is None


def test_unrelated_label_survives_untouched():
    """Clearing cat_name/bird_species is scoped to the label that pins
    it — a squirrel event's cat_name (a stale identity from a much
    earlier registration) must not be wiped by an unrelated edit."""
    ev = _event(labels=["squirrel"], top_label="squirrel")
    apply_label_change(ev, ["squirrel", "cat"])
    assert ev.get("cat_name") == "Whiskers"


def test_top_label_survives_when_still_present():
    ev = _event(labels=["cat", "motion"], top_label="cat")
    apply_label_change(ev, ["cat", "motion"])
    assert ev["top_label"] == "cat"


def test_top_label_falls_back_to_first_remaining_label():
    ev = _event(labels=["cat", "squirrel"], top_label="cat")
    apply_label_change(ev, ["squirrel"])
    assert ev["top_label"] == "squirrel"


# ── labels_after_correction ─────────────────────────────────────────────


def test_plain_no_drops_the_wrong_label_only():
    out = labels_after_correction(["cat", "motion"], "cat", None)
    assert out == ["motion"]


def test_correction_replaces_and_becomes_primary():
    """A named correction goes to the FRONT — primary_label()/
    sync_top_label both pick labels[0]."""
    out = labels_after_correction(["cat", "motion"], "cat", "squirrel")
    assert out == ["squirrel", "motion"]


def test_correction_end_to_end_relabels_the_event():
    """The full chain a Telegram '🐿 Eichhörnchen' tap drives: the event
    that was pinned as a cat with an identity name ends up filed as a
    squirrel, with the stale cat identity gone."""
    ev = _event()
    new_labels = labels_after_correction(ev["labels"], "cat", "squirrel")
    apply_label_change(ev, new_labels)
    assert ev["labels"] == ["squirrel"]
    assert ev["top_label"] == "squirrel"
    assert ev.get("cat_name") is None
