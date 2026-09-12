"""gzip für Text-Antworten — und die eine Antwort, die es nie anfassen darf.

„Bitte mach auch einen Lauf mal und schau, wie viel Daten werden geladen,
wenn das Handy von mobil auf die Seite geht. … Mir kommt's so vor, als
würde das immer mehr werden und dadurch die Seite mobil deutlich
langsamer werden."

Gemessen am 2026-09-12 gegen die laufende Box: 3 625 KiB statisch in 367
Anfragen plus 544 KiB Boot-API, **jede einzelne Antwort mit
`Content-Encoding: identity`**. Es war nie eine Kompression eingebaut.

Die Gefahr an einem Kompressions-Hook ist nicht die Kompression, sondern
das, was er versehentlich mitnimmt: der MJPEG-Strom ist ein endloser
Generator, und ihn einzusammeln, um ihn zu packen, hieße, das Livebild
nie auszuliefern. Deshalb prüft die Hälfte dieser Datei, was NICHT
angefasst wird.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest
from flask import Flask, Response, jsonify

from app.http_compression import (
    LEVEL,
    MAX_BYTES,
    MIN_BYTES,
    compress_response,
    install,
    should_compress,
)

_LONG = "Kohlmeise " * 500  # ~5 KiB, sehr gut komprimierbar

_STATIC = Path(__file__).resolve().parents[1] / "web" / "static"


@pytest.fixture()
def client():
    app = Flask(__name__)

    @app.get("/text")
    def _text():
        return Response(_LONG, mimetype="text/plain")

    @app.get("/json")
    def _json():
        return jsonify({"items": ["Kohlmeise"] * 500})

    @app.get("/tiny")
    def _tiny():
        return Response("ok", mimetype="text/plain")

    @app.get("/jpeg")
    def _jpeg():
        return Response(b"\xff\xd8" + b"x" * 40000, mimetype="image/jpeg")

    @app.get("/stream.mjpg")
    def _stream():
        def gen():
            for _ in range(3):
                yield b"--frame\r\n" + b"y" * 20000

        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/boom")
    def _boom():
        return Response(_LONG, mimetype="text/plain", status=500)

    install(app)
    return app.test_client()


def _gz(client, path):
    return client.get(path, headers={"Accept-Encoding": "gzip, deflate"})


# ── was gepackt wird ────────────────────────────────────────────────────


def test_text_comes_back_gzipped_and_intact(client):
    r = _gz(client, "/text")
    assert r.headers["Content-Encoding"] == "gzip"
    assert gzip.decompress(r.data).decode() == _LONG


def test_it_actually_saves_most_of_the_bytes(client):
    """Der ganze Zweck. Wenn hier je etwas unter einem Faktor zwei
    herauskäme, wäre der Hook die CPU nicht wert."""
    packed = len(_gz(client, "/text").data)
    plain = len(client.get("/text", headers={"Accept-Encoding": "identity"}).data)
    assert packed * 5 < plain, f"{plain} → {packed} B ist zu wenig gespart"


def test_json_is_compressed_too(client):
    """Die Boot-API ist der zweitgrößte Posten — /api/timeline allein
    waren 294 KiB."""
    r = _gz(client, "/json")
    assert r.headers["Content-Encoding"] == "gzip"
    assert b"Kohlmeise" in gzip.decompress(r.data)


def test_the_content_length_describes_the_packed_body(client):
    r = _gz(client, "/text")
    assert int(r.headers["Content-Length"]) == len(r.data)


# ── was nicht gepackt wird ──────────────────────────────────────────────


def test_a_client_that_did_not_ask_gets_plain_bytes(client):
    r = client.get("/text", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in r.headers
    assert r.data.decode() == _LONG


def test_every_answer_carries_vary_accept_encoding(client):
    """Ohne den Header darf ein Zwischenspeicher die gepackte Antwort an
    einen Client ausliefern, der gzip nie angemeldet hat."""
    for headers in ({"Accept-Encoding": "gzip"}, {"Accept-Encoding": "identity"}):
        r = client.get("/text", headers=headers)
        assert "Accept-Encoding" in r.headers.get("Vary", "")


def test_the_mjpeg_stream_is_never_touched(client):
    """DIE Stelle, an der ein naiver Hook das Produkt kaputtmacht: der
    Strom hat keine bekannte Länge, und ihn einzusammeln hieße, das
    Livebild nie auszuliefern."""
    r = _gz(client, "/stream.mjpg")
    assert "Content-Encoding" not in r.headers
    assert r.data.startswith(b"--frame")


def test_already_compressed_media_is_left_alone(client):
    r = _gz(client, "/jpeg")
    assert "Content-Encoding" not in r.headers


def test_a_short_answer_is_not_worth_a_header(client):
    r = _gz(client, "/tiny")
    assert "Content-Encoding" not in r.headers
    assert r.data == b"ok"


def test_an_error_page_is_left_alone(client):
    r = _gz(client, "/boom")
    assert r.status_code == 500
    assert "Content-Encoding" not in r.headers


# ── die Regeln für sich ─────────────────────────────────────────────────


class _Resp:
    """Das Wenige, das `should_compress` an einer Antwort abfragt."""

    def __init__(
        self,
        *,
        mimetype="text/css",
        length=MIN_BYTES,
        status=200,
        encoding=None,
        passthrough=False,
    ):
        self.mimetype = mimetype
        self.status_code = status
        self.direct_passthrough = passthrough
        self.is_streamed = length is None
        self.content_length = length
        self._length = length
        self.headers = {"Content-Encoding": encoding} if encoding else {}

    def calculate_content_length(self):
        return self._length


def test_the_threshold_is_inclusive():
    assert should_compress(_Resp(length=MIN_BYTES), "gzip") is True
    assert should_compress(_Resp(length=MIN_BYTES - 1), "gzip") is False


def test_anything_bigger_than_the_ceiling_is_left_alone():
    assert should_compress(_Resp(length=MAX_BYTES), "gzip") is True
    assert should_compress(_Resp(length=MAX_BYTES + 1), "gzip") is False


def test_an_unknown_length_means_a_stream():
    assert should_compress(_Resp(length=None), "gzip") is False


def test_a_file_response_is_NOT_skipped_for_being_passthrough():
    """Der Fehler, an dem der erste Entwurf gemessen nichts gepackt hat.

    Flask liefert jede statische Datei mit ``direct_passthrough`` aus —
    also `app.css` und alle 365 ES-Module, exakt die Fracht, um die es
    geht. Wer hier abbricht, baut eine Kompression, die nur so aussieht.
    """
    assert should_compress(_Resp(passthrough=True, length=50_000), "gzip") is True


def test_a_passthrough_response_without_a_length_is_still_refused():
    r = _Resp(passthrough=True, length=None)
    r.content_length = None
    assert should_compress(r, "gzip") is False


def test_packing_something_twice_is_refused():
    assert should_compress(_Resp(encoding="gzip"), "gzip") is False


@pytest.mark.parametrize(
    "mimetype,expected",
    [
        ("text/html", True),
        ("text/css", True),
        ("application/javascript", True),
        ("application/json", True),
        ("image/svg+xml", True),
        ("application/manifest+json", True),
        ("image/png", False),
        ("video/mp4", False),
        ("application/zip", False),
    ],
)
def test_the_allowlist_covers_the_text_formats_and_nothing_else(mimetype, expected):
    assert should_compress(_Resp(mimetype=mimetype), "gzip") is expected


def test_a_broken_body_falls_back_to_the_plain_response():
    """Kompression ist eine Optimierung. Scheitert sie, geht die Antwort
    unverändert raus — sie darf nie der Grund sein, dass gar nichts
    ankommt."""

    class _Bad(_Resp):
        def get_data(self):
            raise RuntimeError("kaputt")

    out = compress_response(_Bad(), "gzip")
    assert isinstance(out, _Bad)
    assert "Content-Encoding" not in out.headers


def test_the_level_is_the_knee_of_the_curve():
    assert 1 <= LEVEL <= 9


# ── die echte Fracht ────────────────────────────────────────────────────


@pytest.fixture()
def static_client():
    """Eine App über dem WIRKLICHEN Static-Ordner. Alles darunter ist der
    Grund, warum dieses Modul existiert."""
    app = Flask(__name__, static_folder=str(_STATIC))
    install(app)
    return app.test_client()


@pytest.mark.parametrize("path", ["/static/js/main.js", "/static/js/dashboard.js"])
def test_the_modules_that_make_up_the_page_are_compressed(static_client, path):
    """Die 365 ES-Module sind zwei Drittel des kalten Ladens. Kommen sie
    ungepackt heraus, hat dieses Modul nichts bewirkt."""
    r = static_client.get(path, headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers["Content-Encoding"] == "gzip"
    plain = static_client.get(path, headers={"Accept-Encoding": "identity"})
    assert gzip.decompress(r.data) == plain.data
    assert len(r.data) * 2 < len(plain.data)


def test_the_stylesheet_is_compressed(static_client):
    """`app.css` ist mit Abstand die größte Einzeldatei der Seite —
    880 KiB, gemessen am 2026-09-12. Ein Build-Artefakt, das in einem
    frischen Klon fehlen kann; dann gibt es hier nichts zu prüfen."""
    r = static_client.get("/static/app.css", headers={"Accept-Encoding": "gzip"})
    if r.status_code == 404:
        pytest.skip("app.css ist ein Build-Artefakt und noch nicht gebaut")
    assert r.headers["Content-Encoding"] == "gzip"
    plain = static_client.get("/static/app.css", headers={"Accept-Encoding": "identity"})
    assert gzip.decompress(r.data) == plain.data
    assert len(r.data) * 2 < len(plain.data)
