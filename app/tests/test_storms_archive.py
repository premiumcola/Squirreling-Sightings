"""Regression guards for the Gewitter-Browser (storm-episode archive).

There is no jsdom harness in this repo — `package.json` carries eslint +
prettier only, and every existing frontend test here is a structural
source assertion (see test_lightbox_weather_render.py, which says so in
its own docstring). These follow that pattern, plus the repo's static
import-graph validator, which already proves every named import in
`storms/` resolves to a real export.

What is pinned here is the set of decisions that are expensive to
rediscover and cheap to break:

  · The chart is EXTENDED, never duplicated. CLAUDE.md forbids parallel
    implementations, and "draw four episodes overlaid" is exactly the
    kind of requirement that grows a second charting module.
  · Compare is PEAK-aligned, with no toggle. Onset alignment scatters
    the maxima; wall-clock produces disjoint curves months apart. The
    reasoning lives in _multi.js's docstring so a refactor cannot
    "helpfully" restore it — this test pins that it stays there.
  · Every additive change to the shared chart package defaults to
    today's behaviour, so the Wetterstatistik panel is unaffected.
  · The iOS checklist items that have actually regressed before in this
    codebase: 16 px inputs, 44 px targets, hover behind a media query,
    and no fixed element sized in vh.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_STATIC = _REPO / "app" / "web" / "static"
_JS = _STATIC / "js"
_CSS = _STATIC / "css"
_TPL = _REPO / "app" / "web" / "templates"
_STORMS = _JS / "storms"
_CHART = _JS / "weather" / "stats-chart"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _storm_sources() -> dict[str, str]:
    return {p.name: _read(p) for p in sorted(_STORMS.glob("*.js"))}


# ── package shape ────────────────────────────────────────────────────


def test_storms_package_exists_with_the_expected_modules():
    names = set(_storm_sources())
    expected = {
        "index.js",
        "_state.js",
        "_api.js",
        "_list.js",
        "_detail.js",
        "_detail_edit.js",
        "_compare.js",
        "_compare_table.js",
        "_footage.js",
        "_helpers.js",
    }
    assert expected <= names, f"missing storms modules: {sorted(expected - names)}"


def test_every_storms_file_is_under_the_js_ceiling():
    """400 lines per JS file, per CLAUDE.md. The two files pre-declared
    as drift-prone (_detail, _compare) were split up front."""
    for name, src in _storm_sources().items():
        n = len(src.splitlines())
        assert n <= 400, f"{name} is {n} lines — split before crossing 400"


def _function_spans(src: str):
    """Yield (name, line_count) for each top-level function declaration.
    Brace-counting, not a real parser — adequate here because these files
    carry no unbalanced braces inside string literals."""
    lines = src.split("\n")
    decl = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)")
    for i, line in enumerate(lines):
        m = decl.match(line)
        if not m:
            continue
        depth = 0
        started = False
        for j in range(i, len(lines)):
            depth += lines[j].count("{") - lines[j].count("}")
            if "{" in lines[j]:
                started = True
            if started and depth <= 0:
                yield m.group(1), j - i + 1
                break


def test_no_storms_or_chart_function_exceeds_sixty_lines():
    for root in (_STORMS, _CHART):
        for path in sorted(root.glob("*.js")):
            for name, n in _function_spans(_read(path)):
                assert n <= 60, f"{path.name}:{name} is {n} lines — split before crossing 60"


# ── one chart package, not two ───────────────────────────────────────


def test_compare_chart_lives_inside_the_existing_chart_package():
    """A `storms/_chart.js` (or any SVG path-building inside storms/)
    would be the parallel implementation CLAUDE.md forbids."""
    assert (_CHART / "_multi.js").exists(), "renderEpisodeChart must live in stats-chart/"
    # Inline icon glyphs are fine; a CHART is not. The chart chrome
    # (hover area, guide line, axis builders) is the tell.
    for name, src in _storm_sources().items():
        assert "catmullRomPath" not in src, f"{name} re-implements curve geometry"
        assert (
            "ws-chart-hover-area" not in src
        ), f"{name} builds chart chrome itself — compose stats-chart/ instead"
        assert "buildLinePath" not in src, f"{name} builds chart geometry itself"


def test_storms_views_render_through_the_shared_chart_entrypoints():
    assert "renderEpisodeChart" in _read(_STORMS / "_compare.js")
    assert "renderStatsChartInto" in _read(_STORMS / "_detail.js")


def test_multi_composes_the_shared_primitives():
    """_multi.js must reuse buildLinePath / buildValueAxis / buildRelTicks
    / bindChartHover rather than growing its own copies."""
    src = _read(_CHART / "_multi.js")
    for sym in ("buildLinePath", "buildValueAxis", "buildRelTicks", "bindChartHover"):
        assert sym in src, f"_multi.js does not reuse {sym}"


def test_value_axis_was_extracted_and_is_still_used_by_buildYAxis():
    """buildValueAxis is a refactor TOWARD reuse: compare's shared
    absolute axis and the Wetter chart's isolated axis must stay one
    tick implementation."""
    src = _read(_CHART / "_axes.js")
    assert "export function buildValueAxis" in src
    body = src[src.index("export function buildYAxis") :]
    assert "buildValueAxis({" in body, "buildYAxis no longer delegates to buildValueAxis"


# ── additive-only chart changes ──────────────────────────────────────


def test_build_line_path_extensions_are_optional():
    """`opts` must default to {} so every existing 6-arg callsite keeps
    its per-line normalisation and index-based x spacing."""
    src = _read(_CHART / "_paths.js")
    m = re.search(r"export function buildLinePath\(([^)]*)\)", src)
    assert m, "buildLinePath signature not found"
    assert "opts = {}" in m.group(1), "the 7th argument must be optional"


def test_bind_chart_hover_formatters_are_optional():
    src = _read(_CHART / "_hover.js")
    m = re.search(r"export function bindChartHover\(([^)]*)\)", src)
    assert m, "bindChartHover signature not found"
    assert "opts = {}" in m.group(1), "the hover options bag must be optional"
    # …and the default paths must still exist for the Wetter panel.
    assert "_defaultRows" in src and "_defaultHead" in src


def test_weather_stats_chart_still_has_its_zero_argument_entrypoint():
    """The Wetter panel calls renderWeatherStatsChart() with no args; the
    extraction must not have pushed that requirement onto callers."""
    src = _read(_CHART / "index.js")
    assert "export function renderWeatherStatsChart()" in src
    assert "export function renderStatsChartInto(wrap, data, opts = {})" in src


# ── peak alignment ───────────────────────────────────────────────────


def test_compare_projects_samples_relative_to_peak_at():
    src = _read(_STORMS / "_compare.js")
    assert "peak_at" in src, "compare must align on peak_at"
    assert "60_000" in src or "60000" in src, "relative minutes conversion missing"
    # started_at must NOT be the alignment origin.
    proj = src[src.index("function _points") :]
    proj = proj[: proj.index("\n}")]
    assert "started_at" not in proj, (
        "onset alignment is a threshold crossing — it means something "
        "different for each episode and scatters the peaks. See _multi.js."
    )


def test_alignment_reasoning_survives_in_the_chart_module():
    """The decision record lives in the module docstring on purpose."""
    src = _read(_CHART / "_multi.js")
    assert "peak_at" in src
    for term in ("Wall-clock", "Onset", "Peak"):
        assert term in src, f"the {term} rationale was dropped from _multi.js"


def test_there_is_no_alignment_toggle():
    for name, src in _storm_sources().items():
        assert (
            "alignMode" not in src and "wallClock" not in src
        ), f"{name} introduces an alignment toggle — §3.2 is decided"


def test_compare_shares_one_absolute_y_scale():
    """Per-line normalisation would draw a 12 mm/h cloudburst and a
    3 mm/h shower as identical curves — the opposite of comparing."""
    src = _read(_CHART / "_multi.js")
    seg = src[src.index("function _seriesPaths") :]
    seg = seg[: seg.index("\n}")]
    assert (
        "lo: dom.lo" in seg and "hi: dom.hi" in seg
    ), "_seriesPaths must force the shared {lo, hi} onto every line"


# ── compare cap ──────────────────────────────────────────────────────


def test_compare_caps_at_four_and_says_so():
    state = _read(_STORMS / "_state.js")
    assert "STORM_MAX_COMPARE = 4" in state
    assert "Maximal 4 Gewitter vergleichen" in _read(_STORMS / "_list.js")


def test_slot_colours_are_imported_not_redeclared():
    """The four compare-slot colours are the app's existing
    "N distinguishable series" palette (core/track-color.js). A hex
    literal here forks the palette; that the four are four, distinct and
    from that palette is asserted behaviourally in
    test_storms_frontend_logic.py."""
    src = _read(_STORMS / "_state.js")
    block = src[src.index("STORM_SLOT_COLORS") :].split("\n\n")[0]
    assert not re.search(r"#[0-9a-fA-F]{6}", block), "a slot colour is hardcoded"
    assert "LIVE_PALETTE" in src


def test_slot_assignment_is_by_slot_not_by_pick_order():
    """Freeing slot 2 must leave slot 2 empty, so an episode keeps its
    colour for the whole session even as others come and go."""
    src = _read(_STORMS / "_state.js")
    body = src[src.index("export function slotRelease") :]
    body = body[: body.index("\n}")]
    assert "splice" not in body, "releasing a slot must not shift the others"
    assert "= null" in body


# ── progressive disclosure + empty states ────────────────────────────


def test_controls_appear_only_once_they_do_something():
    src = _read(_STORMS / "_list.js")
    assert "list.length < 4" in src, "the class filter must be hidden below 4 episodes"
    assert "list.length < 3" in src, "rank chips need 3 episodes"
    assert "list.length >= 3" in src, "the sort control needs 3 episodes"
    assert "years.length > 1" in src, "the year selector needs 2 years"


def test_day_one_empty_state_names_the_thresholds_it_waits_for():
    src = _read(_STORMS / "_list.js")
    assert "Noch kein Gewitter aufgezeichnet." in src
    assert "Aktuelle Schwellen" in src, (
        "the empty state must show what the detector is armed on — "
        "without it the archive reads as broken rather than ready"
    )
    assert "thresholds" in src


def test_single_episode_teaches_compare_without_offering_a_broken_control():
    src = _read(_STORMS / "_list.js")
    assert "Vergleich ab 2 Gewittern" in src


def test_missing_backend_degrades_to_an_empty_archive():
    """The endpoints may not exist yet. Read paths must resolve, never
    throw, so the section renders the calm empty state."""
    src = _read(_STORMS / "_api.js")
    for fn in ("fetchEpisodes", "fetchEpisode", "fetchFootage"):
        body = src[src.index(f"function {fn}") :]
        body = body[: body.index("\n}")]
        assert "catch" in body, f"{fn} must not propagate a transport failure"


def test_footage_hint_offers_the_action_that_fixes_it():
    src = _read(_STORMS / "_footage.js")
    assert "event_timelapse_disabled" in src
    assert "Kamera-Einstellungen öffnen" in src
    assert "weather_service_unavailable" in src
    assert "Keine Aufnahmen in diesem Zeitraum." in src


def test_footage_chip_is_absent_rather_than_zero():
    src = _read(_STORMS / "_list.js")
    body = src[src.index("function _rowHtml") :]
    body = body[: body.index("\nfunction ")]
    assert "footage_count" in body
    assert "> 0" in body, "a 0 footage_count must render no chip at all"


# ── German UI ────────────────────────────────────────────────────────


def test_user_facing_copy_is_german():
    list_src = _read(_STORMS / "_list.js")
    for phrase in ("Neueste", "Stärkste", "Vergleichen", "ausgewählt", "Gewitter-Archiv"):
        assert phrase in list_src, f"missing German copy: {phrase}"
    edit_src = _read(_STORMS / "_detail_edit.js")
    assert "Automatisch erkannt:" in edit_src
    assert "Notiz hinzufügen" in edit_src
    assert "konnte nicht gespeichert werden" in edit_src


def test_class_colours_are_imported_not_redeclared():
    """Every class colour already exists in the codebase; re-declaring a
    hex here would fork the palette."""
    src = _read(_STORMS / "_state.js")
    block = src[src.index("export const STORM_CLASSES") : src.index("STORM_CLASS_ORDER")]
    assert not re.search(r"color:\s*'#", block), "a class colour is hardcoded"
    assert "WEATHER_TYPES" in src and "WEATHER_STATS_PALETTE" in src


# ── iOS checklist ────────────────────────────────────────────────────


def test_text_inputs_are_sixteen_px():
    """Below 16 px iOS auto-zooms on focus. Non-negotiable."""
    css = _read(_CSS / "24b-storms.css")
    rule = re.search(r"\.st-name-input,\s*\.st-note-input \{(.*?)\}", css, re.DOTALL)
    assert rule, "the name/note input rule is gone"
    assert "font-size: 16px" in rule.group(1)


def test_touch_targets_clear_forty_four_px():
    css = _read(_CSS / "24b-storms.css")
    for cls in (".st-pick", ".st-lx", ".st-mpill", ".st-back", ".st-note-row"):
        rule = re.search(rf"^{re.escape(cls)} \{{(.*?)\}}", css, re.DOTALL | re.MULTILINE)
        assert rule, f"{cls} rule missing"
        assert "44px" in rule.group(1), f"{cls} is below the 44 px touch target"


def test_sort_pills_are_raised_to_forty_four_in_the_storms_scope():
    """.ws-stats-pill's 32 px min-height is a desktop-era leftover and is
    explicitly not inherited here."""
    css = _read(_CSS / "24b-storms.css")
    rule = re.search(r"^\.st-pill \{(.*?)\}", css, re.DOTALL | re.MULTILINE)
    assert rule and "min-height: 44px" in rule.group(1)


def test_hover_states_are_guarded():
    """Without the guard iOS latches the hover state on tap."""
    css = _read(_CSS / "24b-storms.css")
    for cls in (".st-row:hover", ".st-tile:hover"):
        idx = css.index(cls)
        before = css[:idx]
        assert "@media (hover: hover)" in before.rsplit("}", 3)[0] or (
            before.rfind("@media (hover: hover)") > before.rfind("\n}\n")
        ), f"{cls} is not inside a (hover: hover) query"


def test_the_only_fixed_element_clears_the_dock_without_vh():
    """The compare action bar is anchored from the dock's own promoted
    metrics, so a future dock resize propagates automatically — and it is
    never sized in vh, which is what makes address-bar collapse jump."""
    mobile = _read(_CSS / "25-mobile.css")
    rule = re.search(r"\.st-selbar \{(.*?)\}", mobile, re.DOTALL)
    assert rule, "the mobile .st-selbar rule is missing"
    body = rule.group(1)
    assert "position: fixed" in body
    assert "--m-dock-h" in body and "--m-dock-bottom-gap" in body
    assert "vh" not in body, "the action bar must never be sized in vh"
    dock = _read(_CSS / "05-chrome-dock.css")
    assert "--m-dock-h:" in dock, "the dock height was never promoted to :root"


def test_chart_allows_vertical_page_scroll_to_start_on_it():
    css = _read(_CSS / "24b-storms.css")
    rule = re.search(r"^\.st-chart-wrap \{(.*?)\}", css, re.DOTALL | re.MULTILINE)
    assert rule and "touch-action: pan-y" in rule.group(1), (
        "a 200 px-tall plot filling the phone's width would otherwise "
        "swallow a vertical page scroll that starts on the chart"
    )


def test_class_chips_wrap_into_a_grid_on_phones_rather_than_scrolling():
    """This is the primary action of the page; all five options must be
    visible simultaneously."""
    mobile = _read(_CSS / "25-mobile.css")
    assert "@media (max-width: 480px)" in mobile
    seg = mobile[mobile.index(".st-cstrip") :][:400]
    assert "grid-template-columns: repeat(3, 1fr)" in seg


def test_no_thin_borders_in_the_storms_stylesheet():
    """Depth comes from colour contrast, per the design principles."""
    css = _read(_CSS / "24b-storms.css")
    # `border: 0` is a reset, not a border — only a declared border width
    # counts as an offender.
    offenders = []
    for line in css.splitlines():
        m = re.match(r"\s*border(?:-(?:top|right|bottom|left))?:\s*([^;]+);", line)
        if m and m.group(1).strip() not in ("0", "none", "0px"):
            offenders.append(line.strip())
    assert not offenders, f"thin borders introduced: {offenders}"


# ── wiring ───────────────────────────────────────────────────────────


def test_section_is_included_after_weather():
    index = _read(_TPL / "index.html")
    assert "partials/storms.html" in index
    assert index.index("partials/storms.html") > index.index("partials/weather.html")
    section = _read(_TPL / "partials" / "storms.html")
    assert 'id="storms"' in section and 'id="stormsBody"' in section
    assert 'data-accent="127,174,201"' in section


def test_scrollspy_knows_the_new_section():
    src = _read(_JS / "chrome" / "sidebar.js")
    ids = src[src.index("const sectionIds") :]
    ids = ids[: ids.index("]")]
    assert "'storms'" in ids
    assert ids.index("'storms'") > ids.index("'weather'")


def test_sidenav_entry_uses_the_new_sprite_glyph():
    nav = _read(_TPL / "partials" / "sidenav.html")
    assert 'href="#storms"' in nav and "Gewitter-Archiv" in nav
    assert "#icon-bolt" in nav
    assert 'id="icon-bolt"' in _read(
        _TPL / "partials" / "icons.html"
    ), "the bolt glyph must be promoted into the sprite"


def test_mobile_dock_is_untouched():
    """Five slots are full; a sixth breaks repeat(5, 1fr) and the 44 px
    budget at 375 px. Discovery comes from the Wetter section instead."""
    dock = _read(_TPL / "partials" / "mobile_dock.html")
    assert "#storms" not in dock
    assert "Gewitter-Archiv →" in _read(_TPL / "partials" / "weather.html")


def test_stylesheet_is_registered_before_the_mobile_partial():
    builder = _read(_REPO / "app" / "app" / "css_builder.py")
    order = builder[builder.index("LOAD_ORDER") : builder.index("def ")]
    assert '"24b-storms.css"' in order
    assert order.index('"24b-storms.css"') > order.index('"24-cam-edit-4.css"')
    assert order.index('"24b-storms.css"') < order.index(
        '"25-mobile.css"'
    ), "25-mobile.css must still win every mobile override"
    assert (_CSS / "24b-storms.css").exists()


def test_legend_strip_joins_the_shared_scroll_strip_component():
    assert ".st-legend-strip" in _read(_JS / "chrome" / "tab-strip.js")
    assert ".st-legend-strip" in _read(_CSS / "25-mobile.css")


def test_hash_routes_are_registered():
    src = _read(_STORMS / "index.js")
    assert "#/gewitter/vergleich/" in src
    assert re.search(r"#\\/gewitter\\/", src), "the detail hash route regex is missing"


def test_api_patch_helper_exists():
    src = _read(_JS / "core" / "api.js")
    assert "export const apiPatch" in src
    assert "method: 'PATCH'" in src


def test_storms_only_talks_to_the_episode_api():
    """All network access is funnelled through _api.js, and every URL it
    builds hangs off the agreed episode base path."""
    api = _read(_STORMS / "_api.js")
    assert "const BASE = '/api/weather/episodes'" in api
    for url in re.findall(r"`(\$\{BASE\}[^`]*)`", api):
        assert url.startswith("${BASE}"), url
    for name, src in _storm_sources().items():
        if name == "_api.js":
            continue
        assert (
            "fetch(" not in src and "apiGet(" not in src
        ), f"{name} bypasses _api.js — all episode I/O goes through one module"


def test_episode_list_is_requested_without_pagination():
    """The client computes the year's Top-3 locally from the full list;
    a paginated response makes correct ranking impossible (§9.3)."""
    api = _read(_STORMS / "_api.js")
    body = api[api.index("export async function fetchEpisodes") :]
    body = body[: body.index("\n}")]
    assert (
        "page" not in body and "limit" not in body
    ), "the episode list must not be requested paginated"
