"""The Erkennungsprofil's PRIMARY radar (camera-wide settings) and its backend
route agree on field names.

This is exactly the drift class the D1-D9 comments in erkennung.html and
_cards.js warn about repeatedly: a control renamed on one side of the
wire while the other side keeps the old name silently stops saving (the
axis still renders, still LOOKS wired, and nothing throws — the payload
key the backend never reads is the only symptom). A source-text
cross-check catches it without needing a real DOM.

_settings_axes.js is the single source of truth for which keys are
spokes on the chart (TUNE_AXIS_ORDER) — this replaced the earlier
per-field `data-tune="..."` slider markup this file used to check, which
no longer exists after the redesign into a draggable settings radar.
"""

from __future__ import annotations

import re
from pathlib import Path

_CAMERAS_PY = (
    Path(__file__).resolve().parents[1] / "app" / "routes" / "cameras.py"
).read_text(encoding="utf-8")
_SETTINGS_AXES_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_settings_axes.js"
).read_text(encoding="utf-8")
_CARDS_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_cards.js"
).read_text(encoding="utf-8")
_TUNE_RADAR_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_tune_radar.js"
).read_text(encoding="utf-8")
_NETZ_HELPERS_PY = (
    Path(__file__).resolve().parents[1] / "app" / "routes" / "_netz_helpers.py"
).read_text(encoding="utf-8")

# The 8 spokes, plus track_filter_ghosts (a boolean toggle beside the
# chart, not a spoke — see _cards.js's header comment for why) and the
# two preset-only fields (never a standalone control, only ever written
# together by the three tracker-preset buttons).
_NON_SPOKE_TUNING_FIELDS = {
    "track_filter_ghosts",
    "track_continue_min_score",
    "track_spawn_min_score",
}


def _tune_axis_order():
    m = re.search(r"TUNE_AXIS_ORDER\s*=\s*\[(.*?)\]", _SETTINGS_AXES_JS, re.DOTALL)
    assert m, "TUNE_AXIS_ORDER not found in _settings_axes.js"
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_every_spoke_has_a_spec():
    order = _tune_axis_order()
    assert len(order) == 8, order
    for key in order:
        assert f"{key}: {{" in _SETTINGS_AXES_JS, f"{key}: no TUNE_SPECS entry"


def test_every_spoke_is_accepted_by_the_backend_route():
    for key in _tune_axis_order():
        assert key in _CAMERAS_PY, f"{key}: not in _TUNING_FLOAT_FIELDS/_TUNING_ENUM_FIELDS"


def test_every_backend_tuning_field_is_either_a_spoke_or_explicitly_excluded():
    """Catches the OTHER direction of drift: a field added to the
    backend route that never made it onto the chart (or the excluded
    set) is a control nobody can reach."""
    spoke_fields = set(_tune_axis_order())
    field_dict = re.search(r"_TUNING_FLOAT_FIELDS\s*=\s*\{(.*?)\n\}", _CAMERAS_PY, re.DOTALL)
    assert field_dict
    backend_fields = set(re.findall(r'"([a-z_]+)":', field_dict.group(1)))
    unaccounted = backend_fields - spoke_fields - _NON_SPOKE_TUNING_FIELDS
    assert not unaccounted, f"reachable from neither the chart nor the exclusion list: {unaccounted}"


def test_the_netz_state_payload_backs_every_spoke_and_the_ghost_toggle():
    """`net_state`'s `tuning` dict seeds the chart's initial values — a
    field the chart renders but the payload never sends would hydrate
    as the spec default, silently masking whatever is actually stored."""
    for key in [*_tune_axis_order(), "track_filter_ghosts"]:
        assert f'"{key}"' in _NETZ_HELPERS_PY, f"{key}: missing from net_state's tuning dict"


def test_the_chart_is_built_generically_not_one_field_at_a_time():
    """The render/drag/save path must go through buildTuneAxes/TUNE_SPECS
    — a hand-written field list here is exactly the kind of listing that
    drifts from _settings_axes.js the moment one of the two is edited
    without the other."""
    assert "buildTuneAxes(" in _CARDS_JS
    assert "renderTuneRadar(" in _CARDS_JS


def test_every_write_path_takes_its_camera_from_the_dom():
    """With every camera's net on screen at once, a module-level "current
    camera" is how a drag on one camera PATCHes another. The card's own
    dataset is the only correct source."""
    assert "card.dataset.cam" in _CARDS_JS
    assert "netzState.camId" not in _CARDS_JS


def test_the_settings_radar_keeps_a_uniform_viewbox_mapping():
    """_radar.js:13-20 documents the past bug: a viewBox whose aspect
    ratio differs from the element's scales x and y by different factors
    and visibly distorts the glyphs. An ellipse is fine; a stretched
    square is not — so the width/height attributes must carry the same
    numbers as the viewBox."""
    assert 'viewBox="0 0 ${TUNE_W} ${TUNE_H}" ` +\n    `width="${TUNE_W}" height="${TUNE_H}"' in _TUNE_RADAR_JS
    assert "preserveAspectRatio" not in _TUNE_RADAR_JS
