"""``PublishMixin._publish_dossiers`` — which species get dossier credit.

The bug this locks out: the hook used to read ``meta["detections"]``, one
FRAME's worth of detections (the trigger frame, or whichever tick last
upgraded the event) — never the whole clip. Motion confirms (~0.7 s)
before the bird classifier does (~1.05 s), so a bird event routinely
opens with no bird detection at all yet, and a later frame's detections
just as routinely miss a species the clip showed earlier. The event's
own ``bird_species`` field was already fixed for this exact gap
(``_motion.py::_refresh_bird_species``, folding in the whole-clip
``ClipTally``) — this hook read a different, stale key and silently
under-counted every species whose only detection landed outside that one
frame. The fix: read ``meta["whole_clip"]["species"]`` (the same
whole-clip tally ``bird_species`` already trusts), which
``_recording_step.py::_absorb_clip_frame`` keeps live on ``meta`` across
every tick of the recording.
"""

from __future__ import annotations

from app import app_state
from app.camera_runtime._recording._publish import PublishMixin


class _Cam(PublishMixin):
    def __init__(self):
        self.camera_id = "cam-test"


class _SpyDossierService:
    def __init__(self):
        self.calls: list[tuple[str, str | None, str, str]] = []

    def on_new_species(self, latin, common_de, event_id, camera_id):
        self.calls.append((latin, common_de, event_id, camera_id))
        return True


def setup_function(_fn):
    app_state.bird_dossiers = None


def teardown_function(_fn):
    app_state.bird_dossiers = None


def _species_row(species: str, latin: str) -> dict:
    return {"species": species, "species_latin": latin}


def test_credits_every_species_from_the_whole_clip_tally():
    svc = _SpyDossierService()
    app_state.bird_dossiers = svc
    cam = _Cam()
    meta = {
        "detections": [],  # the trigger frame caught no bird at all
        "whole_clip": {
            "species": [
                _species_row("Kohlmeise", "Parus major"),
                _species_row("Elster", "Pica pica"),
            ]
        },
    }

    cam._publish_dossiers(meta, "evt1")

    assert svc.calls == [
        ("Parus major", "Kohlmeise", "evt1", "cam-test"),
        ("Pica pica", "Elster", "evt1", "cam-test"),
    ]


def test_a_species_absent_from_the_final_frame_still_gets_credited():
    """The exact regression: the species that opened/rode the clip is
    long gone from `detections` (whichever frame that key now holds) by
    finalize time, but it was seen — the whole-clip tally still has it."""
    svc = _SpyDossierService()
    app_state.bird_dossiers = svc
    cam = _Cam()
    meta = {
        "detections": [{"label": "bird", "species": "Amsel", "species_latin": "Turdus merula"}],
        "whole_clip": {"species": [_species_row("Kohlmeise", "Parus major")]},
    }

    cam._publish_dossiers(meta, "evt2")

    assert svc.calls == [("Parus major", "Kohlmeise", "evt2", "cam-test")]


def test_dedupes_by_latin_name_within_one_event():
    svc = _SpyDossierService()
    app_state.bird_dossiers = svc
    cam = _Cam()
    meta = {
        "whole_clip": {
            "species": [
                _species_row("Kohlmeise", "Parus major"),
                _species_row("Kohlmeise", "Parus major"),
            ]
        }
    }

    cam._publish_dossiers(meta, "evt3")

    assert len(svc.calls) == 1


def test_a_row_with_no_latin_name_is_skipped():
    svc = _SpyDossierService()
    app_state.bird_dossiers = svc
    cam = _Cam()
    meta = {"whole_clip": {"species": [_species_row("unsicher", "")]}}

    cam._publish_dossiers(meta, "evt4")

    assert svc.calls == []


def test_no_whole_clip_block_is_a_safe_no_op():
    svc = _SpyDossierService()
    app_state.bird_dossiers = svc
    cam = _Cam()

    cam._publish_dossiers({}, "evt5")

    assert svc.calls == []


def test_no_dossier_service_wired_up_is_a_safe_no_op():
    app_state.bird_dossiers = None
    cam = _Cam()
    meta = {"whole_clip": {"species": [_species_row("Kohlmeise", "Parus major")]}}

    cam._publish_dossiers(meta, "evt6")  # must not raise
