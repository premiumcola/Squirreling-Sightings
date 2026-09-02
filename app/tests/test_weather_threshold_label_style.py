"""HYG · the threshold label's legibility halo must actually be applied.

`stats-thresholds.js` emits the isolated-mode threshold label with
`class="ws-chart-threshold-label"` and a comment promising it "keeps
paint-order halo for legibility against the chart background". The only
rule that ever provided that halo is called `.ws-stats-threshold-label`.
Commit 5f88e0a ("grafana-style ticks") renamed the class on the JS side
alone, so since then the rule has matched nothing: the label has been
painted as plain 10 px text with no dark stroke behind the glyphs,
directly on top of the coloured data lines it sits among.

Nothing caught it because the two names live in different files and
neither side is unused on its own — the CSS rule simply stopped being
reachable.

Pure source inspection. No browser, no DOM.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_JS = _REPO / "app" / "web" / "static" / "js" / "weather" / "stats-thresholds.js"
_CSS = _REPO / "app" / "web" / "static" / "css" / "23-weather-3.css"


def _rule_body(css: str, selector: str) -> str | None:
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    return m.group(1) if m else None


def _emitted_svg_classes(js: str) -> set[str]:
    """Class names the module puts into the SVG it builds."""
    return set(re.findall(r"""<(?:text|line|rect|g)\s[^>]*class="([^"{]+)\"""", js))


def test_every_class_the_threshold_overlay_emits_has_a_css_rule():
    js = _JS.read_text(encoding="utf-8")
    css = _CSS.read_text(encoding="utf-8")
    emitted = _emitted_svg_classes(js)
    assert emitted, "no classed SVG element found — did the builder change shape?"
    for cls in sorted(emitted):
        assert _rule_body(css, f".{cls}") is not None, (
            f"stats-thresholds.js emits .{cls} but 23-weather-3.css has no "
            f"rule for it — the styling silently does nothing"
        )


def test_the_threshold_label_still_gets_its_halo():
    """The halo is the whole point of the rule: without paint-order the
    label is unreadable where it crosses a data line."""
    css = _CSS.read_text(encoding="utf-8")
    js = _JS.read_text(encoding="utf-8")
    (cls,) = [c for c in _emitted_svg_classes(js) if "threshold-label" in c]
    body = _rule_body(css, f".{cls}")
    assert body is not None, f".{cls} has no rule"
    assert "paint-order: stroke" in body, "the dark stroke is drawn over the fill, not behind it"
    assert re.search(r"stroke:\s*rgba", body), "no stroke colour — nothing to make a halo from"


def test_the_label_rule_does_not_pin_a_fill():
    """The line colour is a presentation attribute set per field
    (`fill="${colour}"`); a `fill` in the CSS would beat it and repaint
    every threshold label the old uniform red, undoing the deliberate
    "reads as part of the same series" change 5f88e0a made."""
    css = _CSS.read_text(encoding="utf-8")
    js = _JS.read_text(encoding="utf-8")
    (cls,) = [c for c in _emitted_svg_classes(js) if "threshold-label" in c]
    body = _rule_body(css, f".{cls}")
    assert body is not None, f".{cls} has no rule"
    assert not re.search(r"(^|;)\s*fill\s*:", body), (
        f".{cls} pins a fill — the per-line colour from stats-thresholds.js " f"would be overridden"
    )
