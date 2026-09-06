"""Umgewandelt wird begrenzt und der Reihe nach — älteste zuerst.

„Nimmst du mehrere videos parallel auf?? Das macht keinen sinn."
„Wandel von alt nach neu der reihe nach um!"

Gemessen am 2026-09-06 um 16:13: 1 Aufnahme, aber 8 gleichzeitige
Umwandlungen, Alter 7 / 135 / 449 / 534 / 543 / 539 / 655 / 901 s. Keine
wurde fertig. `libx264` nimmt sich alle Kerne, also waren das auf 30
Kernen acht mal dreissig Threads — jeder Auftrag achtmal langsamer,
wodurch mehr aufliefen, wodurch alle noch langsamer wurden.

Ein `BoundedSemaphore` hätte die Zahl begrenzt, aber nicht die
Reihenfolge: er weckt einen BELIEBIGEN Wartenden. Deshalb eine echte
Reihe, sortiert nach Ereignis-ID — die ist ein Zeitstempel und sortiert
damit von selbst von alt nach neu.
"""

from __future__ import annotations

import threading

import pytest

from app.camera_runtime._recording import _encode_queue as q


@pytest.fixture(autouse=True)
def _reset():
    """Der Zustand ist modulweit — jeder Test bekommt eine leere Reihe."""
    with q._CV:
        q._running = 0
        q._wartend.clear()
        q._inflight.clear()
        q._lfd = 0
    yield
    with q._CV:
        q._running = 0
        q._wartend.clear()
        q._inflight.clear()


def test_die_voreinstellung_ist_kleiner_als_der_gemessene_schaden():
    # Acht gleichzeitige 4K-Transkodierungen waren der Fehler. Die
    # Voreinstellung muss deutlich darunter liegen, sonst ändert die
    # ganze Reihe nichts.
    assert q._slots() == 2
    assert 1 <= q.ENCODE_SLOTS <= 8


def test_ein_platz_wird_belegt_und_wieder_frei():
    assert q.queue_depth() == (0, 0)
    with q.encode_slot("cam_a", "20260906-160000-000001"):
        assert q.queue_depth() == (1, 0)
        assert "20260906-160000-000001" in q.inflight_event_ids()
    assert q.queue_depth() == (0, 0)
    assert q.inflight_event_ids() == frozenset()


def test_mehr_als_erlaubt_laeuft_nicht_gleichzeitig():
    hoechststand = 0
    stand = 0
    zaehler = threading.Lock()
    los = threading.Event()
    halt = threading.Event()

    def auftrag(eid):
        nonlocal hoechststand, stand
        los.wait(5)
        with q.encode_slot("cam_a", eid):
            with zaehler:
                stand += 1
                hoechststand = max(hoechststand, stand)
            halt.wait(5)
            with zaehler:
                stand -= 1

    threads = [
        threading.Thread(target=auftrag, args=(f"20260906-1600{i:02d}-000000",))
        for i in range(q.ENCODE_SLOTS + 3)
    ]
    for t in threads:
        t.start()
    los.set()
    # Warten, bis die Reihe voll ist und der Rest ansteht.
    for _ in range(500):
        if q.queue_depth() == (q.ENCODE_SLOTS, 3):
            break
        threading.Event().wait(0.01)
    assert q.queue_depth() == (q.ENCODE_SLOTS, 3)
    halt.set()
    for t in threads:
        t.join(5)
    assert hoechststand == q.ENCODE_SLOTS
    assert q.queue_depth() == (0, 0)


def test_der_aelteste_kommt_zuerst_dran():
    """Der Kern der Forderung: von alt nach neu, nicht wer zufällig wach wird."""
    reihenfolge: list[str] = []
    schreiben = threading.Lock()
    blocker_frei = threading.Event()
    alle_da = threading.Event()

    def blocker():
        with q.encode_slot("cam_a", "00000000-000000-000000"):
            blocker_frei.wait(5)

    # Alle Plätze belegen, damit die Bewerber garantiert warten müssen.
    blocker_threads = [threading.Thread(target=blocker) for _ in range(q.ENCODE_SLOTS)]
    for t in blocker_threads:
        t.start()
    for _ in range(500):
        if q.queue_depth()[0] == q.ENCODE_SLOTS:
            break
        threading.Event().wait(0.01)

    # Bewerber in VERKEHRTER Reihenfolge anstellen — jüngster zuerst.
    ids = [f"20260906-1{i}0000-000000" for i in range(5)]

    def bewerber(eid):
        with q.encode_slot("cam_a", eid):
            with schreiben:
                reihenfolge.append(eid)

    threads = []
    for eid in reversed(ids):
        t = threading.Thread(target=bewerber, args=(eid,))
        t.start()
        threads.append(t)
        # Einzeln abwarten, bis dieser Bewerber wirklich in der Reihe
        # steht. Sonst ist die Ankunftsreihenfolge zufällig und der Test
        # prüft nicht, was er zu prüfen behauptet.
        for _ in range(500):
            if len(q._wartend) == len(threads):
                break
            threading.Event().wait(0.01)
        assert len(q._wartend) == len(threads), "Bewerber kam nicht in der Reihe an"

    # ERST jetzt freigeben. Gäben die Blocker vorher frei, wäre der erste
    # Ankömmling zu Recht dran und der Test bewiese nichts.
    alle_da.set()
    blocker_frei.set()
    for t in blocker_threads + threads:
        t.join(5)

    # Angestellt: neu→alt. Bedient: alt→neu.
    assert reihenfolge == ids


def test_ein_clip_ohne_id_draengelt_sich_nicht_vor():
    # Sortierschlüssel "~" liegt hinter jeder Ziffer — ein Clip ohne
    # Zeitstempel landet am Ende, nicht zufällig mittendrin.
    with q._CV:
        q._wartend.extend([("~", 1), ("20260906-100000-000000", 2)])
        q._wartend.sort()
        assert q._wartend[0][0] == "20260906-100000-000000"


def test_ein_fehler_gibt_den_platz_trotzdem_frei():
    with pytest.raises(RuntimeError):
        with q.encode_slot("cam_a", "20260906-160000-000001"):
            raise RuntimeError("ffmpeg explodiert")
    assert q.queue_depth() == (0, 0)
    assert q.inflight_event_ids() == frozenset()
