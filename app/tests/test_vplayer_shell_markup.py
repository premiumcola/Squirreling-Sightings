"""Guard the vplayer shell's slot skeleton.

Source-text pins, in the style test_sim_chrome_layout.py already uses:
the markup is a module-level template string, so reading it is the
cheapest way to assert its shape without a DOM.

What is pinned and why:

  · THE SLOT SET. Every mount function resolves its host by
    ``[data-slot="…"]``. A renamed or dropped slot fails silently — the
    querySelector returns null, the mount function's own guard returns
    null, and the player opens with a region simply missing. That is the
    failure this file exists to turn into a red test.

  · THE TIMELINE IS INSIDE THE STAGE. Mounting it there instead of in a
    strip below the picture is the central structural change of this
    player; a later edit that moves it back out would look harmless.

  · THE SKELETON LIVES IN ITS OWN FILE. Four pytest files pin
    mediaview/shell.js's markup by reading that file's source, which is
    why its layout could never be extracted. Giving this markup its own
    stable path from the first commit means _shell.js can grow without
    ever moving this guard.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "app" / "web" / "static"
_HTML = _ROOT / "js" / "vplayer" / "_shell-html.js"
_SHELL = _ROOT / "js" / "vplayer" / "_shell.js"

# Every slot the package's mount functions resolve by name.
_EXPECTED_SLOTS = {
    "topbar",
    "stage",
    "frame",
    "timeline",
    "toggles",
    "controls",
    "panel",
}


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _code_only(src: str) -> str:
    """Drop comments. The headers in this package NAME the legacy ids in
    order to explain what the package deliberately does not touch, so a
    grep over raw source would flag its own documentation."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"^\s*//.*$", "", src, flags=re.MULTILINE)


def test_every_expected_slot_is_present_in_the_skeleton():
    src = _read(_HTML)
    found = set(re.findall(r'data-slot="([a-z]+)"', src))
    missing = _EXPECTED_SLOTS - found
    assert not missing, f"slots dropped from the shell skeleton: {sorted(missing)}"


def test_the_slot_list_and_the_markup_agree():
    """VP_SHELL_SLOTS is what callers read; the markup is what exists."""
    src = _read(_HTML)
    declared = set(re.findall(r"^\s*'([a-z]+)',$", src, re.MULTILINE))
    in_markup = set(re.findall(r'data-slot="([a-z]+)"', src))
    assert declared == in_markup, (
        "VP_SHELL_SLOTS and the skeleton disagree: "
        f"declared-only={sorted(declared - in_markup)} "
        f"markup-only={sorted(in_markup - declared)}"
    )


def test_the_timeline_and_frame_are_mounted_inside_the_stage():
    """Both must fall between the stage opener and the next sibling slot.

    Mounting the timeline inside the stage rather than in a strip below
    the picture is the central structural change of this player, and a
    later edit that moved it back out would look harmless.
    """
    src = _read(_HTML)
    stage = src.index('data-slot="stage"')
    frame = src.index('data-slot="frame"')
    timeline = src.index('data-slot="timeline"')
    next_sibling = src.index('data-slot="toggles"')
    assert (
        stage < frame < timeline < next_sibling
    ), "frame and timeline must sit INSIDE the stage, before the next slot"


def test_every_class_in_the_skeleton_uses_the_vp_prefix():
    """A `.mv-`/`.lb-` class here would join the old player's cascade."""
    src = _read(_HTML)
    classes = re.findall(r'class="([^"]+)"', src)
    for chunk in classes:
        for cls in chunk.split():
            assert cls.startswith("vp-"), f"non-vplayer class in the skeleton: {cls}"


def test_the_shell_never_reaches_for_the_legacy_modal_ids():
    """The package owns its DOM — that is what makes it removable."""
    src = _code_only(_read(_SHELL) + _read(_HTML))
    for legacy in ("lightboxModal", "lightboxInner", "lightboxMediaWrap", "lightboxVideo"):
        assert legacy not in src, f"{legacy} referenced by the vplayer shell"


def test_the_shell_installs_a_capture_phase_key_trap():
    """Document-level handlers bound at module load must stay inert."""
    src = _read(_SHELL)
    assert "addEventListener('keydown'" in src
    assert re.search(
        r"addEventListener\('keydown',[^)]*,\s*true\)", src
    ), "the keydown listener must be registered in the CAPTURE phase"
    assert re.search(
        r"removeEventListener\('keydown',[^)]*,\s*true\)", src
    ), "and removed with the same capture flag, or it leaks"


def test_the_body_scroll_lock_restores_the_previous_value():
    """Clobbering an outer overlay's lock leaves the page unscrollable."""
    src = _read(_SHELL)
    assert "prevOverflow" in src, "the previous inline overflow must be captured"
    assert "body.style.overflow = prevOverflow" in src, "and restored verbatim"
