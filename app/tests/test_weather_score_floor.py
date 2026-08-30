"""Sun-timelapse score lives in [0.5, 1.0] — the "floor of dignity"
(`_sun_tl/__init__.py`'s `score = 0.5 + 0.5*(1 - cloud/100)`), never in
[0, 1] like every other weather event's severity. Two quality gates were
authored assuming the [0, 1] convention:

  * the recap candidate floor (`_recaps.py`, a literal 0.4)
  * the Telegram push gate (`_clip.py`, `push.weather.min_score`, default 0.4)

Both were a structural no-op against sun-timelapse: a literal 0.4 can
never exceed a value whose domain floor is 0.5, so every capture,
however overcast, cleared the bar. `score_floor_for_type()`
(`weather_service/_consts.py`) rescales the configured floor onto each
event type's own domain so both gates apply meaningfully to every type.
Found by a session-wide "inconsistencies in scoring" audit, not a user
bug report — hence the extra emphasis on proving the OLD behaviour was
really broken, not just asserting the new numbers.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.weather_service._clip import ClipMixin
from app.weather_service._consts import score_floor_for_type
from app.weather_service._recaps import RecapsMixin


def test_the_default_domain_is_unchanged_for_ordinary_events():
    assert score_floor_for_type(0.4, "thunder") == 0.4
    assert score_floor_for_type(0.4, "heavy_rain") == 0.4
    assert score_floor_for_type(0.0, "fog") == 0.0
    assert score_floor_for_type(1.0, "snow") == 1.0


def test_sun_timelapse_floor_is_rescaled_onto_its_own_half_width_domain():
    # domain is [0.5, 1.0] (width 0.5): floor = 0.5 + min_score * 0.5
    assert score_floor_for_type(0.4, "sun_timelapse") == 0.7
    assert score_floor_for_type(0.4, "sun_timelapse_rise") == 0.7
    assert score_floor_for_type(0.4, "sun_timelapse_set") == 0.7
    assert score_floor_for_type(0.0, "sun_timelapse") == 0.5
    assert score_floor_for_type(1.0, "sun_timelapse") == 1.0


class _RecapsSvc(RecapsMixin):
    def __init__(self, root: Path):
        self._root = root

    def _sightings_dir(self) -> Path:
        return self._root


def _write_manifest(root: Path, cam: str, evt: str, name: str, **fields):
    d = root / cam / evt
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"started_at": "2026-08-15T12:00:00", "event_type": evt, **fields}
    (d / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_an_overcast_sun_timelapse_no_longer_passes_the_recap_floor(tmp_path):
    """Under the OLD literal 0.4 this candidate (score 0.5) would have
    been collected — 0.5 clears 0.4 easily. It must not any more."""
    _write_manifest(tmp_path, "cam1", "sun_timelapse", "a", score=0.5)
    svc = _RecapsSvc(tmp_path)
    cands = svc._collect_recap_candidates(date(2026, 8, 1), date(2026, 8, 31))
    assert cands == [], "a fully-overcast sun-timelapse must not qualify for a recap"


def test_a_clear_sky_sun_timelapse_still_passes_the_recap_floor(tmp_path):
    _write_manifest(tmp_path, "cam1", "sun_timelapse", "a", score=1.0)
    svc = _RecapsSvc(tmp_path)
    cands = svc._collect_recap_candidates(date(2026, 8, 1), date(2026, 8, 31))
    assert len(cands) == 1


def test_a_weak_storm_below_the_ordinary_floor_is_still_excluded(tmp_path):
    """Unrelated event types must keep their existing [0, 1] floor."""
    _write_manifest(tmp_path, "cam1", "heavy_rain", "a", score=0.3)
    svc = _RecapsSvc(tmp_path)
    cands = svc._collect_recap_candidates(date(2026, 8, 1), date(2026, 8, 31))
    assert cands == []


class _TgStub:
    def __init__(self, push_cfg):
        self.enabled = True
        self.push_cfg = push_cfg
        self.sent = []

    def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))


class _ClipSvc(ClipMixin):
    def __init__(self, tg):
        self.server_cfg = {}
        self._tg = tg

    def telegram_getter(self):
        return self._tg


def _push_cfg(min_score=0.4):
    return {
        "weather": {
            "enabled": True,
            "min_score": min_score,
            "events": {"sun_timelapse_rise": True, "heavy_rain": True},
        }
    }


def test_an_overcast_sun_timelapse_push_is_now_gated(tmp_path):
    """Under the OLD literal 0.4 this manifest (score 0.5) would have
    pushed to Telegram unconditionally — every sun-timelapse the user
    opted into would spam, however grey the sky."""
    tg = _TgStub(_push_cfg())
    svc = _ClipSvc(tg)
    manifest = {"event_type": "sun_timelapse_rise", "score": 0.5, "id": "x", "cam_id": "cam1"}
    svc._maybe_push_telegram(manifest, tmp_path / "clip.mp4")
    assert tg.sent == [], "an overcast sun-timelapse must not clear the push gate"


def test_a_clear_sky_sun_timelapse_still_pushes(tmp_path):
    tg = _TgStub(_push_cfg())
    svc = _ClipSvc(tg)
    manifest = {"event_type": "sun_timelapse_rise", "score": 1.0, "id": "x", "cam_id": "cam1"}
    svc._maybe_push_telegram(manifest, tmp_path / "clip.mp4")
    assert len(tg.sent) == 1


def test_ordinary_event_push_gate_is_unchanged(tmp_path):
    tg = _TgStub(_push_cfg())
    svc = _ClipSvc(tg)
    manifest = {"event_type": "heavy_rain", "score": 0.3, "id": "x", "cam_id": "cam1"}
    svc._maybe_push_telegram(manifest, tmp_path / "clip.mp4")
    assert tg.sent == [], "a weak rain event must still be gated exactly as before"
