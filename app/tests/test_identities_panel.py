"""Die Identitäten-Karte: Ablegen, Vorschlagen, Zurücknehmen — und was
aus der Karte VERSCHWUNDEN ist.

„Aber bitte nimm dir die Identitäten vor und prüf bitte, was in
Identitäten drin ist, weil … aktuell liegt da irgendwas ab, keine Ahnung,
das denkt man, das brauchen wir nicht."

Was dort ablag, war `telegram_actions`: bis zu achtzig Einträge der Form
„menu_root" / „menu_wetter", also jeder Tastendruck im Telegram-Menü. Der
letzte war über vier Monate alt. Der Preis dafür war nicht der Platz,
sondern der Schreibweg — jeder Tastendruck schrieb die settings.json
komplett neu, ausgerechnet die Datei mit Token, Chat-IDs und
RTSP-Kennwörtern. Die Hälfte dieser Datei hält fest, dass er weg bleibt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.cat_identity import IdentityRegistry, profile_crops, profile_samples
from app.routes._identity_helpers import (
    AUTO_MAX_DISTANCE,
    REJECT_BUCKET,
    clear_person,
    file_crop,
    read_crop,
    reject_crop,
    suggest_for,
    walk_person_crops,
)
from app.settings.migrations import migrate_drop_telegram_action_log

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "app" / "app"
_WEB = _REPO / "app" / "web"


class _FakeStore:
    """Nur die zwei Methoden, die das Ablegen anfasst."""

    def __init__(self, events: dict):
        self.events = events

    def get_event(self, cam_id, event_id):
        return self.events.get((cam_id, event_id))

    def update_event(self, cam_id, event_id, event):
        self.events[(cam_id, event_id)] = event


def _write_crop(root: Path, relpath: str, seed: int) -> str:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    cv2.imwrite(str(path), rng.integers(0, 255, size=(48, 32, 3), dtype=np.uint8))
    return relpath


@pytest.fixture()
def bench(tmp_path):
    registry = IdentityRegistry(tmp_path / "person_registry.json")
    store = _FakeStore({("cam_a", "e1"): {"event_id": "e1"}, ("cam_a", "e2"): {"event_id": "e2"}})
    return registry, store, tmp_path


# ── Ablegen ─────────────────────────────────────────────────────────────


def test_filing_a_crop_writes_BOTH_halves(bench):
    """Probe in die Registry UND Name auf das Ereignis. Fehlt die zweite
    Hälfte, bietet derselbe Clip das Gesicht morgen wieder an."""
    registry, store, root = bench
    item = {"relpath": _write_crop(root, "crops/a.jpg", 1), "cam_id": "cam_a", "event_id": "e1"}
    assert file_crop(registry, store, root, item, "Anna")
    profile = registry.get_profile("Anna")
    assert profile_crops(profile) == ["crops/a.jpg"]
    # Die Clip-Kennung wandert mit — ohne sie misst die Güteprüfung
    # später zwei Ausschnitte derselben Sekunde gegeneinander.
    assert profile_samples(profile)[0]["event_id"] == "e1"
    assert store.events[("cam_a", "e1")]["person_name"] == "Anna"


def test_a_hand_filed_crop_is_marked_as_hand_filed(bench):
    """Damit eine automatische Zuordnung später davon zu unterscheiden
    ist — die eine darf man kommentarlos glauben, die andere nicht."""
    registry, store, root = bench
    item = {"relpath": _write_crop(root, "crops/a.jpg", 1), "cam_id": "cam_a", "event_id": "e1"}
    file_crop(registry, store, root, item, "Anna")
    assert store.events[("cam_a", "e1")]["person_source"] == "manual"
    file_crop(registry, store, root, item, "Anna", auto=True)
    assert store.events[("cam_a", "e1")]["person_source"] == "auto"


def test_a_crop_that_is_not_there_files_nothing(bench):
    registry, store, root = bench
    item = {"relpath": "crops/missing.jpg", "cam_id": "cam_a", "event_id": "e1"}
    assert not file_crop(registry, store, root, item, "Anna")
    assert registry.list_profiles() == []
    assert "person_name" not in store.events[("cam_a", "e1")]


def test_a_path_that_climbs_out_of_the_archive_is_refused(bench):
    """Der Pfad kommt aus unserer eigenen Liste, aber er kommt über das
    Netz zurück."""
    _registry, _store, root = bench
    outside = root.parent / "secret.jpg"
    _write_crop(root.parent, "secret.jpg", 1)
    assert outside.exists()
    assert read_crop(root, "../secret.jpg") is None


def test_clearing_takes_the_name_off_the_event(bench):
    """Der Weg zurück aus einer falschen automatischen Zuordnung."""
    _registry, store, _root = bench
    store.events[("cam_a", "e1")].update({"person_name": "Anna", "person_source": "auto"})
    assert clear_person(store, "cam_a", "e1")
    assert "person_name" not in store.events[("cam_a", "e1")]
    assert "person_source" not in store.events[("cam_a", "e1")]
    assert not clear_person(store, "cam_a", "nope")


# ── Vorschlagen ─────────────────────────────────────────────────────────


def test_no_profiles_means_no_suggestions_and_no_disk_reads(bench):
    """Ohne einen einzigen benannten Namen gibt es nichts zu vergleichen —
    dann jedes Bild von der Platte zu holen wäre reine Arbeit für nichts."""
    registry, _store, root = bench
    rows = [{"relpath": _write_crop(root, "crops/a.jpg", 1)}]
    suggest_for(registry, root, rows, 50)
    assert "suggest" not in rows[0]


def test_the_same_picture_again_is_suggested_and_is_confident(bench):
    registry, store, root = bench
    relpath = _write_crop(root, "crops/a.jpg", 7)
    file_crop(registry, store, root, {"relpath": relpath}, "Anna")
    rows = [{"relpath": relpath}]
    suggest_for(registry, root, rows, 50)
    assert rows[0]["suggest"]["name"] == "Anna"
    assert rows[0]["suggest"]["distance"] == 0
    assert rows[0]["suggest"]["confident"] is True


def test_the_automatic_run_is_stricter_than_the_bare_suggestion(bench):
    """Etwas vorzuschlagen und es von allein abzulegen sind zwei
    verschiedene Zusagen — der Abgleich ist Bildähnlichkeit, keine
    Gesichtserkennung."""
    registry, _store, _root = bench
    assert AUTO_MAX_DISTANCE < registry.threshold


def test_the_budget_caps_how_many_pictures_a_run_opens(bench):
    registry, store, root = bench
    file_crop(registry, store, root, {"relpath": _write_crop(root, "crops/a.jpg", 7)}, "Anna")
    rows = [{"relpath": _write_crop(root, f"crops/x{i}.jpg", 7)} for i in range(5)]
    suggest_for(registry, root, rows, 2)
    assert sum(1 for r in rows if "suggest" in r) == 2


# ── Was verschwunden ist ────────────────────────────────────────────────


def test_the_telegram_menu_log_has_no_writer_left():
    """Kein Schreibweg, kein Endpunkt, kein Vorgabewert. Ein einziger
    verbliebener Aufruf brächte das Protokoll in der settings.json
    zurück, ohne dass es je wieder jemand zu sehen bekäme."""
    # Ausgenommen sind die beiden Stellen, die den Schlüssel ENTFERNEN:
    # die Migration selbst und ihr Aufruf beim Laden.
    remover = {Path("app/app/settings/migrations.py"), Path("app/app/settings/store.py")}
    hits = []
    for path in _APP.rglob("*.py"):
        rel = path.relative_to(_REPO)
        text = path.read_text(encoding="utf-8")
        if rel in remover:
            assert "migrate_drop_telegram_action_log" in text
            continue
        if "telegram_actions" in text or re.search(r"\blog_action\b", text):
            hits.append(rel)
    assert not hits, f"der Menü-Mitschnitt lebt noch in {hits}"


def test_the_migration_drops_the_key_once_and_then_says_so(tmp_path):
    data = {"telegram": {"token": "<BOT_TOKEN>"}, "telegram_actions": [{"action": "menu_root"}]}
    assert migrate_drop_telegram_action_log(data) is True
    assert "telegram_actions" not in data
    # Und der Rest der Datei bleibt unangetastet — es ist ein gezieltes
    # `pop`, kein Überschreiben.
    assert data["telegram"] == {"token": "<BOT_TOKEN>"}
    assert migrate_drop_telegram_action_log(data) is False


def test_the_identity_card_hosts_the_panel_and_nothing_else():
    html = (_WEB / "templates" / "partials" / "settings.html").read_text(encoding="utf-8")
    section = html[html.index('id="set-profiles"') :]
    section = section[: section.index("<!-- 6.")]
    assert 'id="identityPanel"' in section
    for gone in ('id="auditPanel"', 'id="catList"', 'id="personList"'):
        assert gone not in section, f"{gone} steht noch in der Identitäten-Karte"


def test_the_panel_stylesheet_is_actually_compiled():
    """LOAD_ORDER ist eine ausdrückliche Liste — eine Datei, die niemand
    einträgt, wird schlicht nicht kompiliert, ohne Fehler und ohne
    Warnung."""
    from app.css_builder import LOAD_ORDER

    assert "41-identities.css" in LOAD_ORDER
    assert (_WEB / "static" / "css" / "41-identities.css").exists()


# ── „das ist gar keine Person" ──────────────────────────────────────────


def test_rejecting_marks_the_crop_and_remembers_the_picture(bench):
    """Zwei Schreibvorgänge, beide nötig: der Vermerk am Ausschnitt holt
    ihn aus dem Stapel, die Probe im Gegenregister sorgt dafür, dass
    derselbe Baumstamm morgen von allein erkannt wird."""
    _registry, store, root = bench
    rejects = IdentityRegistry(root / "reject_registry.json")
    relpath = _write_crop(root, "crops/trunk.jpg", 11)
    store.events[("cam_a", "e1")]["person_crops"] = [{"relpath": relpath, "track_id": "t1"}]
    item = {"relpath": relpath, "cam_id": "cam_a", "event_id": "e1"}

    assert reject_crop(rejects, store, root, item, REJECT_BUCKET)
    assert rejects.get_profile(REJECT_BUCKET) is not None
    crop = store.events[("cam_a", "e1")]["person_crops"][0]
    assert crop["rejected"] is True
    assert crop["rejected_as"] == REJECT_BUCKET


def test_rejecting_does_NOT_relabel_the_event(bench):
    """In einem Clip können eine echte Person und ein Baumstamm
    nebeneinander stehen. „Person" vom Ereignis zu nehmen nähme der
    echten Person ihre Sichtung — die Korrektur gehört an den Ausschnitt,
    nicht an den Clip."""
    _registry, store, root = bench
    rejects = IdentityRegistry(root / "reject_registry.json")
    relpath = _write_crop(root, "crops/trunk.jpg", 11)
    event = store.events[("cam_a", "e1")]
    event.update({"labels": ["motion", "person"], "top_label": "person"})
    event["person_crops"] = [{"relpath": relpath}]
    reject_crop(
        rejects,
        store,
        root,
        {"relpath": relpath, "cam_a": "", "event_id": "e1", "cam_id": "cam_a"},
        REJECT_BUCKET,
    )
    assert event["top_label"] == "person"
    assert event["labels"] == ["motion", "person"]


def test_only_the_named_crop_of_a_clip_is_rejected(bench):
    """Der zweite Ausschnitt desselben Clips — die echte Person — bleibt
    unangetastet."""
    _registry, store, root = bench
    rejects = IdentityRegistry(root / "reject_registry.json")
    trunk = _write_crop(root, "crops/trunk.jpg", 11)
    human = _write_crop(root, "crops/human.jpg", 12)
    store.events[("cam_a", "e1")]["person_crops"] = [{"relpath": trunk}, {"relpath": human}]
    reject_crop(
        rejects, store, root, {"relpath": trunk, "cam_id": "cam_a", "event_id": "e1"}, REJECT_BUCKET
    )
    crops = store.events[("cam_a", "e1")]["person_crops"]
    assert crops[0].get("rejected") is True
    assert "rejected" not in crops[1]


def test_a_rejected_crop_never_comes_back_into_the_pile(bench, tmp_path):
    """Der ganze Punkt des Vermerks am Ereignis."""
    events_dir = tmp_path / "events" / "cam_a"
    events_dir.mkdir(parents=True)
    (events_dir / "e1.json").write_text(
        json.dumps(
            {
                "event_id": "e1",
                "camera_id": "cam_a",
                "time": "2026-09-13T10:00:00",
                "person_crops": [
                    {"relpath": "crops/trunk.jpg", "rejected": True},
                    {"relpath": "crops/human.jpg"},
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = walk_person_crops(tmp_path / "events", only_unnamed=True)
    assert [r["relpath"] for r in rows] == ["crops/human.jpg"]


def test_a_known_reject_is_flagged_and_gets_no_name_suggested(bench):
    """DIE Ersparnis: derselbe Baumstamm steht morgen wieder da. Er wird
    markiert statt benannt — für etwas, von dem der Betreiber gesagt hat,
    es sei kein Mensch, einen Namen vorzuschlagen wäre die falsche
    Frage."""
    registry, store, root = bench
    rejects = IdentityRegistry(root / "reject_registry.json")
    trunk = _write_crop(root, "crops/trunk.jpg", 11)
    # Dieselbe Person ist auch bekannt — der Vorschlag würde also greifen.
    file_crop(registry, store, root, {"relpath": trunk}, "Anna")
    reject_crop(rejects, store, root, {"relpath": trunk}, REJECT_BUCKET)

    rows = [{"relpath": trunk}]
    suggest_for(registry, root, rows, 50, rejects)
    assert rows[0]["reject"]["name"] == REJECT_BUCKET
    assert "suggest" not in rows[0], "die Ablehnung steht vor dem Vorschlag"


def test_without_a_reject_register_nothing_changes(bench):
    registry, store, root = bench
    relpath = _write_crop(root, "crops/a.jpg", 7)
    file_crop(registry, store, root, {"relpath": relpath}, "Anna")
    rows = [{"relpath": relpath}]
    suggest_for(registry, root, rows, 50, IdentityRegistry(root / "empty.json"))
    assert rows[0]["suggest"]["name"] == "Anna"


def test_an_unreadable_crop_is_not_silently_recorded(bench):
    _registry, store, root = bench
    rejects = IdentityRegistry(root / "reject_registry.json")
    assert not reject_crop(rejects, store, root, {"relpath": "crops/nope.jpg"}, REJECT_BUCKET)
    assert rejects.list_profiles() == []
