"""The save panel's ambient weather backdrop stays safe and cheap.

weather/save-panel-fx/ paints rain, snow, fog and lightning behind the
manual-event save form, driven by the category chips. Two halves of that
are load-bearing in a way no node test can reach, because they live in
css/23c-weather-fx.css:

  · the flash. A bright, irregular, full-panel bloom is the one effect
    here that can genuinely hurt somebody — the recognised danger zone
    starts at three flashes per second. The JS floor (3.2 s between
    strikes) only holds if the keyframe itself carries a SINGLE
    luminance peak; a keyframe with a second peak part-way through would
    put two flashes a few dozen milliseconds apart no matter how patient
    the scheduler is. Both halves are asserted below, the JS one by
    reading the constant straight out of _helpers.js.

  · the opt-out. prefers-reduced-motion must kill the whole layer, not
    just slow it down.

Plus the mechanical iOS/CSS rules CLAUDE.md runs on every UI commit, for
this partial: no bare vh, no unguarded :hover, no fixed positioning.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FX_CSS = _ROOT / "app" / "web" / "static" / "css" / "23c-weather-fx.css"
_FX_JS = _ROOT / "app" / "web" / "static" / "js" / "weather" / "save-panel-fx"


def _css() -> str:
    return _FX_CSS.read_text(encoding="utf-8")


def _no_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _no_line_comments(js: str) -> str:
    """Drop `//` comments so a rule can assert on the CODE.

    The modules under test explain in prose exactly what they refuse to
    do ("rather than setInterval …"), which a naive substring check
    would read as the forbidden call itself.
    """
    return re.sub(r"^\s*//.*$", "", js, flags=re.MULTILINE)


def _keyframe_opacities(css: str, name: str) -> list[float]:
    block = re.search(rf"@keyframes {name} \{{(.*?)\n\}}", css, re.DOTALL)
    assert block, f"no @keyframes {name}"
    return [float(v) for v in re.findall(r"opacity:\s*([0-9.]+)", block.group(1))]


def test_the_partial_is_registered_in_the_load_order():
    builder = (_ROOT / "app" / "app" / "css_builder.py").read_text(encoding="utf-8")
    assert _FX_CSS.exists()
    assert '"23c-weather-fx.css"' in builder
    order = builder[builder.index("LOAD_ORDER") : builder.index("def ")]
    # After 23b (whose .ws-zoom-save rule it extends) and before mobile.
    assert order.index('"23c-weather-fx.css"') > order.index('"23b-weather-zoom.css"')
    assert order.index('"23c-weather-fx.css"') < order.index('"25-mobile.css"')


def test_the_strike_has_exactly_one_luminance_peak():
    """Two peaks inside one 620 ms animation would be ~10 Hz however far
    apart the strikes themselves are scheduled."""
    stops = _keyframe_opacities(_no_comments(_css()), "ws-fx-strike")
    lit = [v for v in stops if v > 0]
    assert len(lit) == 1, f"the strike must rise once and decay, got {stops}"
    assert stops[0] == 0 and stops[-1] == 0, "it must start and end dark"


def test_the_flash_never_washes_the_form_out():
    """Peak alpha is the contrast budget. At 0.28, with the hot spot hung
    above the panel's top edge, the brightest instant still leaves the
    body text at ≈7.5:1 and the 12 px uppercase labels at ≈3.3:1."""
    (peak,) = [v for v in _keyframe_opacities(_no_comments(_css()), "ws-fx-strike") if v > 0]
    assert peak <= 0.28, f"peak alpha {peak} is brighter than the contrast budget"


def test_the_scheduler_keeps_strikes_an_order_below_three_hertz():
    src = (_FX_JS / "_helpers.js").read_text(encoding="utf-8")
    m = re.search(r"FLASH_MIN_GAP_MS\s*=\s*(\d+)", src)
    assert m, "FLASH_MIN_GAP_MS is gone"
    gap_ms = int(m.group(1))
    assert gap_ms >= 3000, f"{gap_ms} ms between strikes is too fast"
    assert 1000 / gap_ms < 0.5


def test_reduced_motion_removes_the_whole_layer():
    css = _no_comments(_css())
    block = re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}",
        css,
        re.DOTALL,
    )
    assert block, "no prefers-reduced-motion block"
    body = block.group(1)
    assert ".ws-fx {" in body and "display: none" in body, "the layer must go, not just slow down"
    assert "animation: none" in body


def test_the_backdrop_can_never_intercept_a_tap():
    css = _no_comments(_css())
    layer = re.search(r"^\.ws-fx \{(.*?)\}", css, re.DOTALL | re.MULTILINE)
    assert layer, "no .ws-fx rule"
    assert "pointer-events: none" in layer.group(1)


def test_the_form_paints_above_the_backdrop():
    css = _no_comments(_css())
    assert "z-index: 0" in css and "z-index: 1" in css
    assert ".ws-zoom-save > .ws-zsave-row" in css


def test_the_partial_keeps_the_mechanical_ios_rules():
    css = _no_comments(_css())
    assert "position: fixed" not in css
    for prop in set(re.findall(r"([a-z-]+)\s*:\s*[^;]*\bvh\b", css)):
        assert re.search(rf"{prop}\s*:\s*[^;]*\bdvh\b", css), f"'{prop}' is sized in vh"
    guarded = re.sub(
        r"@media\s*\(hover:\s*hover\)\s*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}",
        "",
        css,
        flags=re.DOTALL,
    )
    assert ":hover" not in guarded


def test_every_fx_module_stays_inside_the_js_size_budget():
    """CLAUDE.md's 400-line ceiling, checked where the feature is young
    enough that keeping it split is still cheap."""
    for path in sorted(_FX_JS.glob("*.js")):
        lines = path.read_text(encoding="utf-8").count("\n")
        assert lines <= 400, f"{path.name} is {lines} lines"


def test_the_loop_cannot_outlive_the_panel():
    """Every requestAnimationFrame and setTimeout the backdrop starts has
    a matching cancel, and the teardown path removes the layer itself —
    this runs next to live detection, not on an idle desktop."""
    particles = (_FX_JS / "_particles.js").read_text(encoding="utf-8")
    lightning = _no_line_comments((_FX_JS / "_lightning.js").read_text(encoding="utf-8"))
    index = (_FX_JS / "index.js").read_text(encoding="utf-8")
    assert "cancelAnimationFrame" in particles
    assert "setInterval" not in lightning, "an interval would also be a metronome"
    assert "clearTimeout" in lightning
    for call in ("_fx.ro?.disconnect()", "_fx.particles?.stop()", "_fx.lightning?.stop()"):
        assert call in index, f"_unmount does not {call}"
    assert "removeEventListener('visibilitychange'" in index
    assert "_fx.root.remove()" in index
