"""Die Clip-Bilanz überlebt einen Re-Encode, der nie ankommt.

„Wie kann es sein dass in einem so klarem video mit elster diese nicht
erkannt wird sondern nur grob vogel???"

Sie WURDE erkannt. Der Replay desselben Clips mit denselben gespeicherten
Einstellungen fand sie auf 7 von 26 Bildern (Elster · Pica pica · 48 %).
Live wuchs dieselbe Bilanz Bild für Bild — im Arbeitsspeicher. Auf die
Platte kam sie an genau EINER Stelle: ganz am Ende der Re-Encode-Kette.
Bei 4K bleibt die Kette regelmässig hängen; der Hänger-Sweep stempelt den
Clip 15 Minuten später auf „fertig" und fasst die Bilanz nicht an. Also
wurde der Auslöse-Platzhalter — ein Bild, Sekunde 0, ohne Artnamen — als
Ergebnis konserviert.

Gemessen: von 37 fertigen Clips trugen 31 den Platzhalter. Die Trennung
war scharf und ausnahmslos:

    ordentlich fertig   6 Clips · Vorlauf > 0: 6/6 · Art benannt: 5/6
    Platzhalter        31 Clips · Vorlauf > 0: 0/31 · Art benannt: 2/31

Dieser Test hält die Reparatur fest: die Bilanz wird beim AUFNAHMEENDE
geschrieben, nicht erst nach dem Re-Encode.
"""

from __future__ import annotations

from app.camera_runtime._clip_tally import clip_aggregate_fields, single_frame_summary
from app.camera_runtime._recording._stages import (
    STAGE_QUEUED,
    STAGE_STATUS,
    set_clip_stage,
)


class _Store:
    """Nur so viel EventStore, wie set_clip_stage anfasst."""

    def __init__(self, event=None):
        self.events = {"e1": dict(event or {})}
        self.writes = 0

    def get_event(self, _cam, eid):
        ev = self.events.get(eid)
        return dict(ev) if ev is not None else None

    def update_event(self, _cam, eid, ev):
        self.events[eid] = dict(ev)
        self.writes += 1


class _BlowsUp(_Store):
    def update_event(self, *_a, **_k):
        raise RuntimeError("Platte weg")


ELSTER_BILANZ = {
    "detections": [{"label": "bird", "species": "Elster", "frames": 7}],
    "species": ["Elster"],
    "frames": 26,
    "truncated": False,
}


# ── clip_aggregate_fields ───────────────────────────────────────────────


def test_die_bilanz_und_die_art_reisen_zusammen():
    got = clip_aggregate_fields({"whole_clip": ELSTER_BILANZ, "bird_species": "Elster"})
    assert got == {"whole_clip": ELSTER_BILANZ, "bird_species": "Elster"}


def test_ein_leeres_feld_ueberschreibt_nichts():
    # Der springende Punkt: ein Anhang darf einen schon geschriebenen
    # Wert niemals durch None ersetzen. Sonst nähme die frühe Schreibung
    # der späten das Ergebnis weg.
    assert clip_aggregate_fields({"whole_clip": None, "bird_species": None}) == {}
    assert clip_aggregate_fields({"bird_species": ""}) == {}
    assert clip_aggregate_fields({}) == {}
    assert clip_aggregate_fields(None) == {}


def test_eine_bilanz_ohne_art_reist_trotzdem():
    # Ein Clip ohne Vogel hat trotzdem eine Bilanz — die Kästen und die
    # Bildzahl sind das, woraus der Player die Objektliste baut.
    got = clip_aggregate_fields({"whole_clip": ELSTER_BILANZ})
    assert got == {"whole_clip": ELSTER_BILANZ}


# ── set_clip_stage(extra=…) ─────────────────────────────────────────────


def test_die_bilanz_landet_auf_der_platte_wenn_die_aufnahme_endet():
    stub = {"whole_clip": single_frame_summary([]), "stage": "recording"}
    store = _Store(stub)

    set_clip_stage(
        store,
        "cam_a",
        "e1",
        STAGE_QUEUED,
        clip_aggregate_fields({"whole_clip": ELSTER_BILANZ, "bird_species": "Elster"}),
    )

    ev = store.events["e1"]
    assert ev["whole_clip"]["frames"] == 26
    assert ev["bird_species"] == "Elster"
    assert ev["stage"] == STAGE_QUEUED
    # Eine Schreibung, nicht zwei — der Anhang reist auf der Stufen-
    # schreibung mit, die ohnehin stattfindet.
    assert store.writes == 1


def test_der_anhang_kann_die_stufe_nicht_ueberschreiben():
    store = _Store({"stage": "recording"})
    set_clip_stage(
        store,
        "cam_a",
        "e1",
        STAGE_QUEUED,
        {"stage": "ready", "status": "ready", "stage_since": "1999-01-01T00:00:00"},
    )
    ev = store.events["e1"]
    assert ev["stage"] == STAGE_QUEUED
    assert ev["status"] == STAGE_STATUS[STAGE_QUEUED]
    assert ev["stage_since"] != "1999-01-01T00:00:00"


def test_ohne_anhang_bleibt_alles_wie_vorher():
    store = _Store({"whole_clip": ELSTER_BILANZ, "stage": "recording"})
    set_clip_stage(store, "cam_a", "e1", STAGE_QUEUED)
    assert store.events["e1"]["whole_clip"] == ELSTER_BILANZ
    assert store.events["e1"]["stage"] == STAGE_QUEUED


def test_eine_kaputte_platte_reisst_die_aufnahme_nicht_mit():
    # Die Stufenschreibung war immer schon best-effort. Ein Anhang darf
    # daran nichts ändern — sonst kostet ein Schreibfehler den Clip.
    set_clip_stage(_BlowsUp(), "cam_a", "e1", STAGE_QUEUED, {"whole_clip": ELSTER_BILANZ})
