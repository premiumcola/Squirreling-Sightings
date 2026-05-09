"""End-to-end tests for storage_migration.migrate.

We build a fake on-disk layout that mirrors the dual-folder pattern seen
in the wild (cam-<ip-dashes> + cam-<name> for the same camera) alongside
a single clean folder, point a stub SettingsStore at it, and verify the
migration:
  - merges the dual folders into the new canonical id
  - rewrites event JSON paths
  - removes the empty object_detection placeholder
  - is idempotent (second invocation is a no-op)

IPs in fixtures are RFC 5737 documentation addresses (192.0.2.0/24)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.storage_migration import migrate  # noqa: E402


class _FakeSettingsStore:
    """Just enough of SettingsStore for migrate(). Holds an in-memory data
    dict + a path attribute so the migration's settings-backup helper can
    write to a real file."""

    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def save(self):
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")


def _make_storage(tmp_path: Path) -> Path:
    """Build a representative dual-folder scaffold in tmp."""
    storage = tmp_path / "storage"
    # motion_detection: Werkstatt has TWO legacy folders, Squirrel has one
    md = storage / "motion_detection"
    (md / "cam-192-0-2-172" / "2026-04-25").mkdir(parents=True)
    (md / "cam-192-0-2-172" / "2026-04-25" / "evt_a.jpg").write_bytes(b"a")
    (md / "cam-192-0-2-172" / "2026-04-25" / "evt_a.json").write_text(json.dumps({
        "event_id": "a",
        "camera_id": "cam-192-0-2-172",
        "video_relpath": "timelapse/cam-192-0-2-172/foo.mp4",
        "snapshot_relpath": "motion_detection/cam-192-0-2-172/2026-04-25/evt_a.jpg",
    }), encoding="utf-8")
    (md / "cam-Werkstatt.rechts.oben" / "2026-04-26").mkdir(parents=True)
    (md / "cam-Werkstatt.rechts.oben" / "2026-04-26" / "evt_b.jpg").write_bytes(b"b")
    (md / "cam-Werkstatt.rechts.oben" / "2026-04-26" / "evt_b.json").write_text(json.dumps({
        "event_id": "b",
        "camera_id": "cam-Werkstatt.rechts.oben",
        "snapshot_relpath": "motion_detection/cam-Werkstatt.rechts.oben/2026-04-26/evt_b.jpg",
    }), encoding="utf-8")
    (md / "cam-192-0-2-183" / "2026-04-26").mkdir(parents=True)
    (md / "cam-192-0-2-183" / "2026-04-26" / "evt_c.jpg").write_bytes(b"c")
    # timelapse_frames + timelapse — only the Werkstatt-named variant exists
    tlf = storage / "timelapse_frames"
    (tlf / "cam-Werkstatt.rechts.oben" / "daily" / "2026-04-26").mkdir(parents=True)
    (tlf / "cam-Werkstatt.rechts.oben" / "daily" / "2026-04-26" / "120000.jpg").write_bytes(b"f")
    (tlf / "cam-192-0-2-183" / "daily" / "2026-04-26").mkdir(parents=True)
    tl = storage / "timelapse"
    (tl / "cam-Werkstatt.rechts.oben").mkdir(parents=True)
    (tl / "cam-Werkstatt.rechts.oben" / "2026-04-26.mp4").write_bytes(b"v")
    (tl / "cam-192-0-2-183").mkdir(parents=True)
    # weather: not per-cam in the user's current state, but the migration
    # should tolerate the absence
    (storage / "weather").mkdir()
    # object_detection placeholder (empty) — must be rmdir'd
    (storage / "object_detection").mkdir()
    return storage


def _make_cams() -> list[dict]:
    return [
        {
            "id": "cam-Werkstatt.rechts.oben",
            "name": "Werkstatt",
            "manufacturer": "",
            "model": "",
            "rtsp_url": "rtsp://user:pass@192.0.2.172/h264Preview_01_main",
        },
        {
            "id": "cam-192-0-2-183",
            "name": "Squirrel Town",
            "manufacturer": "Reolink",
            "model": "RLC-810A",
            "rtsp_url": "rtsp://user:pass@192.0.2.183/h264Preview_01_main",
        },
    ]


class TestMigrate:
    def test_dual_folder_collapse(self, tmp_path):
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        summary = migrate(store, storage)
        assert summary["noop"] is False
        # Werkstatt → unknown_unknown_werkstatt_172
        new_werk = "unknown_unknown_werkstatt_172"
        assert (storage / "motion_detection" / new_werk).is_dir()
        # Old folders gone
        assert not (storage / "motion_detection" / "cam-192-0-2-172").exists()
        assert not (storage / "motion_detection" / "cam-Werkstatt.rechts.oben").exists()
        # Both source-day subfolders ended up under the new id
        assert (storage / "motion_detection" / new_werk / "2026-04-25" / "evt_a.jpg").is_file()
        assert (storage / "motion_detection" / new_werk / "2026-04-26" / "evt_b.jpg").is_file()

    def test_canonical_camera_renamed(self, tmp_path):
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        migrate(store, storage)
        # Squirrel → reolink_rlc810a_squirreltown_183 (manufacturer + model set)
        new_squirrel = "reolink_rlc810a_squirreltown_183"
        assert (storage / "motion_detection" / new_squirrel).is_dir()
        assert (storage / "timelapse_frames" / new_squirrel).is_dir()
        assert (storage / "timelapse" / new_squirrel).is_dir()

    def test_event_jsons_rewritten(self, tmp_path):
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        migrate(store, storage)
        new_werk = "unknown_unknown_werkstatt_172"
        evt_a = (storage / "motion_detection" / new_werk / "2026-04-25" / "evt_a.json").read_text(encoding="utf-8")
        meta = json.loads(evt_a)
        assert "cam-192-0-2-172" not in evt_a
        assert meta["video_relpath"] == f"timelapse/{new_werk}/foo.mp4"
        assert meta["snapshot_relpath"] == f"motion_detection/{new_werk}/2026-04-25/evt_a.jpg"
        evt_b = (storage / "motion_detection" / new_werk / "2026-04-26" / "evt_b.json").read_text(encoding="utf-8")
        assert "cam-Werkstatt.rechts.oben" not in evt_b
        assert new_werk in evt_b

    def test_settings_id_updated(self, tmp_path):
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        migrate(store, storage)
        ids = {c["id"] for c in store.data["cameras"]}
        assert "unknown_unknown_werkstatt_172" in ids
        assert "reolink_rlc810a_squirreltown_183" in ids
        # settings.json on disk reflects the new ids too
        on_disk = json.loads(store.path.read_text(encoding="utf-8"))
        on_disk_ids = {c["id"] for c in on_disk["cameras"]}
        assert on_disk_ids == ids

    def test_object_detection_placeholder_removed(self, tmp_path):
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        migrate(store, storage)
        assert not (storage / "object_detection").exists()

    def test_idempotent(self, tmp_path):
        """Second invocation must report noop=True and change nothing."""
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        first = migrate(store, storage)
        assert first["noop"] is False
        # Snapshot disk + settings, then run again.
        before = sorted(p.relative_to(storage).as_posix()
                        for p in storage.rglob("*") if p.is_file())
        before_settings = store.path.read_text(encoding="utf-8")
        second = migrate(store, storage)
        assert second["noop"] is True, f"second run was not noop: {second}"
        after = sorted(p.relative_to(storage).as_posix()
                       for p in storage.rglob("*") if p.is_file())
        assert before == after
        assert before_settings == store.path.read_text(encoding="utf-8")

    def test_settings_backup_created(self, tmp_path):
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        summary = migrate(store, storage)
        assert summary["backup"] is not None
        bak = Path(summary["backup"])
        assert bak.exists()
        # Backup contains the OLD ids
        bak_content = bak.read_text(encoding="utf-8")
        assert "cam-Werkstatt.rechts.oben" in bak_content
        assert "cam-192-0-2-183" in bak_content

    def test_no_cameras_no_op(self, tmp_path):
        storage = tmp_path / "storage"
        storage.mkdir()
        store = _FakeSettingsStore(tmp_path / "settings.json", {"cameras": []})
        s = migrate(store, storage)
        assert s["noop"] is True
        assert s["cameras"] == 0


class TestBackupRetentionAndPrune:
    """Pruning + conditional-promotion regression coverage. The prune
    helper MUST never touch the bare ``settings.json.bak`` /
    ``settings.json.bak2`` rotation files, and it MUST cap the
    timestamped backups at the configured ``keep`` value."""

    def _seed_history(self, settings_path: Path, n: int = 5) -> list[Path]:
        """Drop ``n`` synthetic ``.bak.<ts>`` files plus the bare
        rotation pair next to the settings file. Returns the
        timestamped paths in age order (oldest first) so callers can
        assert which ones got pruned."""
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text("{}", encoding="utf-8")
        # Rotation pair (no timestamp) — never pruned.
        (settings_path.parent / "settings.json.bak").write_text("rot1", encoding="utf-8")
        (settings_path.parent / "settings.json.bak2").write_text("rot2", encoding="utf-8")
        out: list[Path] = []
        # Use distinct mtimes so the prune helper's age sort is
        # deterministic — naming alone isn't enough on filesystems
        # that round mtime to the second.
        import os as _os
        import time as _t
        base_t = _t.time() - 86400
        # Real migration backups carry exactly 8 digits (YYYYMMDD)
        # and 6 digits (HHMMSS); the prune regex requires that.
        # Walk through January 2026 day-by-day for a deterministic
        # 8-digit date string regardless of ``n``.
        for i in range(n):
            ts = f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}_120000"
            p = settings_path.parent / f"settings.json.bak.{ts}"
            p.write_text(f"hist-{i}", encoding="utf-8")
            _os.utime(p, (base_t + i, base_t + i))
            out.append(p)
        return out

    def test_prune_skips_rotation_files(self, tmp_path):
        from app.storage_migration import _prune_old_settings_backups
        store = _FakeSettingsStore(tmp_path / "settings.json", {"cameras": []})
        seeded = self._seed_history(store.path, n=3)
        # keep=10 — nothing to prune yet.
        pruned = _prune_old_settings_backups(store, keep=10)
        assert pruned == 0
        for p in seeded:
            assert p.exists()
        # Rotation pair still present.
        assert (store.path.parent / "settings.json.bak").exists()
        assert (store.path.parent / "settings.json.bak2").exists()

    def test_prune_caps_timestamped_to_keep(self, tmp_path):
        from app.storage_migration import _prune_old_settings_backups
        store = _FakeSettingsStore(tmp_path / "settings.json", {"cameras": []})
        seeded = self._seed_history(store.path, n=12)
        pruned = _prune_old_settings_backups(store, keep=5)
        # Oldest 7 (12 - 5) must be gone; newest 5 must survive.
        assert pruned == 7
        for old in seeded[:7]:
            assert not old.exists(), f"expected {old.name} to be pruned"
        for kept in seeded[7:]:
            assert kept.exists(), f"expected {kept.name} to survive"
        # Rotation pair still present.
        assert (store.path.parent / "settings.json.bak").exists()
        assert (store.path.parent / "settings.json.bak2").exists()

    def test_prune_clamps_invalid_keep(self, tmp_path):
        """A malformed ``settings.server.settings_backup_keep`` value
        must clamp to the [1, 100] range, not wipe history."""
        from app.storage_migration import _prune_old_settings_backups
        store = _FakeSettingsStore(tmp_path / "settings.json", {"cameras": []})
        seeded = self._seed_history(store.path, n=4)
        # keep=0 → clamped to 1 (newest survives, rest pruned).
        pruned = _prune_old_settings_backups(store, keep=0)
        assert pruned == 3
        assert seeded[-1].exists()
        for old in seeded[:-1]:
            assert not old.exists()

    def test_idle_boot_prunes_no_new_backup(self, tmp_path):
        """An idempotent re-run does not create a new timestamped
        backup, but it DOES prune any leftover history beyond keep."""
        storage = _make_storage(tmp_path)
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": _make_cams()})
        # First run: real migration → one backup is promoted.
        summary1 = migrate(store, storage)
        assert summary1["backup_retained"] is True
        # Seed a few extra fake history files so the second (idle) run
        # has something to prune.
        extra = self._seed_history(store.path, n=12)
        # Set a tight keep cap on the store config.
        store.data.setdefault("server", {})["settings_backup_keep"] = 3
        # Second run: nothing changes → no new .bak.<ts> file, but
        # prune fires.
        before_count = len(list(store.path.parent.glob("settings.json.bak.*")))
        summary2 = migrate(store, storage)
        after_count = len(list(store.path.parent.glob("settings.json.bak.*")))
        assert summary2["noop"] is True
        assert summary2["backup_retained"] is False
        assert summary2["pruned"] >= 1
        assert after_count <= 3
        assert after_count < before_count
        # Rotation pair still present.
        assert (store.path.parent / "settings.json.bak").exists()
        assert (store.path.parent / "settings.json.bak2").exists()
        # Suppress unused-warning on `extra` — it's the population set
        # the assertion above is implicitly comparing against.
        del extra

    def test_no_op_run_leaves_no_partial_file(self, tmp_path):
        """Idle boots must not leave a ``.bak.<ts>.partial`` file
        behind. The first run writes one (during Pass 2), the second
        (idle) run never enters Pass 2 at all so neither a partial
        nor a final should appear."""
        storage = tmp_path / "storage"
        storage.mkdir()
        store = _FakeSettingsStore(tmp_path / "settings.json",
                                   {"cameras": []})
        migrate(store, storage)
        for p in store.path.parent.iterdir():
            assert not p.name.endswith(".partial"), (
                f"unexpected partial file left behind: {p.name}"
            )
