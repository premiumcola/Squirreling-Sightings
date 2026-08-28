"""The "Jetzt bereinigen" button may not be a way around its own guard.

The nightly sweep defers a NARROWED retention window: if settings.json
now says 7 days where config.yaml said 14, deleting on 7 would remove
everything in between, permanently and unasked. So the sweep keeps the
wider window, logs a warning, and waits for the operator to confirm the
new number.

The attended path had no such deferral. An empty retention field posts
`{}`, so `override` was None, `nightly_window` was skipped entirely, and
the narrow window ran immediately — the button deleted what the timer
was still refusing to. And a click on a number the operator never typed
is not a confirmation of it.

Confirmation is now exactly one thing: pressing the button with an
explicit `retention_days`. Without one, the button may delete no more
than the nightly sweep already would.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

from app import app_state, maintenance
from app.routes import media as media_routes
from app.storage import EventStore

CAM = "reolink_rlc811a_squirreltownnutbar_183"

# settings.json says 7; config.yaml — what the sweep enforced before
# settings entered the resolution order — says 14.
NARROW, WIDE = 7, 14


@pytest.fixture
def calls(monkeypatch, tmp_storage_root: Path):
    """Flask client over the media blueprint; records cleanup_old's arg."""
    seen: list[int] = []
    store = EventStore(str(tmp_storage_root))
    monkeypatch.setattr(store, "cleanup_old", lambda days: seen.append(days) or 0)

    app = Flask(__name__)
    app.register_blueprint(media_routes.bp)
    monkeypatch.setattr(app_state, "store", store, raising=False)
    monkeypatch.setattr(app_state, "storage_root", tmp_storage_root, raising=False)
    monkeypatch.setattr(
        app_state, "settings", SimpleNamespace(get_review=lambda _k: None), raising=False
    )
    # Nothing has been acknowledged yet, so nightly_window falls back to
    # the config.yaml baseline as "what was last enforced".
    monkeypatch.setattr(maintenance, "config_retention_days", lambda: WIDE)
    monkeypatch.setattr(
        maintenance, "resolve_retention_days", lambda override=None: int(override or NARROW)
    )
    return SimpleNamespace(client=app.test_client(), seen=seen)


def test_an_empty_field_does_not_confirm_a_narrowed_window(calls):
    """THE regression test — pre-fix this swept on 7 instead of 14."""
    r = calls.client.post("/api/media/cleanup", json={})
    assert r.status_code == 200
    assert calls.seen == [
        WIDE
    ], f"an unconfirmed narrowing must keep the wider window, sweep used {calls.seen}"
    assert (
        r.get_json()["retention_days"] == WIDE
    ), "the response must report what was actually enforced, not what was asked"


def test_an_explicit_number_is_the_confirmation(calls):
    """Typing the number and pressing the button is the operator's consent."""
    r = calls.client.post("/api/media/cleanup", json={"retention_days": NARROW})
    assert r.status_code == 200
    assert calls.seen == [NARROW]
    assert r.get_json()["retention_days"] == NARROW


def test_a_widening_needs_no_confirmation(calls, monkeypatch):
    """The guard only ever defers deleting MORE. Keeping more is free."""
    monkeypatch.setattr(
        maintenance, "resolve_retention_days", lambda override=None: int(override or 30)
    )
    calls.client.post("/api/media/cleanup", json={})
    assert calls.seen == [30]
