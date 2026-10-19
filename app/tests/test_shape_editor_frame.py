"""The zone/mask editor's frame: the snapshot, the gutter, the canvas.

"Auf dem Handy … die Punkte am Rand kann man nicht greifen, man kann die
Punkte aus dem Rahmen herausziehen, und evtl. passt das Format nicht."

Two of those were CSS, not JavaScript:

  * `.canvas-wrap { min-height: 240px }` — a 16:9 snapshot on a phone is
    about 180 px tall, the canvas covered the 240-px wrap, and taps plus
    drawings landed in the grey strip below the picture;
  * `.canvas-wrap { overflow: hidden; border-radius }` with the canvas
    ending at the frame edge — a vertex on the edge was half outside the
    touch surface, one in a corner was under the rounding.

The arithmetic half is in shape-editor/_tests/editor.test.js.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_DOCK = _REPO / "app" / "web" / "static" / "css" / "05-chrome-dock.css"
_ZONEN = _REPO / "app" / "web" / "templates" / "partials" / "cam_edit" / "zonen.html"


def _rule(selector: str) -> str:
    css = _DOCK.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(selector)} \{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
    assert m, f"{selector} missing from {_DOCK.name}"
    return m.group(1)


def test_the_wrap_does_not_stretch_past_the_snapshot():
    assert "min-height" not in _rule(".canvas-wrap")


def test_the_wrap_does_not_clip_edge_handles():
    assert "overflow" not in _rule(".canvas-wrap")
    assert "padding" in _rule(".canvas-wrap")


def test_the_stage_keeps_the_frame_aspect():
    assert "aspect-ratio" in _rule(".canvas-stage")


def test_a_failed_snapshot_can_actually_be_hidden():
    """`.canvas-stage img { display: block }` beats the UA `[hidden]`
    rule — author origin wins regardless of specificity."""
    assert "display: none" in _rule(".canvas-stage img[hidden]")


def test_the_canvas_spans_the_gutter_not_only_the_stage():
    """The canvas is the stage's sibling inside the wrap, so it covers
    the padding too — that is where an edge vertex's handle lives."""
    html = _ZONEN.read_text(encoding="utf-8")
    stage = html.index('id="maskStage"')
    stage_close = html.index("</div>", stage)
    canvas = html.index('id="maskCanvas"')
    assert canvas > stage_close
