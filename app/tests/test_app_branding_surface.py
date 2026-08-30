"""The Setup-Wizard must not collect branding nothing renders.

``renderShell`` hydrated ``#appName``, ``#appTagline``, ``#sideAppName``
and ``#appSubtitle`` from ``config.app``. None of those four ids exists
in any template: the hero became a static lockup — an SVG squirrel
glyph on the hyphen plus a fixed wordmark — and the sidenav is pure
navigation with no brand element at all. Every branch of the function
was a null-guarded no-op.

The near end was worse than dead, it was a promise. The wizard's first
step still offered "App-Name", "Tagline" and "Logo Emoji" (defaulting
to a cat emoji the app does not use anywhere), wrote all three to
settings.json, and nothing on any screen ever changed. So both ends go:
the hydration and the three inputs. Re-wiring them was the alternative
and it loses — the static lockup with its ornament is a deliberate
design, not an oversight, and a user-typed string cannot carry it.

``app.theme`` is untouched: it has no UI control either way, so it is a
config.yaml-level constant rather than a control that lies.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JS_DIR = _ROOT / "web" / "static" / "js"
_TPL_DIR = _ROOT / "web" / "templates"

_DEAD_IDS = ("appName", "appTagline", "sideAppName", "appSubtitle")
_WIZARD_FIELDS = ("wiz_app_name", "wiz_tagline", "wiz_logo")


def _js_sources() -> dict[str, str]:
    """Keyed by path relative to the js root — several packages have
    their own `index.js`, and keying by bare filename silently dropped
    all but one of them."""
    return {
        p.relative_to(_JS_DIR).as_posix(): p.read_text(encoding="utf-8")
        for p in _JS_DIR.rglob("*.js")
    }


def _template_sources() -> dict[str, str]:
    return {
        p.relative_to(_TPL_DIR).as_posix(): p.read_text(encoding="utf-8")
        for p in _TPL_DIR.rglob("*.html")
    }


def test_no_js_hydrates_an_id_no_template_defines():
    js = _js_sources()
    tpl = "\n".join(_template_sources().values())
    for dead in _DEAD_IDS:
        hydrators = [name for name, src in js.items() if f"'{dead}'" in src]
        assert not hydrators, (
            f"{dead} is hydrated by {hydrators} but no template defines it — "
            "either wire the id into the shell or drop the hydration"
        )
        assert f'id="{dead}"' not in tpl


def _code_lines(src: str) -> str:
    """Source with `//` comment lines dropped — the removal is explained
    in comments that name the symbol, and a naive substring scan would
    read its own epitaph as a survivor."""
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


# `_renderShell` in detection-cloud.js is an unrelated private helper;
# the negative lookbehind keeps it out of the match.
_RENDER_SHELL = re.compile(r"(?<![\w_])renderShell\b")


def test_render_shell_is_gone():
    survivors = [
        name for name, src in _js_sources().items() if _RENDER_SHELL.search(_code_lines(src))
    ]
    assert survivors == [], f"renderShell survives in {survivors}"


def test_the_wizard_offers_no_branding_it_cannot_apply():
    js = "\n".join(_js_sources().values())
    tpl = "\n".join(_template_sources().values())
    for field in _WIZARD_FIELDS:
        assert field not in tpl, f"{field} is still an input the wizard shows"
        assert field not in js, f"{field} is still read by the wizard payload builder"


def test_the_hero_lockup_stays_static():
    """Guard the other direction: this is a design decision, so the
    wordmark must not quietly become config-driven again."""
    hero = (_TPL_DIR / "partials" / "hero.html").read_text(encoding="utf-8")
    assert "hero-wordmark" in hero
    assert "Squirreling · Sightings" in hero
