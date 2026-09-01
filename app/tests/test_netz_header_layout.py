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

The single shared Verlauf button is gone too — there is no longer one
header to hang it off. Each camera's own panel now carries its own
Verlauf toggle (netz/_panel.js), scoped to that camera's own state
instead of camera 0's.

"Werte, die fest bleiben" made a second trip: briefly per-panel (one
button per camera), then back to page-level once more — FROZEN_KEYS
(app/app/routes/_netz_helpers.py) was always one flat constant sent
identically to every camera, so a per-panel button never had anything
camera-specific to show. It now shares the "Was zusammen wirkt" box
(netz/_cards.js's frozenSectionHtml), the same page-level home combosHtml
already used.
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


# ── 2 · frozen values are page-level again — this time explicit ────────


def test_the_frozen_box_has_no_per_panel_button():
    """No `netzFrozenBox-<id>` id, no per-panel toggle button — see
    netz/_cards.js's frozenSectionHtml for where the content lives now."""
    assert "netzFrozenBox-" not in _PANEL
    assert "data-netz-toggle-frozen" not in _PANEL
    assert 'id="netzFrozenBtn"' not in _PANEL


def test_the_frozen_content_rides_the_shared_combos_box():
    cards = (_JS / "netz" / "_cards.js").read_text(encoding="utf-8")
    assert "export function frozenSectionHtml" in cards
    assert "frozenSectionHtml()" in _PANEL


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
