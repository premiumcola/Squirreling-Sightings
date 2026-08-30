"""weather_service/_retention.py — the per-category nightly sweep.

Mirrors storage_retention.py's own hazard-test style (test_storage_
retention_hazards.py): a "the sweep deletes more than anyone asked it
to" bug here is a lost sighting, not a stack trace. Three properties
pinned:

  * a directory bucket (thunder/, event_timelapse/, sunrise_timelapse/,
    an unrecognised one) sweeps under the right category and nothing
    else — a category-A slider must never delete category-B media.
  * `"pinned": true` is an absolute exemption, checked before the age
    cutoff, for both a sighting and a recap.
  * a recap keeps its own rule: the WEATHER_RECAP_MIN_KEEP most recent
    are never swept regardless of age, on top of the flat day cutoff.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app import app_state, storage_retention
from app.weather_service import _retention as retention_module
from app.weather_service._manifests import ManifestsMixin
from app.weather_service._retention import (
    WEATHER_RECAP_MIN_KEEP,
    WeatherRetentionMixin,
    _dir_category,
    acknowledge_weather_retention_from_payload,
    weather_retention_runtime_key,
)


class _Svc(WeatherRetentionMixin, ManifestsMixin):
    """Just enough of WeatherService for the sweep — same stub pattern
    as test_weather_score_floor.py's `_RecapsSvc`."""

    def __init__(self, root: Path, weather: dict | None = None):
        self._root = root
        self.settings_store = SimpleNamespace(data={"weather": weather or {}})
        self._scheduler = None

    def _sightings_dir(self) -> Path:
        return self._root

    def _recaps_dir(self) -> Path:
        return self._root / "recaps"


def _write_sighting(root: Path, cam: str, evt_dir: str, name: str, age_days: float, **fields):
    d = root / cam / evt_dir
    d.mkdir(parents=True, exist_ok=True)
    started = datetime.now() - timedelta(days=age_days)
    manifest = {
        "id": f"{cam}__{evt_dir}__{name}",
        "started_at": started.isoformat(timespec="seconds"),
        **fields,
    }
    (d / f"{name}.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / f"{name}.mp4").write_bytes(b"x")
    (d / f"{name}.jpg").write_bytes(b"x")
    return d / f"{name}.json"


def _write_recap(root: Path, rid: str, age_days: float, **fields):
    recaps = root / "recaps"
    recaps.mkdir(parents=True, exist_ok=True)
    built = datetime.now() - timedelta(days=age_days)
    manifest = {"id": rid, "built_at": built.isoformat(timespec="seconds"), **fields}
    (recaps / f"{rid}.json").write_text(json.dumps(manifest), encoding="utf-8")
    (recaps / f"{rid}.mp4").write_bytes(b"x")


# ── directory → category bucketing ──────────────────────────────────────


def test_raw_event_dirs_bucket_as_sightings():
    for d in ("thunder", "heavy_rain", "snow", "fog"):
        assert _dir_category(d) == "sightings"


def test_event_timelapse_dir_buckets_separately():
    assert _dir_category("event_timelapse") == "event_timelapses"


def test_sun_timelapse_dirs_bucket_separately_old_and_new_layout():
    for d in ("sunrise_timelapse", "sunset_timelapse", "sun_timelapse"):
        assert _dir_category(d) == "sun_timelapses"


def test_an_unrecognised_dir_falls_back_to_the_sightings_bucket():
    assert _dir_category("some_future_kind") == "sightings"


# ── sighting sweep: age cutoff + category isolation ─────────────────────


def test_an_old_sighting_is_removed_and_a_fresh_one_survives(tmp_path):
    old = _write_sighting(tmp_path, "cam1", "thunder", "old", age_days=30)
    fresh = _write_sighting(tmp_path, "cam1", "thunder", "fresh", age_days=1)
    svc = _Svc(tmp_path)
    removed, pinned = svc._sweep_sighting_category("sightings", retention_days=7)
    assert removed == 1
    assert pinned == 0
    assert not old.exists()
    assert fresh.exists()


def test_a_pinned_sighting_survives_regardless_of_age(tmp_path):
    pinned_manifest = _write_sighting(
        tmp_path, "cam1", "thunder", "keepsake", age_days=999, pinned=True
    )
    svc = _Svc(tmp_path)
    removed, pinned = svc._sweep_sighting_category("sightings", retention_days=1)
    assert removed == 0
    assert pinned == 1
    assert pinned_manifest.exists()


def test_sweeping_one_category_never_touches_another(tmp_path):
    """A sun-timelapse category sweep must not delete an old raw clip
    living in a sibling directory — the whole point of per-category
    retention is that one slider can't reach into another bucket."""
    old_raw = _write_sighting(tmp_path, "cam1", "thunder", "old", age_days=999)
    svc = _Svc(tmp_path)
    removed, _ = svc._sweep_sighting_category("sun_timelapses", retention_days=1)
    assert removed == 0
    assert old_raw.exists()


def test_an_unknown_directory_is_swept_under_the_sightings_category(tmp_path):
    old = _write_sighting(tmp_path, "cam1", "mystery_kind", "old", age_days=30)
    svc = _Svc(tmp_path)
    removed, _ = svc._sweep_sighting_category("sightings", retention_days=7)
    assert removed == 1
    assert not old.exists()


def test_a_missing_sightings_dir_is_a_silent_noop(tmp_path):
    svc = _Svc(tmp_path / "does_not_exist")
    assert svc._sweep_sighting_category("sightings", retention_days=7) == (0, 0)


# ── recap sweep: flat cutoff + period-aware keep-last-N + pin ───────────


def test_old_recaps_beyond_the_keep_floor_are_removed(tmp_path):
    # Four recaps, oldest first; keep floor is 2, so #1 and #2 (oldest)
    # must go even though all four are past the retention window.
    for i in range(4):
        _write_recap(tmp_path, f"r{i}", age_days=500 - i)  # r0 oldest .. r3 newest
    svc = _Svc(tmp_path)
    removed = svc._sweep_recaps(retention_days=30)
    assert removed == 2
    remaining = {p.stem for p in (tmp_path / "recaps").glob("*.json")}
    assert remaining == {"r2", "r3"}, "the WEATHER_RECAP_MIN_KEEP most recent must survive"


def test_recaps_within_the_window_are_not_removed(tmp_path):
    _write_recap(tmp_path, "young", age_days=5)
    svc = _Svc(tmp_path)
    removed = svc._sweep_recaps(retention_days=400)
    assert removed == 0
    assert (tmp_path / "recaps" / "young.json").exists()


def test_a_pinned_recap_survives_even_outside_the_keep_floor(tmp_path):
    # Five recaps older than the keep floor could protect; the oldest is
    # pinned and must survive despite being neither recent nor young.
    for i in range(5):
        _write_recap(tmp_path, f"r{i}", age_days=900 - i, pinned=(i == 0))
    svc = _Svc(tmp_path)
    svc._sweep_recaps(retention_days=30)
    assert (tmp_path / "recaps" / "r0.json").exists(), "a pinned recap must never be swept"


def test_keep_floor_constant_is_two():
    # Pinned so a future change to the constant is a deliberate edit,
    # not an accidental one — every test above assumes this value.
    assert WEATHER_RECAP_MIN_KEEP == 2


# ── settings resolution: category key falls back to the legacy blanket ──


def test_category_day_count_falls_back_to_the_legacy_blanket_key(tmp_path):
    svc = _Svc(tmp_path, weather={"retention_days": 45})
    assert svc._resolve_category_days("sightings") == 45
    assert svc._resolve_category_days("recaps") == 45


def test_an_explicit_category_key_wins_over_the_blanket(tmp_path):
    svc = _Svc(tmp_path, weather={"retention_days": 45, "retention_sun_timelapses_days": 21})
    assert svc._resolve_category_days("sun_timelapses") == 21


def test_auto_cleanup_defaults_true_when_unset(tmp_path):
    assert _Svc(tmp_path)._auto_cleanup_enabled() is True


def test_auto_cleanup_can_be_turned_off(tmp_path):
    svc = _Svc(tmp_path, weather={"auto_cleanup_enabled": False})
    assert svc._auto_cleanup_enabled() is False


# ── full sweep entrypoint: disabled toggle + sub-floor refusal ──────────


def test_disabled_auto_cleanup_sweeps_nothing(tmp_path, monkeypatch):
    _write_sighting(tmp_path, "cam1", "thunder", "old", age_days=999)
    svc = _Svc(tmp_path, weather={"auto_cleanup_enabled": False})
    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
    svc._run_weather_retention_sweep()
    assert (tmp_path / "cam1" / "thunder" / "old.json").exists()


def test_a_sub_floor_category_window_is_refused_not_wiped(tmp_path, monkeypatch):
    """retention_sightings_days: 0 must behave like cleanup_old(0) —
    refused outright, never reinterpreted as "delete everything".

    Against the shipped (positive) baseline, `nightly_window` itself
    already defers a resolved 0 up to that baseline (pinned by
    test_storage_retention_hazards.py's own guard tests) — this test
    pins the sweep's OWN belt-and-suspenders floor check for the one
    case the widening guard can't catch on its own: the baseline is
    ALSO at/under the floor, so there is nothing wider to fall back to.
    """
    old = _write_sighting(tmp_path, "cam1", "thunder", "old", age_days=999)
    runtime: dict = {}
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data={},
            runtime_get=lambda key, default=None: runtime.get(key, default),
            runtime_set=runtime.__setitem__,
        ),
        raising=False,
    )
    monkeypatch.setitem(retention_module._DEFAULT_CATEGORY_DAYS, "sightings", 0)
    svc = _Svc(tmp_path, weather={"retention_sightings_days": 0})
    svc._run_weather_retention_sweep()
    assert old.exists(), "a 0-day window must be refused, not treated as an empty retention"


# ── acknowledge-on-save (the widening-guard confirmation path) ──────────


def test_runtime_key_is_namespaced_per_category():
    assert weather_retention_runtime_key("sightings") != weather_retention_runtime_key("recaps")
    assert weather_retention_runtime_key("sightings") != storage_retention.ENFORCED_KEY


def test_acknowledge_from_payload_only_confirms_categories_present(monkeypatch):
    runtime: dict = {}
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data={},
            runtime_get=lambda key, default=None: runtime.get(key, default),
            runtime_set=runtime.__setitem__,
        ),
        raising=False,
    )
    acknowledge_weather_retention_from_payload({"retention_sun_timelapses_days": 21})
    assert runtime[weather_retention_runtime_key("sun_timelapses")] == 21
    assert weather_retention_runtime_key("sightings") not in runtime
    assert weather_retention_runtime_key("recaps") not in runtime
