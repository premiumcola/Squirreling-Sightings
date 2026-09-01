"""``event["provenance"]`` — the settings snapshot a re-simulation needs.

Pure-builder tests: no camera thread, no model file bigger than a few
bytes. The stub detectors carry only the attributes ``describe_model``
reads (``mode`` / ``_cpu_mode`` / ``reason`` / ``active_model_path``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.camera_runtime._recording._provenance import (  # noqa: E402
    PROVENANCE_SCHEMA,
    ProvenanceMixin,
    build_provenance,
)
from app.detect_setup import build_detection_setup  # noqa: E402
from app.detectors import STAGE_BIRD, STAGE_DETECTOR, Detection  # noqa: E402
from app.detectors._describe import describe_backend, model_fingerprint  # noqa: E402
from app.detectors._postprocess import ssd_snapshot, to_detections  # noqa: E402
from app.net_archive._tuning import TUNING_LABELS_DE  # noqa: E402
from app.tracker_core import Track  # noqa: E402


@dataclass
class _Stage:
    mode: str = "none"
    _cpu_mode: bool = False
    reason: str = "disabled"
    active_model_path: str | None = None


_CAM = {
    "name": "Garten",
    "role": "wildlife",
    "alarm_profile": "quiet",
    "detection_trigger": "motion_and_objects",
    "resolution": "1920x1080",
    "frame_interval_ms": 200,
    "track_spawn_min_score": 0.6,
    "track_filter_ghosts": False,
    "roi_mode": "2x2",
    "object_filter": ["bird", "cat"],
    "excluded_classes": ["dog"],
    "label_thresholds": {"bird": 0.42},
    "post_motion_tail_s": 4,
    "zones": [{"id": "z1", "points": [[0, 0], [10, 0], [10, 10]]}],
    "masks": [{"points": [[5, 5], [6, 5], [6, 6]]}],
}
_GLOBAL = {"processing": {"pre_motion_seconds": 2.5, "motion": {"frame_interval_ms": 150}}}
_TS = datetime(2026, 8, 31, 14, 3, 7, tzinfo=timezone(timedelta(hours=2), "CEST"))


def _build(tmp_path, **kw):
    model = tmp_path / "coco_edgetpu.tflite"
    model.write_bytes(b"model-bytes")
    det = _Stage("coral", True, "ok", str(model))
    setup = build_detection_setup("cam1", _CAM, roi_mode="2x2", global_cfg=_GLOBAL)
    args = dict(
        cam_id="cam1",
        cam_cfg=_CAM,
        global_cfg=_GLOBAL,
        setup=setup,
        roi_mode="2x2",
        detector=det,
        bird=_Stage("cpu", True, "cpu_requested", None),
        wildlife=None,
        build_info={"commit": "abc1234", "date": "2026-08-30", "count": 42},
        analysed_fps=4.87,
        source_fps=25.0,
        captured_at=_TS,
    )
    args.update(kw)
    return build_provenance(**args)


def test_schema_time_zone_and_build(tmp_path):
    p = _build(tmp_path)
    assert p["schema"] == PROVENANCE_SCHEMA
    assert p["captured_at"] == "2026-08-31T14:03:07+02:00"
    assert p["timezone"] == {"name": "CEST", "utc_offset": "+0200"}
    assert p["build"] == {"commit": "abc1234", "date": "2026-08-30", "count": 42}


def test_camera_block_carries_role_and_profile(tmp_path):
    cam = _build(tmp_path)["camera"]
    assert cam == {
        "id": "cam1",
        "name": "Garten",
        "role": "wildlife",
        "alarm_profile": "quiet",
        "detection_trigger": "motion_and_objects",
        "resolution": "1920x1080",
    }


def test_tuning_lists_every_spoke_even_when_unset(tmp_path):
    tuning = _build(tmp_path)["tuning"]
    for key in TUNING_LABELS_DE:
        assert key in tuning, key
    assert tuning["track_spawn_min_score"] == 0.6
    assert tuning["track_miss_grace_seconds"] is None
    assert tuning["track_filter_ghosts"] is False
    assert tuning["label_thresholds"] == {"bird": 0.42}
    assert tuning["net_pin"] is None


def test_effective_is_the_resolved_setup(tmp_path):
    eff = _build(tmp_path)["effective"]
    assert "camera_id" not in eff
    assert eff["roi_mode"] == "2x2"
    assert eff["spawn_default"] == 0.6
    assert eff["object_filter"] == ["bird", "cat"]
    assert eff["excluded_classes"] == ["dog"]
    assert eff["label_thresholds"] == {"bird": 0.42}
    assert eff["trigger_mode"] == "motion_and_objects"
    assert eff["track_filter_ghosts"] is False
    assert eff["floor"] > 0


def test_effective_without_setup_still_names_the_roi_mode(tmp_path):
    assert _build(tmp_path, setup=None)["effective"] == {"roi_mode": "2x2"}


def test_zones_and_masks_keep_ids_polygons_and_a_signature(tmp_path):
    p = _build(tmp_path)
    assert p["zones"]["count"] == 1
    assert p["zones"]["ids"] == ["z1"]
    assert p["zones"]["polygons"] == _CAM["zones"]
    assert len(p["zones"]["signature"]) == 12
    assert p["masks"]["ids"] == ["0"]
    assert p["masks"]["signature"] != p["zones"]["signature"]
    empty = _build(tmp_path, cam_cfg={**_CAM, "zones": []})["zones"]
    assert empty == {"count": 0, "ids": [], "signature": None, "polygons": []}


def test_models_name_device_api_file_and_hash(tmp_path):
    models = _build(tmp_path)["models"]
    det = models["detector"]
    assert det["device"] == "tpu"
    assert det["api"] == "tflite-delegate"
    assert det["file"] == "coco_edgetpu.tflite"
    assert len(det["sha256"]) == 12
    assert models["bird_classifier"] == {
        "device": "cpu",
        "api": "tflite-cpu",
        "mode": "cpu",
        "reason": "cpu_requested",
        "file": None,
        "sha256": None,
    }
    assert models["wildlife_classifier"]["device"] == "off"
    assert "wildlife_inat" not in models
    assert models["tpu_active"] is True


def test_tpu_active_false_when_everything_runs_on_cpu(tmp_path):
    models = _build(tmp_path, detector=_Stage("cpu", True, "cpu_fallback:no_tpu"))["models"]
    assert models["tpu_active"] is False


def test_timing_resolves_pre_post_roll_interval_and_fps(tmp_path):
    t = _build(tmp_path)["timing"]
    assert t == {
        "pre_roll_s": 2.5,
        "post_roll_s": 4.0,
        "analysis_interval_ms": 200.0,
        "analysed_fps": 4.87,
        "source_fps": 25.0,
    }
    inherited = _build(tmp_path, cam_cfg={**_CAM, "frame_interval_ms": 0})["timing"]
    assert inherited["analysis_interval_ms"] == 150.0


def test_snapshot_is_json_serialisable(tmp_path):
    import json

    json.dumps(_build(tmp_path))


# ── describe_backend / model_fingerprint ──────────────────────────────────


def test_describe_backend_matrix():
    assert describe_backend(_Stage("coral", False, "ok"))["api"] == "pycoral"
    assert describe_backend(_Stage("coral", True, "ok"))["api"] == "tflite-delegate"
    assert describe_backend(_Stage("cpu", True, "x")) == {
        "device": "cpu",
        "api": "tflite-cpu",
        "mode": "cpu",
        "reason": "x",
    }
    assert describe_backend(None)["device"] == "off"


def test_model_fingerprint_follows_the_file_content(tmp_path):
    assert model_fingerprint(None) is None
    assert model_fingerprint(tmp_path / "missing.tflite") is None
    f = tmp_path / "m.tflite"
    f.write_bytes(b"one")
    first = model_fingerprint(f)
    assert len(first) == 12
    f.write_bytes(b"two-bytes")
    assert model_fingerprint(f) != first


# ── ProvenanceMixin ───────────────────────────────────────────────────────


class _Runtime(ProvenanceMixin):
    camera_id = "cam1"
    cfg = _CAM
    global_cfg = _GLOBAL
    detector = _Stage("cpu", True, "cpu_requested")
    _main_fps = 3.0
    _source_fps = 15.0

    def _effective_roi_mode(self):
        return "roi"


def test_mixin_reads_the_runtime_attributes():
    p = _Runtime()._build_provenance_snapshot()
    assert p["camera"]["id"] == "cam1"
    assert p["effective"] == {"roi_mode": "roi"}
    assert p["timing"]["analysed_fps"] == 3.0
    assert p["timing"]["source_fps"] == 15.0
    assert "commit" in p["build"]


def test_mixin_never_raises_into_the_event_writer():
    class Broken(_Runtime):
        def _effective_roi_mode(self):
            raise RuntimeError("boom")

    assert Broken()._build_provenance_snapshot() is None


# ── the `model` stage on detections and tracks ────────────────────────────


def test_detection_to_dict_carries_the_stage():
    d = Detection(label="bird", score=0.9, bbox=(0, 0, 1, 1), model=STAGE_BIRD)
    assert d.to_dict()["model"] == "bird_classifier"
    assert Detection(label="x", score=0.1, bbox=(0, 0, 1, 1)).to_dict()["model"] is None


def test_postprocess_stamps_detector_and_undoes_the_letterbox():
    snap = ssd_snapshot(
        [[0.0, 0.0, 0.5, 0.5], [0.0, 0.0, 1.0, 1.0]],
        [0, 1],
        [0.9, 0.1],
        in_w=100,
        in_h=100,
        threshold=0.5,
    )
    assert len(snap) == 1
    dets = to_detections(
        snap,
        frame_hw=(50, 50),
        scale=2.0,
        pad_x=0.0,
        pad_y=0.0,
        labels={0: "cat"},
        region_filter=True,
    )
    assert len(dets) == 1
    assert dets[0].label == "cat"
    assert dets[0].bbox == (0, 0, 25, 25)
    assert dets[0].model == STAGE_DETECTOR


def test_track_remembers_the_stage_of_its_last_detect_sample():
    tr = Track("t1", "bird", 0)
    box = {"x1": 0, "y1": 0, "x2": 10, "y2": 10}
    assert tr.to_dict()["model"] is None
    tr.add_sample(0, 0.0, box, 0.8, "detect", "bird", STAGE_DETECTOR)
    assert tr.model == STAGE_DETECTOR
    tr.add_sample(1, 0.2, box, 0.8, "detect", "bird", STAGE_BIRD)
    tr.add_sample(2, 0.4, box, None, "predicted")
    assert tr.to_dict()["model"] == STAGE_BIRD
