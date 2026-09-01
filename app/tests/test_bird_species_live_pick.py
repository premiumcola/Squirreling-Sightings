"""camera_runtime/_motion.py::_build_event_meta's `bird_species`
aggregate — the live-path twin of bird_species_backfill.py's own
aggregate. Both now share bird_species_rank.py::pick_headline_species,
so a clip with several bird species headlines the rarest one (or a
never-recorded one), not just whichever detection fired first.

The live path resolves the dossier lookup itself, off `app_state.
bird_dossiers` — see _resolve_bird_species's docstring for why that is
safe to do synchronously on the hot detection path (a single in-memory
dict read behind a lock, same access _recording/_publish.py::
_publish_dossiers already makes).
"""

from __future__ import annotations

from datetime import datetime

from app import app_state
from app.camera_runtime._motion import MotionMixin
from app.detectors import Detection


class _Cam(MotionMixin):
    def __init__(self, **cfg):
        self.camera_id = "cam-test"
        self.cfg = {"armed": True, "alarm_profile": "soft", **cfg}
        self.person_registry = None
        self.recent_detections: list = []


class _FakeDossierService:
    def __init__(self, counts: dict[str, int]):
        self._counts = counts

    def get_dossier(self, latin: str):
        return {"sighting_count": self._counts[latin]} if latin in self._counts else None


def _bird(species: str, latin: str, score: float = 0.8) -> Detection:
    return Detection(
        label="bird", score=score, bbox=(0, 0, 10, 10), species=species, species_latin=latin
    )


def setup_function(_fn):
    # Isolate each test from whatever a previous one (or boot) left on
    # the shared app_state singleton.
    app_state.bird_dossiers = None


def teardown_function(_fn):
    app_state.bird_dossiers = None


def test_no_dossier_service_falls_back_to_first_in_order():
    cam = _Cam()
    detections = [_bird("Amsel", "Turdus merula"), _bird("Rotkehlchen", "Erithacus rubecula")]
    meta = cam._build_event_meta(datetime.now(), ["bird"], detections, None, None)
    assert meta["bird_species"] == "Amsel"


def test_live_path_picks_the_rarest_species_via_app_state_dossiers():
    app_state.bird_dossiers = _FakeDossierService(
        {"Turdus merula": 5, "Erithacus rubecula": 1, "Parus major": 10}
    )
    cam = _Cam()
    detections = [
        _bird("Amsel", "Turdus merula"),
        _bird("Rotkehlchen", "Erithacus rubecula"),
        _bird("Kohlmeise", "Parus major"),
    ]
    meta = cam._build_event_meta(datetime.now(), ["bird"], detections, None, None)
    assert meta["bird_species"] == "Rotkehlchen"


def test_live_path_prefers_a_never_recorded_species():
    app_state.bird_dossiers = _FakeDossierService({"Turdus merula": 1})
    cam = _Cam()
    detections = [_bird("Amsel", "Turdus merula"), _bird("Seltener Gast", "Genus novus")]
    meta = cam._build_event_meta(datetime.now(), ["bird"], detections, None, None)
    assert meta["bird_species"] == "Seltener Gast"


def test_live_path_ties_fall_back_to_stored_order():
    app_state.bird_dossiers = _FakeDossierService({"Parus major": 3, "Cyanistes caeruleus": 3})
    cam = _Cam()
    detections = [
        _bird("Kohlmeise", "Parus major"),
        _bird("Blaumeise", "Cyanistes caeruleus"),
    ]
    meta = cam._build_event_meta(datetime.now(), ["bird"], detections, None, None)
    assert meta["bird_species"] == "Kohlmeise"


def test_no_bird_detections_leaves_bird_species_none():
    app_state.bird_dossiers = _FakeDossierService({})
    cam = _Cam()
    detections = [Detection(label="cat", score=0.9, bbox=(0, 0, 10, 10))]
    meta = cam._build_event_meta(datetime.now(), ["cat"], detections, None, None)
    assert meta["bird_species"] is None
