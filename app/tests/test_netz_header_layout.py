"""Erkennungsprofil panel header + the Timelapse-aktiv pill's new home.

Follow-up to the reshape that gave every camera its own Erkennungsprofil
panel beside its own Live-Feed tile, and moved two other header elements
out of the way to make room:

  · "die Bildinformation schiebst Du in die Einstellung App und Server
    rein ... das brauch ich nicht mehr ganz oben" — the build-info chip
    left the hero header for Einstellungen → App & Server.
  · "schiebt der Timelapse aktiv ... nach rechts oben in die Ecke" — the
    pill moved into the corner the build-info chip vacated: the hero row,
    not the Geräte head row it used to ride.

The single shared "Werte, die fest bleiben" button and the single shared
Verlauf button are gone too — there is no longer one header to hang them
off. Each camera's own panel now carries its own frozen-values button and
its own Verlauf toggle (netz/_panel.js), scoped to that camera's own
state instead of camera 0's.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JS = _ROOT / "web" / "static" / "js"
_CSS = _ROOT / "web" / "static" / "css"
_TPL = _ROOT / "web" / "templates" / "partials"

_PANEL = (_JS / "netz" / "_panel.js").read_text(encoding="utf-8")
_HERO_TPL = (_TPL / "hero.html").read_text(encoding="utf-8")
_CAM_TPL = (_TPL / "cam_edit.html").read_text(encoding="utf-8")
_HERO_CSS = (_CSS / "02-hero.css").read_text(encoding="utf-8")
_TL_CSS = (_CSS / "07-timelapse-1.css").read_text(encoding="utf-8")


# ── 1 · the Verlauf toggle is per panel now, not a shared header button ──


def test_every_panel_carries_its_own_verlauf_toggle():
    assert "data-netz-toggle-verlauf" in _PANEL


def test_the_shared_global_verlauf_button_is_gone():
    """`#netzViewBtn` was the single header button every camera's Verlauf
    used to share — CLAUDE.md: don't leave a corpse once every panel has
    its own toggle."""
    tpl = "\n".join(p.read_text(encoding="utf-8") for p in _TPL.glob("*.html"))
    assert 'id="netzViewBtn"' not in tpl
    assert 'id="netzViewBtn"' not in _PANEL


# ── 2 · frozen values behind a PER-PANEL header button ──────────────────


def test_the_frozen_box_is_scoped_to_its_own_camera():
    """One box id per camera (`netzFrozenBox-<id>`), not one shared
    `#netzFrozenBox` — camera 3's operator must see camera 3's frozen
    values, not camera 0's leftover from the old shared-header design."""
    assert "netzFrozenBox-" in _PANEL
    assert 'id="netzFrozenBtn"' not in _PANEL
    assert 'id="netzFrozenBox"' not in _PANEL


def test_the_frozen_box_starts_hidden_behind_its_panels_own_button():
    assert "data-netz-toggle-frozen" in _PANEL
    assert 'aria-controls="netzFrozenBox-' in _PANEL
    assert 'class="netz-frozen-box" id="netzFrozenBox-' in _PANEL
    assert "hidden>" in _PANEL


def test_the_frozen_box_has_a_hidden_opt_out():
    """`display` in an author rule beats the UA's `[hidden]`. This exact
    trap was swept repo-wide in test_weather_zoom_panel_css.py; a newly
    toggled element must not reintroduce it."""
    netz_css = (_CSS / "32-netz.css").read_text(encoding="utf-8")
    assert ".netz-frozen-box[hidden]" in netz_css


def test_toggling_the_box_does_not_repaint_the_panel():
    """A repaint mid-drag drops the drag. The toggle flips the attribute
    directly instead of routing through renderPanel."""
    start = _PANEL.index("function _bindHeader(")
    body = _PANEL[start : _PANEL.index("\n}", start)]
    frozen_part = body[body.index("data-netz-toggle-frozen") :]
    assert "toggleAttribute" in frozen_part
    assert "renderPanel(" not in frozen_part


# ── 3 · camera identity, shared with the Statistik cloud ─────────────


def test_the_panel_header_uses_the_shared_camera_helpers():
    assert "from '../core/icons.js'" in _PANEL
    assert "getCameraIcon(" in _PANEL and "getCameraColor(" in _PANEL


def test_the_same_helpers_drive_the_statistik_cloud():
    """If Statistik ever stops using them, this file's premise is stale."""
    stats = (_JS / "statistics.js").read_text(encoding="utf-8")
    assert "getCameraIcon(" in stats and "getCameraColor(" in stats


# ── 4 · the Timelapse pill rides the hero row now ────────────────────


def test_the_timelapse_pill_sits_in_the_hero_row():
    assert 'id="tlStatusBar"' in _HERO_TPL


def test_the_pill_left_the_geraete_head_row():
    assert 'id="tlStatusBar"' not in _CAM_TPL


def test_the_pill_appears_exactly_once():
    assert _HERO_TPL.count('id="tlStatusBar"') == 1


def test_the_hero_row_may_wrap_so_the_title_is_never_squeezed():
    assert ".hero {" in _HERO_CSS
    start = _HERO_CSS.index(".hero {")
    seg = _HERO_CSS[start : _HERO_CSS.index("}", start)]
    assert "flex-wrap: wrap" in seg


def test_an_empty_pill_slot_costs_no_space():
    """It is filled by JS; before hydration and with no active timelapse
    it is an empty div that would still claim the row's gap."""
    assert ".tl-status-bar:empty" in _TL_CSS
