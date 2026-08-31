"""Erkennungsprofil header + Geräte header — five height/identity fixes.

All five came from one operator message after using the panel on a
phone:

  · "Werte, die fest bleiben ... die würd ich rausnehmen oder auf 'nem
    kleinen Info Button rechts oben legen, weil die fressen zu viel
    Höhe."
  · "Die Timelapse aktiv Meldung bitte bei Geräte auch nach rechts,
    neben Netzwerk Discovery, auch um Höhe zu sparen."
  · "Über Erkennungsprofil, über dem Titel, ist noch irgendwie viel Luft."
  · "das Verlauf Icon ... ist jetzt dreimal unter den einzelnen Kameras
    und dann oben noch mal — bring den nur oben rein."
  · "vor die Kameras ... auch das Icon der Kamera mit rein, genau wie in
    die Buttons ... die kannst Du wiederverwenden aus der
    Erkennungswolke aus dem Statistikbereich."

The last one is the reason several of these are worth a test rather than
a glance: the camera glyph and tint must come from the SAME helpers the
Statistik cloud uses, or the two drift and one camera reads as two
different cameras in two places.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JS = _ROOT / "web" / "static" / "js"
_CSS = _ROOT / "web" / "static" / "css"
_TPL = _ROOT / "web" / "templates" / "partials"

_CARDS = (_JS / "netz" / "_cards.js").read_text(encoding="utf-8")
_INDEX = (_JS / "netz" / "index.js").read_text(encoding="utf-8")
_NETZ_TPL = (_TPL / "netz.html").read_text(encoding="utf-8")
_CAM_TPL = (_TPL / "cam_edit.html").read_text(encoding="utf-8")
_NETZ_CSS = (_CSS / "32-netz.css").read_text(encoding="utf-8")
_TL_CSS = (_CSS / "07-timelapse-1.css").read_text(encoding="utf-8")


# ── 1 · the Verlauf icon appears once, not once per camera ───────────


def test_the_history_icon_is_only_in_the_header():
    assert "data-netz-hist" not in _CARDS, "the per-card Verlauf button is back"
    assert "netz-card-hist" not in _CARDS
    assert 'id="netzViewBtn"' in _NETZ_TPL, "the header Verlauf button is gone too"


def test_the_removed_button_left_no_dead_wiring():
    """CLAUDE.md: git history is the archive, don't leave corpses."""
    assert "onHistory" not in _CARDS, "the callback thread outlived its only caller"
    assert "openCameraHistory" not in _INDEX


# ── 2 · frozen values behind a header button ─────────────────────────


def test_the_frozen_box_starts_hidden_behind_a_header_button():
    assert 'id="netzFrozenBtn"' in _NETZ_TPL
    assert 'aria-controls="netzFrozenBox"' in _NETZ_TPL
    assert 'id="netzFrozenBox" hidden' in _CARDS, "the box still opens by default"


def test_the_frozen_box_has_a_hidden_opt_out():
    """`display` in an author rule beats the UA's `[hidden]`. This exact
    trap was swept repo-wide in test_weather_zoom_panel_css.py; a newly
    toggled element must not reintroduce it."""
    assert ".netz-frozen-box[hidden]" in _NETZ_CSS


def test_toggling_the_box_does_not_repaint_the_nets():
    """A repaint mid-drag drops the drag. The toggle flips the attribute
    directly instead of routing through showTab/renderNet."""
    body = _INDEX[_INDEX.index("byId('netzFrozenBtn')") :]
    body = body[: body.index("byId('netzViewBtn')")]
    assert "toggleAttribute" in body
    for forbidden in ("showTab(", "renderNet(", "loadNet("):
        assert forbidden not in body, f"the info toggle triggers {forbidden}"


# ── 3 · camera identity, shared with the Statistik cloud ─────────────


def test_the_chips_and_card_headers_use_the_shared_camera_helpers():
    assert "from '../core/icons.js'" in _CARDS
    assert "getCameraIcon(" in _CARDS and "getCameraColor(" in _CARDS


def test_the_same_helpers_drive_the_statistik_cloud():
    """If Statistik ever stops using them, this file's premise is stale."""
    stats = (_JS / "statistics.js").read_text(encoding="utf-8")
    assert "getCameraIcon(" in stats and "getCameraColor(" in stats


# ── 4 · less air above the title ─────────────────────────────────────


def test_the_block_no_longer_doubles_the_sections_own_padding():
    seg = _NETZ_CSS[_NETZ_CSS.index("#netz .netz-block {") :][:220]
    assert "padding: 8px 12px" in seg, "the 14px top padding is back"


# ── 5 · the Timelapse pill rides the Geräte head row ─────────────────


def test_the_timelapse_pill_sits_in_the_head_row():
    head = _CAM_TPL[_CAM_TPL.index("<h3>Geräte</h3>") : _CAM_TPL.index("cameraSettingsList")]
    assert 'id="tlStatusBar"' in head, "the pill is not in the header"
    assert head.index('id="tlStatusBar"') < head.index(
        'id="discoverBtn"'
    ), "the pill must sit left of Netzwerk-Discovery"


def test_the_pill_appears_exactly_once():
    assert _CAM_TPL.count('id="tlStatusBar"') == 1


def test_the_head_row_may_wrap_so_the_title_is_never_squeezed():
    assert "#cameras .section-head" in _TL_CSS
    seg = _TL_CSS[_TL_CSS.index("#cameras .section-head") :][:160]
    assert "flex-wrap: wrap" in seg


def test_an_empty_pill_slot_costs_no_space():
    """It is filled by JS; before hydration and with no active timelapse
    it is an empty div that would still claim the row's gap."""
    assert ".tl-status-bar:empty" in _TL_CSS
