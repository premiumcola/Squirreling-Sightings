"""The Netz-hosted Kamera-Feinschliff fold and its backend route agree
on field names.

This is exactly the drift class the D1-D7 comments in erkennung.html
warn about repeatedly: a control renamed on one side of the wire while
the other side keeps the old name silently stops saving (the input
still renders, still LOOKS wired, and nothing throws — the payload key
the backend never reads is the only symptom). A source-text cross-check
catches it without needing a real DOM.
"""

from __future__ import annotations

import re
from pathlib import Path

_CAMERAS_PY = (
    Path(__file__).resolve().parents[1] / "app" / "routes" / "cameras.py"
).read_text(encoding="utf-8")
_TUNING_JS = (
    Path(__file__).resolve().parents[1] / "web" / "static" / "js" / "netz" / "_tuning.js"
).read_text(encoding="utf-8")
_NETZ_HELPERS_PY = (
    Path(__file__).resolve().parents[1] / "app" / "routes" / "_netz_helpers.py"
).read_text(encoding="utf-8")

# roi_mode is a segmented button set (data-tune-roi), not a plain
# data-tune input — the save handler folds it in separately.
_PLAIN_FIELDS = {
    "frame_interval_ms",
    "motion_sensitivity",
    "post_motion_tail_s",
    "track_miss_grace_seconds",
    "track_iou_match_threshold",
    "track_filter_ghosts",
    "wildlife_motion_sensitivity",
    "roi_min_net_disp_frac",
}
_ALL_FIELDS = _PLAIN_FIELDS | {"roi_mode"}


def test_every_backend_tuning_field_has_a_frontend_control():
    for field in _PLAIN_FIELDS:
        assert f'data-tune="{field}"' in _TUNING_JS, f"{field}: no data-tune input in _tuning.js"
    assert "data-tune-roi=" in _TUNING_JS


def test_the_frontend_sends_no_field_the_backend_does_not_accept():
    sent = set(re.findall(r'data-tune="([a-z_]+)"', _TUNING_JS))
    assert sent <= _ALL_FIELDS, f"_tuning.js references unknown field(s): {sent - _ALL_FIELDS}"
    for field in sent:
        assert field in _CAMERAS_PY, f"{field}: not in _TUNING_FLOAT_FIELDS/_TUNING_BOOL_FIELDS"


def test_the_netz_state_payload_backs_every_field_the_panel_renders():
    """`net_state`'s `tuning` dict is what seeds every control's initial
    value — a field the panel renders but the payload never sends would
    hydrate as `undefined`."""
    for field in _ALL_FIELDS:
        assert f'"{field}"' in _NETZ_HELPERS_PY, f"{field}: missing from net_state's tuning dict"


def test_the_save_button_reads_every_plain_field_generically():
    """The click handler must build its payload from `[data-tune]`
    generically (querySelectorAll), not one hardcoded field at a time —
    otherwise adding a field to the render functions without also adding
    it to the collector is silent."""
    assert "qsa('[data-tune]', root)" in _TUNING_JS
