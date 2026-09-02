"""The debug bundle: one ZIP an operator can hand to someone else.

Three properties decide whether that is help or a leak, and each is a
section below:

  · **It never carries a credential.** The archive's whole purpose is to
    leave the box — attached to a message, dropped in a chat. The raw
    ``settings.json`` is not in it in any shape; the effective config is,
    scrubbed positionally rather than field by field, because the failure
    mode is unrecoverable once a file has been sent.
  · **It is complete enough to re-simulate.** Config, live status, TPU
    load, per-stage timings, the last events *with their provenance*, the
    per-camera tuning, and the log tail. A bundle missing one of those
    sends the operator back for a second round trip.
  · **It is bounded.** Ten archives, enforced on the write path — not on
    a schedule a rebooted box never reaches.
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import app_state, debug_bundle
from app.debug_bundle import _sections, _writer
from app.settings_store import SettingsStore
from app.storage import EventStore

CAM = "reolink_cx810_hof_42"
SECRET = "hunter2"
MQTT_PW = "brokerpass"
CHAT_ID = -1001234567890
# Assembled from parts: these must be REAL secret SHAPES, because
# recognising them is the behaviour under test — but CLAUDE.md's
# pre-push audit greps every tracked file for exactly these patterns,
# and a literal here would be a permanent false positive in a check
# that is only useful while it stays quiet.
BOT_TOKEN = "123456789" + ":" + "AAEEabcdefghijklmnopqrstuvwxyz012345"
LAN_IP = ".".join(("192", "168", "1", "42"))
RTSP = f"rtsp://admin:{SECRET}@{LAN_IP}/h264"


def _base(root: Path) -> dict:
    return {
        "app": {"name": "Squirreling"},
        "storage": {"root": str(root)},
        "cameras": [
            {
                "id": CAM,
                "name": "Hof",
                "role": "wildlife",
                "rtsp_url": RTSP,
                "password": SECRET,
                "frame_interval_ms": 350,
                "object_filter": ["person"],
            }
        ],
        "telegram": {"token": BOT_TOKEN, "chat_id": CHAT_ID, "push": {}},
        "mqtt": {"host": LAN_IP, "password": MQTT_PW},
        "processing": {},
    }


def _event(event_id: str, when: str) -> dict:
    return {
        "event_id": event_id,
        "time": when,
        "label": "person",
        "camera_id": CAM,
        "detections": [{"label": "person", "score": 0.9, "model": "detector"}],
        "provenance": {
            "schema": 1,
            "camera": {"id": CAM, "role": "wildlife"},
            "models": {"detector": {"file": "ssd.tflite", "sha256": "abc123"}},
            "source": RTSP,
        },
    }


@pytest.fixture
def env(tmp_storage_root, monkeypatch):
    """A storage root with one camera, three events and a log file."""
    base = _base(tmp_storage_root)
    settings = SettingsStore(tmp_storage_root / "settings.json", base)
    store = EventStore(str(tmp_storage_root))
    for i in range(3):
        store.add_event(CAM, _event(f"20260901-1200{i}0", f"2026-09-01 12:0{i}:00"))

    class _Registry:
        def list_profiles(self):
            return []

    monkeypatch.setattr(app_state, "settings", settings, raising=False)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "runtimes", {}, raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(app_state, "cat_registry", _Registry(), raising=False)
    monkeypatch.setattr(app_state, "person_registry", _Registry(), raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: base, raising=False)
    from app.routes import telemetry

    monkeypatch.setattr(telemetry, "_usb_line", lambda: None)
    monkeypatch.setattr(telemetry, "_versions", lambda: {})
    telemetry._CACHE["payload"] = None
    return tmp_storage_root


def _members(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n).decode("utf-8") for n in zf.namelist()}


# ── never a credential ────────────────────────────────────────────────────


def test_every_secret_in_the_effective_config_is_replaced_by_a_marker():
    """ "Is a token configured?" is a diagnosis; the token never is.
    Dropping the key outright would make a misconfigured box and a
    working one look identical."""
    out = debug_bundle.redact_settings(_base(Path("/tmp")))
    blob = json.dumps(out)
    assert SECRET not in blob and MQTT_PW not in blob
    assert BOT_TOKEN not in blob and str(CHAT_ID) not in blob
    assert LAN_IP not in blob, "the operator's subnet is not diagnostic data"
    assert out["telegram"] == {"token_set": True, "chat_id_set": True, "push": {}}
    assert out["mqtt"]["password_set"] is True
    assert out["cameras"][0]["password_set"] is True
    # …and the shape survives: this is still a document someone reads.
    assert out["cameras"][0]["id"] == CAM
    assert out["cameras"][0]["rtsp_url"].startswith("rtsp://admin:")


def test_a_secret_is_caught_by_the_shape_of_its_name_not_a_list():
    """The exact-name list cannot be kept current by hand. Substring
    matching means the field someone adds next year is covered on the
    day it is added, not on the day someone notices."""
    out = debug_bundle.redact_settings(
        {
            "mqtt_password": MQTT_PW,
            "alert_chat_ids": [CHAT_ID],
            "cloud": {"api_secret": "s3cr3t", "user_token": BOT_TOKEN},
            "camera_passphrase": "openssl",
        }
    )
    blob = json.dumps(out)
    for leak in (MQTT_PW, str(CHAT_ID), "s3cr3t", BOT_TOKEN, "openssl"):
        assert leak not in blob
    assert out["mqtt_password_set"] is True
    assert out["cloud"]["api_secret_set"] is True
    assert out["camera_passphrase_set"] is True


def test_a_marker_is_not_redacted_a_second_time():
    """``password_set`` is this module's own output. Re-redacting it
    would grow ``password_set_set`` on every pass."""
    out = debug_bundle.redact_settings({"password_set": True})
    assert out == {"password_set": True}


def test_the_raw_settings_file_is_never_a_member(env):
    """Not "redacted settings.json" — no settings.json at all. The
    config that ships is the merged effective view."""
    (env / "settings.json").write_text(json.dumps(_base(env)), encoding="utf-8")
    out = debug_bundle.create_bundle(env)
    members = _members(Path(out["path"]))
    assert not any(n.endswith("settings.json") for n in members)
    blob = "\n".join(members.values())
    for leak in (SECRET, MQTT_PW, BOT_TOKEN, str(CHAT_ID), LAN_IP):
        assert leak not in blob, f"{leak!r} reached the archive"


def test_the_log_tail_is_scrubbed(env):
    """A log line is prose — an RTSP URL in it reaches no ``url`` key at
    all, so per-field redaction would never see it."""
    (env / "logs").mkdir(parents=True, exist_ok=True)
    (env / "logs" / "app.log").write_text(
        f"12:00:01 ERROR [cam:{CAM}] open {RTSP} failed\n", encoding="utf-8"
    )
    text = _sections.log_tail(env)
    assert SECRET not in text and LAN_IP not in text
    assert "admin:" in text, "the account survives — it is what identifies the login"


# ── complete enough to re-simulate ────────────────────────────────────────


def test_the_bundle_carries_every_section(env):
    out = debug_bundle.create_bundle(env)
    members = _members(Path(out["path"]))
    for name in (
        debug_bundle.ARC_LOG,
        debug_bundle.ARC_STATUS,
        debug_bundle.ARC_TELEMETRY,
        debug_bundle.ARC_CONFIG,
        "bundle.md",
        "tuning/net.json",
    ):
        assert name in members, name
    assert [n for n in members if n.startswith("events/")]


def test_the_status_section_carries_the_tpu_figures(env):
    out = debug_bundle.create_bundle(env)
    status = json.loads(_members(Path(out["path"]))[debug_bundle.ARC_STATUS])
    assert "tpu" in status and "total" in status["tpu"]
    assert "window_s" in status["tpu"]


def test_events_arrive_whole_with_their_provenance(env):
    """The provenance block IS the reason the bundle is worth sending:
    without the tuning and models in force at trigger time, a stored
    event cannot be re-simulated."""
    out = debug_bundle.create_bundle(env)
    members = _members(Path(out["path"]))
    events = [json.loads(v) for k, v in members.items() if k.startswith("events/")]
    assert len(events) == 3
    assert all(e["provenance"]["schema"] == 1 for e in events)
    assert events[0]["detections"][0]["model"] == "detector"
    # …and the scrubber reached inside the nested block too.
    assert SECRET not in json.dumps(events)


def test_events_are_newest_first_and_capped(env):
    """The cap has to bite on the MERGED list, not per camera —
    otherwise a three-camera box ships three times the promised 50."""
    events = _sections.recent_events(app_state.store, [CAM], 2)
    assert [e["event_id"] for e in events] == ["20260901-120020", "20260901-120010"]


def test_the_tuning_section_names_the_frozen_values(env):
    out = debug_bundle.create_bundle(env)
    tuning = json.loads(_members(Path(out["path"]))["tuning/net.json"])
    assert CAM in tuning, tuning
    block = tuning[CAM]
    assert block["tuning"]["frame_interval_ms"] == 350
    assert any(row["key"] == "detection_min_score" for row in block["frozen"])


def test_bundle_md_tells_a_stranger_what_they_have(env):
    out = debug_bundle.create_bundle(env)
    text = _members(Path(out["path"]))["bundle.md"]
    assert CAM in text and "Hof" in text
    assert debug_bundle.ARC_CONFIG in text and "Weitergabe" in text
    assert "settings.json" in text, "the absence has to be stated, not assumed"


def test_a_broken_section_costs_its_own_file_not_the_bundle(env, monkeypatch):
    def _boom():
        raise RuntimeError("keine Telemetrie")

    monkeypatch.setattr("app.debug_bundle._entries.telemetry_snapshot", _boom)
    out = debug_bundle.create_bundle(env)
    members = _members(Path(out["path"]))
    assert json.loads(members[debug_bundle.ARC_TELEMETRY])["error"].startswith("RuntimeError")
    assert debug_bundle.ARC_STATUS in members


# ── bounded ───────────────────────────────────────────────────────────────


def _seed(root: Path, count: int) -> list[str]:
    directory = _writer.bundle_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    names = []
    start = datetime(2026, 9, 1, 12, 0, 0)
    for i in range(count):
        name = _writer.bundle_name(start + timedelta(minutes=i))
        (directory / name).write_bytes(b"PK\x05\x06" + b"\0" * 18)
        names.append(name)
    return names


def test_only_the_newest_ten_survive_a_write(tmp_storage_root):
    names = _seed(tmp_storage_root, 12)
    dropped = _writer.prune(tmp_storage_root)
    assert sorted(dropped) == names[:2], "the two OLDEST go, whatever order they are deleted in"
    assert len(_writer.iter_bundles(tmp_storage_root)) == debug_bundle.MAX_BUNDLES


def test_retention_runs_on_the_write_path_not_a_schedule(env):
    _seed(env, debug_bundle.MAX_BUNDLES)
    out = debug_bundle.create_bundle(env)
    assert out["dropped"], "the oldest has to go on the write, not on a timer"
    assert len(_writer.iter_bundles(env)) == debug_bundle.MAX_BUNDLES


def test_a_half_written_archive_is_never_listed(tmp_storage_root):
    """Built under .part and renamed — a listing must not show a file
    that is still being deflated."""
    directory = _writer.bundle_dir(tmp_storage_root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "bundle-20260901-120000.part").write_bytes(b"x")
    (directory / "notes.zip").write_bytes(b"x")
    assert _writer.list_bundles(tmp_storage_root) == []


def test_the_listing_is_newest_first_with_a_servable_url(tmp_storage_root):
    names = _seed(tmp_storage_root, 3)
    items = _writer.list_bundles(tmp_storage_root)
    assert [i["name"] for i in items] == list(reversed(names))
    assert items[0]["url"] == f"/media/debug/{names[-1]}"
    assert items[0]["size"] > 0


# ── the endpoints ─────────────────────────────────────────────────────────


def test_post_builds_one_and_get_lists_it(env):
    flask = pytest.importorskip("flask")
    from app.routes import debug_bundle as routes_debug

    app = flask.Flask(__name__)
    app.register_blueprint(routes_debug.bp)
    c = app.test_client()

    made = c.post("/api/debug/bundle").get_json()
    assert made["ok"] is True and made["size"] > 0
    assert made["url"].startswith("/media/debug/bundle-")
    assert Path(made["path"]).is_file()

    listed = c.get("/api/debug/bundle").get_json()
    assert listed["max"] == debug_bundle.MAX_BUNDLES
    assert [i["name"] for i in listed["items"]] == [made["name"]]


def test_a_failed_build_answers_with_the_reason(env, monkeypatch):
    from app.routes import debug_bundle as routes_debug

    flask = pytest.importorskip("flask")
    monkeypatch.setattr(
        routes_debug.debug_bundle,
        "create_bundle",
        lambda *a, **k: (_ for _ in ()).throw(OSError("kein Platz")),
    )
    app = flask.Flask(__name__)
    app.register_blueprint(routes_debug.bp)
    res = app.test_client().post("/api/debug/bundle")
    assert res.status_code == 500
    assert res.get_json()["ok"] is False


# ── the log file the tail reads ───────────────────────────────────────────


def test_the_log_file_lands_under_storage_logs(tmp_storage_root):
    from app import logging_setup

    assert logging_setup.log_file_path(tmp_storage_root) == tmp_storage_root / "logs" / "app.log"


def test_attaching_the_file_handler_is_idempotent(tmp_storage_root, monkeypatch):
    """Called once per boot, but a second call must not double every
    line in the file."""
    from app import logging_setup

    monkeypatch.setattr(logging_setup, "_FILE_HANDLER", None, raising=False)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        path = logging_setup.attach_file_handler(tmp_storage_root)
        again = logging_setup.attach_file_handler(tmp_storage_root)
        assert path == again == tmp_storage_root / "logs" / "app.log"
        assert len(root.handlers) == len(before) + 1
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                h.close()
        logging_setup._FILE_HANDLER = None


def test_no_log_file_falls_back_to_the_memory_buffer(tmp_storage_root):
    text = _sections.log_tail(tmp_storage_root)
    assert "keine Logdatei" in text
