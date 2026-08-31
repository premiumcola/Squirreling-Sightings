"""One panel, one hydration path, one form.

The operator asked for the two Wartung panels to become a single
Mediathek-Verwaltungselement. What made that more than cosmetics is that
the second panel's hydration never worked: `weather/maintenance.js`
painted its sliders from `/api/bootstrap` → `data.app.weather`, and
`SettingsStore.bootstrap_state()` returns five keys of which `app` is
not one — so `w` was always `{}`, every weather slider showed its Jinja
literal, and a saved 30 came back as the shipped 90 on the next reload.
Meanwhile the Mediathek slider hydrated from `state.config.storage`
inside the cam-edit hydrate path. Two panels, two sources, one of them
broken.

Pinned here: the panel renders once with server-resolved values in it,
every control carries the settings.json coordinates the DOM-walk
collector needs, the Wetter-Sektion still has an entry point, and no JS
module hydrates a retention control from a payload that does not carry
one.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader

_pkg_root = str(Path(__file__).parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from app import app_state  # noqa: E402
from app.retention_catalog import RETENTION_ROWS, panel_groups  # noqa: E402

_WEB = Path(__file__).resolve().parents[1] / "web"
_TPL = _WEB / "templates"
_JS = _WEB / "static" / "js"
_CSS = _WEB / "static" / "css" / "34-retention.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> str:
    """Source with `//` line comments stripped. Every check below is
    about what the module DOES; the comments deliberately name the
    retired ids so the next reader knows where they went."""
    return "\n".join(
        line for line in _read(path).splitlines() if not line.lstrip().startswith("//")
    )


@pytest.fixture
def rendered(monkeypatch) -> str:
    """The maintenance macro rendered exactly as mediathek.html calls
    it, with `retention_groups` from the real catalog. Rendering rather
    than grepping the template: the row set is data now, so the only
    honest check is what Jinja actually emits."""
    monkeypatch.setattr(
        app_state,
        "settings",
        SimpleNamespace(
            data={
                "storage": {"retention_days": 33, "auto_cleanup_enabled": True},
                "weather": {"retention_recaps_days": 222},
                "trash": {"grace_days": 9},
            }
        ),
        raising=False,
    )
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)
    env = Environment(loader=FileSystemLoader(str(_TPL)), autoescape=True)
    tpl = env.from_string(
        "{% from 'partials/_maintenance_panel.html' import maintenance_panel %}"
        "{% call maintenance_panel(panel_id='set-media-maint', accent='143,158,181',"
        " title='Mediathek-Verwaltung', hint='h',"
        " retention={'form_id': 'retentionForm', 'groups': retention_groups}) %}"
        "<button id='fixThumbsBtn'></button>{% endcall %}"
    )
    return tpl.render(retention_groups=panel_groups())


# ── one panel ──────────────────────────────────────────────────────────


def test_exactly_one_template_renders_a_retention_form():
    callers = {
        path.name
        for path in _TPL.rglob("*.html")
        if path.name != "_maintenance_panel.html" and "'form_id'" in _read(path)
    }
    assert callers == {
        "mediathek.html"
    }, f"two panels with retention forms is what this change removed — found {sorted(callers)}"


def test_the_weather_section_no_longer_carries_its_own_sliders():
    weather = _read(_TPL / "partials" / "weather.html")
    assert "ws_retention_" not in weather
    assert "weatherMaintForm" not in weather


def test_the_weather_section_still_reaches_the_panel():
    """Merging the panels may not orphan the entry point the operator
    already uses to get to the Wetter-Fristen."""
    weather = _read(_TPL / "partials" / "weather.html")
    assert 'data-action="openRetentionPanel"' in weather
    assert "openRetentionPanel" in _read(_JS / "maintenance" / "index.js")


# ── every row, rendered, with its coordinates ──────────────────────────


def test_every_catalog_row_is_rendered(rendered):
    for row in RETENTION_ROWS:
        assert f'id="ret_{row.key}"' in rendered, f"{row.key} missing from the panel"
        assert row.label in rendered


def test_every_control_carries_its_settings_json_coordinates(rendered):
    """The save handler walks the DOM for these instead of holding a
    field map — a map is the thing that drifts when a category is added.
    """
    for row in RETENTION_ROWS:
        pattern = rf'data-section="{row.section}"\s+data-field="{row.field}"'
        assert re.search(pattern, rendered), f"{row.key} cannot be collected from the DOM"


def test_the_panel_renders_the_stored_values_not_jinja_literals(rendered):
    assert 'id="ret_motion_clips"' in rendered
    assert re.search(r'id="ret_motion_clips"[^>]*value="33"', rendered, re.DOTALL)
    assert re.search(r'id="ret_trash_grace"[^>]*value="9"', rendered, re.DOTALL)


def test_the_camera_timelapse_row_says_nie_loeschen_at_zero(rendered):
    """0 has to read as the OFF position. A bare "0 Tage" reads as
    "delete everything tonight", which is the opposite of what it does.
    """
    assert "= nie löschen" in rendered
    assert 'data-off-at-zero="1"' in rendered


def test_both_auto_cleanup_switches_are_rendered(rendered):
    assert 'id="ret_auto_kamera"' in rendered
    assert 'id="ret_auto_wetter"' in rendered


def test_the_sonderaktionen_row_still_renders_its_callers_buttons(rendered):
    assert "fixThumbsBtn" in rendered


# ── hydration ──────────────────────────────────────────────────────────


def test_no_js_module_hydrates_retention_from_the_bootstrap_payload():
    """`bootstrap_state()` returns wizard/camera/telegram/mqtt flags and
    nothing else. Any retention control painted from it shows a Jinja
    literal forever."""
    for path in _JS.rglob("*.js"):
        src = _code(path)
        if "/api/bootstrap" not in src:
            continue
        assert (
            "retention" not in src
        ), f"{path.name} reads retention out of /api/bootstrap, which does not carry it"


def test_the_retired_hydration_paths_are_gone():
    assert "ms_retention_days" not in _code(_JS / "camedit" / "index.js")
    assert "mediaSettingsForm" not in _code(_JS / "chrome" / "storage-stats.js")
    assert "RETENTION_FIELDS" not in _code(_JS / "weather" / "maintenance.js")


def test_the_manual_cleanup_button_still_reads_the_motion_row():
    """`POST /api/media/cleanup` confirms a narrowed window only when the
    request carries the number. Pointing it at a dead id silently turned
    every manual cleanup into "use whatever is already enforced"."""
    src = _code(_JS / "chrome" / "storage-stats.js")
    assert "byId('ret_motion_clips')" in src


# ── iOS ────────────────────────────────────────────────────────────────


def test_the_number_inputs_do_not_trigger_the_ios_zoom():
    """Below 16 px iOS zooms the whole page on focus and never zooms
    back out."""
    css = _read(_CSS)
    m = re.search(r"\.ret-num \{(.*?)\}", css, re.DOTALL)
    assert m, "no .ret-num rule"
    size = re.search(r"font-size:\s*(\d+(?:\.\d+)?)px", m.group(1))
    assert size and float(size.group(1)) >= 16


def test_both_controls_have_a_44px_touch_target():
    css = _read(_CSS)
    assert re.search(r"\.ret-num \{[^}]*min-height:\s*44px", css, re.DOTALL)
    assert re.search(r"\.ret-range \{[^}]*height:\s*44px", css, re.DOTALL)


def test_hover_styling_is_guarded():
    css = _read(_CSS)
    for match in re.finditer(r"([^\n{]*):hover", css):
        prefix = css[: match.start()]
        assert "@media (hover: hover)" in prefix, "unguarded :hover sticks after a tap on iOS"


def test_the_partial_is_in_the_css_build_order():
    from app.css_builder import LOAD_ORDER

    assert "34-retention.css" in LOAD_ORDER


# ── wiring ─────────────────────────────────────────────────────────────


def test_the_context_processor_reaches_every_template(monkeypatch):
    """The blueprint carries no routes — its whole job is this. Registered
    but not injecting means a silently row-less panel."""
    import flask

    from app.routes.retention_panel import bp

    monkeypatch.setattr(app_state, "settings", SimpleNamespace(data={}), raising=False)
    monkeypatch.setattr(app_state, "base_cfg", {}, raising=False)
    app = flask.Flask(__name__)
    app.register_blueprint(bp)
    with app.test_request_context("/"):
        out = flask.render_template_string("{{ retention_groups | length }}")
    assert out == "3"


def test_the_blueprint_is_registered():
    import inspect

    from app import routes

    src = inspect.getsource(routes.register_blueprints)
    assert "retention_panel.bp" in src
