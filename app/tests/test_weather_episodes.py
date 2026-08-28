"""Storm-episode archive — segmentation, margins, folding, scoring.

Stub-based throughout: the input is a synthetic history buffer in the
exact shape ``weather_service._history._record_sample`` appends, and the
output is a JSONL file under pytest's tmp_path. No Open-Meteo call, no
camera, no scheduler.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from app import app_state
from app.routes import weather_episodes as episode_routes
from app.weather_episodes import (
    delete_episode,
    detect_episodes,
    episodes_path,
    get_episode,
    intensity_score,
    list_episodes,
    patch_episode,
    sweep,
)

# Module level on purpose. A fixture-local import would leave
# `app.routes.weather_episodes` absent from sys.modules during
# collection, and test_rebuild_runtimes' `import app.server` would then
# import it under a stubbed `flask` — caching a module whose blueprint
# is a MagicMock for the rest of the session.
flask = pytest.importorskip("flask")

BASE = datetime(2026, 8, 20, 6, 0, 0)
STEP_MIN = 5

# A SYNTHETIC threshold set, deliberately not the shipped one. These
# tests are about segmentation — where an episode starts, when it
# settles, how margins merge — and round numbers like 1000/1500/2400
# keep the series in each test readable.
#
# It used to claim "Matches WEATHER_DEFAULTS", which stopped being true
# when the thunder threshold was corrected from 1000.0 to 0.2 J/kg: the
# field is the Lightning Potential Index, not CAPE, and its observed
# thunderstorm band is 0.2-0.8. The physical values live in
# test_thunder_lpi_scale.py, which asserts them against the real
# WEATHER_DEFAULTS — that is the test to change if a threshold moves.
EVENTS = {
    "thunder": {"enabled": True, "threshold": 1000.0},
    "heavy_rain": {"enabled": True, "threshold": 5.0},
    "snow": {"enabled": True, "threshold": 0.5},
    "fog": {"enabled": True, "vis_max_m": 1000},
}

# Tight margins so the merge horizon (pre+post) does not mask whatever
# the individual test is actually about. Tests that exercise merging or
# the archive's finalisation window set their own.
TIGHT = {"enabled": True, "pre_min": 10, "post_min": 10, "settle_min": 30}


def _history(series, *, base=BASE, step_min=STEP_MIN, field="lightning_potential"):
    """Build a history buffer from a list of values for one field.

    ``None`` in the series means "the API returned nothing for this
    slot" — the same gap `_record_sample` writes.
    """
    rows = []
    for i, val in enumerate(series):
        ts = base + timedelta(minutes=i * step_min)
        values = {
            "precipitation": None,
            "snowfall": None,
            "lightning_potential": None,
            "visibility": None,
            "wind_gusts_10m": None,
            "cloud_cover": None,
            "sun_altitude": None,
        }
        if isinstance(val, dict):
            values.update(val)
        else:
            values[field] = val
        rows.append({"ts": ts.isoformat(timespec="seconds"), "values": values})
    return rows


def _quiet(n, value=0.0):
    """`n` calm slots. `value` because a calm WIND series is 20 km/h, not
    0 — a gust field that reads zero for an hour is a broken sensor, not
    a quiet afternoon, and the storm tests need the difference."""
    return [value] * n


# ── Segmentation ───────────────────────────────────────────────────────


def test_detects_one_episode_with_its_boundaries():
    # 12 quiet slots, 6 above the 1000 J/kg thunder line, then 60 quiet
    # slots (5 h) so the segment is comfortably finalisable.
    rows = _history(_quiet(12) + [1500.0, 2400.0, 2000.0, 1800.0, 1200.0, 1100.0] + _quiet(60))
    records, pending = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert len(records) == 1
    assert pending is None
    rec = records[0]
    assert rec["auto_class"] == "thunder"
    assert rec["started_at"] == rows[12]["ts"]
    assert rec["ended_at"] == rows[17]["ts"]
    # 6 samples at 5-min spacing -> first to last is 25 minutes.
    assert rec["duration_min"] == 25
    assert rec["peak_at"] == rows[13]["ts"]  # the 2400 J/kg slot
    assert rec["peaks"]["lightning_potential"] == 2400.0
    assert rec["id"] == "{}_thunder".format(rows[12]["ts"])


def test_settle_time_prevents_fragmentation():
    """A storm that drops below the line for 15 min stays ONE episode."""
    pulsing = [1500.0, 1400.0] + _quiet(3) + [1600.0, 1300.0] + _quiet(3) + [1800.0]
    rows = _history(_quiet(6) + pulsing + _quiet(60))
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert len(records) == 1
    assert records[0]["duration_min"] == 50  # first crossing to last, 10 slots

    # Same series, settle shortened below the 20-min lulls: the storm
    # now fragments, which is exactly what settle_min exists to
    # prevent. Margins are zeroed so the merge stage cannot put the
    # pieces back together and mask the effect being measured.
    short_settle = dict(TIGHT, settle_min=5, pre_min=0, post_min=0)
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=short_settle)
    assert len(records) == 3


def test_gap_beyond_settle_and_margins_splits_into_two():
    rows = _history(_quiet(6) + [1500.0, 1600.0] + _quiet(30) + [1400.0, 1300.0] + _quiet(60))
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert len(records) == 2
    assert records[0]["ended_at"] < records[1]["started_at"]


def test_overlapping_margins_merge_into_one_episode():
    """Same 150-min gap, but 90-min margins on both sides overlap."""
    rows = _history(_quiet(6) + [1500.0, 1600.0] + _quiet(30) + [1400.0, 1300.0] + _quiet(60))
    wide = {"enabled": True, "pre_min": 90, "post_min": 90, "settle_min": 30}
    records, pending = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=wide)
    # The trailing quiet run (5 h) is shorter than the 180-min quiet
    # window plus the merged episode, so check both halves are in ONE
    # segment rather than two.
    segments = records + ([pending] if pending else [])
    assert len(segments) == 1
    assert segments[0]["duration_min"] == 165


def test_margins_are_captured_around_the_episode():
    rows = _history(_quiet(12) + [1500.0, 2000.0] + _quiet(60))
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    rec = records[0]
    # pre_min=post_min=10 at 5-min spacing -> 2 samples each side.
    assert rec["samples"][0]["ts"] == rows[10]["ts"]
    assert rec["samples"][-1]["ts"] == rows[15]["ts"]
    assert rec["sample_count"] == len(rec["samples"]) == 6
    assert rec["pre_min"] == 10 and rec["post_min"] == 10


def test_running_storm_is_pending_not_archived():
    """The tail of the history cannot be finalised — it may still grow."""
    rows = _history(_quiet(12) + [1500.0, 2000.0, 1700.0])
    records, pending = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert records == []
    assert pending is not None
    assert pending["auto_class"] == "thunder"
    assert "samples" not in pending
    assert pending["finalizes_at"] > pending["ended_at"]


def test_disabled_event_yields_no_episodes():
    rows = _history(_quiet(6) + [1500.0, 2000.0] + _quiet(60))
    off = {"thunder": {"enabled": False, "threshold": 1000.0}}
    records, pending = detect_episodes(rows, events_cfg=off, episode_cfg=TIGHT)
    assert records == [] and pending is None


def test_fog_triggers_below_its_threshold():
    rows = _history(
        [{"visibility": 8000.0}] * 6
        + [{"visibility": 400.0}, {"visibility": 300.0}]
        + [{"visibility": 8000.0}] * 60
    )
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert len(records) == 1
    assert records[0]["auto_class"] == "fog"


def test_thunder_wins_auto_class_over_rain():
    rows = _history(
        _quiet(6) + [{"lightning_potential": 1500.0, "precipitation": 9.0}] * 4 + _quiet(60)
    )
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert records[0]["auto_class"] == "thunder"
    assert sorted(records[0]["auto_events"]) == ["heavy_rain", "thunder"]


def test_precipitation_total_integrates_the_episode():
    # 12 mm/h held for four 5-min slots = 12 * (20/60) = 4.0 mm, minus
    # the first slot which carries the spacing of the sample before it
    # (also 5 min) -> 4.0 mm exactly.
    rows = _history(_quiet(6) + [{"precipitation": 12.0}] * 4 + _quiet(60), field="precipitation")
    records, _ = detect_episodes(rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert records[0]["totals"]["precipitation_mm"] == pytest.approx(4.0, abs=0.01)


# ── Intensity ──────────────────────────────────────────────────────────


def test_intensity_orders_two_known_storms():
    # Lightning values are LPI (Lynn & Yair 2010), whose observed
    # thunderstorm band is 0.2-0.8 J/kg. These fixtures used to read
    # 1200 / 2800 — CAPE magnitudes, matching the trigger threshold that
    # was wrong by three orders of magnitude. Both clamped to 1.0 under
    # the corrected reference, so the ordering this test exists to check
    # became untestable.
    mild = {"lightning_potential": 0.4, "precipitation": 3.0, "wind_gusts_10m": 40.0}
    severe = {"lightning_potential": 1.6, "precipitation": 18.0, "wind_gusts_10m": 95.0}
    mild_score = intensity_score(mild, {"precipitation_mm": 4.0})
    severe_score = intensity_score(severe, {"precipitation_mm": 31.0})
    assert 0.0 < mild_score < severe_score <= 1.0


def test_intensity_reference_value_scores_one():
    """An axis at its documented reference alone is intensity 1.0."""
    assert intensity_score({"lightning_potential": 2.0}) == 1.0
    assert intensity_score({"precipitation": 20.0}) == 1.0
    assert intensity_score({"wind_gusts_10m": 120.0}) == 1.0


def test_intensity_ignores_missing_axes():
    """A missing wind reading must not make a storm look milder."""
    assert intensity_score({"lightning_potential": 1.0}) == pytest.approx(0.5)
    assert intensity_score({}) == 0.0


def test_intensity_is_monotone_in_every_axis():
    low = {"lightning_potential": 1.0, "precipitation": 5.0}
    high = {"lightning_potential": 1.0, "precipitation": 10.0}
    assert intensity_score(high) > intensity_score(low)


# ── Archive: persistence, idempotency, patches ─────────────────────────


@pytest.fixture
def storm_rows():
    return _history(_quiet(12) + [1500.0, 2400.0, 1800.0] + _quiet(60))


def test_sweep_archives_and_is_idempotent(tmp_path, storm_rows):
    first = sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert first["archived"] == 1
    second = sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert second["archived"] == 0
    assert second["detected"] == 1
    assert len(list_episodes(tmp_path)) == 1


def test_sweep_backfills_the_whole_window_on_first_run(tmp_path):
    """Three separated storms across the buffer all land in one pass."""
    rows = _history(
        _quiet(6)
        + [1500.0, 1600.0]
        + _quiet(60)
        + [1400.0, 1900.0]
        + _quiet(60)
        + [1200.0, 1300.0]
        + _quiet(60)
    )
    result = sweep(tmp_path, rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert result["archived"] == 3
    assert len(list_episodes(tmp_path)) == 3


def test_list_omits_samples_and_sorts_newest_first(tmp_path):
    rows = _history(_quiet(6) + [1500.0] + _quiet(60) + [1900.0] + _quiet(60))
    sweep(tmp_path, rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    items = list_episodes(tmp_path)
    assert len(items) == 2
    assert all("samples" not in it for it in items)
    assert all(it["sample_count"] > 0 for it in items)
    assert items[0]["started_at"] > items[1]["started_at"]
    # The full record still carries its curve.
    full = get_episode(tmp_path, items[0]["id"])
    assert len(full["samples"]) == full["sample_count"]


def test_patch_folds_over_base_without_rewriting_it(tmp_path, storm_rows):
    sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    ep_id = list_episodes(tmp_path)[0]["id"]

    patch_episode(tmp_path, ep_id, {"user_class": "storm", "user_name": "Erstes Gewitter"})
    patch_episode(tmp_path, ep_id, {"user_note": "Hagel im Garten"})
    patch_episode(tmp_path, ep_id, {"user_class": "hail"})

    folded = get_episode(tmp_path, ep_id)
    assert folded["user_class"] == "hail"  # last patch wins
    assert folded["user_name"] == "Erstes Gewitter"
    assert folded["user_note"] == "Hagel im Garten"
    assert folded["auto_class"] == "thunder"  # detector verdict untouched

    # The base record on disk is byte-identical to what was written.
    lines = [
        json.loads(ln)
        for ln in episodes_path(tmp_path).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    bases = [r for r in lines if r.get("kind") == "episode"]
    assert len(bases) == 1
    assert bases[0]["user_class"] is None
    assert len([r for r in lines if r.get("kind") == "patch"]) == 3


def test_patch_can_clear_a_field(tmp_path, storm_rows):
    sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    ep_id = list_episodes(tmp_path)[0]["id"]
    patch_episode(tmp_path, ep_id, {"user_class": "storm"})
    patch_episode(tmp_path, ep_id, {"user_class": None})
    assert get_episode(tmp_path, ep_id)["user_class"] is None


def test_patch_ignores_non_patchable_fields(tmp_path, storm_rows):
    sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    ep_id = list_episodes(tmp_path)[0]["id"]
    patch_episode(tmp_path, ep_id, {"intensity": 9.9, "auto_class": "harmless"})
    rec = get_episode(tmp_path, ep_id)
    assert rec["auto_class"] == "thunder"
    assert rec["intensity"] <= 1.0


def test_patch_on_unknown_id_returns_none(tmp_path):
    assert patch_episode(tmp_path, "nope", {"user_class": "storm"}) is None


def test_delete_tombstones_and_blocks_re_detection(tmp_path, storm_rows):
    sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    ep_id = list_episodes(tmp_path)[0]["id"]
    assert delete_episode(tmp_path, ep_id) is True
    assert list_episodes(tmp_path) == []
    assert get_episode(tmp_path, ep_id) is None
    # The base record survives on disk — only a tombstone was appended.
    text = episodes_path(tmp_path).read_text(encoding="utf-8")
    assert '"kind": "episode"' in text
    # And the next sweep must not resurrect it while the history that
    # produced it is still inside the rolling window.
    again = sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert again["archived"] == 0
    assert list_episodes(tmp_path) == []


def test_delete_on_unknown_id_is_false(tmp_path):
    assert delete_episode(tmp_path, "nope") is False


def test_torn_final_line_does_not_lose_earlier_records(tmp_path, storm_rows):
    sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    path = episodes_path(tmp_path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"kind": "episode", "id": "trunc')  # power loss mid-append
    assert len(list_episodes(tmp_path)) == 1
    # The next append repairs the line break rather than fusing onto it.
    ep_id = list_episodes(tmp_path)[0]["id"]
    patch_episode(tmp_path, ep_id, {"user_name": "nach dem Absturz"})
    assert get_episode(tmp_path, ep_id)["user_name"] == "nach dem Absturz"


def test_empty_and_garbage_history_are_survivable(tmp_path):
    assert detect_episodes([], events_cfg=EVENTS, episode_cfg=TIGHT) == ([], None)
    junk = [{"ts": "not-a-date", "values": {}}, "nonsense", {"values": {}}, None]
    assert detect_episodes(junk, events_cfg=EVENTS, episode_cfg=TIGHT) == ([], None)
    assert sweep(tmp_path, junk, events_cfg=EVENTS, episode_cfg=TIGHT)["archived"] == 0


def test_out_of_order_rows_do_not_split_a_storm():
    rows = _history(_quiet(6) + [1500.0, 1600.0, 1700.0] + _quiet(60))
    shuffled = [rows[7]] + [rows[6]] + rows[:6] + rows[8:]
    records, _ = detect_episodes(shuffled, events_cfg=EVENTS, episode_cfg=TIGHT)
    assert len(records) == 1
    assert records[0]["duration_min"] == 10


# ── WeatherService wiring ──────────────────────────────────────────────


class _StubStore:
    """Just enough SettingsStore for the history/episode path."""

    def __init__(self, root):
        self.base_config = {"storage": {"root": str(root)}}


def _service(tmp_path, rows):
    from app.weather_service import WeatherService

    svc = WeatherService(
        {"enabled": True, "events": EVENTS, "episodes": TIGHT},
        {},
        _StubStore(tmp_path),
        {"location": {"lat": 48.0, "lon": 11.0}},
    )
    svc._history.extend(rows)
    return svc


def test_service_sweep_archives_and_exposes_pending(tmp_path, storm_rows):
    """The poll-time hook writes the archive and reports the open storm."""
    svc = _service(tmp_path, storm_rows)
    svc._sweep_episodes()
    assert len(list_episodes(tmp_path)) == 1
    assert svc.episodes_pending() is None

    # A storm still running at the tail is pending, not archived.
    running = _service(tmp_path, _history(_quiet(12) + [1500.0, 2000.0]))
    running._sweep_episodes()
    pending = running.episodes_pending()
    assert pending is not None and pending["auto_class"] == "thunder"


def test_service_sweep_survives_an_archive_failure(tmp_path, storm_rows, monkeypatch):
    """An archive failure must never break the poll cadence."""
    import app.weather_episodes as we

    def _boom(*_a, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(we, "sweep", _boom)
    svc = _service(tmp_path, storm_rows)
    svc._sweep_episodes()  # must not raise
    assert svc.episodes_pending() is None


# ── HTTP contract ──────────────────────────────────────────────────────
# Flask's test client only — the blueprint is registered on a throwaway
# app, nothing binds a port. Port 8099 is the live instance.


@pytest.fixture
def client(tmp_path, storm_rows, monkeypatch):
    sweep(tmp_path, storm_rows, events_cfg=EVENTS, episode_cfg=TIGHT)
    monkeypatch.setattr(app_state, "storage_root", tmp_path, raising=False)
    monkeypatch.setattr(app_state, "weather_service", None, raising=False)
    flask_app = flask.Flask(__name__)
    flask_app.register_blueprint(episode_routes.bp)
    return flask_app.test_client()


def test_route_list_has_no_samples(client, tmp_path):
    body = client.get("/api/weather/episodes").get_json()
    assert body["count"] == 1
    assert "samples" not in body["items"][0]
    assert body["pending"] is None


def test_route_get_carries_samples(client, tmp_path):
    ep_id = list_episodes(tmp_path)[0]["id"]
    body = client.get("/api/weather/episodes/{}".format(ep_id)).get_json()
    assert body["id"] == ep_id
    assert len(body["samples"]) == body["sample_count"]
    assert client.get("/api/weather/episodes/nope").status_code == 404


def test_route_patch_sets_user_fields(client, tmp_path):
    ep_id = list_episodes(tmp_path)[0]["id"]
    url = "/api/weather/episodes/{}".format(ep_id)
    r = client.patch(url, json={"user_class": "hail", "user_name": "  Hagelsturm  "})
    assert r.status_code == 200
    assert r.get_json()["episode"]["user_class"] == "hail"
    assert get_episode(tmp_path, ep_id)["user_name"] == "Hagelsturm"


def test_route_patch_rejects_bad_input(client, tmp_path):
    ep_id = list_episodes(tmp_path)[0]["id"]
    url = "/api/weather/episodes/{}".format(ep_id)
    assert client.patch(url, json={"user_class": "tornado"}).status_code == 400
    assert client.patch(url, json={"user_note": 17}).status_code == 400
    assert client.patch(url, json={"intensity": 1.0}).status_code == 400
    assert client.patch(url, json={}).status_code == 400
    # Nothing was written by any of the rejections.
    assert get_episode(tmp_path, ep_id)["user_class"] is None


def test_route_delete_tombstones(client, tmp_path):
    ep_id = list_episodes(tmp_path)[0]["id"]
    url = "/api/weather/episodes/{}".format(ep_id)
    assert client.delete(url).status_code == 200
    assert client.get("/api/weather/episodes").get_json()["count"] == 0
    assert client.delete(url).status_code == 404


# ── Wind gusts as a trigger ────────────────────────────────────────────
#
# On 2026-08-28 a squall peaked at ~65 km/h on Garten 'Dach Terrasse'
# while lightning sat at 1 J/kg and rain at 0.20 mm/h. Nothing was
# archived, and the operator asked why: gusts were charted, carried a
# palette entry, an intensity reference and even a `storm` user-class in
# the frontend — but `wind_gusts_10m` had no entry in HISTORY_FIELD_TO_EVENT
# or FIELD_DIRECTION, so the one remarkable number in the window was the
# one that could not start an episode.
#
# 60 km/h sits just under Beaufort 8 (62) and far above the 22–26 km/h
# that is an ordinary breezy afternoon at this location.

STORM_EVENTS = dict(EVENTS, storm={"enabled": True, "threshold": 60.0})


def test_a_gale_alone_is_archived_as_a_storm():
    """THE regression test — this window produced no episode at all."""
    rows = _history(
        _quiet(12, 20.0) + [58.0, 65.0, 70.0, 66.0, 61.0] + _quiet(60, 22.0),
        field="wind_gusts_10m",
    )
    eps, _ = detect_episodes(rows, events_cfg=STORM_EVENTS, episode_cfg=TIGHT)
    assert len(eps) == 1, f"a 70 km/h gale must be archivable, got {eps}"
    ep = eps[0]
    assert ep["auto_class"] == "storm"
    assert ep["peaks"]["wind_gusts_10m"] == 70.0


def test_an_ordinary_breezy_afternoon_is_not_a_storm():
    """The counter-test — the threshold has to exclude normal weather."""
    rows = _history(_quiet(40, 26.0), field="wind_gusts_10m")
    eps, _ = detect_episodes(rows, events_cfg=STORM_EVENTS, episode_cfg=TIGHT)
    assert eps == []


def test_lightning_still_outranks_gusts_in_one_episode():
    """A thunderstorm with gusts in it is a thunderstorm, not a Sturm."""
    rows = _history(_quiet(12) + [1500.0, 2400.0, 1800.0] + _quiet(60))
    for i, r in enumerate(rows):
        r["values"]["wind_gusts_10m"] = 70.0 if 12 <= i < 15 else 20.0
    eps, _ = detect_episodes(rows, events_cfg=STORM_EVENTS, episode_cfg=TIGHT)
    assert len(eps) == 1
    assert eps[0]["auto_class"] == "thunder", "EVENT_PRIORITY puts thunder first"
