"""The confirmed-video counter that gates the per-species recording cap.

Deliberately a separate file from the diagnostic ledger: that one is
bounded and prunes old records on compaction, which would let a
species' count silently shrink and uncap itself. This counter must
only ever grow.
"""

from __future__ import annotations

import json
import threading

from app.species_video_count import confirmed_video_count, record_confirmed_video


def _counts(root) -> dict:
    p = root / "species_video_counts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def test_a_species_never_seen_before_counts_zero(tmp_path):
    assert confirmed_video_count(tmp_path, "Elster") == 0
    assert confirmed_video_count(tmp_path, "") == 0
    assert confirmed_video_count(tmp_path, None) == 0


def test_each_confirmation_increments_by_one(tmp_path):
    assert record_confirmed_video(tmp_path, "Elster") == 1
    assert record_confirmed_video(tmp_path, "Elster") == 2
    assert record_confirmed_video(tmp_path, "Elster") == 3
    assert confirmed_video_count(tmp_path, "Elster") == 3


def test_species_are_counted_separately(tmp_path):
    record_confirmed_video(tmp_path, "Elster")
    record_confirmed_video(tmp_path, "Elster")
    record_confirmed_video(tmp_path, "Kohlmeise")
    assert confirmed_video_count(tmp_path, "Elster") == 2
    assert confirmed_video_count(tmp_path, "Kohlmeise") == 1
    assert confirmed_video_count(tmp_path, "Blaumeise") == 0


def test_the_key_is_case_and_whitespace_insensitive(tmp_path):
    record_confirmed_video(tmp_path, "Elster")
    record_confirmed_video(tmp_path, "  ELSTER  ")
    assert confirmed_video_count(tmp_path, "elster") == 2


def test_an_empty_species_records_nothing(tmp_path):
    assert record_confirmed_video(tmp_path, "") == 0
    assert record_confirmed_video(tmp_path, None) == 0
    assert _counts(tmp_path) == {}


def test_a_corrupt_file_fails_open_not_closed(tmp_path):
    """The cap this feeds must fail toward "keep recording", never
    toward "silently stop" — a species is never worth losing footage of
    over a JSON parse error."""
    (tmp_path / "species_video_counts.json").write_text("{not json", encoding="utf-8")
    assert confirmed_video_count(tmp_path, "Elster") == 0
    # Recovers on the next successful write rather than staying wedged.
    assert record_confirmed_video(tmp_path, "Elster") == 1


def test_concurrent_confirmations_do_not_lose_an_increment(tmp_path):
    threads = [
        threading.Thread(target=record_confirmed_video, args=(tmp_path, "Elster"))
        for _ in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert confirmed_video_count(tmp_path, "Elster") == 20


def test_persists_across_reads(tmp_path):
    record_confirmed_video(tmp_path, "Star")
    record_confirmed_video(tmp_path, "Star")
    # A fresh read (no cache) sees the same number a second caller would.
    assert confirmed_video_count(tmp_path, "Star") == 2
    assert _counts(tmp_path)["star"] == 2
