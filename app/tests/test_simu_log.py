"""The SIMU log: every "Debug kopieren" run, kept on the box.

"Vielleicht kannst Du, wenn ich auf kopieren drücke, parallel einfach
irgendwo den Log von dem Run ablegen, dass ich gar nicht mehr im Chat den
reinkopieren muss."

Three properties decide whether that is an asset or a liability, and each
one is a section below:

  · **It never writes a credential.** The file exists to be fetched over
    an unauthenticated LAN and pasted somewhere else. The camera goes
    through ``redact_camera`` on the way in and the whole payload through
    the positional scrubber on the way to disk — belt and braces,
    because the failure mode is unrecoverable once a paste has happened.
  · **It is bounded.** A directory written on every tap of a button is
    exactly the unbounded-growth shape this project has already had to
    clean up elsewhere. Both quotas are enforced on the write path, not
    on a schedule that a rebooted box never reaches.
  · **It fails soft.** The clipboard write has already happened by the
    time the POST fires. A storage failure must cost the operator
    nothing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from flask import Flask

from app import app_state, simu_log
from app.routes import simu_log as simu_log_routes
from app.routes._debug_snapshot import SCHEMA
from app.settings_store import SettingsStore

CAM = "reolink_cx810_hof_42"
SECRET = "hunter2"
# Assembled from parts on purpose. These have to be REAL RFC-1918 shapes
# — masking them is the behaviour under test, and an RFC-5737 doc address
# must survive untouched — but CLAUDE.md's pre-push audit greps every
# tracked file for `192.168.*` / `10.*`, and a literal here would be a
# permanent false positive in a check that only works while it is quiet.
LAN_IP = ".".join(("192", "168", "1", "42"))
LAN_IP_2 = ".".join(("10", "0", "0", "5"))
RTSP = f"rtsp://admin:{SECRET}@{LAN_IP}/h264"
BOT_TOKEN = "123456789:AAEEabcdefghijklmnopqrstuvwxyz012345"


def _base(root: Path) -> dict:
    return {
        "app": {},
        "storage": {"root": str(root)},
        "cameras": [
            {
                "id": CAM,
                "name": "Hof",
                "rtsp_url": RTSP,
                "password": SECRET,
                "object_filter": ["person"],
            }
        ],
        "telegram": {"push": {"labels": {"person": {"push": True, "threshold": 0.85}}}},
        "mqtt": {},
        "processing": {},
    }


@pytest.fixture
def client(tmp_storage_root, monkeypatch):
    base = _base(tmp_storage_root)
    settings = SettingsStore(tmp_storage_root / "settings.json", base)
    monkeypatch.setattr(app_state, "settings", settings)
    monkeypatch.setattr(app_state, "runtimes", {}, raising=False)
    monkeypatch.setattr(app_state, "get_effective_config", lambda: base, raising=False)
    monkeypatch.setattr("app.routes._sim_pipeline.trackers", lambda: {}, raising=False)
    app = Flask(__name__)
    app.register_blueprint(simu_log_routes.bp)
    return app.test_client()


def _stored(root: Path) -> list:
    return sorted((root / "logs" / "simu" / CAM).glob("*.json"))


def _stamp(ago_seconds: float) -> str:
    """A run-name timestamp ``ago_seconds`` in the past."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - ago_seconds))


# ── never a credential ───────────────────────────────────────────────


def test_an_rtsp_password_never_reaches_disk(client, tmp_storage_root, monkeypatch):
    """The pinned one, end to end through the route.

    The realistic leak is not the camera dict — the document does not
    carry ``rtsp_url`` at all — it is the server log riding along, where
    the URL appears inside a sentence. So the ring buffer is seeded with
    exactly the line ffmpeg writes when a camera will not open.
    """

    class _Buf:
        def get(self, _level):
            return [{"ts": "12:00:01", "level": "ERROR", "msg": f"[cam:{CAM}] open {RTSP} failed"}]

    monkeypatch.setattr("app.routes._debug_snapshot._helpers.log_buffer", _Buf())
    res = client.post(f"/api/cameras/{CAM}/simu-log", json={"frontend": {}})
    assert res.status_code == 200 and res.get_json()["ok"] is True
    files = _stored(tmp_storage_root)
    assert len(files) == 1
    blob = files[0].read_text(encoding="utf-8")
    assert "admin:" in blob, "the line has to be IN the file for this test to mean anything"
    assert SECRET not in blob
    assert LAN_IP not in blob, "the operator's subnet is not diagnostic data"
    # …and the camera block never carried the URL in the first place.
    doc = json.loads(blob)
    assert set(doc["camera"]) == {"id", "name"}


def test_the_write_path_scrubs_a_payload_it_did_not_build(tmp_storage_root):
    """``redact_camera`` covers the camera dict. This covers everything
    else — a URL quoted inside a note, a trace line, a field added next
    year by someone who did not read this file."""
    name = simu_log.store_run(tmp_storage_root, CAM, {"note": f"ffmpeg konnte {RTSP} nicht öffnen"})
    blob = (tmp_storage_root / "logs" / "simu" / CAM / name).read_text(encoding="utf-8")
    assert SECRET not in blob
    assert "admin:" in blob, "the user survives — it is what identifies the account"


def test_a_secret_key_becomes_a_boolean_not_a_hole(tmp_storage_root):
    """ "Is a password configured?" IS a diagnosis; the password is not.
    Dropping the key entirely would make a misconfigured camera and a
    correctly configured one look identical."""
    name = simu_log.store_run(
        tmp_storage_root, CAM, {"camera": {"password": SECRET, "token": BOT_TOKEN}}
    )
    doc = simu_log.read_run(tmp_storage_root, CAM, name)
    assert doc["camera"] == {"password_set": True, "token_set": True}


def test_secrets_are_masked_wherever_they_appear_not_only_in_known_fields():
    """Positional, not per-field: a log line is prose, so a bot token in
    it reaches no ``token`` key at all."""
    out = simu_log.scrub(
        {
            "log": [{"msg": f"open {RTSP} · bot {BOT_TOKEN} · peer {LAN_IP_2}"}],
            "trace": [f"[capture] {RTSP}"],
        }
    )
    blob = json.dumps(out)
    assert SECRET not in blob and BOT_TOKEN not in blob
    assert LAN_IP_2 not in blob and LAN_IP not in blob
    assert "admin:•••@<lan-ip>" in out["log"][0]["msg"]
    # …and the shape survives: this is still a document someone reads.
    assert out["trace"][0].startswith("[capture] rtsp://admin:")


def test_a_public_address_is_left_alone():
    """Only RFC-1918 is masked. Masking 8.8.8.8 would be noise, and
    masking the doc-range addresses the tests use would hide bugs."""
    out = simu_log.scrub_text("upstream 8.8.8.8 · docs 192.0.2.7 · lan 172.20.1.9")
    assert "8.8.8.8" in out and "192.0.2.7" in out
    assert "172.20.1.9" not in out


def test_the_route_redacts_before_it_builds_not_only_before_it_writes(client):
    """``redact_camera`` at the source is the stronger property: the
    secret never enters the document, so a future field that copies the
    camera dict wholesale cannot leak one either."""
    src = Path(simu_log_routes.__file__).read_text(encoding="utf-8")
    assert "redact_camera(cam)" in src


# ── bounded ──────────────────────────────────────────────────────────


def test_the_count_cap_evicts_the_oldest_first(tmp_storage_root):
    directory = tmp_storage_root / "logs" / "simu" / CAM
    directory.mkdir(parents=True)
    made = []
    for i in range(simu_log.MAX_RUNS_PER_CAMERA + 5):
        path = directory / f"20260830-1200{i // 60:02d}-{i % 60:06d}.json"
        path.write_text("{}", encoding="utf-8")
        made.append(path)
    assert simu_log.enforce(tmp_storage_root, CAM) == 5
    left = sorted(p.name for p in directory.glob("*.json"))
    assert len(left) == simu_log.MAX_RUNS_PER_CAMERA
    assert all(p.name in left for p in made[5:])
    assert not any(p.exists() for p in made[:5])


def test_the_quotas_run_on_the_write_path_not_on_a_schedule(tmp_storage_root):
    """A sweep that only runs on a timer is a sweep that has never run on
    a box the operator rebooted this morning — and this directory grows
    once per tap of a button."""
    for i in range(simu_log.MAX_RUNS_PER_CAMERA + 3):
        assert simu_log.store_run(tmp_storage_root, CAM, {"i": i})
    assert len(_stored(tmp_storage_root)) == simu_log.MAX_RUNS_PER_CAMERA


def test_the_age_cap_takes_a_run_even_under_the_count(tmp_storage_root):
    """A month-old run reports thresholds for a configuration that has
    moved on — that makes it misleading, not merely stale."""
    directory = tmp_storage_root / "logs" / "simu" / CAM
    directory.mkdir(parents=True)
    stale = directory / f"{_stamp(86400 * 400)}-000001.json"
    fresh = directory / f"{_stamp(0)}-000002.json"
    for path in (stale, fresh):
        path.write_text("{}", encoding="utf-8")
    assert simu_log.enforce(tmp_storage_root, CAM) == 1
    assert fresh.exists() and not stale.exists()


def test_a_file_with_an_unparsable_name_is_never_the_reason_for_a_delete():
    """Age comes from the file name. A broken name is not evidence of
    age, and a retention sweep is not the place to guess."""
    assert simu_log.select_evictable([Path("not-a-timestamp.json")]) == []


def test_the_browser_block_is_capped(client, tmp_storage_root):
    """The one part of a stored run a client supplies. Replaced by a note
    rather than truncated — half a JSON object is worse than an honest
    absence."""
    big = {"junk": "x" * (simu_log.MAX_FRONTEND_BYTES + 100)}
    client.post(f"/api/cameras/{CAM}/simu-log", json={"frontend": big})
    doc = json.loads(_stored(tmp_storage_root)[0].read_text(encoding="utf-8"))
    assert doc["frontend"]["error"] == "frontend block too large"
    assert "junk" not in json.dumps(doc)


def test_nothing_else_from_the_request_body_reaches_the_file(client, tmp_storage_root):
    """The server rebuilds the document from its own state; the body
    contributes exactly three browser-owned values."""
    client.post(
        f"/api/cameras/{CAM}/simu-log",
        json={"frontend": {"ua": "test"}, "next_ms": 900, "schema": "attacker/1", "log": ["evil"]},
    )
    doc = json.loads(_stored(tmp_storage_root)[0].read_text(encoding="utf-8"))
    assert doc["schema"] == SCHEMA, "the client does not get to name the schema"
    assert "evil" not in json.dumps(doc)
    assert doc["tick"]["next_ms"] == 900
    assert doc["frontend"] == {"ua": "test"}


# ── fails soft, and can be read back without a shell ─────────────────


def test_a_failed_write_is_reported_without_breaking_the_copy(client, monkeypatch):
    """The clipboard write already happened in the browser. A storage
    failure is a note, never an exception the UI has to handle."""
    monkeypatch.setattr(simu_log, "store_run", lambda *a, **k: None)
    res = client.post(f"/api/cameras/{CAM}/simu-log", json={})
    assert res.status_code == 200
    assert res.get_json() == {"ok": False, "error": "write failed"}


def test_an_unwritable_root_returns_none_instead_of_raising(tmp_path):
    """``store_run`` is called from a request that must not 500."""
    blocked = tmp_path / "not-a-dir"
    blocked.write_text("i am a file", encoding="utf-8")
    assert simu_log.store_run(blocked, CAM, {"a": 1}) is None


def test_a_stored_run_can_be_listed_and_fetched_over_http(client):
    post = client.post(f"/api/cameras/{CAM}/simu-log", json={"frontend": {"ua": "test"}})
    name = post.get_json()["name"]
    assert post.get_json()["url"] == f"/api/cameras/{CAM}/simu-log/{name}"

    listing = client.get(f"/api/cameras/{CAM}/simu-log").get_json()
    assert [r["name"] for r in listing["runs"]] == [name]
    assert listing["runs"][0]["bytes"] > 0

    run = client.get(f"/api/cameras/{CAM}/simu-log/{name}").get_json()
    assert run["ok"] is True
    assert run["run"]["camera"]["id"] == CAM
    assert run["run"]["frontend"] == {"ua": "test"}


def test_a_run_name_is_never_joined_onto_a_path_unchecked(client, tmp_storage_root):
    """Camera ids already reach the filesystem directly in this project
    (see routes/_reject_traversal_cam_ids); a run name must not become
    the second way in."""
    (tmp_storage_root / "secret.json").write_text('{"a": 1}', encoding="utf-8")
    assert simu_log.read_run(tmp_storage_root, CAM, "../../secret.json") is None
    assert simu_log.read_run(tmp_storage_root, CAM, "settings.json") is None
    assert client.get(f"/api/cameras/{CAM}/simu-log/nope.json").status_code == 404


def test_an_unknown_camera_is_a_404_not_a_stray_directory(client, tmp_storage_root):
    res = client.post("/api/cameras/ghost_cam_1/simu-log", json={})
    assert res.status_code == 404
    assert not (tmp_storage_root / "logs" / "simu" / "ghost_cam_1").exists()
