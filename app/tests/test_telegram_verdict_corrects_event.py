"""A Telegram "❌ Nein" / "war etwas anderes" must correct the EVENT
itself, not just the diagnostic ledger and the threshold-tuning archive.

Traced bug: `_book_verdict` wrote `detection_feedback.record_verdict`
and `net_archive.append_verdict` on every branch, and only stamped the
event's own `confirmed`/`confirmed_at` when the verdict was "ok"
(`_stamp_confirmed`). A "Nein" on a cat false-positive therefore left
the event's own `labels: ["cat"]` standing forever — the Mediathek
badge, the label filters and the achievement counters all derive
`labels` straight off the event on every render, so nothing downstream
ever saw the correction, exactly as the operator described: "es müsste
... unbekannt oder unklar oben hingeschrieben werden."

These tests drive the real `TelegramService._book_verdict` (the method
both `_cb_verdict` and `_cb_corrected` call) against a real `EventStore`
on disk — no mock of the method under test.
"""

from __future__ import annotations

from app.storage import EventStore
from app.telegram_bot import TelegramService

CAM_ID = "cam_squirrel_town"
EVENT_ID = "20260830-120000-000001"


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


def _make_service(tmp_storage_root, store):
    global_cfg = {"storage": {"root": str(tmp_storage_root)}, "cameras": [], "telegram": {}}
    settings = _SettingsStub()
    # Seeds _event_context: alert_index is what a real push writes before
    # the question/alarm goes out (see _outbound._question / _outbound
    # publish path) — without it the callback has no camera/label to act
    # on, same as a tap arriving after the 200-entry LRU has rolled over.
    settings.runtime_set("alert_index", {EVENT_ID: {"cam": CAM_ID, "label": "cat", "score": 0.71}})
    svc = TelegramService(
        cfg={},  # enabled=False — no real Bot/network needed for this path
        store=store,
        runtimes={},
        global_cfg=lambda: global_cfg,
        settings_store=settings,
    )
    return svc


def _seed_event(store, **overrides):
    payload = {
        "event_id": EVENT_ID,
        "labels": ["cat"],
        "top_label": "cat",
        "cat_name": "Whiskers",
        "time": "2026-08-30T12:00:00",
    }
    payload.update(overrides)
    store.add_event(CAM_ID, payload)
    return payload


def test_a_no_verdict_removes_the_disproven_label(tmp_storage_root):
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    svc._book_verdict(EVENT_ID, correct=False, source="telegram")

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert "cat" not in updated["labels"]
    # The residual bucket this codebase already uses for "no recognized
    # class" — see labels.primary_label / event_relabel's docstring.
    assert updated["top_label"] == "motion"


def test_a_no_verdict_clears_the_stale_cat_identity(tmp_storage_root):
    """Regression guard for the operator's exact complaint: a disproven
    cat must not keep pinning a cat identity name, or a `label=cat`
    filter still matches the event through `extras` even once the
    badge stops showing "Katze"."""
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    svc._book_verdict(EVENT_ID, correct=False, source="telegram")

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated.get("cat_name") is None


def test_a_correction_relabels_the_event_to_the_true_class(tmp_storage_root):
    """ "War etwas anderes" → Eichhörnchen: the event must end up filed
    as a squirrel, not left as a wrong cat nor blanked to nothing."""
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    svc._book_verdict(EVENT_ID, correct=False, source="telegram_q", corrected="squirrel")

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["labels"] == ["squirrel"]
    assert updated["top_label"] == "squirrel"
    assert updated.get("cat_name") is None


def test_an_ok_verdict_still_confirms_without_touching_labels(tmp_storage_root):
    """Guard against a regression the other way: a real "Ja" must keep
    stamping confirmed/confirmed_at (_stamp_confirmed) and must not run
    the correction path at all."""
    store = EventStore(str(tmp_storage_root))
    _seed_event(store)
    svc = _make_service(tmp_storage_root, store)

    svc._book_verdict(EVENT_ID, correct=True, source="telegram")

    updated = store.get_event(CAM_ID, EVENT_ID)
    assert updated["confirmed"] is True
    assert updated["labels"] == ["cat"]
    assert updated.get("cat_name") == "Whiskers"
