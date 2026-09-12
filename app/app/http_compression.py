"""gzip für Text-Antworten — der größte Einzelhebel für das Handy.

„Bitte mach auch einen Lauf mal und schau, wie viel Daten werden geladen,
wenn das Handy von mobil auf die Seite geht."

GEMESSEN AM 2026-09-12, kaltes Laden gegen die laufende Box:

    index.html                    180 KiB
    app.css                       880 KiB
    365 ES-Module               2 568 KiB
    ──────────────────────────────────────
    Statisch                    3 625 KiB   in 367 Anfragen
    /api/timeline                 294 KiB
    /api/bird-dossiers            175 KiB
    übrige Boot-Aufrufe            75 KiB
    ──────────────────────────────────────
    Gesamt                      ~4 170 KiB

Jede einzelne Antwort kam mit ``Content-Encoding: identity``. Es war
schlicht nie eine Kompression eingebaut — kein Reverse Proxy davor, und
Flask macht das von sich aus nicht. CSS, JavaScript und JSON schrumpfen
dabei typischerweise auf ein Sechstel bis ein Achtel; das ist der
billigste Hebel, den dieses Projekt hat, und er ändert am Verhalten
nichts.

WAS AUSDRÜCKLICH NICHT KOMPRIMIERT WIRD:

  * Alles ohne bekannte Länge (``is_streamed``). Der MJPEG-Strom ist ein
    endloser Generator — ihn einzusammeln, um ihn zu packen, hieße, das
    Livebild nie auszuliefern. Das ist die eine Stelle, an der ein
    naiver Kompressions-Hook das Produkt kaputtmacht.
  * Alles, was schon gepackt ist: JPEG, PNG, MP4, ZIP. Ein zweiter
    Durchgang kostet CPU und macht die Datei minimal größer.
  * Kleinkram unter ``MIN_BYTES`` — unter etwa einem Kilobyte gewinnt
    man nichts mehr, was ein Paket ausmacht.
"""

from __future__ import annotations

import gzip
import logging

log = logging.getLogger(__name__)

#: Ab dieser Größe lohnt es sich. Darunter passt die Antwort ohnehin in
#: ein Paket, und der Header kostet mehr, als die Kompression spart.
MIN_BYTES = 1024

#: Obergrenze. Darüber wird nichts mehr in den Speicher geholt, um es zu
#: packen — Dateien dieser Größe sind in diesem Projekt ohnehin Videos
#: und damit schon gepackt. Die größte Textdatei ist `app.css` mit
#: 880 KiB.
MAX_BYTES = 4 * 1024 * 1024

#: Kompressionsstufe. 6 ist die übliche Voreinstellung und der Knick in
#: der Kurve: 9 holt bei diesen Dateien unter ein Prozent mehr heraus
#: und kostet ein Vielfaches an Rechenzeit.
LEVEL = 6

#: Was gepackt wird — nach MIME-Typ, nicht nach Dateiendung. Ein
#: Allowlist-Ansatz, weil die Liste der Dinge, die man NICHT packen
#: darf, sich mit jedem neuen Endpunkt ändert, und die der Textformate
#: nicht.
COMPRESSIBLE = (
    "text/",
    "application/json",
    "application/javascript",
    "application/manifest+json",
    "image/svg+xml",
)


def body_length(response):
    """Die Länge des Rumpfs, oder None, wenn sie nicht feststeht.

    DER HEADER ZUERST, und das ist die ganze Unterscheidung zwischen
    einer Datei und einem Strom. Werkzeugs ``is_streamed`` fragt, ob der
    Rumpf ein ``len()`` hat — eine Datei-Antwort von ``send_file`` hat
    keines (sie ist ein Datei-Wrapper), gilt damit als „gestreamt" und
    wäre ausgeschlossen. Genau daran ist der erste Entwurf gescheitert:
    er hat gemessen nichts gepackt, weil `app.css` und alle 365 Module
    als Ströme durchgingen.

    Eine Datei kennt ihre Länge und schreibt sie in den Header; der
    MJPEG-Generator kann das nicht. Das ist der belastbare Unterschied.
    ``calculate_content_length`` kommt zuletzt und nur, wenn feststeht,
    dass der Rumpf endlich ist — es liest ihn nämlich.
    """
    if response.content_length is not None:
        return response.content_length
    if response.is_streamed or response.direct_passthrough:
        return None
    return response.calculate_content_length()


def should_compress(response, accept_encoding: str) -> bool:
    """Ob diese Antwort gepackt werden darf. Rein, damit die Regeln
    prüfbar sind, ohne einen Server zu starten.

    ``direct_passthrough`` ist AUSDRÜCKLICH kein Ausschlussgrund, und das
    ist der Unterschied zwischen einer Kompression, die wirkt, und einer,
    die nur so aussieht: Flask liefert jede statische Datei so aus — also
    `app.css` und alle 365 ES-Module, exakt die Fracht, um die es geht.
    Ein erster Entwurf, der hier abgebrochen hat, hat gemessen NICHTS
    gepackt. Was den Strom fernhält, ist die unbekannte Länge, nicht das
    Durchreichen.
    """
    if "gzip" not in (accept_encoding or "").lower():
        return False
    if response.status_code < 200 or response.status_code >= 300:
        return False
    if response.headers.get("Content-Encoding"):
        return False
    mimetype = (response.mimetype or "").lower()
    if not mimetype.startswith(COMPRESSIBLE):
        return False
    length = body_length(response)
    return length is not None and MIN_BYTES <= length <= MAX_BYTES


def compress_response(response, accept_encoding: str):
    """Die Antwort gepackt zurückgeben — oder unverändert.

    ``Vary: Accept-Encoding`` ist Pflicht und nicht Kosmetik: ohne den
    Header darf ein Zwischenspeicher die gepackte Antwort an einen
    Client ausliefern, der gzip nicht angemeldet hat.
    """
    if not should_compress(response, accept_encoding):
        response.headers.add("Vary", "Accept-Encoding")
        return response
    try:
        # Das Durchreichen abschalten, BEVOR der Rumpf gelesen wird —
        # sonst gibt `get_data()` bei einer Datei-Antwort nichts heraus.
        response.direct_passthrough = False
        packed = gzip.compress(response.get_data(), LEVEL)
    except Exception as e:  # pragma: no cover - defensiv
        log.debug("[http] gzip übersprungen: %s", e)
        return response
    response.set_data(packed)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(packed))
    response.headers.add("Vary", "Accept-Encoding")
    return response


def install(app) -> None:
    """Den Hook an die Flask-App hängen."""

    @app.after_request
    def _gzip(response):  # pragma: no cover - über compress_response geprüft
        from flask import request

        return compress_response(response, request.headers.get("Accept-Encoding", ""))
