"""C9 · /api/system/telegram must map the states the service really emits.

`connected` used to be `state in ("polling", "running", "active")`.
`LifecycleMixin.get_polling_status` never returns "polling" or "running" —
its whole vocabulary is off / starting / active / conflict /
conflict_quarantine / stale. So two thirds of the tuple were dead and
"starting" (bot booting) plus "conflict" (bot up, fighting a stale
getUpdates slot) were reported as disconnected.

Stub-only: no bot, no network, no server. A fake service object stands in
for TelegramService and just hands back a canned status dict.
"""

from __future__ import annotations

import flask
import pytest

from app import app_state
from app.routes.telegram import bp
from app.telegram_bot._lifecycle import LifecycleMixin

# The full state vocabulary of get_polling_status → expected `connected`.
# True == "the instance is up and trying".
STATE_EXPECTATIONS = {
    "active": True,
    "starting": True,
    "conflict": True,
    "off": False,
    "conflict_quarantine": False,
    "stale": False,
}


class _FakeService:
    enabled = True
    _last_push_ts = None

    def __init__(self, state: str):
        self._state = state

    def get_polling_status(self) -> dict:
        return {"state": self._state, "since_seconds": 3, "enabled": True}


@pytest.fixture
def client():
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    return app.test_client()


def _connected(client, monkeypatch, state: str) -> bool:
    monkeypatch.setattr(app_state, "telegram_service", _FakeService(state), raising=False)
    resp = client.get("/api/system/telegram")
    assert resp.status_code == 200
    return resp.get_json()["connected"]


@pytest.mark.parametrize("state,expected", sorted(STATE_EXPECTATIONS.items()))
def test_connected_matches_real_state_vocabulary(client, monkeypatch, state, expected):
    assert _connected(client, monkeypatch, state) is expected


def test_dead_state_strings_are_not_matched(client, monkeypatch):
    """ "polling" / "running" are not states this service can be in.
    Matching them made the endpoint look like it understood states the
    rest of the code never produces."""
    assert _connected(client, monkeypatch, "polling") is False
    assert _connected(client, monkeypatch, "running") is False


def test_documented_states_are_the_ones_the_mixin_documents():
    """Pins the tuple above to the docstring of the real implementation,
    so a new state added to get_polling_status fails here instead of
    silently defaulting to connected=False."""
    doc = LifecycleMixin.get_polling_status.__doc__ or ""
    for state in STATE_EXPECTATIONS:
        assert state in doc, f"{state} missing from get_polling_status docstring"
