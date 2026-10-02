"""O17 · Shared pytest fixtures.

Pulled out of individual test files so the next test that needs a
``tmp_storage_root`` / ``settings_store`` / ``sample_event`` doesn't
re-roll the boilerplate. Adding new fixtures here is preferable to
copy-pasting a 15-line helper at the top of yet another test file.

The fixtures intentionally stay minimal — each test pulls only the
slice it needs and overrides defaults per-test. The goal is "less
boilerplate" not "leak shared state across tests".
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _contain_tempfile(tmp_path_factory):
    """Every `tempfile` call during the tests lands under pytest's basetemp.

    Tests use `tmp_path` / `tmp_path_factory`; this is the safety net for
    whatever does not — a helper deep in the app that calls `mkstemp`, a
    library that calls `gettempdir()`. Pointing `tempfile.tempdir` here
    means such a file is created inside pytest's basetemp, of which pytest
    keeps only the last three runs, instead of in the devbox's shared /tmp,
    where 346 507 never-removed `tmp*` entries (18 GB, from several
    projects) had piled up by 2026-10-02 and were filling the Unraid
    docker.img.

    Not covered: a `tempfile` call at IMPORT time, which runs during
    collection, before any fixture. There is none left —
    test_rebuild_runtimes.py was the one, see its header.
    """
    previous = tempfile.tempdir
    tempfile.tempdir = str(tmp_path_factory.mktemp("tempfile"))
    yield
    tempfile.tempdir = previous


@pytest.fixture
def tmp_storage_root(tmp_path: Path) -> Path:
    """Fresh on-disk storage tree under pytest's tmp_path. Carries
    the four directories the runtime expects:
        motion_detection/  · event JSONs + mp4 + thumbs
        timelapse/         · per-cam daily mp4s
        timelapse_frames/  · per-cam per-profile frames
        weather/           · sun-tl + weather-event clips
    """
    storage = tmp_path / "storage"
    for sub in ("motion_detection", "timelapse", "timelapse_frames", "weather"):
        (storage / sub).mkdir(parents=True, exist_ok=True)
    return storage


@pytest.fixture
def settings_store(tmp_storage_root: Path):
    """Minimal SettingsStore backed by tmp_storage_root. Pulls the
    real module (drops the test-stub if it's been registered) so
    fixtures see actual upsert/merge behaviour."""
    sys.modules.pop("app.settings_store", None)
    import app.settings_store  # noqa: F401 — re-import side effect

    from app.settings_store import SettingsStore

    base_config = {
        "app": {"name": "Squirreling · Sightings"},
        "storage": {"root": str(tmp_storage_root)},
        "cameras": [],
        "telegram": {},
        "mqtt": {},
        "processing": {},
    }
    settings_path = tmp_storage_root / "settings.json"
    return SettingsStore(settings_path, base_config)


@pytest.fixture
def sample_event() -> dict:
    """A minimal event dict in the storage/motion_detection JSON
    shape — enough fields for Mediathek lightbox + EventStore round-
    trips. Tests can mutate this freely; pytest re-creates it per
    request."""
    return {
        "id": "evt_test_001",
        "ts_iso": "2026-05-22T12:00:00",
        "camera_id": "cam_test",
        "labels": ["person"],
        "snapshot_path": "motion_detection/cam_test/2026-05-22/evt_test_001.jpg",
        "video_path": "motion_detection/cam_test/2026-05-22/evt_test_001.mp4",
        "thumb_path": "motion_detection/cam_test/2026-05-22/evt_test_001-thumb.jpg",
        "confirmed": False,
        "alarm_level": "info",
    }


@pytest.fixture
def frame_factory():
    """Factory for blank BGR frames. Default 640x360 (substream-ish);
    test passes width/height via call. Returns numpy uint8 — never
    None, so the validator stages can run."""
    import numpy as np

    def _make(width: int = 640, height: int = 360) -> "np.ndarray":
        return np.zeros((height, width, 3), dtype=np.uint8)

    return _make
