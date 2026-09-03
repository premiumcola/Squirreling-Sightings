"""`classified` must mean "the second stage ran", not "it was asked for".

The flag exists to keep two answers apart that an empty species list
cannot: "looked and found nothing" versus "never looked". Everything
downstream leans on it — `_report.build_comparison` republishes it,
`replay_batch/_aggregate` counts `classified_events` from it, and the
Mediathek renders that count as "Mit Artbestimmung geprüft".

It was computed as `classify and classifier is not None`. But
`tracking_worker._classifier.bird_classifier()` returns a
`BirdSpeciesClassifier` object even when the operator has species
classification switched off — an object with `available=False` and
`reason="disabled"`. `make_sample_hook` correctly refuses to build a
hook for such a classifier, so nothing is classified, while the flag
said it had been.

`replay_clip` is stubbed at `open_video` / `_walk_clip`, the two seams
that need a real video; everything the flag depends on runs for real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.replay import _run  # noqa: E402
from app.replay._species import make_sample_hook  # noqa: E402
from app.species_tally import SpeciesTally  # noqa: E402


class _Classifier:
    """Stand-in for BirdSpeciesClassifier in its two relevant states."""

    def __init__(self, *, available: bool, reason: str):
        self.available = available
        self.reason = reason
        self.mode = "cpu" if available else "none"
        self.active_model_path = "/models/inat_bird_quant.tflite" if available else None


class _Detector:
    available = True
    mode = "cpu"
    reason = "ok"
    active_model_path = "/models/efficientdet_lite0.tflite"


class _Worker:
    def __init__(self, classifier):
        self._classifier = classifier

    def detector(self):
        return _Detector()

    def bird_classifier(self):
        return self._classifier


class _Cap:
    def release(self) -> None:
        pass


@pytest.fixture
def stubbed(monkeypatch):
    """Neutralise the two calls that need a decodable file on disk."""
    meta = {"fps": 25.0, "frame_count": 250, "sample_interval": 25, "duration_s": 10.0}
    monkeypatch.setattr(_run, "open_video", lambda *a, **kw: (_Cap(), meta))
    monkeypatch.setattr(
        _run,
        "_walk_clip",
        lambda *a, **kw: {"tracks": [], "gates": {}, "filter_applied": None},
    )


def _replay(classifier, *, classify: bool = True) -> dict:
    return _run.replay_clip(
        worker=_Worker(classifier),
        camera_id="cam-1",
        video_path=Path("/nowhere/clip.mp4"),
        storage_root=Path("/nowhere"),
        cfg={},
        classify=classify,
    )


def test_a_disabled_classifier_does_not_count_as_classified(stubbed):
    """The reported case: species classification is switched off, the
    worker still hands back an object, and nothing gets classified."""
    disabled = _Classifier(available=False, reason="disabled")
    result = _replay(disabled)

    assert make_sample_hook(disabled, SpeciesTally(max_crops=10)) is None
    assert result["classified"] is False
    # The honest reason survives — the point is not to hide the object,
    # it is to stop claiming its stage ran.
    assert result["classifier"]["reason"] == "disabled"
    assert result["classifier"]["available"] is False


def test_an_unloadable_classifier_does_not_count_as_classified(stubbed):
    """Same flag, the other way a classifier ends up unusable."""
    broken = _Classifier(available=False, reason="model file not found")
    result = _replay(broken)

    assert result["classified"] is False
    assert result["classifier"]["reason"] == "model file not found"


def test_a_working_classifier_still_counts_as_classified(stubbed):
    result = _replay(_Classifier(available=True, reason="ok"))

    assert result["classified"] is True
    assert result["classifier"]["available"] is True


def test_a_detector_only_run_is_not_classified(stubbed):
    """classify=False was always reported correctly; keep it that way."""
    result = _replay(_Classifier(available=True, reason="ok"), classify=False)

    assert result["classified"] is False
    assert result["classifier"]["reason"] == "not_requested"


def test_the_flag_agrees_with_the_hook_in_every_state(stubbed):
    """The invariant behind all of the above: `classified` is true
    exactly when `make_sample_hook` would have built a hook."""
    for available, classify in ((True, True), (True, False), (False, True), (False, False)):
        clf = _Classifier(available=available, reason="ok" if available else "disabled")
        result = _replay(clf, classify=classify)
        hook = make_sample_hook(clf if classify else None, SpeciesTally(max_crops=10))
        assert result["classified"] is (hook is not None), (available, classify)
