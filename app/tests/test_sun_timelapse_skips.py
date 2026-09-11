"""Ein ausgefallener Sonnenlauf muss sagen können, warum.

„Es sind keine sunrise sunset timelapses da — nur die daily! Wo sind die
sunset videos?"

Gemessen an der laufenden Anlage, 11.09.2026:

    06:11:37  Garten 'Dach Terrasse': aborting capture — 21 consecutive
              backfills (~525 s without a fresh grab)
    06:11:37  _skip.json written (reason=too_many_consecutive_backfills,
              n_written=27, min=30)

Der Grund stand also die ganze Zeit auf der Platte — in einer Datei, die
sechs Fehlerpfade schreiben und niemand liest. `list_sightings` hat sie
zwar eingesammelt, ihr aber mangels `started_at` den Zeitpunkt
`datetime.min` gegeben, sie unter dem Verzeichnisnamen verbucht und an
einen Verbraucher weitergereicht, der alles ohne `id` verwirft. Ein
fehlender Sonnenaufgang sah damit exakt aus wie einer, der nie geplant
war.
"""

from __future__ import annotations

import json

from app.weather_service._consts import SUN_SKIP_EVENT_TYPE
from app.weather_service._sun_tl import _write_sun_skip_json


def _skip(tmp_path, cam="cam_a", phase="sunrise", stem="2026-09-11_sunrise_cam_a", **kw):
    out_dir = tmp_path / "weather" / cam / f"{phase}_timelapse"
    _write_sun_skip_json(
        out_dir,
        stem,
        phase=phase,
        camera_id=cam,
        skip_reason=kw.get("reason", "too_many_consecutive_backfills"),
        n_written=kw.get("n_written", 27),
        min_required=kw.get("min_required", 30),
        log_tail=["[weather] aborting capture — 21 consecutive backfills"],
    )
    return json.loads((out_dir / f"{stem}_skip.json").read_text(encoding="utf-8"))


def test_die_ausfallspur_traegt_eine_identitaet(tmp_path):
    payload = _skip(tmp_path)

    # Ohne diese drei Schlüssel war der Datensatz unauffindbar.
    assert payload["id"] == "cam_a__sun_timelapse_skip__2026-09-11_sunrise_cam_a"
    assert payload["event_type"] == SUN_SKIP_EVENT_TYPE
    assert payload["started_at"], "ohne Zeitpunkt sortiert er auf datetime.min"


def test_die_ausfallspur_nennt_den_grund_und_wie_knapp_es_war(tmp_path):
    payload = _skip(tmp_path, n_written=27, min_required=30)

    assert payload["skip_reason"] == "too_many_consecutive_backfills"
    assert (payload["n_written"], payload["min_required"]) == (27, 30)
    assert payload["sun_phase"] == "sunrise"
    assert payload["cam_id"] == "cam_a"
    # Der Log-Auszug bleibt: er ist das Einzige, was den Ringpuffer
    # überlebt, der sich in einer halben Stunde einmal umwälzt.
    assert payload["log_tail"]


def test_ein_ausfall_ist_kein_video(tmp_path):
    """Er hat jetzt eine ID und einen Zeitstempel — genau das, woran der
    Medien-Feed erkennt, dass er eine Kachel bauen soll. Eine Kachel auf
    eine Datei, die es nicht gibt, wäre schlimmer als keine."""
    from app.weather_episodes._footage_sources import weather_candidates

    skip = _skip(tmp_path)

    class _Svc:
        def list_sightings(self, **kw):
            return {"items": [skip]}

    assert weather_candidates(_Svc()) == []


def test_ein_echtes_video_kommt_weiter_durch(tmp_path):
    """Gegenprobe: der Filter darf nicht die Aufnahmen mitnehmen."""
    from app.weather_episodes._footage_sources import weather_candidates

    real = {
        "id": "cam_a__sun_timelapse_rise__2026-09-10_sunrise_cam_a",
        "event_type": "sun_timelapse_rise",
        "cam_id": "cam_a",
        "started_at": "2026-09-10T07:06:31",
        "clip_path": "weather/cam_a/sunrise_timelapse/2026-09-10_sunrise_cam_a.mp4",
    }

    class _Svc:
        def list_sightings(self, **kw):
            return {"items": [real]}

    out = weather_candidates(_Svc())
    assert len(out) == 1
    assert out[0]["kind"] == "sun_timelapse_rise"
