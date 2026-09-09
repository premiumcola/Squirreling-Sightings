"""Species-level confirmation on a bird question/alarm.

Before this, a bird caption only ever asked "Vermutung: Vogel · 72 % —
War das richtig?" — the specific species guess (`bird_species`, already
computed and sitting on the event before the message goes out) was
never shown or confirmable, so the operator's own request — "please
suggest something to me, and ask me about the species" — had nothing to
answer with in Telegram.

These tests drive the real async callback handlers through
`asyncio.run`, against a real `EventStore` on disk, mirroring
`test_telegram_verdict_corrects_event.py`'s pattern — no mock of the
method under test, only of the Telegram `CallbackQuery`.
"""

from __future__ import annotations

import asyncio
import json

from app.species_video_count import confirmed_video_count
from app.storage import EventStore
from app.telegram_bot import TelegramService
from app.telegram_bot._outbound._event_alert import _event_buttons
from app.telegram_bot._outbound._question import question_markup, species_correction_markup

CAM_ID = "cam_nutbar"
EVENT_ID = "20260909-120000-000001"


class _SettingsStub:
    """Just enough of SettingsStore for _event_context/_mark_judged."""

    def __init__(self):
        self.runtime = {}

    def runtime_get(self, key, default=None):
        return self.runtime.get(key, default)

    def runtime_set(self, key, value):
        self.runtime[key] = value

    def runtime_get_subkey(self, key, subkey, default=None):
        return (self.runtime.get(key) or {}).get(subkey, default)

    def runtime_set_subkey_lru(self, key, subkey, value, _cap):
        self.runtime.setdefault(key, {})[subkey] = value


class _FakeQuery:
    """Enough of a Telegram CallbackQuery for the handlers under test."""

    def __init__(self):
        self.markups = []
        self.answers = []

    async def edit_message_reply_markup(self, reply_markup=None):
        self.markups.append(reply_markup)

    async def answer(self, text=None):
        self.answers.append(text)


def _make_service(tmp_storage_root, store, *, label="bird", score=0.72):
    global_cfg = {"storage": {"root": str(tmp_storage_root)}, "cameras": [], "telegram": {}}
    settings = _SettingsStub()
    settings.runtime_set("alert_index", {EVENT_ID: {"cam": CAM_ID, "label": label, "score": score}})
    return TelegramService(
        cfg={},  # enabled=False — no real Bot/network needed for this path
        store=store,
        runtimes={},
        global_cfg=lambda: global_cfg,
        settings_store=settings,
    )


def _seed_event(store, **overrides):
    payload = {
        "event_id": EVENT_ID,
        "labels": ["bird"],
        "top_label": "bird",
        "bird_species": "Elster",
        "species_candidates": [
            {"name": "Elster", "latin": "Pica pica", "score": 0.59},
            {"name": "Kohlmeise", "latin": "Parus major", "score": 0.31},
            {"name": "Elster", "latin": "Pica pica", "score": 0.59},  # duplicate, must collapse
            {"name": None, "latin": "sp.", "score": 0.10},  # untranslated, must be dropped
        ],
        "time": "2026-09-09T12:00:00",
    }
    payload.update(overrides)
    store.add_event(CAM_ID, payload)
    return payload


def _counts(root) -> dict:
    p = root / "species_video_counts.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ── the caption/keyboard know the species ────────────────────────────────


def test_question_markup_offers_the_species_row_only_when_known():
    with_species = question_markup("e1", species_known=True)
    without = question_markup("e1", species_known=False)
    assert any("sp" in btn[1].split(":") for row in with_species for btn in row)
    assert not any("sp" in btn[1].split(":") for row in without for btn in row)


def test_event_buttons_offers_the_species_row_only_when_known():
    with_species = _event_buttons("e1", CAM_ID, False, "", species_known=True)
    without = _event_buttons("e1", CAM_ID, False, "", species_known=False)
    assert any("sp" in btn[1].split(":") for row in with_species for btn in row)
    assert not any("sp" in btn[1].split(":") for row in without for btn in row)


# ── the picker itself ─────────────────────────────────────────────────


def test_the_picker_dedupes_drops_untranslated_and_excludes_the_current_guess():
    candidates = [
        {"name": "Elster", "latin": "Pica pica", "score": 0.59},
        {"name": "Kohlmeise", "latin": "Parus major", "score": 0.31},
        {"name": "Elster", "latin": "Pica pica", "score": 0.59},
        {"name": None, "latin": "sp.", "score": 0.10},
    ]
    rows = species_correction_markup("e1", candidates, "Elster")
    names = [row[0][0] for row in rows]
    assert names == ["Kohlmeise", "❓ unsicher, welche genau", "← zurück"]


def test_the_picker_caps_at_five_species_rows():
    candidates = [{"name": f"Art{i}", "latin": f"lat{i}", "score": 0.5} for i in range(9)]
    rows = species_correction_markup("e1", candidates, None)
    species_rows = rows[:-2]  # drop the fixed "unsicher" + "zurück" rows
    assert len(species_rows) == 5


# ── "Ja" on a bird question confirms the species too ────────────────────


def test_ja_on_a_bird_event_counts_the_guessed_species(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    asyncio.run(svc._cb_verdict(_FakeQuery(), EVENT_ID, "ok"))

    assert confirmed_video_count(tmp_storage_root, "Elster") == 1
    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["confirmed"] is True
    assert updated["bird_species"] == "Elster"  # unchanged — the guess stood


def test_nein_on_a_bird_event_counts_nothing(tmp_storage_root):
    """Disputing the whole detection is not a confirmation of anything."""
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    asyncio.run(svc._cb_verdict(_FakeQuery(), EVENT_ID, "no"))

    assert _counts(tmp_storage_root) == {}


def test_ja_on_a_non_bird_event_is_unaffected(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store, labels=["cat"], top_label="cat", bird_species=None)
    svc = _make_service(tmp_storage_root, store, label="cat")

    asyncio.run(svc._cb_verdict(_FakeQuery(), EVENT_ID, "ok"))

    assert _counts(tmp_storage_root) == {}


# ── picking a corrected species ──────────────────────────────────────────


def test_picking_a_different_species_corrects_the_event_and_counts_it(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    asyncio.run(svc._handle_species_cb(_FakeQuery(), EVENT_ID, "Kohlmeise"))

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["bird_species"] == "Kohlmeise"
    assert updated["confirmed"] is True
    assert confirmed_video_count(tmp_storage_root, "Kohlmeise") == 1
    # The original (wrong) guess must NOT gain a count from this.
    assert confirmed_video_count(tmp_storage_root, "Elster") == 0


def test_species_unsure_confirms_the_bird_but_counts_no_species(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    asyncio.run(svc._handle_species_cb(_FakeQuery(), EVENT_ID, "none"))

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["confirmed"] is True
    assert updated["bird_species"] == "Elster"  # left as the original guess, just unconfirmed
    assert _counts(tmp_storage_root) == {}


def test_species_back_does_not_book_any_verdict(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    q = _FakeQuery()
    asyncio.run(svc._handle_species_cb(q, EVENT_ID, "back"))

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated.get("confirmed") is not True
    assert _counts(tmp_storage_root) == {}
    assert q.markups  # the keyboard was restored


def test_a_species_pick_after_the_event_is_already_judged_is_refused(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)
    asyncio.run(svc._cb_verdict(_FakeQuery(), EVENT_ID, "ok"))

    asyncio.run(svc._handle_species_cb(_FakeQuery(), EVENT_ID, "Kohlmeise"))

    # The second (species) tap must not add a second count on top.
    assert confirmed_video_count(tmp_storage_root, "Elster") == 1
    assert confirmed_video_count(tmp_storage_root, "Kohlmeise") == 0


def test_the_menu_opens_without_recording_anything(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    q = _FakeQuery()
    asyncio.run(svc._handle_species_cb(q, EVENT_ID, None))

    assert q.markups
    assert store.get_event(CAM_ID, EVENT_ID).get("confirmed") is not True
    assert _counts(tmp_storage_root) == {}
