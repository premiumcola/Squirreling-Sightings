"""Stage 9 — the merged library grid becomes the Mediathek's third state.

Two operator asks, from two annotated screenshots:

  1. The camera-tile overview (#mediaOverview, plus the Tiere/Menschen/
     Wetterereignisse quick tiles) is what shows by default. Touching a
     quick tile OR any #libraryFilterBar chip shows the merged
     `/api/library` results (#libraryBlock) in the SAME area instead —
     the tiles disappear while a filter/tile selection is active and
     reappear once it's cleared. A camera tile still opens the
     per-camera drilldown (#mediaDrilldown) as its own, different state
     — never at the same time as the results grid.
  2. The always-visible "Alle Ereignisse" heading that used to sit above
     #libraryBlock as a permanent, separate section is gone completely
     — "die Summe muss komplett raus". The grid markup itself
     (#libraryGrid / #libraryPagination) is unchanged, only its
     always-on framing. (#libraryLoadMore, the old "Mehr laden" control
     this test originally pinned by that name, was itself replaced by
     the page-numbered #libraryPagination in Stage 11 — a later, unrelated
     change; see library/_pagination.js and library/_cursor-stack.js.)

mediathek/_view-toggle.js::showMediathekView is the single toggle
behind all three states; mediathek/_tests/view-toggle.test.js and
core/_tests/scroll-anchor.test.js (node --test) cover its own behaviour
and the companion scroll-anchor fix respectively — this file pins the
template/wiring side only.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TPL = _REPO / "app" / "web" / "templates"
_JS = _REPO / "app" / "web" / "static" / "js"
_CSS = _REPO / "app" / "web" / "static" / "css"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> str:
    """The file without its `//` comment lines.

    „X kommt nicht mehr vor" ist sonst keine Aussage über den Code: in
    diesem Projekt erklärt jede Entfernung sich selbst an Ort und Stelle,
    und der Kommentar, der sagt WARUM es weg ist, nennt es beim Namen.
    Ein Test, der über den Kommentar stolpert, verbietet die Erklärung.
    Gleiches gilt für die CSS-Variante mit `/* … */`.
    """
    src = _read(path)
    if path.suffix == ".css":
        out, rest = [], src
        while "/*" in rest:
            head, _, rest = rest.partition("/*")
            out.append(head)
            _, _, rest = rest.partition("*/")
        out.append(rest)
        return "".join(out)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


_MEDIATHEK = _TPL / "partials" / "mediathek.html"


# ── "Alle Ereignisse" is gone, completely ────────────────────────────────


def test_alle_ereignisse_heading_is_gone_from_the_template():
    assert "Alle Ereignisse" not in _read(_MEDIATHEK)


def test_library_block_no_longer_carries_its_own_permanent_subsection_head():
    """Exactly one `.lib-subsection-head` remains — "Kamera-Ansicht &
    Auswahl" — not two. The second one used to frame #libraryBlock as
    its own always-visible section."""
    mediathek = _read(_MEDIATHEK)
    assert mediathek.count("lib-subsection-head") == 1
    assert "Kamera-Ansicht" in mediathek


# ── #libraryBlock is the toggle's third state, not a permanent section ───


def test_library_block_starts_hidden_like_the_drilldown_does():
    mediathek = _read(_MEDIATHEK)
    block = mediathek[mediathek.index('id="libraryBlock"') - 40 :]
    block = block[: block.index(">") + 1]
    assert "display: none" in block, "libraryBlock must start hidden, same as mediaDrilldown"


def test_the_three_states_are_still_all_present_and_still_siblings():
    """#mediaOverview / #mediaDrilldown / #libraryBlock all still render
    inside #media, in that order — the toggle only changes which one is
    visible, never removes any of them from the DOM."""
    mediathek = _read(_MEDIATHEK)
    for needle in ('id="mediaOverview"', 'id="mediaDrilldown"', 'id="libraryBlock"'):
        assert needle in mediathek
    assert (
        mediathek.index('id="mediaOverview"')
        < mediathek.index('id="mediaDrilldown"')
        < mediathek.index('id="libraryBlock"')
    )


def test_library_grid_markup_itself_is_unchanged():
    """The operator asked for the ALWAYS-VISIBLE FRAMING gone, not the
    grid — #libraryGrid / #libraryPagination still render, just under the
    toggle instead of a permanent heading."""
    mediathek = _read(_MEDIATHEK)
    for needle in ('id="libraryGrid"', 'id="libraryPagination"'):
        assert needle in mediathek


def test_no_banner_claims_the_grid_follows_the_weather_time_chooser():
    """The Wetterdaten time chooser sits at the FOOT of this section and
    controls its own chart only. The "Gefiltert auf den im Chart
    gewählten Zeitraum." note that used to sit above the grid described a
    coupling that no longer exists — a filter whose control is off-screen
    is the confusion, and a banner about it is not the cure."""
    mediathek = _read(_MEDIATHEK)
    assert 'id="libraryZoomNote"' not in mediathek
    assert "Gefiltert auf den im Chart" not in mediathek
    # …and the same coupling is gone from the two JS surfaces that read
    # the chart's zoom directly: the banner toggle and the empty state.
    for module in ("page.js", "_grid.js"):
        src = _read(_JS / "library" / module)
        assert "isZoomActive" not in src, f"library/{module} still follows the weather chart"


# ── a way back to the tile overview ───────────────────────────────────────


def test_a_reset_control_exists_inside_the_results_state():
    mediathek = _read(_MEDIATHEK)
    assert 'data-action="resetLibraryView"' in mediathek
    # Reuses the existing drilldown "back" visual language rather than
    # inventing a new control style.
    block = mediathek[mediathek.index('data-action="resetLibraryView"') - 200 :]
    block = block[: block.index('data-action="resetLibraryView"') + 40]
    assert "media-drill-back" in block


def test_reset_library_view_is_exported_and_bridged():
    src = _read(_JS / "library" / "page.js")
    assert "export function resetLibraryView" in src
    assert "window.resetLibraryView = resetLibraryView" in src


def test_reset_library_view_clears_every_filter_dimension():
    src = _read(_JS / "library" / "page.js")
    fn = src[src.index("export function resetLibraryView") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "_filter.cameraIds.clear()" in fn
    assert "_filter.labels.clear()" in fn
    assert "_filter.categories.clear()" in fn
    assert "_kinds = null" in fn


def test_reset_action_is_registered_in_the_global_click_delegator():
    src = _read(_JS / "core" / "action-registry.js")
    assert "registerAction('resetLibraryView'" in src


# ── showMediathekView: the one toggle, not a parallel visibility system ──


def test_view_toggle_module_exists_and_covers_all_three_states():
    src = _read(_JS / "mediathek" / "_view-toggle.js")
    assert "export function showMediathekView" in src
    for state_id in ("mediaOverview", "mediaDrilldown", "libraryBlock"):
        assert state_id in src


def test_drilldown_reuses_the_shared_toggle_instead_of_its_own_style_writes():
    """Regression: _drilldown.js used to flip #mediaOverview/#mediaDrilldown
    via manual `byId(...).style.display = ...` writes in four places —
    a second, parallel visibility mechanism next to the new results
    state would have meant two places a future third state has to be
    taught about instead of one."""
    src = _read(_JS / "mediathek" / "_drilldown.js")
    assert "from './_view-toggle.js'" in src
    assert src.count("showMediathekView(") >= 4
    assert "byId('mediaOverview').style.display" not in src
    assert "byId('mediaDrilldown').style.display" not in src


def test_library_page_drives_the_toggle_from_the_filter_state():
    src = _read(_JS / "library" / "page.js")
    assert "from '../mediathek/_view-toggle.js'" in src
    assert "showMediathekView('libraryBlock')" in src
    assert "showMediathekView('mediaOverview')" in src


def test_library_page_syncs_the_toggle_on_every_filter_change():
    """_onFilterChange is the one function every trigger (chip clicks,
    both quick-tile setters, the reset control) already funnels
    through — the toggle sync has to live there, not duplicated per
    trigger."""
    src = _read(_JS / "library" / "page.js")
    fn = src[src.index("function _onFilterChange") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "_syncMediathekView()" in fn


def test_leaving_an_open_drilldown_reuses_its_own_close_bridge():
    """A programmatic filter change (a quick tile, resetLibraryView) has
    to be able to override an open per-camera drilldown — reusing
    window.closeMediaDrilldown (the exact function the drilldown's own
    "← Alle Kameras" button already calls) keeps that cleanup
    (state.mediaDrillOpen, the active moc-card, the section title) in one
    place instead of re-derived here.

    The bar itself is no longer TAPPABLE during a drilldown — it is
    hidden with the grid it filters, see the dedup tests below — so this
    path is now reached from code rather than a chip."""
    src = _read(_JS / "library" / "page.js")
    assert "window.closeMediaDrilldown" in src


# ── „Filter sind doppelt drin!" — one class-filter row per state ─────────
#
# The class taxonomy (Katze/Vogel/Hund/…) was on screen twice in BOTH
# states. In the overview: #libraryFilterBar's label chips, and a few
# pixels below them a #mediaFilterBarOverview painted by the very same
# vocabulary. In the drilldown: #libraryFilterBar again, over the
# drilldown's own #mediaFilterBar — with the top one filtering a grid
# that was not even visible, and each printing its own count for „Vogel".


def test_the_camera_overview_paints_no_class_row_of_its_own():
    """#mediaFilterBarOverview is gone, and with it renderMediaFilter-
    Pills' 'overview' mode — the branch existed only to feed it."""
    overview = _code(_JS / "mediathek" / "_overview.js")
    filters = _code(_JS / "mediathek" / "filters.js")
    assert "mediaFilterBarOverview" not in overview
    assert "mediaFilterBarOverview" not in filters
    assert "'overview'" not in filters


def test_the_drilldown_hides_the_merged_feed_bar():
    """The toggle owns it: whichever grid is on screen, only its own
    filter row is. Behaviour covered by mediathek/_tests/
    view-toggle.test.js — this pins that the toggle is where it lives,
    rather than duplicated into each of the drilldown's four openers."""
    src = _read(_JS / "mediathek" / "_view-toggle.js")
    assert "libraryFilterBar" in src
    assert "mediaDrilldown" in src


# ── „aktualisiere die angezeigte zahl … basierend auf der aktuellen
#     filterung!!" ───────────────────────────────────────────────────────


def test_a_chosen_species_rewrites_every_class_count():
    """Picking „Elster" makes effectiveMediaLabels send [Elster] and
    nothing else, so every other class can only return nothing — while
    the row above still printed „Person 151" from the whole archive.
    The counts have to come down to what the active filter can actually
    reach, and _aggregateMediaCounts is the one place they are made."""
    src = _read(_JS / "mediathek" / "filters.js")
    fn = src[src.index("export function _aggregateMediaCounts") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "state.mediaSpecies" in fn
    assert "speciesClipCount" in fn


def test_a_filter_that_can_only_return_nothing_is_not_drawn():
    """Zero-count pills used to render greyed and non-tappable so the
    whole taxonomy stayed visible; on a 393 px phone each one cost a line
    of the grid it was filtering („Diese filter masse ist zu viel!").
    The rule is shared with the merged feed's chips, not written twice."""
    src = _code(_JS / "mediathek" / "filters.js")
    assert "media-pill--empty" not in src
    assert "chipVisible" in src
    # And the CSS for the state went with it.
    assert "media-pill--empty" not in _code(_CSS / "18-telegram-2.css")


# ── touch target: the new "← Übersicht" control reuses an audited class ──


def test_media_drill_back_meets_the_44px_touch_target_floor():
    css = _read(_CSS / "04-coral-1.css")
    rule = css[css.index(".media-drill-back {") :]
    rule = rule[: rule.index("}")]
    assert "min-height: 44px" in rule
