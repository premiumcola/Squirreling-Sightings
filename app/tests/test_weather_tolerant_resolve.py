"""Regression — weather clip / thumb endpoints must fall back to a
same-dir glob when the stored manifest path 404s.

Background: a cam-slug suffix migration renamed clip/thumb files
in-place but didn't rewrite manifests pointing at the pre-rename
names. The endpoints used to hard-404 in that case. The tolerant
resolver introduced in `routes/weather.py` looks for any file in
the same directory whose stem shares the date-prefix portion of
the stored name and serves it. This test pins that behaviour so
the fallback doesn't silently regress.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.routes.weather import _tolerant_resolve


def test_finds_renamed_clip(tmp_path: Path):
    # Manifest still points at the original (un-suffixed) filename.
    stored = tmp_path / "2026-05-09_sunrise.mp4"
    # On disk only the slug-suffixed file exists.
    (tmp_path / "2026-05-09_sunrise_gartendachterrasse.mp4").write_bytes(b"x")
    out = _tolerant_resolve(stored, tmp_path, "mp4")
    assert out is not None
    assert out.name == "2026-05-09_sunrise_gartendachterrasse.mp4"


def test_finds_unsuffixed_clip_when_stored_has_suffix(tmp_path: Path):
    # Manifest points at the suffixed name (post-migration write), but
    # disk only has the un-suffixed legacy file.
    stored = tmp_path / "2026-05-09_sunrise_gartendachterrasse.mp4"
    (tmp_path / "2026-05-09_sunrise.mp4").write_bytes(b"x")
    out = _tolerant_resolve(stored, tmp_path, "mp4")
    assert out is not None
    assert out.name == "2026-05-09_sunrise.mp4"


def test_returns_none_when_no_match(tmp_path: Path):
    stored = tmp_path / "2026-05-09_sunrise.mp4"
    out = _tolerant_resolve(stored, tmp_path, "mp4")
    assert out is None


def test_thumb_extension_independent(tmp_path: Path):
    stored = tmp_path / "2026-05-09_sunset.jpg"
    (tmp_path / "2026-05-09_sunset_werkstatt.jpg").write_bytes(b"x")
    out = _tolerant_resolve(stored, tmp_path, "jpg")
    assert out is not None
    assert out.suffix == ".jpg"


def test_prefers_exact_stem_when_present(tmp_path: Path):
    # Both files exist — exact match wins over the glob alternative.
    stored = tmp_path / "2026-05-09_sunrise.mp4"
    (tmp_path / "2026-05-09_sunrise.mp4").write_bytes(b"x")
    (tmp_path / "2026-05-09_sunrise_gartendachterrasse.mp4").write_bytes(b"y")
    out = _tolerant_resolve(stored, tmp_path, "mp4")
    assert out is not None
    assert out.name == "2026-05-09_sunrise.mp4"


def test_rejects_path_outside_storage_root(tmp_path: Path):
    # storage_root is a subdir; the candidate file lives outside.
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    other = tmp_path / "outside"
    other.mkdir()
    (other / "2026-05-09_sunrise.mp4").write_bytes(b"x")
    stored = other / "2026-05-09_sunrise.mp4"
    out = _tolerant_resolve(stored, storage_root, "mp4")
    assert out is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
