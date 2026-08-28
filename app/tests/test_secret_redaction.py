"""Pins the credential-redaction contract for the settings API.

Two things must hold together, or the Chrome "Passwort speichern"
fix silently eats the operator's Telegram bot token:

1. Responses carry ``<key>_set`` booleans, never the secret. The app
   has no authentication and the dashboard polls /api/config every
   few seconds, so anything in that body is on the wire in cleartext.
2. An OMITTED key on save means "unchanged"; an explicit empty string
   means "cleared". The client renders an empty password input with an
   "unverändert" placeholder, so without rule 2 every save of the
   Telegram tab would wipe the token.

IPs / tokens here are documentation placeholders only.
"""

from __future__ import annotations

import sys
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.routes._camera_helpers import redact_secrets  # noqa: E402

# Same placeholder shape the settings.html field already uses, kept
# short enough that the public-repo secret audit does not flag it.
_FAKE_TOKEN = "123456789:AAExampleBotToken"


def test_redact_secrets_replaces_value_with_boolean():
    out = redact_secrets({"enabled": True, "token": _FAKE_TOKEN}, ("token",))
    assert "token" not in out
    assert out["token_set"] is True
    assert out["enabled"] is True


def test_redact_secrets_does_not_mutate_source():
    src = {"password": "hunter2"}
    redact_secrets(src, ("password",))
    assert src == {"password": "hunter2"}


def test_redact_secrets_reports_false_for_empty_and_missing():
    assert redact_secrets({}, ("token",))["token_set"] is False
    assert redact_secrets({"token": ""}, ("token",))["token_set"] is False


def test_omitted_key_keeps_stored_secret(settings_store):
    """Empty password field → client omits the key → token survives."""
    settings_store.update_section("telegram", {"enabled": True, "token": _FAKE_TOKEN})
    assert settings_store.data["telegram"]["token"] == _FAKE_TOKEN

    # A save with the token field left blank sends everything BUT the key.
    settings_store.update_section("telegram", {"enabled": False, "chat_id": "-100123456"})

    reloaded = settings_store.data["telegram"]
    assert reloaded["token"] == _FAKE_TOKEN, "omitted key must mean 'unchanged'"
    assert reloaded["enabled"] is False
    assert reloaded["chat_id"] == "-100123456"


def test_explicit_empty_string_clears_secret(settings_store):
    """The distinction the omission semantic rests on: '' still clears."""
    settings_store.update_section("telegram", {"token": _FAKE_TOKEN})
    settings_store.update_section("telegram", {"token": ""})
    assert settings_store.data["telegram"]["token"] == ""


def test_mqtt_password_follows_the_same_two_rules(settings_store):
    settings_store.update_section("mqtt", {"host": "mqtt.example", "password": "hunter2"})
    settings_store.update_section("mqtt", {"host": "broker.example"})
    assert settings_store.data["mqtt"]["password"] == "hunter2"
    assert settings_store.data["mqtt"]["host"] == "broker.example"

    redacted = redact_secrets(settings_store.data["mqtt"], ("password",))
    assert "password" not in redacted
    assert redacted["password_set"] is True

    settings_store.update_section("mqtt", {"password": ""})
    assert settings_store.data["mqtt"]["password"] == ""
