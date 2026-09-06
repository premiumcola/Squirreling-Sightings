"""Wie viele Clips gleichzeitig umgewandelt werden — und in welcher Reihenfolge.

„Nimmst du mehrere videos parallel auf?? Das macht keinen sinn."

Aufgenommen wird immer nur einer. UMGEWANDELT wurden acht — gemessen am
2026-09-06 um 16:13, Alter der acht Aufträge: 7 s, 135 s, 449 s, 534 s,
543 s, 539 s, 655 s, 901 s. Keiner davon wurde fertig.

Bis hierher bekam jeder Clip beim Aufnahmeende einen eigenen Thread, der
sofort in ffmpeg lief — ohne Bremse, ohne Pool, ohne Semaphor. Das war
kein Versehen, sondern stand so im Konzept: „each clip gets its OWN
thread, so this is *not* a FIFO position. Never render it as '3rd in
line' — there is no line." Solange Clips einzeln kommen, stimmt das.

Bei Fütterung am Vogelhaus kommen sie nicht einzeln. Und `libx264` nimmt
sich per Voreinstellung alle Kerne: auf den 30 Kernen dieses Hosts sind
acht 4K-Transkodierungen 240 Threads auf 30 Kernen. Jeder Auftrag wird
achtmal langsamer, wodurch mehr Auslöser auflaufen, wodurch alle noch
langsamer werden. Eine Lawine, die sich selbst füttert — und am Ende
greift der 15-Minuten-Hänger-Sweep und stempelt halbfertige Clips auf
„fertig".

Also gibt es jetzt eine Linie. Zwei gleichzeitig, der Rest wartet
sichtbar in `queued`.

WARUM KEIN SEMAPHOR. „Wandel von alt nach neu der Reihe nach um!" — ein
`threading.BoundedSemaphore` weckt einen BELIEBIGEN Wartenden, nicht den
ältesten. Bei acht Wartenden kann der jüngste Clip dreimal drankommen,
während der älteste steht; genau das Verhalten, das aus „dauert lang"
ein „wird nie fertig" macht. Deshalb hier eine echte Reihe, sortiert
nach Ereignis-ID — die ist ein Zeitstempel (`20260906-161324-194462`)
und sortiert damit von selbst von alt nach neu.
"""

from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger("app.camera_runtime")


def _slots() -> int:
    """Gleichzeitige Umwandlungen. Zwei, nicht eins: eine einzelne
    4K-Datei sättigt die Kerne nicht (x264 skaliert nicht linear), und
    ein einzelner hängender Auftrag würde sonst ALLES blockieren statt
    nur die Hälfte. Über ``SQ_ENCODE_SLOTS`` verstellbar ohne Neubau des
    Images — die Anlage läuft auf fremder Hardware, und die richtige Zahl
    hängt an ihr."""
    try:
        want = int(os.environ.get("SQ_ENCODE_SLOTS", "2"))
    except (TypeError, ValueError):
        want = 2
    return max(1, min(8, want))


ENCODE_SLOTS = _slots()

_CV = threading.Condition()
_running = 0
#: Wartende als (sortier_schlüssel, laufende_nummer). Die Nummer bricht
#: Gleichstände auf und macht die Reihenfolge damit total — zwei Clips
#: mit derselben ID gäbe es nicht, aber eine Reihe, deren Kopf nicht
#: eindeutig ist, könnte hängenbleiben.
_wartend: list[tuple[str, int]] = []
_lfd = 0
#: Ereignis-IDs, hinter denen JETZT ein lebender Thread steht.
_inflight: set[str] = set()


def queue_depth() -> tuple[int, int]:
    """(laufend, wartend) — für Log und Statusanzeige."""
    with _CV:
        return _running, len(_wartend)


def inflight_event_ids() -> frozenset[str]:
    """Die Ereignisse, hinter denen JETZT ein lebender Thread steht.

    Der Hänger-Sweep adoptiert alles, was länger als 15 Minuten in
    derselben Stufe steht. Mit einer echten Warteschlange kann ein Clip
    diese 15 Minuten legitim WARTEND verbringen — und würde dann
    weggeschnappt und auf „fertig" gestempelt, obwohl gleich ein Thread
    ihn ordentlich umgewandelt hätte. Diese Menge ist der Unterschied
    zwischen „niemand kümmert sich" und „ist gleich dran".
    """
    with _CV:
        return frozenset(_inflight)


class encode_slot:
    """Ein Platz in der Umwandlungs-Warteschlange, älteste zuerst.

    Als Kontextmanager zu benutzen. Blockiert, bis dieser Clip der
    älteste Wartende ist UND ein Platz frei ist — er bleibt währenddessen
    auf `queued` stehen, was jetzt die Wahrheit ist statt einer
    Millisekunde.

    Absichtlich OHNE Zeitlimit: einen Auftrag fallenzulassen, weil die
    Kiste beschäftigt ist, verliert genau das Video, das der Betreiber
    sehen will. Die Obergrenze steckt schon eine Ebene tiefer, im
    300-Sekunden-Timeout von ffmpeg selbst — ein Platz kann also nie
    länger als gut fünf Minuten belegt bleiben.
    """

    __slots__ = ("camera_id", "event_id", "_ticket")

    def __init__(self, camera_id: str = "", event_id: str = ""):
        self.camera_id = camera_id
        self.event_id = event_id
        self._ticket: tuple[str, int] | None = None

    def __enter__(self):
        global _running, _lfd
        with _CV:
            _lfd += 1
            # Die Ereignis-ID IST der Zeitstempel. Ein Clip ohne ID
            # sortiert ans Ende statt zufällig mittendrin.
            self._ticket = (self.event_id or "~", _lfd)
            _wartend.append(self._ticket)
            _wartend.sort()
            _inflight.add(self.event_id)
            if _running >= ENCODE_SLOTS:
                log.info(
                    "[%s] Umwandlung wartet — %d laufen, %d in der Schlange (%s)",
                    self.camera_id or "cam",
                    _running,
                    len(_wartend),
                    self.event_id or "?",
                )
            while _running >= ENCODE_SLOTS or _wartend[0] != self._ticket:
                _CV.wait()
            _wartend.remove(self._ticket)
            _running += 1
        return self

    def __exit__(self, *_exc):
        global _running
        with _CV:
            _running -= 1
            _inflight.discard(self.event_id)
            # Alle wecken, damit der neue Kopf der Reihe sich meldet —
            # nur er kommt durch die Schleifenbedingung.
            _CV.notify_all()
        return False
