"""maintenance.py::_sweep_bird_dossier_prebuild — the daily-timer sibling
of _sweep_bird_species (bird_species_backfill.py) that warms reference
dossiers for the WHOLE classifier vocabulary, not just detected species.

Stub-based: no real BirdDossierService, no real latin_to_de file I/O —
both are monkeypatched to fakes so the test exercises only the wiring
(does the sweep call through with the vocabulary and the documented
budget, does it no-op safely when the service or vocabulary is absent).
"""

from __future__ import annotations

import sys
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

import logging  # noqa: E402

from app import app_state, maintenance  # noqa: E402


class _FakeDossierService:
    def __init__(self):
        self.calls = []
        self.backfills = 0

    def sweep_prebuild(self, vocabulary, *, budget):
        self.calls.append((dict(vocabulary), budget))
        return {"examined": len(vocabulary), "created": len(vocabulary)}

    def sweep_photo_backfill(self):
        self.backfills += 1
        return {"pending": 0}


def test_prebuild_sweep_passes_the_full_vocabulary_and_documented_budget(monkeypatch):
    from app.bird_dossiers import DOSSIER_PREBUILD_BUDGET

    svc = _FakeDossierService()
    monkeypatch.setattr(app_state, "bird_dossiers", svc, raising=False)
    monkeypatch.setattr(
        "app.detectors._label_loader._load_bird_latin_to_de",
        lambda path: {"Erithacus rubecula": "Rotkehlchen", "Turdus merula": "Amsel"},
    )
    maintenance._sweep_bird_dossier_prebuild(logging.getLogger("test"))
    assert len(svc.calls) == 1
    vocabulary, budget = svc.calls[0]
    assert vocabulary == {"Erithacus rubecula": "Rotkehlchen", "Turdus merula": "Amsel"}
    assert budget == DOSSIER_PREBUILD_BUDGET


def test_the_same_tick_also_backfills_photos_of_cached_dossiers(monkeypatch):
    """sweep_prebuild only ever CREATES missing dossiers, so on its own it
    would never revisit the hundreds already on disk that were cached
    with a single reference photo. The photo backfill has to ride the
    same daily tick or those never grow."""
    svc = _FakeDossierService()
    monkeypatch.setattr(app_state, "bird_dossiers", svc, raising=False)
    monkeypatch.setattr(
        "app.detectors._label_loader._load_bird_latin_to_de",
        lambda path: {"Erithacus rubecula": "Rotkehlchen"},
    )
    maintenance._sweep_bird_dossier_prebuild(logging.getLogger("test"))
    assert svc.backfills == 1


def test_prebuild_sweep_noop_without_a_dossier_service(monkeypatch):
    monkeypatch.setattr(app_state, "bird_dossiers", None, raising=False)
    # Must not raise even though nothing is wired up.
    maintenance._sweep_bird_dossier_prebuild(logging.getLogger("test"))


def test_prebuild_sweep_noop_with_an_empty_vocabulary(monkeypatch):
    svc = _FakeDossierService()
    monkeypatch.setattr(app_state, "bird_dossiers", svc, raising=False)
    monkeypatch.setattr("app.detectors._label_loader._load_bird_latin_to_de", lambda path: {})
    maintenance._sweep_bird_dossier_prebuild(logging.getLogger("test"))
    assert svc.calls == []


def test_daily_cleanup_runs_the_prebuild_sweep_and_survives_its_failure(monkeypatch):
    """Mirrors the existing _sweep_bird_species wiring in
    _run_daily_cleanup: a failure in the new sweep must not prevent the
    function from re-arming its own timer, and must not raise out."""
    monkeypatch.setattr(maintenance, "auto_cleanup_enabled", lambda: False)
    monkeypatch.setattr(maintenance, "_sweep_trash", lambda log: None)
    monkeypatch.setattr(maintenance, "_sweep_bird_species", lambda log: None)

    calls = []

    def _boom(log):
        calls.append(True)
        raise RuntimeError("boom")

    monkeypatch.setattr(maintenance, "_sweep_bird_dossier_prebuild", _boom)

    class _FakeTimer:
        def __init__(self, *a, **kw):
            pass

        def __setattr__(self, key, value):
            object.__setattr__(self, key, value)

        def start(self):
            pass

    monkeypatch.setattr(maintenance.threading, "Timer", _FakeTimer)

    maintenance._run_daily_cleanup()
    assert calls == [True]
