"""The hero frame shows the whole bird.

„vögel nicht abschneiden!" — the third complaint about the same box.
It was `cover` centred (head cut off), then `contain` (photos at
different widths on different grounds), then `cover` at 38 % (tail and
beak cut off). CLAUDE.md's rule for a component patched more than twice
for one symptom is to rewrite it, so the frame now layers a blurred copy
of the photo behind a `contain` subject: nothing is cropped AND every
box keeps the same size and ground.

These tests pin the property, not the pixels — if someone reaches for
`object-fit: cover` on the subject again, this fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
CSS = (WEB / "static" / "css" / "29-birds.css").read_text(encoding="utf-8")
HERO_JS = (WEB / "static" / "js" / "sichtungen" / "_hero-overlay.js").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """The declaration block of one CSS rule, by exact selector."""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"no rule for {selector}"
    return m.group(1)


# ── the subject is never cropped ─────────────────────────────────────


def test_the_subject_layer_is_contain():
    assert "object-fit: contain" in _rule(".sd-hero-subject")


def test_the_subject_layer_is_not_cropped_by_any_rule():
    """No later rule may quietly put `cover` back on the subject."""
    for block in re.findall(r"\.sd-hero-subject[^{]*\{([^}]*)\}", CSS):
        assert "object-fit: cover" not in block
        assert "object-position" not in block, (
            "object-position only matters when something is being cropped"
        )


def test_the_old_blanket_image_rule_is_gone():
    """`.sd-hero-photo img { object-fit: cover }` covered both layers and
    is what cut the birds; it must not survive alongside the new rules."""
    assert not re.search(r"\.sd-hero-photo\s+img\s*\{", CSS)


# ── the frame still lines up ─────────────────────────────────────────


def test_the_fill_layer_covers_the_whole_box():
    fill = _rule(".sd-hero-photo::before")
    assert "background-size: cover" in fill
    assert "position: absolute" in fill
    assert "inset: 0" in fill


def test_the_fill_is_blurred_beyond_legibility():
    fill = _rule(".sd-hero-photo::before")
    blur = re.search(r"blur\((\d+)px\)", fill)
    assert blur, "the ground has to be out of focus or it competes with the subject"
    assert int(blur.group(1)) >= 12


def test_the_fill_is_overscaled_so_the_blur_has_no_rim():
    fill = _rule(".sd-hero-photo::before")
    scale = re.search(r"scale\(([\d.]+)\)", fill)
    assert scale and float(scale.group(1)) > 1.0


def test_the_fill_sits_under_the_subject():
    fill = int(re.search(r"z-index:\s*(\d+)", _rule(".sd-hero-photo::before")).group(1))
    subject = int(re.search(r"z-index:\s*(\d+)", _rule(".sd-hero-subject")).group(1))
    assert fill < subject


def test_the_caption_stays_on_top_of_both():
    caption = re.search(r"\.sd-hero-scrim,\s*\.sd-hero-caption,\s*\.sd-hero-play\s*\{([^}]*)\}", CSS)
    assert caption, "the caption group lost its stacking rule"
    z = int(re.search(r"z-index:\s*(\d+)", caption.group(1)).group(1))
    assert z > 1


def test_the_box_makes_its_own_stacking_context():
    """Without this the z-indexes leak into the page's context."""
    assert "isolation: isolate" in _rule(".sd-hero-photo")


# ── the markup carries both layers ───────────────────────────────────


def test_each_photo_renders_a_ground_and_a_subject():
    assert "--sd-hero-src" in HERO_JS, "no photo URL is handed to the blurred ground"
    assert "sd-hero-subject" in HERO_JS


def test_the_ground_is_not_a_second_image_element():
    """One <img> per photo. A duplicate would be announced twice by a
    screen reader, and — the reason it was changed — an over-scaled
    <img> keeps a layout box that escapes the frame."""
    assert HERO_JS.count("<img class=") == 1
    assert "sd-hero-fill" not in HERO_JS


def test_the_photo_url_is_escaped_for_css():
    """The URL comes from Wikipedia and lands inside url() inside a
    style attribute — two nested contexts, so esc() alone is wrong."""
    assert "cssUrl(src)" in HERO_JS
    dom = (WEB / "static" / "js" / "core" / "dom.js").read_text(encoding="utf-8")
    body = dom[dom.index("export const cssUrl"):]
    body = body[: body.index("\n};")]
    for hostile in ("\\\\", "(", ")", ";", '"', "'"):
        assert hostile in body, f"the allowlist does not mention {hostile!r}"


def test_reduced_transparency_drops_the_blur():
    """A big blur per dossier is decoration; honour the preference."""
    m = re.search(r"@media \(prefers-reduced-transparency: reduce\)\s*\{(.*?)\n\}", CSS, re.S)
    assert m, "no reduced-transparency guard on the blurred ground"
    assert ".sd-hero-photo::before" in m.group(1)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_every_layout_keeps_a_fixed_frame(count):
    """Equal height / equal width was the OTHER half of the complaint;
    each layout still pins its own aspect ratio rather than letting the
    photos size the box."""
    assert "aspect-ratio" in _rule(f".sd-hero--{count}")
