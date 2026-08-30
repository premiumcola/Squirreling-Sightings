"""Camera-WIDE setting changes land in the Verlauf too.

„Ich brauch eine Historie für die Kamera, wie die Einstellungen der
Reihe nach geändert wurden … welcher Wert wie verändert wurde."

The gap this closes: ``PATCH /api/netz/<cam>/axes`` has archived every
per-class threshold drag since the archive existed, while
``PATCH /api/cameras/<id>/detection-tuning`` — Analyse-Intervall,
Nachlauf, Gnadenfrist, IoU-Schwelle, ROI-Modus, Spur-Start,
Doppel-Sperre, the tracker presets, the Ghost-Spuren switch — archived
nothing at all. Half the history was missing and the archive looked
complete.

Three properties carry it, and each one has a way of failing silently:

* one record per CHANGED field, never per request;
* a value that did not move writes NOTHING (the sentinel traps: absent
  vs. 0.0 vs. "system default" are the same value, and `frame_interval_ms`
  has a real default of 350 that an absent key must not read as 0);
* the list comes back in TIME order — manual-change records live in the
  ``unknown`` month folder, which sorted ahead of every real month.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from flask import Flask

from app import app_state, net_archive
from app.routes import cameras as cameras_routes
from app.settings_store import SettingsStore

CAM = "cam_werkstatt"

_SETTINGS_AXES_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_settings_axes.js"
).read_text(encoding="utf-8")


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
                "object_filter": ["person", "cat"],
                "role": "security",
                "frame_interval_ms": 350,
            }
        ],
        "telegram": {"push": {}},
        "mqtt": {},
        "processing": {},
    }
    settings = SettingsStore(tmp_storage_root / "settings.json", base)
    monkeypatch.setattr(app_state, "settings", settings)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root)
    monkeypatch.setattr(app_state, "runtimes", {})
    app = Flask(__name__)
    app.register_blueprint(cameras_routes.bp)
    with app.test_client() as c:
        yield c


def _patch(client, **fields):
    res = client.patch(f"/api/cameras/{CAM}/detection-tuning", json=fields)
    assert res.status_code == 200, res.get_json()
    return res.get_json()


def _records(root):
    return net_archive.list_records(root)["items"]


# ── one record per changed field ──────────────────────────────────────


def test_a_camera_wide_change_is_archived(tmp_storage_root, client):
    _patch(client, frame_interval_ms=500)
    rows = _records(tmp_storage_root)
    assert len(rows) == 1
    row = rows[0]
    assert row["kind"] == net_archive.KIND_TUNING
    assert row["cam_name"] == "Werkstatt"
    assert row["field_de"] == "Analyse-Intervall"
    assert "350 ms" in row["reason_de"] and "500 ms" in row["reason_de"]
    assert row["has_frame"] is False


def test_one_request_touching_four_fields_writes_four_records(tmp_storage_root, client):
    """„welcher Wert wie verändert wurde" — a tracker preset moves four
    fields, and one lumped record cannot answer that question four times."""
    _patch(
        client,
        track_spawn_min_score=0.5,
        track_continue_min_score=0.2,
        track_miss_grace_seconds=6,
        track_iou_match_threshold=0.2,
    )
    rows = _records(tmp_storage_root)
    assert len(rows) == 4
    assert {r["field_de"] for r in rows} == {
        "Spur-Start",
        "Spur-Fortsetzung",
        "Gnadenfrist",
        "IoU-Schwelle",
    }


def test_a_value_that_did_not_move_is_not_a_change(tmp_storage_root, client):
    _patch(client, frame_interval_ms=500)
    _patch(client, frame_interval_ms=500)
    assert len(_records(tmp_storage_root)) == 1, "a no-op save wrote a history entry"


def test_the_system_default_sentinel_is_not_a_change(tmp_storage_root, client):
    """0.0 means "use the system default" for almost every field here, so
    a first save that sends 0.0 for an absent key changed nothing. The two
    fields with a REAL default (frame_interval_ms 350, motion_sensitivity
    0.5) must not read an absent key as 0 either."""
    _patch(
        client,
        track_miss_grace_seconds=0,
        track_iou_match_threshold=0,
        roi_mode="off",
        track_filter_ghosts=True,
        motion_sensitivity=0.5,
        frame_interval_ms=350,
    )
    assert _records(tmp_storage_root) == []


def test_the_ghost_switch_is_archived_in_words(tmp_storage_root, client):
    _patch(client, track_filter_ghosts=False)
    (row,) = _records(tmp_storage_root)
    assert row["field_de"] == "Ghost-Spuren ausblenden"
    assert "von an auf aus" in row["reason_de"], row["reason_de"]


def test_the_roi_mode_is_archived_in_german(tmp_storage_root, client):
    _patch(client, roi_mode="2x2")
    (row,) = _records(tmp_storage_root)
    assert "von Aus auf 2×2" in row["reason_de"], row["reason_de"]


def test_a_rejected_value_is_not_archived(tmp_storage_root, client):
    res = client.patch(f"/api/cameras/{CAM}/detection-tuning", json={"roi_mode": "4x4"})
    assert res.status_code == 400
    assert _records(tmp_storage_root) == []


def test_an_archive_failure_never_fails_the_save(tmp_storage_root, client, monkeypatch):
    """A camera setting must save even when the history cannot be written
    — the archive is best-effort throughout (net_archive/_io.py)."""

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(net_archive, "record_tuning_changes", _boom)
    body = _patch(client, frame_interval_ms=700)
    assert body["ok"] is True
    assert body["effective"]["frame_interval_ms"] == 700


# ── the Verlauf reads in time order ───────────────────────────────────


def test_the_list_comes_back_newest_first_across_record_kinds(tmp_storage_root, client):
    """Manual per-class changes carry an event_id starting with `netz-`,
    which `_month_of` cannot date — they land in the `unknown` month
    folder, and reverse-sorted that folder came before every real month.
    The whole change history therefore sat above the whole question
    history whatever the clock said."""
    net_archive.record_net_change(
        tmp_storage_root,
        event_id="netz-old-00-person",
        cam_id=CAM,
        cam_name="Werkstatt",
        label="person",
        e_before=50,
        e_after=60,
        push_before=0.85,
        push_after=0.79,
        net_state={},
        rails={},
    )
    rec = net_archive.get_record(tmp_storage_root, "netz-old-00-person")
    rec["ts"] = "2020-01-01T00:00:00"
    net_archive._io.save_record(tmp_storage_root, "netz-old-00-person", rec)

    _patch(client, frame_interval_ms=500)
    rows = _records(tmp_storage_root)
    assert len(rows) == 2
    assert rows[0]["kind"] == net_archive.KIND_TUNING, "the 2020 record sorted above today's"
    assert rows[1]["ts"].startswith("2020")


def test_a_camera_wide_record_files_under_its_own_month(tmp_storage_root, client):
    """Date-leading event_id, so retention and the month walk see it."""
    _patch(client, frame_interval_ms=500)
    months = {p.parent.name for p in (tmp_storage_root / "net_archive").rglob("*.json")}
    assert months and "unknown" not in months, months


def test_the_history_filters_to_one_camera(tmp_storage_root, client):
    """What the card's Verlauf button does: the same archive, `cam=`."""
    _patch(client, frame_interval_ms=500)
    assert len(net_archive.list_records(tmp_storage_root, cam=CAM)["items"]) == 1
    assert net_archive.list_records(tmp_storage_root, cam="cam_other")["items"] == []


# ── the German labels stay a mirror ───────────────────────────────────


def test_every_radar_axis_has_a_german_name_on_the_python_side():
    """`TUNING_LABELS_DE` mirrors `TUNE_LABELS_DE` in
    netz/_settings_axes.js. A field added to the chart without a German
    name here archives as its raw key — readable to nobody."""
    m = re.search(r"TUNE_AXIS_ORDER\s*=\s*\[(.*?)\]", _SETTINGS_AXES_JS, re.DOTALL)
    assert m
    for key in re.findall(r"'([a-z_]+)'", m.group(1)):
        assert key in net_archive.TUNING_LABELS_DE, f"{key}: no German name for the Verlauf"


def test_the_german_names_agree_with_the_frontend_wording():
    m = re.search(r"TUNE_LABELS_DE\s*=\s*\{(.*?)\n\}", _SETTINGS_AXES_JS, re.DOTALL)
    assert m
    js = dict(re.findall(r"(\w+):\s*'([^']+)'", m.group(1)))
    for key, de in js.items():
        assert net_archive.TUNING_LABELS_DE.get(key) == de, (
            f"{key}: Verlauf says {net_archive.TUNING_LABELS_DE.get(key)!r}, "
            f"the panel says {de!r}"
        )


# ── the frontend reaches it ───────────────────────────────────────────

_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz"


def test_each_card_carries_a_history_button_wired_to_its_own_camera():
    cards = (_JS / "_cards.js").read_text(encoding="utf-8")
    index = (_JS / "index.js").read_text(encoding="utf-8")
    assert "data-netz-hist" in cards, "no per-camera Verlauf button on the card"
    assert "onHistory(camId)" in cards, "the button does not carry its own camera id"
    assert "openCameraHistory" in index, "nothing routes the card button to the archive"
    assert "archiveFilter = { cam: camId" in index, "the archive is not filtered to the camera"


def test_the_detail_sheet_omits_the_net_block_for_a_setting_change():
    """A camera-wide change has no per-class state — an empty radar under
    a „Netz zu diesem Zeitpunkt" heading, with a restore button that can
    only answer 400, is worse than leaving the section out."""
    src = (_JS / "_archive_detail.js").read_text(encoding="utf-8")
    assert "function _netHtml(" in src
    assert "Object.keys(rec.net_state || {}).length" in src
