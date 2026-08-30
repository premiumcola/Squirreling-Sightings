"""The Simulieren panel's MODUS control must start on what the camera runs.

`S.session.detMode` was hardcoded to `'off'` at session open, so opening
the simulator on a camera configured for `2x2` presented — and then
actually ran — a different detection pipeline than production, without
saying so. The operator caught it themselves:

    "wenn ich in den Simulator geh, dann ist das zwei mal zwei nicht an,
     obwohl die ja so läuft"

That is the same family as every other divergence found in this panel:
the diagnostic quietly describing a system other than the one running.

Two halves, both pinned here, because the seed cannot work unless BOTH
are true: the API has to ship `roi_mode` in the camera list projection,
and the session has to read it instead of a literal.

NOT fixed here, and deliberately so: the simulator tiles on EVERY tick
while production tiles only as a rescue (coherent motion blob, 1.5 s
cooldown, no confirmable box). Matching the MODE is what belongs at
session open; the cadence difference is stated in the decision trace
instead, because making the sim tile conditionally would mean it could
show nothing at all on a still scene.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_CAMERAS_PY = (_ROOT / "app" / "routes" / "cameras.py").read_text(encoding="utf-8")
_LIVE_DETECT_JS = (_ROOT / "web" / "static" / "js" / "mediaview" / "live-detect.js").read_text(
    encoding="utf-8"
)


def _list_projection() -> str:
    """The block of `/api/cameras` that builds each camera's dict.

    Sliced at `zones`, which is well inside the projection and stable —
    matching to the end of the function would swallow the per-camera
    detail route below it, whose own `roi_mode` line is NOT the one this
    test is about.
    """
    start = _CAMERAS_PY.index('s["track_filter_ghosts"]')
    end = _CAMERAS_PY.index('s["resolution"]')
    return _CAMERAS_PY[start:end]


def test_the_camera_list_ships_roi_mode():
    """Without this the frontend has nothing to seed from — `state.cameras`
    is populated from this projection."""
    assert 's["roi_mode"]' in _list_projection(), (
        "/api/cameras no longer exposes roi_mode — the Simulieren MODUS "
        "control silently falls back to 'off' for every camera"
    )


def test_the_projection_defaults_a_missing_roi_mode_to_off():
    """A camera that predates the field must not emit None — the enum the
    save route validates against has no null member."""
    seg = _list_projection()
    m = re.search(r's\["roi_mode"\]\s*=\s*(.+)', seg)
    assert m, "roi_mode assignment not found"
    assert 'or "off"' in m.group(1), m.group(1)


def test_the_session_seeds_det_mode_from_the_camera():
    """THE regression: a literal here is the bug, whatever its value."""
    m = re.search(r"detMode:\s*(.+?),", _LIVE_DETECT_JS)
    assert m, "detMode seed not found in the session object"
    seed = m.group(1).strip()
    assert seed != "'off'", (
        "detMode is hardcoded again — the simulator will diagnose a "
        "pipeline the camera does not run"
    )
    assert "_configuredRoiMode(" in seed, seed


def test_the_seed_helper_rejects_a_mode_the_backend_would_refuse():
    """The stored value is not trusted blindly: a drifted config must fall
    back to 'off' rather than have the panel post an invalid enum."""
    assert "const _ROI_MODES = ['off', 'roi', '2x2', '3x3'];" in _LIVE_DETECT_JS
    body = _LIVE_DETECT_JS[_LIVE_DETECT_JS.index("function _configuredRoiMode") :]
    body = body[: body.index("\n}")]
    assert "_ROI_MODES.includes(" in body
    assert "'off'" in body, "no fallback for an unrecognised stored mode"


def test_the_seed_enum_matches_the_one_the_save_route_validates():
    """Two lists of the same four strings in two languages is exactly the
    drift this repo keeps finding. If the backend gains a mode, this fails
    until the frontend learns it too."""
    m = re.search(r'"roi_mode":\s*\(([^)]*)\)', _CAMERAS_PY)
    assert m, "_TUNING_ENUM_FIELDS entry for roi_mode not found"
    backend = re.findall(r'"([^"]+)"', m.group(1))
    m2 = re.search(r"const _ROI_MODES = \[([^\]]*)\]", _LIVE_DETECT_JS)
    assert m2
    frontend = re.findall(r"'([^']+)'", m2.group(1))
    assert backend == frontend, f"backend {backend} != frontend {frontend}"
