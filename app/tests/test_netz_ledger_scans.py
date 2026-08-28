"""How many times one drag reads the 8 MB ledger.

The read side folds the whole JSONL for every question asked of it, and
the Netz panel asks one per axis. ``net_state`` ran ``corpus_stats``
once and then ``judged_alerts`` again inside ``axis_proposal`` for EVERY
axis; ``api_netz_axes`` called ``net_state`` twice on top of that — once
for the archive record, once for the response body. Eleven axes came to
twelve full parses per page load and twenty-four per commit, plus one on
the thread that had just finished encoding a clip, for every event.

The fix is one cache keyed on the file's own (size, mtime_ns), so a run
of readers over an unchanged ledger parses it once, and one call site
that stopped asking for the same payload twice. These pin both, by
counting the parses rather than by reading the source.
"""

from __future__ import annotations

import time

import pytest
from flask import Flask

from app import app_state
from app.detection_feedback import _io as fb_io
from app.detection_feedback import (
    MIN_JUDGED_PER_STRATUM,
    corpus_stats,
    judged_alerts,
    record_alert,
    record_verdict,
)
from app.routes import _netz_helpers as H
from app.routes import netz as netz_routes
from app.settings_store import SettingsStore
from app.storage import EventStore

CAM = "cam_werkstatt"
AXES = ["person", "cat", "dog", "bird"]


@pytest.fixture
def parses(monkeypatch):
    """Counts every full fold of the ledger, wherever it is triggered."""
    calls = []
    real = fb_io.index_records

    def _counted(records):
        calls.append(1)
        return real(records)

    monkeypatch.setattr(fb_io, "index_records", _counted)
    return calls


def _seed_ready_corpus(root):
    """Enough judged alerts on every axis to clear the stratum bar, so
    `axis_proposal` actually reaches `judged_alerts` instead of stopping
    at "not ready" — which is the only shape in which the old code paid
    the per-axis cost."""
    ts = 1_700_000_000.0
    for label in AXES:
        for i in range(MIN_JUDGED_PER_STRATUM + 10):
            eid = f"{label}-{i}"
            record_alert(
                root,
                cam_id=CAM,
                event_id=eid,
                label=label,
                score=0.9 if i % 2 else 0.4,
                threshold=0.8,
                ts=ts + i,
            )
            record_verdict(
                root,
                event_id=eid,
                correct=bool(i % 2),
                ts=ts + i,
                source="telegram_q",
                cam_id=CAM,
            )


@pytest.fixture
def client(tmp_storage_root, monkeypatch):
    base = {
        "app": {},
        "storage": {"root": str(tmp_storage_root)},
        "cameras": [
            {
                "id": CAM,
                "name": "Werkstatt",
                "rtsp_url": "rtsp://cam.lan/s",
                "object_filter": list(AXES),
                "role": "security",
            }
        ],
        "telegram": {"push": {"labels": {"person": {"push": True, "threshold": 0.85}}}},
        "mqtt": {},
        "processing": {},
    }
    settings = SettingsStore(tmp_storage_root / "settings.json", base)
    monkeypatch.setattr(app_state, "settings", settings)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root)
    monkeypatch.setattr(app_state, "store", EventStore(tmp_storage_root), raising=False)
    monkeypatch.setattr(app_state, "rebuild_runtimes", lambda: None, raising=False)
    _seed_ready_corpus(tmp_storage_root)
    app = Flask(__name__)
    app.register_blueprint(netz_routes.bp)
    return app.test_client()


def test_one_page_load_parses_the_ledger_once(client, tmp_storage_root, parses):
    """Was 1 + one per ready axis. Four axes here; eleven in production."""
    state = H.net_state(CAM)
    assert len(state["axes"]) == len(AXES)
    assert len(parses) == 1


def test_one_commit_parses_the_ledger_once(client, parses):
    res = client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 62, "cat": 44}})
    assert res.status_code == 200
    assert len(parses) == 1


def test_the_state_payload_is_not_computed_twice_per_commit(client, monkeypatch):
    """The archive record and the response body want the same net state.
    Asking for it twice doubled the cost of the whole endpoint."""
    calls = []
    real = H.net_state

    def _counted(cam_id):
        calls.append(cam_id)
        return real(cam_id)

    # `netz.py` reaches it as `H.net_state`, so patching the helper
    # module is what the route actually resolves.
    monkeypatch.setattr(H, "net_state", _counted)
    client.patch(f"/api/netz/{CAM}/axes", json={"axes": {"person": 62}})
    assert calls == [CAM]


def test_a_write_to_the_ledger_invalidates_the_cache(client, tmp_storage_root, parses):
    """A cache that outlives its file would freeze the corpus: the 03:30
    run and every panel would keep answering from the state before the
    evening's answers."""
    before = judged_alerts(tmp_storage_root, cam_id=CAM, label="person")
    assert len(parses) == 1
    record_alert(
        tmp_storage_root,
        cam_id=CAM,
        event_id="fresh-1",
        label="person",
        score=0.77,
        threshold=0.8,
        ts=time.time(),
    )
    record_verdict(
        tmp_storage_root,
        event_id="fresh-1",
        correct=True,
        ts=time.time(),
        source="telegram_q",
        cam_id=CAM,
    )
    after = judged_alerts(tmp_storage_root, cam_id=CAM, label="person")
    assert len(after) == len(before) + 1
    assert len(parses) > 1


def test_repeated_readers_over_an_unchanged_ledger_parse_once(client, tmp_storage_root, parses):
    corpus_stats(tmp_storage_root)
    for label in AXES:
        judged_alerts(tmp_storage_root, cam_id=CAM, label=label)
    corpus_stats(tmp_storage_root)
    assert len(parses) == 1
