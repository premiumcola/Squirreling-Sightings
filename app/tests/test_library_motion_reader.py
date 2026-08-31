"""``library._motion_reader`` — day-folder pruning + label filtering.

Three things pinned here:

* boundary correctness at day/month/year edges — an event exactly at
  the edge of a window must not be lost, and one one second outside it
  must not leak in;
* the prune is real, not just "the happy path returns the right set" —
  a large number of poisoned out-of-range day folders is planted and
  the exact set of files opened is asserted, so a regression back to a
  full tree walk fails deterministically instead of by luck;
* the new ``label``/``labels`` filter matches
  ``EventStore._filter_events``'s semantics bit-for-bit (OR logic,
  `cat_name`/`bird_species` fold into the match set alongside `labels`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.library._motion_reader import motion_events_between


class _Store:
    def __init__(self, root):
        self.events_dir = root / "motion_detection"


def _write_event(root, cam, day, hhmmss, event_id=None, **extra):
    eid = event_id or "{}-{}-000000".format(day.replace("-", ""), hhmmss)
    payload = {
        "event_id": eid,
        "time": "{}T{}:{}:{}".format(day, hhmmss[:2], hhmmss[2:4], hhmmss[4:6]),
        "snapshot_relpath": "motion_detection/{}/{}/{}.jpg".format(cam, day, eid),
    }
    payload.update(extra)
    d = root / "motion_detection" / cam / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "{}.json".format(eid)).write_text(json.dumps(payload), encoding="utf-8")
    return payload


# ── boundary correctness ────────────────────────────────────────────────


def test_day_start_and_day_end_are_both_inside_an_inclusive_window(tmp_path):
    _write_event(tmp_path, "cam1", "2026-08-20", "000000")
    _write_event(tmp_path, "cam1", "2026-08-20", "235959")
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-20T00:00:00", "2026-08-20T23:59:59"
    )
    assert sorted(e["time"] for e in events) == ["2026-08-20T00:00:00", "2026-08-20T23:59:59"]


def test_one_second_outside_the_window_on_either_edge_is_excluded(tmp_path):
    _write_event(tmp_path, "cam1", "2026-08-19", "235959")  # 1s before lo
    _write_event(tmp_path, "cam1", "2026-08-20", "000000")  # == lo, included
    _write_event(tmp_path, "cam1", "2026-08-20", "235959")  # == hi, included
    _write_event(tmp_path, "cam1", "2026-08-21", "000000")  # 1s after hi
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-20T00:00:00", "2026-08-20T23:59:59"
    )
    assert sorted(e["time"] for e in events) == ["2026-08-20T00:00:00", "2026-08-20T23:59:59"]


def test_a_month_boundary_does_not_lose_or_duplicate_events(tmp_path):
    _write_event(tmp_path, "cam1", "2026-07-31", "230000")
    _write_event(tmp_path, "cam1", "2026-08-01", "010000")
    # Outside the queried window on each side — must not appear.
    _write_event(tmp_path, "cam1", "2026-07-30", "230000")
    _write_event(tmp_path, "cam1", "2026-08-02", "010000")
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-07-31T00:00:00", "2026-08-01T23:59:59"
    )
    assert sorted(e["time"] for e in events) == ["2026-07-31T23:00:00", "2026-08-01T01:00:00"]


def test_a_year_boundary_does_not_lose_or_duplicate_events(tmp_path):
    _write_event(tmp_path, "cam1", "2025-12-31", "230000")
    _write_event(tmp_path, "cam1", "2026-01-01", "010000")
    _write_event(tmp_path, "cam1", "2025-12-30", "230000")
    _write_event(tmp_path, "cam1", "2026-01-02", "010000")
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2025-12-31T00:00:00", "2026-01-01T23:59:59"
    )
    assert sorted(e["time"] for e in events) == ["2025-12-31T23:00:00", "2026-01-01T01:00:00"]


# ── the prune is real, not incidental ───────────────────────────────────


def test_pruning_survives_dozens_of_out_of_range_poisoned_days(tmp_path, monkeypatch):
    """A regression back to a full tree walk is caught by the FILE-OPEN
    COUNT, not by the returned set — the poisoned days hold invalid JSON
    that ``motion_events_between`` already tolerates (warn + skip), so a
    test that only checked the return value would still pass even if
    every one of these got opened first."""
    good_day = "2026-08-20"
    good = _write_event(tmp_path, "cam1", good_day, "120000")

    for i in range(40):
        day = (datetime(2019, 1, 1) + timedelta(days=i * 37)).strftime("%Y-%m-%d")
        if day == good_day:
            continue
        d = tmp_path / "motion_detection" / "cam1" / day
        d.mkdir(parents=True, exist_ok=True)
        (d / "poison.json").write_text("{not json", encoding="utf-8")

    opened: list = []
    real_read = Path.read_text

    def _spy(self, *a, **kw):
        opened.append(self.name)
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", _spy)
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-19T00:00:00", "2026-08-21T00:00:00"
    )
    assert [e["event_id"] for e in events] == [good["event_id"]]
    assert opened == ["{}.json".format(good["event_id"])]


# ── label / object-class filter (the confirmed gap this stage closes) ──


def test_labels_list_uses_or_logic_across_events(tmp_path):
    fox = _write_event(tmp_path, "cam1", "2026-08-20", "100000", labels=["fox"])
    _write_event(tmp_path, "cam1", "2026-08-20", "110000", labels=["person"])
    hedgehog = _write_event(tmp_path, "cam1", "2026-08-20", "120000", labels=["hedgehog"])
    events = motion_events_between(
        _Store(tmp_path),
        "cam1",
        "2026-08-20T00:00:00",
        "2026-08-20T23:59:59",
        labels=["fox", "hedgehog"],
    )
    assert {e["event_id"] for e in events} == {fox["event_id"], hedgehog["event_id"]}


def test_a_single_label_is_sugar_for_a_one_element_list(tmp_path):
    fox = _write_event(tmp_path, "cam1", "2026-08-20", "100000", labels=["fox"])
    _write_event(tmp_path, "cam1", "2026-08-20", "110000", labels=["person"])
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-20T00:00:00", "2026-08-20T23:59:59", label="fox"
    )
    assert [e["event_id"] for e in events] == [fox["event_id"]]


def test_labels_wins_over_label_when_both_are_given(tmp_path):
    fox = _write_event(tmp_path, "cam1", "2026-08-20", "100000", labels=["fox"])
    events = motion_events_between(
        _Store(tmp_path),
        "cam1",
        "2026-08-20T00:00:00",
        "2026-08-20T23:59:59",
        label="person",
        labels=["fox"],
    )
    assert [e["event_id"] for e in events] == [fox["event_id"]]


def test_the_match_set_also_covers_cat_name_and_bird_species(tmp_path):
    """Mirrors `EventStore._filter_events`: an identity classifier
    stamps `cat_name` / `bird_species` instead of (or as well as)
    `labels`, and the filter has to see those too."""
    cat = _write_event(tmp_path, "cam1", "2026-08-20", "100000", labels=["cat"], cat_name="Minka")
    bird = _write_event(
        tmp_path, "cam1", "2026-08-20", "110000", labels=["bird"], bird_species="Grünfink"
    )
    _write_event(tmp_path, "cam1", "2026-08-20", "120000", labels=["cat"], cat_name="Whiskers")
    events = motion_events_between(
        _Store(tmp_path),
        "cam1",
        "2026-08-20T00:00:00",
        "2026-08-20T23:59:59",
        labels=["Minka", "Grünfink"],
    )
    assert {e["event_id"] for e in events} == {cat["event_id"], bird["event_id"]}


def test_no_filter_set_returns_everything_in_the_window(tmp_path):
    a = _write_event(tmp_path, "cam1", "2026-08-20", "100000", labels=["fox"])
    b = _write_event(tmp_path, "cam1", "2026-08-20", "110000", labels=["person"])
    events = motion_events_between(
        _Store(tmp_path), "cam1", "2026-08-20T00:00:00", "2026-08-20T23:59:59"
    )
    assert {e["event_id"] for e in events} == {a["event_id"], b["event_id"]}
