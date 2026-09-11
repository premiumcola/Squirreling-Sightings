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


# ── per-detection neutralization ────────────────────────────────────────
# "auch wenn ich person raus editiere heisst die spur immernoch person??"
# — the object-list heading is drawn from whole_clip.detections[i].label
# (vplayer/_data/_map.js::objectRowsFor), which apply_label_change never
# touched before. It only ever cleared the EVENT-level cat_name/
# bird_species, never the per-object rows the panel actually renders.


def test_a_disproven_label_is_neutralized_in_whole_clip_detections():
    ev = _event(
        labels=["person", "bird"],
        top_label="person",
        whole_clip={
            "detections": [
                {"label": "person", "score": 0.8, "identity": None},
                {"label": "bird", "score": 0.6, "species": "Elster"},
            ],
            "frames": 10,
        },
    )
    apply_label_change(ev, ["bird"])
    dets = ev["whole_clip"]["detections"]
    assert dets[0]["label"] == "motion"
    assert dets[1]["label"] == "bird"  # untouched — its label survived


def test_neutralizing_a_detection_also_drops_its_species_and_identity():
    """A disproven "person" detection that happened to carry a stale cat
    identity or species guess must not keep either — same reasoning as
    the event-level IDENTITY_FIELDS clear, applied per row."""
    ev = _event(
        labels=["person", "bird"],
        top_label="person",
        whole_clip={
            "detections": [
                {
                    "label": "person",
                    "score": 0.6,
                    "identity": "Whiskers",
                    "species": "Elster",
                    "species_latin": "Pica pica",
                    "species_score": 0.5,
                }
            ]
        },
    )
    apply_label_change(ev, ["bird"])
    d = ev["whole_clip"]["detections"][0]
    assert d["label"] == "motion"
    assert d["identity"] is None
    assert d["species"] is None
    assert d["species_latin"] is None
    assert d["species_score"] is None


def test_the_trigger_frame_detections_are_neutralized_too():
    """The third and last fallback objectRowsFor reads when neither
    whole_clip nor a tracks.json sidecar has anything."""
    ev = _event(labels=["person"], top_label="person", detections=[{"label": "person"}])
    apply_label_change(ev, [])
    assert ev["detections"][0]["label"] == "motion"


def test_a_detection_whose_label_survives_is_left_alone():
    ev = _event(
        labels=["person", "bird"],
        top_label="person",
        whole_clip={"detections": [{"label": "bird", "score": 0.7, "species": "Kohlmeise"}]},
    )
    apply_label_change(ev, ["bird"])
    d = ev["whole_clip"]["detections"][0]
    assert d["label"] == "bird"
    assert d["species"] == "Kohlmeise"


def test_no_detections_at_all_is_not_an_error():
    ev = _event()
    apply_label_change(ev, [])  # must not raise
    assert "whole_clip" not in ev or ev.get("whole_clip") is None


def test_a_malformed_whole_clip_is_not_an_error():
    ev = _event(labels=["person"], top_label="person", whole_clip={"detections": "kaputt"})
    apply_label_change(ev, [])  # must not raise
    assert ev["whole_clip"]["detections"] == "kaputt"


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


# ── The sidecar carries the correction too ──────────────────────────────
# `apply_label_change` rewrites the event's own detection rows, and that
# was enough while the player drew its lanes from them. It is not any
# more: timeline/_basis.js prefers the tracks.json SIDECAR whenever one
# exists, and every clip has one now. So a corrected clip kept a rail
# full of lanes wearing the class that had just been taken off it —
# „das editieren hier, dass ich ein Element raus editiere, muss auch
# funktionieren. Dann müssen die Spuren [...] als unbekannt oder als
# Vogel einfach nur beschriftet werden."

import json as _json  # noqa: E402

from app.event_relabel import (  # noqa: E402
    neutralize_sidecar_file,
    neutralize_sidecar_tracks,
)


def _sidecar(*labels):
    return {
        "schema": 4,
        "tracks": [
            {
                "label": lab,
                "species": "Elster" if lab == "bird" else None,
                "species_latin": "Pica pica" if lab == "bird" else None,
                "species_score": 0.7 if lab == "bird" else None,
                "samples": [{"t": 0.0}],
            }
            for lab in labels
        ],
    }


def test_a_disproven_class_relabels_its_tracks_to_motion():
    sc = _sidecar("bird", "bird")
    assert neutralize_sidecar_tracks(sc, {"bird"}) is True
    assert [t["label"] for t in sc["tracks"]] == ["motion", "motion"]


def test_the_species_on_a_disproven_track_goes_with_it():
    sc = _sidecar("bird")
    neutralize_sidecar_tracks(sc, {"bird"})
    t = sc["tracks"][0]
    assert t["species"] is None and t["species_latin"] is None and t["species_score"] is None


def test_tracks_of_a_class_that_survived_are_untouched():
    sc = _sidecar("bird", "person")
    neutralize_sidecar_tracks(sc, {"bird"})
    assert [t["label"] for t in sc["tracks"]] == ["motion", "person"]


def test_the_track_itself_survives_the_correction():
    """Relabelled, never dropped: the timing and geometry still describe
    something that really moved — only the class guess was wrong."""
    sc = _sidecar("bird")
    neutralize_sidecar_tracks(sc, {"bird"})
    assert len(sc["tracks"]) == 1
    assert sc["tracks"][0]["samples"] == [{"t": 0.0}]


def test_nothing_removed_is_a_no_op():
    sc = _sidecar("bird")
    assert neutralize_sidecar_tracks(sc, set()) is False
    assert sc["tracks"][0]["label"] == "bird"


def test_a_malformed_sidecar_is_survivable():
    assert neutralize_sidecar_tracks({}, {"bird"}) is False
    assert neutralize_sidecar_tracks({"tracks": "nope"}, {"bird"}) is False
    assert neutralize_sidecar_tracks(None, {"bird"}) is False


def test_the_file_round_trip_rewrites_only_what_changed(tmp_path):
    path = tmp_path / "clip.tracks.json"
    path.write_text(_json.dumps(_sidecar("bird", "person")), encoding="utf-8")

    assert neutralize_sidecar_file(path, {"bird"}) is True

    back = _json.loads(path.read_text(encoding="utf-8"))
    assert [t["label"] for t in back["tracks"]] == ["motion", "person"]
    assert back["schema"] == 4, "the rest of the payload must survive verbatim"


def test_a_missing_sidecar_is_not_an_error(tmp_path):
    """A clip whose fine track has not been built yet still has to accept
    a correction — the rail simply has nothing to relabel."""
    assert neutralize_sidecar_file(tmp_path / "nope.tracks.json", {"bird"}) is False


def test_an_unreadable_sidecar_never_breaks_the_correction(tmp_path):
    path = tmp_path / "clip.tracks.json"
    path.write_text("{not json", encoding="utf-8")
    assert neutralize_sidecar_file(path, {"bird"}) is False


# ── „bearbeitet" ────────────────────────────────────────────────────────
#
# Ein korrigierter Clip bleibt nach dem Schließen des Players an seinem
# Platz — der Filter wird erst wieder ausgeführt, wenn der Betreiber
# einen anfasst. Ohne Marke ist der einzige Unterschied zwischen „der
# Detektor sagte Hund" und „ich sagte kein Hund" eine Erinnerung:
# „passe die badge an dass ich auch schön sehe was bearbeitet wurde".


def test_eine_korrektur_hinterlaesst_einen_zeitstempel():
    from datetime import datetime

    event = {"labels": ["dog", "motion"], "top_label": "dog"}
    apply_label_change(event, ["motion"], now=datetime(2026, 9, 11, 7, 44, 0))

    assert event["labels_edited_at"] == "2026-09-11T07:44:00"


def test_der_zeitstempel_kommt_auch_ohne_entfernte_labels():
    """Auch das HINZUFÜGEN einer Klasse ist eine Bearbeitung — die Marke
    sagt „ein Mensch war hier", nicht „etwas wurde weggenommen"."""
    event = {"labels": ["motion"], "top_label": "motion"}
    apply_label_change(event, ["motion", "cat"])

    assert event["labels_edited_at"]
