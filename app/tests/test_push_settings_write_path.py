"""The Telegram push panel must POST to a route that exists.

The whole "Was senden" / "Wann senden" panel — quiet hours, night-alert
escalation, per-label push flags, daily report, highlight, system and
weather pushes — wrote to ``/api/settings/telegram/push``. That route was
never registered: the pre-ES-module code posted ``{telegram: {push: …}}``
to ``/api/settings/app``, and the refactor invented a URL for the subtree
instead. Every save 404'd.

It failed invisibly, which is the worse half: ``savePushCfg`` merged the
new value into ``state.config`` before the await and had no ``catch``, so
the switch stayed flipped and the next ``/api/bootstrap`` quietly put it
back. Nothing in the UI, and nothing in the log, said the setting had not
been stored.

Three things are pinned here:

* the URL half — every ``/api/settings/...`` literal in the frontend
  resolves against the routes Flask actually registers, so "the two
  halves disagree about a string" cannot happen silently again;
* the write half — the save posts the nested ``{telegram: {push: …}}``
  shape, and ``update_section`` deep-merges it onto settings.json without
  wiping the siblings the client did not echo back;
* the failure half — a rejected save rolls its optimistic in-memory
  value back instead of leaving the UI showing a change that was lost.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import flask
import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "js"

# Static URL literals only: a template literal carrying `${…}` is built at
# runtime and has no single path to pin.
_URL_LITERAL = re.compile(r"""['"`](/api/settings/[A-Za-z0-9/_-]*)['"`]""")


def _registered_paths() -> set[str]:
    """Every static rule path the real blueprint set registers."""
    from app.routes import register_blueprints

    app = flask.Flask(__name__)
    register_blueprints(app)
    return {str(r) for r in app.url_map.iter_rules() if "<" not in str(r)}


def _frontend_settings_urls() -> dict[str, list[str]]:
    """``url -> [source files]`` for every settings URL the frontend names."""
    found: dict[str, list[str]] = {}
    for path in sorted(_JS_DIR.rglob("*.js")):
        for url in _URL_LITERAL.findall(path.read_text(encoding="utf-8")):
            found.setdefault(url, []).append(str(path.relative_to(_JS_DIR)))
    return found


def test_every_settings_url_the_frontend_names_is_a_registered_route():
    """The regression that let this ship: nobody compared the two lists."""
    registered = _registered_paths()
    unknown = {
        url: files for url, files in _frontend_settings_urls().items() if url not in registered
    }
    assert not unknown, (
        "frontend posts to settings routes the backend does not register: "
        f"{unknown} — registered: {sorted(p for p in registered if '/api/settings' in p)}"
    )


def test_the_frontend_names_at_least_one_settings_url():
    """Guard on the guard: a collector that silently matches nothing would
    make the test above pass for the wrong reason."""
    assert _frontend_settings_urls()


def test_the_push_panel_saves_through_the_app_settings_endpoint():
    """Quoted literals only — the file's comment names the dead URL on
    purpose, so that the next reader knows what was wrong with it."""
    src = (_JS_DIR / "push.js").read_text(encoding="utf-8")
    assert "'/api/settings/telegram/push'" not in src
    assert "'/api/settings/app'" in src


# ── The write half — deep merge onto settings.json ────────────────────────


def test_a_partial_push_write_keeps_its_siblings(settings_store):
    """What the panel sends is one changed leaf, not the whole subtree."""
    settings_store.update_section(
        "telegram",
        {
            "token": "<BOT_TOKEN>",
            "push": {
                "enabled": True,
                "quiet_hours": {"start": "22:00", "end": "07:00"},
                "labels": {"person": {"push": True}, "cat": {"push": False}},
            },
        },
    )

    settings_store.update_section("telegram", {"push": {"labels": {"person": {"push": False}}}})

    push = settings_store.data["telegram"]["push"]
    assert push["labels"]["person"]["push"] is False
    # Everything the client did not echo back survives — including the
    # per-label threshold the panel no longer renders at all.
    assert push["labels"]["person"]["threshold"] == 0.85
    assert push["labels"]["cat"]["push"] is False
    assert push["quiet_hours"] == {"start": "22:00", "end": "07:00"}
    assert push["enabled"] is True
    assert settings_store.data["telegram"]["token"] == "<BOT_TOKEN>"


def test_the_write_survives_a_reload(settings_store, tmp_storage_root):
    """Round-trip: load → modify → save → reload → diff."""
    settings_store.update_section("telegram", {"push": {"weather": {"recap_push": False}}})
    on_disk = json.loads((tmp_storage_root / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["telegram"]["push"]["weather"]["recap_push"] is False


# ── The failure half — a failed save must not look like a saved one ───────

pytestmark_node = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

# push.js schedules a 30 s deps refresh and toast.js an auto-dismiss; both
# would hold node's event loop open past the harness timeout.
_SETUP = """
  globalThis.setInterval = () => 0;
  globalThis.setTimeout = () => 0;
  const { state } = await import(JS + '/core/state.js');
  const { savePushCfg } = await import(JS + '/push.js');
  state.config = { telegram: { push: {
    enabled: true,
    labels: { person: { push: true }, cat: { push: false } },
  } } };
"""


@pytestmark_node
def test_a_successful_save_posts_the_nested_telegram_push_shape():
    out = _js(
        f"""
        {_SETUP}
        const calls = [];
        globalThis.fetch = (url, init) => {{
          calls.push({{ url, body: JSON.parse(init.body) }});
          return Promise.resolve({{
            ok: true,
            headers: {{ get: () => 'application/json' }},
            json: () => Promise.resolve({{ ok: true }}),
          }});
        }};
        const ok = await savePushCfg({{ labels: {{ person: {{ push: false }} }} }});
        console.log(JSON.stringify({{ ok, calls, person: state.config.telegram.push.labels.person }}));
        """
    )
    assert out["ok"] is True
    assert len(out["calls"]) == 1
    assert out["calls"][0]["url"] == "/api/settings/app"
    assert out["calls"][0]["body"] == {
        "telegram": {"push": {"labels": {"person": {"push": False}}}}
    }
    assert out["person"] == {"push": False}


@pytestmark_node
def test_a_rejected_save_rolls_the_optimistic_value_back():
    """The bug's second half. A 404 left `push: false` in state.config, so
    the switch stayed flipped until the next bootstrap silently undid it."""
    out = _js(
        f"""
        {_SETUP}
        globalThis.fetch = () => Promise.resolve({{
          ok: false, status: 404, statusText: 'NOT FOUND',
          text: () => Promise.resolve('404 Not Found'),
        }});
        const ok = await savePushCfg({{ labels: {{ person: {{ push: false }} }} }});
        console.log(JSON.stringify({{ ok, push: state.config.telegram.push }}));
        """
    )
    assert out["ok"] is False
    assert out["push"]["labels"]["person"] == {"push": True}
    assert out["push"]["labels"]["cat"] == {"push": False}
    assert out["push"]["enabled"] is True
