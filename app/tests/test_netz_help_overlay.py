"""The Erkennungsnetz's "i" help overlay.

Static-content check: the modal markup and its wiring exist and agree
with each other (button controls the right modal id, close button
matches). The CONTENT itself is prose for a human to read, not logic —
a source-text pin is the right tool here, unlike the multi-select
chart's arithmetic next door, which needed real execution to trust.
"""

from __future__ import annotations

from pathlib import Path

_NETZ_HTML = (
    Path(__file__).resolve().parents[1] / "web" / "templates" / "partials" / "netz.html"
).read_text(encoding="utf-8")
_HELP_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_help.js"
).read_text(encoding="utf-8")
_INDEX_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "index.js"
).read_text(encoding="utf-8")


def test_the_help_button_controls_the_modal_it_names():
    assert 'id="netzHelpBtn"' in _NETZ_HTML
    assert 'aria-controls="netzHelpModal"' in _NETZ_HTML
    assert 'id="netzHelpModal"' in _NETZ_HTML
    assert 'id="netzHelpCloseBtn"' in _NETZ_HTML


def test_every_mechanic_the_operator_can_see_is_explained():
    for must in (
        "innen",  # direction legend
        "außen",
        "Übernehmen",  # drag commit
        "Verwerfen",  # drag discard
        "Werk",  # provenance: factory
        "manuell",  # provenance: dragged
        "automatisch",  # provenance: learner
        "Richtig",  # telegram verdict buttons
        "Falsch",
        "Etwas anderes",
        "Sicherheitskamera",  # the person floor
    ):
        assert must in _NETZ_HTML, f"help overlay never mentions {must!r}"


def test_the_modal_starts_hidden():
    # A help overlay open by default would cover the radar on first paint.
    assert 'id="netzHelpModal" class="modal hidden"' in _NETZ_HTML


def test_help_module_is_wired_into_init():
    assert "initNetzHelp" in _INDEX_JS
    assert "from './_help.js'" in _INDEX_JS


def test_help_module_reads_no_netz_state():
    """Content is static markup — this module must stay a pure
    open/close toggle, not grow into a second renderer reading
    netzState. (The module's own comment SAYS this in prose, which is
    fine; what must not appear is an actual import of the state.)"""
    assert "from './_state.js'" not in _HELP_JS
