"""Every Netz write is an ADDITIVE merge onto settings.json.

`settings.json` carries the Telegram token, the chat ids and the RTSP
passwords, and it is the most regression-prone file in the project. The
net writes to it on every drag, so the round-trip gets a test rather
than a one-off check: load → modify → save → reload → diff, and only the
expected fields may differ.

The hazard this guards is specific and was live in the first draft: the
cam-edit save path sends `label_thresholds` as a whole nested dict, and
`upsert_camera` replaces nested dicts WHOLESALE. Once the per-class
sliders were removed (D2/D3) the form collected `{}` — so an unrelated
save from the Erkennung tab would have silently wiped every dragged
value on the camera.
"""

from __future__ import annotations

import json

import pytest

from app.settings_store import SettingsStore
from app.thresholds._apply import manual_patch, push_for, spawn_for

CAM = "cam_werkstatt"


def _flat(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flat(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flat(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


@pytest.fixture
def store(tmp_storage_root):
    base = {
        "app": {},
        "storage": {"root": str(tmp_storage_root)},
        "cameras": [
            {
                "id": CAM,
                "name": "Werkstatt",
                "rtsp_url": "rtsp://cam.lan/stream",
                "object_filter": ["person", "cat"],
                "label_thresholds": {"person": 0.45, "cat": 0.55},
                "push_thresholds": {},
            }
        ],
        "telegram": {"token": "<BOT_TOKEN>", "chat_id": "<CHAT_ID>"},
        "mqtt": {},
        "processing": {},
    }
    return SettingsStore(tmp_storage_root / "settings.json", base), base


def test_a_drag_changes_only_the_fields_it_claims_to(store):
    s, base = store
    path = s.path
    before = _flat(json.loads(path.read_text(encoding="utf-8")))

    cam = s.get_camera(CAM)
    patch = manual_patch("person", 62)
    s.upsert_camera(
        {
            **cam,
            "label_thresholds": {**cam["label_thresholds"], **patch["label_thresholds"]},
            "push_thresholds": {**cam["push_thresholds"], **patch["push_thresholds"]},
            "net_pin": {**(cam.get("net_pin") or {}), **patch["net_pin"]},
        }
    )

    after = _flat(json.loads(path.read_text(encoding="utf-8")))
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    # Only the person axis moved. `cat` keeps its 0.55, the token and the
    # chat id are untouched, and nothing else in the document shifted.
    # `manual_patch` carries no timestamp — it stays a pure function of
    # (label, E) so the mapping tests can drive it deterministically.
    # The route stamps `ts` when it writes.
    expected = {
        "cameras[0].label_thresholds.person",
        "cameras[0].push_thresholds.person",
        "cameras[0].net_pin.person.E",
        "cameras[0].net_pin.person.by",
    }
    assert changed == expected, sorted(changed - expected)
    assert after["cameras[0].label_thresholds.cat"] == 0.55
    assert after["cameras[0].label_thresholds.person"] == spawn_for("person", 62)
    assert after["cameras[0].push_thresholds.person"] == push_for("person", 62)
    assert after["telegram.token"] == base["telegram"]["token"]


def test_the_written_values_survive_a_reload(store, tmp_storage_root):
    s, base = store
    cam = s.get_camera(CAM)
    patch = manual_patch("cat", 20)
    s.upsert_camera(
        {
            **cam,
            "label_thresholds": {**cam["label_thresholds"], **patch["label_thresholds"]},
            "push_thresholds": patch["push_thresholds"],
            "net_pin": patch["net_pin"],
        }
    )
    fresh = SettingsStore(tmp_storage_root / "settings.json", base)
    reloaded = fresh.get_camera(CAM)
    assert reloaded["label_thresholds"]["cat"] == spawn_for("cat", 20)
    assert reloaded["push_thresholds"]["cat"] == push_for("cat", 20)
    assert reloaded["net_pin"]["cat"]["E"] == 20
    # E 20 is stricter than factory, so the bar must have gone UP.
    assert reloaded["push_thresholds"]["cat"] > 0.80


def test_a_camera_save_that_omits_the_net_keys_leaves_them_alone(store):
    """The D-removal hazard, pinned. cam-edit no longer renders the
    threshold inputs; a save from that tab must be a no-op for them."""
    s, _base = store
    cam = s.get_camera(CAM)
    patch = manual_patch("person", 70)
    s.upsert_camera({**cam, **patch})
    # Now an unrelated edit from the Erkennung tab, shaped like the real
    # payload: it echoes label_thresholds back and never mentions
    # push_thresholds or net_pin at all.
    current = s.get_camera(CAM)
    s.upsert_camera(
        {
            "id": CAM,
            "name": "Werkstatt",
            "rtsp_url": "rtsp://cam.lan/stream",
            "frame_interval_ms": 500,
            "label_thresholds": current["label_thresholds"],
        }
    )
    after = s.get_camera(CAM)
    assert after["frame_interval_ms"] == 500
    assert after["label_thresholds"]["person"] == spawn_for("person", 70)
    assert after["push_thresholds"]["person"] == push_for("person", 70)
    assert after["net_pin"]["person"]["E"] == 70


def test_net_auto_false_survives_the_default_backfill(store, tmp_storage_root):
    """`net_auto` is a boolean whose False is meaningful. It is kept out
    of CAMERA_THRESHOLD_KEY_DEFAULTS on purpose — that map is applied
    with `cam.get(key) or default`, which would resurrect it as True."""
    s, base = store
    s.upsert_camera({**s.get_camera(CAM), "net_auto": False})
    fresh = SettingsStore(tmp_storage_root / "settings.json", base)
    assert fresh.get_camera(CAM)["net_auto"] is False


def test_the_migration_lands_the_net_keys_on_an_old_camera(store):
    s, _base = store
    cam = s.get_camera(CAM)
    for key in ("role", "net_pin", "net_adapted", "net_auto"):
        assert key in cam
    assert cam["role"] == "security"  # the safe direction
    assert cam["net_auto"] is True


def test_the_runtime_dedupe_map_is_bounded(store):
    """`runtime.event_feedback` grows one entry per judged event, and
    without a cap it grows settings.json forever."""
    s, _base = store
    for i in range(600):
        s.runtime_set_subkey_lru("event_feedback", f"evt-{i}", {"verdict": "ok"}, 500)
    kept = s.runtime_get("event_feedback")
    assert len(kept) == 500
    # LRU: the oldest went, the newest stayed.
    assert "evt-0" not in kept
    assert "evt-599" in kept
