"""THR-2 · the advice reaches a surface, and it is read-only there.

Two consumers, one recommender: `/api/telegram/push/calibration` and
`scripts/corpus_report`. Both walk the real ledger written by
`record_alert` / `record_verdict`, so this is the end-to-end proof that
something finally READS the corpus — the single fact whose absence held
Schwellen-Dynamik, User-Einstufungen, Rückfragen and Lernen down.

The endpoint boots only the `telegram` blueprint on a bare Flask app.
The real boot sequence starts camera runtimes and a Telegram poller, and
a second poller against the live token is exactly the getUpdates
conflict this repo has already lost days to.
"""

from __future__ import annotations

import json

import pytest

from app import app_state
from app.detection_feedback import record_alert, record_verdict
from app.routes import telegram as telegram_routes

flask = pytest.importorskip("flask")

CAM = "reolink_cx810_garten_198"


class _SettingsStub:
    """The three members the endpoint touches, and nothing else."""

    def __init__(self, cameras=None, push=None):
        self._cams = {c["id"]: c for c in (cameras or [])}
        self.data = {"cameras": list(cameras or [])}
        self._push = push or {"labels": {"person": {"push": True, "threshold": 0.85}}}

    def get_camera(self, cam_id):
        return self._cams.get(cam_id)

    def export_effective_config(self, base_cfg):
        return {"telegram": {"push": self._push}}


def _judged(root, eid, *, cam=CAM, label="person", score, correct, ts):
    record_alert(
        root,
        cam_id=cam,
        event_id=eid,
        label=label,
        score=score,
        threshold=0.85,
        ts=ts,
        passed_threshold=score >= 0.85,
    )
    record_verdict(root, event_id=eid, correct=correct, ts=ts + 0.5, cam_id=cam, source="telegram")


def _fill(root, n_true=30, n_false=30, label="person"):
    """A stratum thick enough to clear every calibration bar."""
    for i in range(n_true):
        _judged(root, f"t{i}", label=label, score=0.60 + i * 0.01, correct=True, ts=float(i))
    for i in range(n_false):
        _judged(root, f"f{i}", label=label, score=0.10 + i * 0.01, correct=False, ts=float(500 + i))


@pytest.fixture
def client(tmp_storage_root, monkeypatch):
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)
    monkeypatch.setattr(app_state, "settings", _SettingsStub(), raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(telegram_routes.bp)
    return app.test_client()


# ── the endpoint ──────────────────────────────────────────────────────


def test_endpoint_says_not_yet_on_an_empty_corpus(client):
    body = json.loads(client.get("/api/telegram/push/calibration").data)
    assert body["ok"] is True
    assert body["items"] == []
    assert body["ready"] == 0
    assert body["advisory_only"] is True


def test_endpoint_refuses_a_number_on_a_thin_corpus(client, tmp_storage_root):
    """Eight judgements is the state this had to be built to survive."""
    _fill(tmp_storage_root, n_true=4, n_false=4)
    body = json.loads(client.get("/api/telegram/push/calibration").data)
    assert body["ready"] == 0
    item = body["items"][0]
    assert item["recommended"] is None
    assert item["verdict"] == "insufficient_data"
    assert "Not enough judged alerts" in item["reason"]
    # It still reports where the bar stands, so the panel has something
    # to show while it waits.
    assert item["current"] == 0.85


def test_endpoint_recommends_once_the_ledger_is_thick_enough(client, tmp_storage_root):
    _fill(tmp_storage_root)
    body = json.loads(client.get("/api/telegram/push/calibration").data)
    assert body["corpus"]["n_judged"] == 60
    assert body["ready"] == 1
    item = body["items"][0]
    assert item["cam"] == CAM and item["label"] == "person"
    assert item["verdict"] == "lower"
    assert 0.39 < item["recommended"] < 0.61
    assert item["evidence"]["at_recommended"]["kept_true"] == 30
    # The dead zone, stated in numbers: today's 0.85 drops most sightings.
    assert item["evidence"]["at_current"]["kept_true"] < 10


def test_endpoint_honours_class_severity_alarm(client, tmp_storage_root, monkeypatch):
    """Same corpus, but `person` is an alarm and the current bar is low —
    the endpoint must not propose raising it."""
    monkeypatch.setattr(
        app_state,
        "settings",
        _SettingsStub(
            cameras=[{"id": CAM, "class_severity": {"person": "alarm"}}],
            push={"labels": {"person": {"push": True, "threshold": 0.30}}},
        ),
        raising=False,
    )
    _fill(tmp_storage_root)
    item = json.loads(client.get("/api/telegram/push/calibration").data)["items"][0]
    assert item["verdict"] == "hold"
    assert item["recommended"] == 0.30
    assert item["evidence"]["severity_capped"] is True


def test_endpoint_writes_nothing(client, tmp_storage_root):
    """Read-only is the property, so it gets asserted, not asserted-about."""
    _fill(tmp_storage_root)
    before = {p: p.stat().st_mtime_ns for p in tmp_storage_root.rglob("*") if p.is_file()}
    resp = client.get("/api/telegram/push/calibration")
    # Assert it actually did the work first — a 404 also writes nothing.
    assert resp.status_code == 200
    assert json.loads(resp.data)["ready"] == 1
    after = {p: p.stat().st_mtime_ns for p in tmp_storage_root.rglob("*") if p.is_file()}
    assert before == after


def test_endpoint_503s_without_a_storage_root(monkeypatch):
    monkeypatch.setattr(app_state, "storage_root", None, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(telegram_routes.bp)
    resp = app.test_client().get("/api/telegram/push/calibration")
    assert resp.status_code == 503


# ── the shell report ──────────────────────────────────────────────────


def test_report_prints_the_same_recommendation(tmp_storage_root):
    from scripts import _corpus_reco, corpus_report

    _fill(tmp_storage_root)
    df = corpus_report._ledger()
    stats = df.corpus_stats(tmp_storage_root)
    recs = _corpus_reco.build(df, tmp_storage_root, stats)
    assert len(recs) == 1
    assert recs[0].recommended is not None
    text = "\n".join(_corpus_reco.block(recs))
    assert "ADVISORY ONLY" in text
    assert "Nothing in this section is applied" in text
    assert "{:.2f}".format(recs[0].recommended) in text
    assert "never raise it" in text
    assert _corpus_reco.summary(recs).startswith("[corpus] 1 advisory recommendation")


def test_report_says_not_yet_rather_than_printing_a_number(tmp_storage_root):
    from scripts import _corpus_reco, corpus_report

    _fill(tmp_storage_root, n_true=4, n_false=4)
    df = corpus_report._ledger()
    recs = _corpus_reco.build(df, tmp_storage_root, df.corpus_stats(tmp_storage_root))
    text = "\n".join(_corpus_reco.block(recs))
    assert "No stratum has enough judged alerts" in text
    assert "recommendation:** none" in text
    assert _corpus_reco.summary(recs) == (
        "[corpus] no threshold recommendation — not enough judged alerts."
    )


def test_report_touches_no_file_while_building_advice(tmp_storage_root):
    """The reason `_corpus_reco` parses settings.json by hand instead of
    building a `SettingsStore`: the store's `load()` writes — defaults
    backfill, migrations, backup rotation. An operator report must not
    be able to rewrite the one file carrying the user's credentials.

    Asserted on mtimes rather than on "does it import the store", so a
    future rewrite that finds another way to write still trips it.
    """
    from scripts import _corpus_reco, corpus_report

    (tmp_storage_root / "settings.json").write_text(
        json.dumps({"telegram": {"push": {"labels": {}}}, "cameras": []}), encoding="utf-8"
    )
    _fill(tmp_storage_root)
    df = corpus_report._ledger()
    stats = df.corpus_stats(tmp_storage_root)
    before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_storage_root.rglob("*")}
    _corpus_reco.build(df, tmp_storage_root, stats)
    after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_storage_root.rglob("*")}
    assert before == after


def test_report_reads_saved_settings_without_rewriting_them(tmp_storage_root):
    from scripts import _corpus_reco, corpus_report

    path = tmp_storage_root / "settings.json"
    path.write_text(
        json.dumps(
            {
                "telegram": {"push": {"labels": {"person": {"push": True, "threshold": 0.30}}}},
                "cameras": [{"id": CAM, "class_severity": {"person": "alarm"}}],
            }
        ),
        encoding="utf-8",
    )
    before = path.read_bytes()
    _fill(tmp_storage_root)
    df = corpus_report._ledger()
    recs = _corpus_reco.build(df, tmp_storage_root, df.corpus_stats(tmp_storage_root))
    assert path.read_bytes() == before, "settings.json must not be touched"
    # The saved config was actually read: the alarm cap bit.
    assert recs[0].current == 0.30
    assert recs[0].evidence["severity_capped"] is True
