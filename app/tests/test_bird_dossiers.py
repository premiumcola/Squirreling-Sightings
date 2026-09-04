"""BirdDossierService — the reference-content pre-build sweep.

Stub-based throughout (no real Wikipedia/Xeno-canto calls) — `_spawn_fetch`
is monkeypatched to a synchronous no-op or to a canned-response stand-in
so tests never touch the network, mirroring test_bird_species_backfill.py's
own `_FakeClassifier` approach.

Covers:
  * `sweep_prebuild` is bounded by its budget per call (mirrors
    test_bird_species_backfill.py::test_sweep_is_bounded_by_its_budget).
  * a species already covered (real sighting OR an earlier sweep call)
    is skipped, never overwritten, and doesn't eat into the budget.
  * repeated calls make cumulative progress across the whole vocabulary.
  * a pre-built placeholder never touches sighting_count / first_seen_at
    — it stays 0 / None, i.e. it cannot unlock or backdate an
    achievement. Achievement unlocking lives entirely in
    achievements.json (routes/sichtungen.py), a separate store this
    module never opens.
  * a pre-built placeholder still sinks to the end of `list_dossiers()`
    (no first_seen_at), so it never displaces a real sighting from the
    "newest first" gallery order.
  * the background fetch machinery actually populates dossier content
    (Wikipedia summary + Xeno-canto recordings) for a species that was
    only pre-built, never detected — the whole point of the sweep.
"""

from __future__ import annotations

from app.bird_dossiers import DOSSIER_PREBUILD_BUDGET, BirdDossierService

assert DOSSIER_PREBUILD_BUDGET > 0  # sanity: the daily sweep stays bounded too


def _service(tmp_path, monkeypatch, *, spawn_noop=True):
    svc = BirdDossierService(tmp_path / "bird_dossiers.json")
    if spawn_noop:
        # Isolate sweep_prebuild's bookkeeping from the background
        # fetcher entirely — no threads, no network, deterministic.
        monkeypatch.setattr(svc, "_spawn_fetch", lambda latin: None)
    return svc


_VOCAB = {
    "Erithacus rubecula": "Rotkehlchen",
    "Turdus merula": "Amsel",
    "Parus major": "Kohlmeise",
}


def test_sweep_prebuild_creates_placeholders_for_the_whole_vocabulary(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    result = svc.sweep_prebuild(_VOCAB, budget=10)
    assert result == {"examined": 3, "created": 3}
    for latin in _VOCAB:
        d = svc.get_dossier(latin)
        assert d is not None
        assert d["sighting_count"] == 0
        assert d["first_seen_at"] is None
        assert d["first_seen_event_id"] is None
        assert d["first_seen_camera_id"] is None
        assert d["common_name_de"] == _VOCAB[latin]


def test_sweep_prebuild_is_bounded_by_its_budget(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    result = svc.sweep_prebuild(_VOCAB, budget=2)
    assert result == {"examined": 2, "created": 2}
    assert len(svc.list_dossiers()) == 2


def test_sweep_prebuild_resumes_across_calls(tmp_path, monkeypatch):
    """A budget too small for the whole vocabulary in one call still
    finishes it across repeated calls (the daily-timer shape) — the
    second call picks up exactly where the first left off instead of
    re-examining (or re-creating) species the first call already
    covered."""
    svc = _service(tmp_path, monkeypatch)
    first = svc.sweep_prebuild(_VOCAB, budget=2)
    second = svc.sweep_prebuild(_VOCAB, budget=2)
    assert first["created"] == 2
    assert second["created"] == 1
    assert second["examined"] == 1
    assert len(svc.list_dossiers()) == 3


def test_sweep_prebuild_never_overwrites_an_existing_dossier(tmp_path, monkeypatch):
    """A species already detected (real sighting_count > 0) must not be
    touched by the prebuild sweep, and doesn't count against its
    budget."""
    svc = _service(tmp_path, monkeypatch)
    svc.on_new_species("Turdus merula", "Amsel", "ev1", "cam1")
    assert svc.get_dossier("Turdus merula")["sighting_count"] == 1

    result = svc.sweep_prebuild(_VOCAB, budget=10)
    # Only the two NOT already present are examined/created.
    assert result == {"examined": 2, "created": 2}
    d = svc.get_dossier("Turdus merula")
    assert d["sighting_count"] == 1  # untouched
    assert d["first_seen_event_id"] == "ev1"  # untouched


def test_sweep_prebuild_skips_a_species_it_already_prebuilt(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    svc.sweep_prebuild(_VOCAB, budget=1)
    assert len(svc.list_dossiers()) == 1
    # Calling again with the same budget makes forward progress, not a
    # repeat of the same one species.
    svc.sweep_prebuild(_VOCAB, budget=1)
    assert len(svc.list_dossiers()) == 2


def test_sweep_prebuild_placeholder_sinks_to_the_end_of_the_gallery(tmp_path, monkeypatch):
    """list_dossiers() is newest-first by first_seen_at; a pre-built,
    never-detected species (first_seen_at=None) must never outrank a
    real sighting in that ordering."""
    svc = _service(tmp_path, monkeypatch)
    svc.on_new_species("Turdus merula", "Amsel", "ev1", "cam1")
    svc.sweep_prebuild(_VOCAB, budget=10)
    ordered = svc.list_dossiers()
    assert ordered[0]["latin"] == "Turdus merula"
    assert ordered[0]["sighting_count"] == 1


def test_sweep_prebuild_ignores_blank_latin_keys(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    vocab = {"": "Kaputt", **_VOCAB}
    result = svc.sweep_prebuild(vocab, budget=10)
    assert result == {"examined": 3, "created": 3}


def test_sweep_prebuild_empty_vocabulary_is_a_noop(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    assert svc.sweep_prebuild({}, budget=10) == {"examined": 0, "created": 0}
    assert svc.sweep_prebuild(None, budget=10) == {"examined": 0, "created": 0}


def test_prebuilt_species_actually_fetches_reference_content(tmp_path, monkeypatch):
    """The whole point of the sweep: a species with zero sightings still
    ends up with real dossier content once its background fetch runs —
    this is what makes a still-locked achievement tile's dossier ready
    to read the instant it's clicked, per the operator's Rotkehlchen ask."""
    svc = _service(tmp_path, monkeypatch, spawn_noop=False)

    def _fake_wiki(latin):
        return {
            "extract": f"{latin} ist ein Singvogel.",
            "title": "Rotkehlchen",
            "thumbnail": {"source": "https://example.invalid/robin.jpg"},
            "content_urls": {"desktop": {"page": "https://example.invalid/wiki/Rotkehlchen"}},
        }

    # Signature follows the service's own call: bird song now comes from
    # Wikimedia Commons FIRST (the article's own recording, no
    # credential) with xeno-canto appended when a key exists, so the
    # fetch takes the wiki summary it already has.
    def _fake_xc(wiki, latin):
        return [
            {
                "id": "1",
                "file_url": "https://example.invalid/song.mp3",
                "type_en": "song",
                "type_de": "Gesang",
                "recordist": "Test Recordist",
                "license_url": "https://example.invalid/license",
                "length": "0:12",
            }
        ]

    def _fake_photos(wiki, latin, want=3):
        return [
            "https://example.invalid/robin.jpg",
            "https://example.invalid/robin-side-view.jpg",
        ]

    monkeypatch.setattr("app.bird_dossiers._fetch_wikipedia", _fake_wiki)
    monkeypatch.setattr("app.bird_dossiers._fetch_bird_audio", _fake_xc)
    monkeypatch.setattr("app.bird_dossiers._fetch_photos", _fake_photos)

    created = svc._create_placeholder("Erithacus rubecula", "Rotkehlchen")
    assert created is True

    # _spawn_fetch runs the real fetch worker on a daemon thread; join it
    # directly via the private worker so the assertion isn't racy.
    svc._fetch_worker("Erithacus rubecula")

    d = svc.get_dossier("Erithacus rubecula")
    assert d["sighting_count"] == 0  # still locked — content only
    assert d["wikipedia_summary"] == "Erithacus rubecula ist ein Singvogel."
    assert d["wikipedia_thumb_url"] == "https://example.invalid/robin.jpg"
    assert d["wikipedia_thumb_url_2"] == "https://example.invalid/robin-side-view.jpg"
    assert len(d["recordings"]) == 1
    assert d["recordings"][0]["recordist"] == "Test Recordist"
    assert d["audio_attribution"] == "Test Recordist"


def test_photo_fetch_receives_the_wikipedia_result(tmp_path, monkeypatch):
    """fetch_photos must be called with the wiki summary dict (it
    needs the page title + host to query the media list) — never blind,
    and never at all when the summary fetch itself missed."""
    svc = _service(tmp_path, monkeypatch)  # spawn_noop=True — one deterministic manual call below
    seen = []

    def _fake_wiki(latin):
        return None

    monkeypatch.setattr("app.bird_dossiers._fetch_wikipedia", _fake_wiki)
    monkeypatch.setattr("app.bird_dossiers._fetch_bird_audio", lambda wiki, latin: [])
    monkeypatch.setattr(
        "app.bird_dossiers._fetch_photos", lambda wiki, latin, want=3: seen.append(wiki) or []
    )

    svc._create_placeholder("Turdus merula", "Amsel")
    svc._fetch_worker("Turdus merula")

    assert seen == [None]  # called once, with the (missed) wiki result
    d = svc.get_dossier("Turdus merula")
    assert d["wikipedia_thumb_url_2"] is None
