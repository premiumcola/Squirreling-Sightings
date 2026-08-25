"""settings.json corruption + concurrency guards.

Two defects this locks down, both on the file CLAUDE.md calls the most
regression-prone in the project (it carries RTSP passwords and the
Telegram token):

1. ``load()`` used to swallow a JSON parse error and then fall through
   to an unconditional ``save()`` of bare defaults. Because ``save()``
   rotates settings.json → .bak → .bak2, booting twice on a corrupt
   file consumed BOTH backups and destroyed the last good credentials.

2. ``save()`` held no lock and wrote through one shared ``.tmp`` path,
   so two concurrent saves could interleave and publish a half-written
   file.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.settings.store import SettingsStore

BASE = {"cameras": [], "server": {"host": "0.0.0.0", "port": 8099}}


def _write(path: Path, payload) -> None:
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload),
        encoding="utf-8",
    )


def _marked(marker: str) -> dict:
    """A settings payload carrying a recognisable credential."""
    return {"telegram": {"token": marker, "enabled": True}, "cameras": []}


def test_corrupt_settings_recovers_from_bak(tmp_path: Path):
    settings = tmp_path / "settings.json"
    _write(settings, "{ this is not json")
    _write(settings.with_suffix(".json.bak"), _marked("GOOD-FROM-BAK"))

    store = SettingsStore(settings, BASE)

    assert store.data["telegram"]["token"] == "GOOD-FROM-BAK"


def test_corrupt_settings_falls_back_to_bak2(tmp_path: Path):
    settings = tmp_path / "settings.json"
    _write(settings, "{ truncated")
    _write(settings.with_suffix(".json.bak"), "also { broken")
    _write(settings.with_suffix(".json.bak2"), _marked("GOOD-FROM-BAK2"))

    store = SettingsStore(settings, BASE)

    assert store.data["telegram"]["token"] == "GOOD-FROM-BAK2"


def test_corrupt_settings_is_quarantined_not_destroyed(tmp_path: Path):
    """Even with no usable backup, the unreadable bytes must survive on
    disk — they may be the only copy of the credentials."""
    settings = tmp_path / "settings.json"
    _write(settings, '{"telegram": {"token": "PARTIAL-BUT-PRECIOUS"')

    SettingsStore(settings, BASE)

    quarantined = list(tmp_path.glob("settings.json.corrupt.*"))
    assert len(quarantined) == 1, f"expected one quarantine file, got {quarantined}"
    assert "PARTIAL-BUT-PRECIOUS" in quarantined[0].read_text(encoding="utf-8")


def test_two_boots_on_corrupt_file_keep_the_good_backup(tmp_path: Path):
    """The original data-loss scenario: boot twice on a corrupt file.

    Previously the first boot wrote defaults and rotated the good state
    out to .bak, and the second boot rotated it out of .bak2 entirely.
    """
    settings = tmp_path / "settings.json"
    _write(settings, "}{ garbage")
    _write(settings.with_suffix(".json.bak"), _marked("SURVIVOR"))

    first = SettingsStore(settings, BASE)
    second = SettingsStore(settings, BASE)

    assert first.data["telegram"]["token"] == "SURVIVOR"
    assert second.data["telegram"]["token"] == "SURVIVOR"


def test_valid_settings_load_untouched(tmp_path: Path):
    settings = tmp_path / "settings.json"
    _write(settings, _marked("NORMAL-BOOT"))

    store = SettingsStore(settings, BASE)

    assert store.data["telegram"]["token"] == "NORMAL-BOOT"
    assert not list(tmp_path.glob("settings.json.corrupt.*"))


def test_concurrent_saves_never_publish_partial_json(tmp_path: Path):
    """Hammer save() from several threads; the file must always parse.

    Each thread writes a payload with a distinct padded token, so a
    torn write shows up as either a parse failure or a spliced token.
    """
    settings = tmp_path / "settings.json"
    _write(settings, _marked("INIT"))
    store = SettingsStore(settings, BASE)

    errors: list[str] = []
    barrier = threading.Barrier(6)

    def writer(n: int):
        barrier.wait()
        for _ in range(25):
            store.data["telegram"]["token"] = f"T{n}" * 200
            try:
                store.save()
            except Exception as e:  # noqa: BLE001 - reported, not raised
                errors.append(f"save failed: {e}")

    def reader():
        barrier.wait()
        for _ in range(25):
            try:
                text = settings.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                json.loads(text)
            except Exception as e:  # noqa: BLE001 - reported, not raised
                errors.append(f"torn read: {e}")

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors[:5]
    # And no temp files left behind.
    assert not list(tmp_path.glob("*.tmp")), list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("payload", ["[]", '"a string"', "42", "null"])
def test_non_object_json_is_treated_as_corrupt(tmp_path: Path, payload: str):
    """A valid-JSON non-object would crash data.update() later."""
    settings = tmp_path / "settings.json"
    _write(settings, payload)
    _write(settings.with_suffix(".json.bak"), _marked("OBJECT-BACKUP"))

    store = SettingsStore(settings, BASE)

    assert store.data["telegram"]["token"] == "OBJECT-BACKUP"
