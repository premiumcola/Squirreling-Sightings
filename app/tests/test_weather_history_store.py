"""The weather history: a 3-year window that does not cost 3 years of writes.

The operator asked for a long history — "setzt es auf 3 Jahre aber nur
wenn es nicht irgendwas langsam macht! sonst beschleunige es!" — and the
old persistence made that impossible: every poll serialised the WHOLE
buffer, atomic-replaced it and fsynced. At 3 years that is ~53 MB
rewritten every five minutes.

Measured on this machine at a full 3-year ledger:

    append + fsync (new)      6 ms
    full rewrite   (old)   1824 ms      → ~300x

So the window and the write cost are now independent. What still scales
is the boot read (~1.2 s for 3 years, once, in a thread) and the number
of points the API would hand a phone — hence the downsampling, which
must preserve SPIKES because that is what the chart is read for.
"""

from __future__ import annotations

import json

from app.weather_service import _history_store as H
from app.weather_service._consts import HISTORY_FIELDS, HISTORY_MAXLEN


def _row(i=0, **vals):
    values = {k: 0.0 for k in HISTORY_FIELDS}
    values.update(vals)
    return {"ts": f"2026-01-01T00:{i % 60:02d}:00", "values": values}


# ── the window itself ────────────────────────────────────────────────


def test_the_window_is_three_years_at_the_default_poll():
    assert HISTORY_MAXLEN == 315_360
    assert round(HISTORY_MAXLEN * 300 / 3600 / 24 / 365) == 3


# ── append-only persistence ──────────────────────────────────────────


def test_a_poll_appends_one_line_and_leaves_the_rest_alone(tmp_path):
    H.compact(tmp_path, [_row(i) for i in range(10)])
    before = H.history_path(tmp_path).read_text(encoding="utf-8")
    H.append(tmp_path, _row(99, precipitation=1.5))
    after = H.history_path(tmp_path).read_text(encoding="utf-8")
    assert after.startswith(before), "an append rewrote earlier lines"
    assert len(after.splitlines()) == 11


def test_a_torn_last_line_costs_one_sample_not_the_archive(tmp_path):
    """kill -9 mid-append. The old full-document format had no such
    property — a torn write lost everything, which is why it fsynced."""
    H.compact(tmp_path, [_row(i) for i in range(5)])
    with H.history_path(tmp_path).open("a", encoding="utf-8") as fh:
        fh.write('{"ts": "2026-01-01T00:0')  # truncated
    rows = H.load(tmp_path, HISTORY_MAXLEN)
    assert len(rows) == 5


def test_an_existing_install_keeps_its_history_across_the_format_change(tmp_path):
    """The legacy document is read once when no ledger exists yet, so
    nobody loses their curve to the migration."""
    legacy = {"version": 1, "samples": [_row(i) for i in range(3)]}
    H.legacy_path(tmp_path).write_text(json.dumps(legacy), encoding="utf-8")
    rows = H.load(tmp_path, HISTORY_MAXLEN)
    assert len(rows) == 3


def test_the_ledger_wins_once_it_exists(tmp_path):
    H.legacy_path(tmp_path).write_text(
        json.dumps({"samples": [_row(i) for i in range(99)]}), encoding="utf-8"
    )
    H.compact(tmp_path, [_row(0)])
    assert len(H.load(tmp_path, HISTORY_MAXLEN)) == 1


def test_load_returns_at_most_the_window(tmp_path):
    H.compact(tmp_path, [_row(i) for i in range(50)])
    assert len(H.load(tmp_path, 10)) == 10


def test_a_field_added_later_reads_as_none_not_a_crash(tmp_path):
    H.history_path(tmp_path).write_text(
        json.dumps({"ts": "2026-01-01T00:00:00", "values": {"precipitation": 1.0}}) + "\n",
        encoding="utf-8",
    )
    rows = H.load(tmp_path, 10)
    assert rows[0]["values"]["precipitation"] == 1.0
    assert rows[0]["values"]["cloud_cover"] is None


def test_compaction_only_triggers_past_the_window(tmp_path):
    H.compact(tmp_path, [_row(i) for i in range(10)])
    assert H.needs_compaction(tmp_path, 10_000) is False
    assert H.needs_compaction(tmp_path, 1) is True


def test_a_failed_write_never_raises(tmp_path):
    """The poll loop must survive a full disk."""
    blocked = tmp_path / "file"
    blocked.write_text("not a directory", encoding="utf-8")
    assert H.append(blocked / "sub", _row()) is False


# ── downsampling ─────────────────────────────────────────────────────


def test_a_short_window_is_never_touched():
    rows = [_row(i) for i in range(100)]
    out, bucket = H.downsample(rows, max_points=2000)
    assert out is rows and bucket == 1


def test_a_lightning_spike_survives_thinning():
    """THE reason this is not a stride. A single spike in three years of
    samples is exactly what the operator reads this chart for."""
    rows = [_row(i) for i in range(50_000)]
    rows[25_000]["values"]["lightning_potential"] = 2.7
    out, bucket = H.downsample(rows, max_points=500)
    assert bucket > 1
    assert max(r["values"]["lightning_potential"] for r in out) == 2.7


def test_a_fog_trough_survives_thinning():
    """Visibility is the inverted metric — its interesting value is the
    LOW one. A max-reducer would erase every fog event."""
    rows = [_row(i, visibility=10_000) for i in range(50_000)]
    rows[10_000]["values"]["visibility"] = 80
    out, _ = H.downsample(rows, max_points=500)
    assert min(r["values"]["visibility"] for r in out) == 80


def test_thinning_respects_the_point_budget():
    rows = [_row(i) for i in range(315_360)]
    out, bucket = H.downsample(rows, max_points=2000)
    assert len(out) <= 2000
    assert bucket == 158


def test_the_x_axis_stays_monotonic_after_thinning():
    rows = [{"ts": f"2026-01-{d:02d}T00:00:00", "values": {}} for d in range(1, 29)]
    out, _ = H.downsample(rows, max_points=4)
    stamps = [r["ts"] for r in out]
    assert stamps == sorted(stamps)
