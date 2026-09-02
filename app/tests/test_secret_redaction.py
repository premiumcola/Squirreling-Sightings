"""Pins the credential boundary between settings.json and the browser.

The box serves plain HTTP on the LAN with no authentication and the
dashboard polls ``/api/config`` and ``/api/cameras`` every few seconds.
Every secret either response carries is therefore a cleartext secret on
the wire, in every browser cache, and — once it lands in a
``type=password`` input — in Chrome's password manager.

Three separate things have to hold together or a fix to one of them
breaks another:

1. **Nothing leaves.** Responses carry ``<key>_set`` booleans and
   credential-free URLs, never a password and never a ``user:pass@``
   userinfo.
2. **Nothing is lost.** An OMITTED key on save means "unchanged" and the
   server puts the stored secret back — including back INTO the
   credential-free URL the browser just sent it. Without this, the very
   first ordinary camera save wipes the RTSP password of three cameras.
3. **Clearing is still possible.** An explicit ``""`` clears, and the UI
   has a control that can actually produce one. The three-state contract
   is worthless if the browser can only ever emit two of the states.

IPs / tokens here are documentation placeholders only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app.routes._secrets import (  # noqa: E402
    CAMERA_URL_KEYS,
    mask_url_password,
    merge_camera_secrets,
    redact_camera,
    redact_secrets,
    set_url_password,
    strip_url_password,
)

WEB = Path(__file__).resolve().parent.parent / "web"
JS = WEB / "static" / "js"

# Same placeholder shape the settings.html field already uses, kept
# short enough that the public-repo secret audit does not flag it.
_FAKE_TOKEN = "123456789:AAExampleBotToken"
_PW = "hunter2"
_RTSP = f"rtsp://admin:{_PW}@192.0.2.10:554/h264Preview_01_main"
_SNAP = f"http://admin:{_PW}@192.0.2.10/cgi-bin/snapshot.cgi"


def _stored_cam() -> dict:
    return {
        "id": "reolink_rlc810a_hof_10",
        "name": "Hof",
        "username": "admin",
        "password": _PW,
        "rtsp_url": _RTSP,
        "snapshot_url": _SNAP,
        "zones": [],
    }


# ── 1 · nothing leaves ───────────────────────────────────────────────────


def test_redact_secrets_replaces_value_with_boolean():
    out = redact_secrets({"enabled": True, "token": _FAKE_TOKEN}, ("token",))
    assert "token" not in out
    assert out["token_set"] is True
    assert out["enabled"] is True


def test_redact_secrets_does_not_mutate_source():
    src = {"password": _PW}
    redact_secrets(src, ("password",))
    assert src == {"password": _PW}


def test_redact_secrets_reports_false_for_empty_and_missing():
    assert redact_secrets({}, ("token",))["token_set"] is False
    assert redact_secrets({"token": ""}, ("token",))["token_set"] is False


def test_redacted_camera_carries_no_password_anywhere():
    """The /api/config + /api/cameras payload shape. The password used to
    ship twice per camera: once as `password`, once inside `rtsp_url`."""
    out = redact_camera(_stored_cam())
    assert "password" not in out
    assert out["password_set"] is True
    assert out["rtsp_url"] == "rtsp://admin@192.0.2.10:554/h264Preview_01_main"
    assert out["snapshot_url"] == "http://admin@192.0.2.10/cgi-bin/snapshot.cgi"
    assert _PW not in repr(out)


def test_redaction_keeps_what_the_browser_actually_reads():
    """The constraint on the fix: strip the secret, not the field. The
    HD / fullscreen / simulate buttons key off `rtsp_url` truthiness, the
    discovery de-dupe off its hostname, the sun-timelapse vendor check
    off its path."""
    out = redact_camera(_stored_cam())
    assert out["rtsp_url"]
    assert "192.0.2.10" in out["rtsp_url"]
    assert out["rtsp_url"].endswith("/h264Preview_01_main")
    assert out["username"] == "admin"


def test_strip_leaves_credential_free_urls_untouched():
    assert strip_url_password("rtsp://192.0.2.10/live") == "rtsp://192.0.2.10/live"
    assert strip_url_password("") == ""
    assert strip_url_password("not a url") == "not a url"


def test_mask_shows_the_shape_without_the_secret():
    masked = mask_url_password(_RTSP)
    assert masked == "rtsp://admin:•••@192.0.2.10:554/h264Preview_01_main"
    assert _PW not in masked


# ── 2 · nothing is lost ──────────────────────────────────────────────────


def test_omitted_password_restores_the_stored_one():
    """The catastrophic case. The browser is handed a credential-free
    URL and a boolean, so an ordinary save carries neither — and both
    have to come back or three cameras go offline."""
    stored = _stored_cam()
    payload = redact_camera(stored)  # exactly what the client got back
    merge_camera_secrets(payload, stored)
    assert payload["password"] == _PW
    assert payload["rtsp_url"] == _RTSP
    assert payload["snapshot_url"] == _SNAP


def test_merge_drops_the_response_only_marker():
    """`password_set` is a response artefact. The partial-save paths
    build their payload by spreading the cached camera record, so it
    arrives on every one of them and must never reach settings.json."""
    stored = _stored_cam()
    payload = redact_camera(stored)
    assert "password_set" in payload
    merge_camera_secrets(payload, stored)
    assert "password_set" not in payload


def test_merge_is_idempotent_so_conn_changed_stays_false():
    """The camera-restart trigger compares payload vs stored for the
    connection fields. A round trip that did not restore byte-for-byte
    would restart the camera on every partial save."""
    stored = _stored_cam()
    payload = merge_camera_secrets(redact_camera(stored), stored)
    for field in CAMERA_URL_KEYS:
        assert payload[field] == stored[field]


def test_typed_password_replaces_and_reaches_the_url():
    stored = _stored_cam()
    payload = redact_camera(stored)
    payload["password"] = "neuespasswort"
    merge_camera_secrets(payload, stored)
    assert payload["password"] == "neuespasswort"
    assert "neuespasswort@192.0.2.10" in payload["rtsp_url"].replace("admin:", "")


def test_a_hand_edited_url_with_its_own_credentials_wins():
    """set_url_password only fills an EMPTY userinfo password — a
    snapshot URL deliberately pointing at a second account keeps it."""
    stored = _stored_cam()
    payload = redact_camera(stored)
    payload["snapshot_url"] = "http://viewer:andere@192.0.2.10/cgi-bin/snapshot.cgi"
    merge_camera_secrets(payload, stored)
    assert payload["snapshot_url"] == "http://viewer:andere@192.0.2.10/cgi-bin/snapshot.cgi"


def test_set_url_password_is_a_noop_without_a_username():
    assert set_url_password("rtsp://192.0.2.10/live", _PW) == "rtsp://192.0.2.10/live"


# ── 3 · clearing is possible, and reachable from the UI ──────────────────


def test_explicit_empty_string_clears_the_camera_password():
    stored = _stored_cam()
    payload = redact_camera(stored)
    payload["password"] = ""
    merge_camera_secrets(payload, stored)
    assert payload["password"] == ""
    assert payload["rtsp_url"] == "rtsp://admin@192.0.2.10:554/h264Preview_01_main"


def test_omitted_key_keeps_stored_secret(settings_store):
    """Empty token field → client omits the key → token survives."""
    settings_store.update_section("telegram", {"enabled": True, "token": _FAKE_TOKEN})
    assert settings_store.data["telegram"]["token"] == _FAKE_TOKEN

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
    settings_store.update_section("mqtt", {"host": "mqtt.example", "password": _PW})
    settings_store.update_section("mqtt", {"host": "broker.example"})
    assert settings_store.data["mqtt"]["password"] == _PW
    assert settings_store.data["mqtt"]["host"] == "broker.example"

    redacted = redact_secrets(settings_store.data["mqtt"], ("password",))
    assert "password" not in redacted
    assert redacted["password_set"] is True

    settings_store.update_section("mqtt", {"password": ""})
    assert settings_store.data["mqtt"]["password"] == ""


# ── The client half of the contract ──────────────────────────────────────
#
# No JS runner in CI, so the three callsites that decide what actually
# leaves the browser are pinned from here. Each of these was, or would
# silently become, a data-loss bug.


def _js(*parts: str) -> str:
    return (JS.joinpath(*parts)).read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("//"))


def _bootstrap_src() -> str:
    """Every line of the bootstrap route package, concatenated.

    Was a single ``routes/bootstrap.py`` until the module outgrew the
    file ceiling and became a package. Reading the whole package keeps
    the assertions below pinned to the behaviour rather than to which
    concern module happens to host the line today.
    """
    pkg = Path(_pkg_root) / "app" / "routes" / "bootstrap"
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(pkg.rglob("*.py")))


def test_camera_form_never_sends_a_raw_empty_password():
    """`password: f['rtsp_pass'].value || ''` plus a server that reads ''
    as "clear" is the three-cameras-offline bug: the field is empty on
    every hydrate because the server no longer ships the secret."""
    src = _strip_comments(_js("camedit", "discovery.js"))
    assert "password: f['rtsp_pass']" not in src
    assert "applySecretField" in src


def test_every_secret_input_goes_through_the_shared_field_helper():
    for module, field in (
        ("telegram.js", "tg_token"),
        ("camedit/mqtt-settings.js", "mqtt_password"),
    ):
        src = _strip_comments(_js(*module.split("/")))
        assert "applySecretField" in src, module
        assert "hydrateSecretField" in src, module
        assert field in src, module


def test_secret_field_helper_can_emit_the_empty_string():
    """A3/A4 · without a control that produces '', an operator who
    mistyped a bot token cannot remove it from the UI at all — and the
    server-side clear path is unreachable dead code."""
    src = _strip_comments(_js("chrome", "secret-field.js"))
    assert "dataset.cleared" in src
    assert "registerAction('clearSecretField'" in src
    assert "return { changed: true, value: '' }" in src


def test_the_clear_button_exists_for_all_three_secret_inputs():
    templates = WEB / "templates" / "partials"
    pages = {
        "settings.html": ("tg_token", "mqtt_password"),
        "cam_edit/verbindung.html": ("rtsp_pass",),
    }
    for page, fields in pages.items():
        html = (templates / page).read_text(encoding="utf-8")
        for field in fields:
            assert f'data-field="{field}"' in html, f"{page}:{field}"


def test_password_inputs_opt_out_of_the_chrome_manager():
    """A3 · a populated type=password next to a populated username is
    the pair Chrome offers to save. autocomplete="off" is documented as
    ignored for password fields; new-password is the form it honours."""
    templates = WEB / "templates" / "partials"
    for page in ("settings.html", "cam_edit/verbindung.html"):
        html = (templates / page).read_text(encoding="utf-8")
        for block in re.findall(r"<input[^>]*type=\"password\"[^>]*>", html, flags=re.S):
            assert 'autocomplete="new-password"' in block, f"{page}: {block[:80]}"


def test_connection_save_does_not_echo_the_message_format():
    """A5 · /api/config never shipped telegram.format, so
    `(state.config?.telegram || {}).format || 'photo'` resolved to
    'photo' on every connection save and silently reset a video/text
    choice. Both halves are fixed; both are pinned."""
    src = _strip_comments(_js("telegram.js"))
    # Just the telegramForm submit handler, up to the next listener.
    submit = src.split("byId('telegramForm')")[1].split("document.querySelectorAll")[0]
    assert "format" not in submit, submit
    # The format radios keep their own save button, which is the only
    # place the key may be written.
    assert "{ telegram: { format: fmt } }" in src
    bootstrap = _bootstrap_src()
    assert '"format": c.get("telegram", {}).get("format", "photo")' in bootstrap


def test_the_config_endpoint_redacts_its_camera_list():
    """The leak this whole module exists for, at its widest point:
    /api/config is unauthenticated, polled by live-update.js on every
    dashboard tick, and used to return the full camera list."""
    src = _bootstrap_src()
    assert '"cameras": [redact_camera(cam) for cam in c.get("cameras", [])]' in src
    assert '"cameras": c.get("cameras", [])' not in src


# ── the cam-edit "eye": JS reassembly must mirror set_url_password ────────
#
# The browser is handed a credential-free URL and rebuilds the displayed
# one itself after fetching the password via /reveal-secret. If the two
# sides disagree, the operator is shown a URL that is not the one the
# server would build — the exact class of confusion the masking refactor
# was meant to end. Same bit-for-bit-mirror rule as camera_id/buildCameraId.

_MIRROR_CASES = [
    ("rtsp://admin@cam.lan:554/h265Preview_01_main", "pw123"),
    ("http://admin@cam.lan/cgi-bin/snapshot.cgi", "pw123"),
    # Already carries a password — hand-edited, must be left alone.
    ("rtsp://admin:other@cam.lan/x", "pw123"),
    # No username — nothing to authenticate.
    ("rtsp://cam.lan/x", "pw123"),
    # No password stored — nothing to add.
    ("rtsp://admin@cam.lan/x", ""),
]


def test_js_with_password_mirrors_set_url_password():
    import json as _json

    import pytest as _pytest

    from app.routes._secrets import set_url_password

    from ._node_js import NODE_AVAILABLE
    from ._node_js import run_js as _js

    if not NODE_AVAILABLE:
        _pytest.skip("node not installed")

    cases = _json.dumps(_MIRROR_CASES)
    got = _js(
        f"""
        const mod = await import(JS + '/camedit/rtsp.js');
        const cases = {cases};
        console.log(JSON.stringify(cases.map(([u, p]) => mod._withPassword(u, p))));
        """
    )
    expected = [set_url_password(u, p) for u, p in _MIRROR_CASES]
    assert got == expected
