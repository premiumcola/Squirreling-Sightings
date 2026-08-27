"""The in-flight surfaces have no JS runner in CI, so their contract is
pinned from here.

Everything asserted below is something that silently *looks* fine while
being wrong, which is exactly the class of regression a source check can
still catch:

* a spinner that vanishes under ``prefers-reduced-motion`` instead of
  going static — the user with motion sensitivity gets a blank tile and
  no idea anything is happening;
* a detail panel reachable only by hover — invisible on the phone, which
  is the primary device for this project;
* a progress percentage nobody can compute honestly;
* a queue strip that implies a FIFO position, when in fact every clip
  re-encodes in its own thread and there is no line to be in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web" / "static"
JS = WEB / "js" / "mediathek" / "_processing.js"
ORCH = WEB / "js" / "mediathek" / "orchestration.js"
CSS_FILE = WEB / "css" / "14-mediathek-1.css"
CSS_MARKER = "In-flight clips: stage tile + queue strip"


def _strip_comments(src: str) -> str:
    """Drop ``//`` lines and ``/* */`` blocks so a comment *about* a
    banned construct doesn't read as the construct itself."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("//"))


@pytest.fixture(scope="module")
def js() -> str:
    return JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def orch() -> str:
    return ORCH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    """Only the in-flight section of the partial.

    Deliberately reads the SOURCE partial: ``web/static/app.css`` is a
    gitignored build artifact, so asserting against it would pass on a
    stale build and fail on a fresh clone.
    """
    text = CSS_FILE.read_text(encoding="utf-8")
    assert CSS_MARKER in text, "in-flight CSS section is gone from the partial"
    return text[text.index(CSS_MARKER) :]


# ── wiring ─────────────────────────────────────────────────────────────────
def test_the_grid_uses_the_processing_module(orch):
    """The placeholder used to be an inline template literal in
    orchestration.js. It is not allowed back — that file is already
    924 lines against a 400-line ceiling."""
    assert "from './_processing.js'" in orch
    assert "processingTileHTML(item" in orch
    assert "renderProcessingQueue(" in orch


def test_the_poll_watches_the_whole_library_not_just_the_page(orch):
    """`state.media` is one page. A clip that starts recording while the
    user is on page 2 lands on page 1 and would never be polled."""
    poll = orch[orch.index("export function _ensureProcessingPoll") :][:800]
    assert "state._allMedia" in poll


def test_a_stalled_clip_does_not_keep_the_poll_alive(orch, js):
    """It stays on screen, but nothing will advance it. Polling for it
    every 3 s costs a full event-tree scan per camera, forever."""
    poll = orch[orch.index("export function _ensureProcessingPoll") :][:800]
    assert "isActivelyPending" in poll
    active = js[js.index("export function isActivelyPending") :]
    assert "!item.stage_stalled" in active[: active.index("\n}")]


def test_an_in_flight_card_does_not_route_into_the_lightbox(orch):
    """There is nothing to play yet, and the tap has another job: it
    opens the stage detail."""
    assert "const wrapClick = isProcessing" in orch
    assert "needsProcessingTile(item)" in orch


# ── reduced motion: degrade, never disappear ───────────────────────────────
def test_reduced_motion_is_handled(css):
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_reduced_motion_stops_the_animation_without_hiding_the_indicator(css):
    block = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert "animation: none" in block
    for banned in ("display: none", "visibility: hidden", "opacity: 0"):
        assert banned not in block, (
            f"reduced motion must degrade the spinner to a static state, not {banned!r} it — "
            "a blank tile tells the user nothing is happening"
        )


# ── the detail must survive a device with no pointer ───────────────────────
def test_the_hover_reveal_is_guarded(css):
    assert "@media (hover: hover)" in css
    hover_rules = re.findall(r"\.mvp-tile:hover[^{]*\{", css)
    assert hover_rules, "no hover reveal at all?"
    for rule in hover_rules:
        before = css[: css.index(rule)]
        assert "@media (hover: hover)" in before, f"unguarded hover rule: {rule.strip()}"


def test_the_detail_is_reachable_by_tap(css, js):
    assert ".mvp-tile.is-open .mvp-detail" in css
    assert "_toggleProcTile" in js
    assert "aria-expanded" in js


def test_the_tile_is_a_button_so_it_is_also_keyboard_reachable(js):
    assert '<button type="button" class="mvp-tile' in js


def test_touch_targets_clear_44px(css):
    head = css[css.index(".mvq-head {") :]
    assert "min-height: 44px" in head[: head.index("}")]


def test_no_viewport_height_units_in_the_new_layout(css):
    """iOS address-bar collapse. `dvh` or nothing."""
    assert not re.search(r"\d\s*vh\b", css)


# ── honesty ────────────────────────────────────────────────────────────────
def test_no_invented_progress_percentage(js):
    """ffmpeg can emit real progress, but only by trading
    `subprocess.run` for a reader thread that rewrites the per-camera
    event JSON at ~1 Hz per clip. Until that trade is worth making, a
    bar moving at a made-up rate is worse than an honest spinner."""
    code = _strip_comments(js).lower()
    for token in ("percent", "progress", "%'", '%"'):
        assert (
            token not in code
        ), f"{token!r} in the in-flight UI — where would the number come from?"


def test_the_queue_never_claims_a_position_in_a_line(js):
    """Each clip re-encodes in its own thread — there is no queue order
    to report. Counting is true; "2 von 3" is not."""
    titles = js[js.index("export function queueTitle") :]
    titles = titles[: titles.index("\n}")]
    assert " von " not in titles
    assert "Platz" not in titles
    assert "werden verarbeitet" in titles


def test_a_stalled_or_failed_clip_stops_spinning(js):
    """The whole point: a tile that spins forever is a lie."""
    assert "st.kind === 'busy' ? _SPIN : _WARN" in js


def test_a_terminal_failure_is_kept_out_of_the_queue_strip(js):
    """It is not in flight any more; it belongs on its own tile with the
    reason and the delete button next to it."""
    body = js[js.index("export function renderProcessingQueue") :]
    assert ".filter(isPendingItem)" in body
