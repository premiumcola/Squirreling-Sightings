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

import json
from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_REPO = Path(__file__).resolve().parents[2]
_TPL = _REPO / "app" / "web" / "templates"
_JS = _REPO / "app" / "web" / "static" / "js"
_CSS = _REPO / "app" / "web" / "static" / "css"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


_BLOCK_COMMENTS = {".css": ("/*", "*/"), ".html": ("{#", "#}")}


def _strip_blocks(src: str, open_tag: str, close_tag: str) -> str:
    out, rest = [], src
    while open_tag in rest:
        head, _, rest = rest.partition(open_tag)
        out.append(head)
        _, _, rest = rest.partition(close_tag)
    out.append(rest)
    return "".join(out)


def _code(path: Path) -> str:
    """The file without its comments.

    „X kommt nicht mehr vor" ist sonst keine Aussage über den Code: in
    diesem Projekt erklärt jede Entfernung sich selbst an Ort und Stelle,
    und der Kommentar, der sagt WARUM etwas weg ist, nennt es beim Namen.
    Ein Test, der über diesen Kommentar stolpert, verbietet die
    Erklärung — also liest er den Code ohne sie: `//` in JS, `/* … */` in
    CSS, `{# … #}` in den Jinja-Vorlagen.
    """
    src = _read(path)
    tags = _BLOCK_COMMENTS.get(path.suffix)
    if tags:
        return _strip_blocks(src, *tags)
    return "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("//"))


_MEDIATHEK = _TPL / "partials" / "mediathek.html"


def _rule(css: str, selector: str) -> str:
    """The declarations of `selector`'s FIRST rule block.

    `selector + " {"` rather than a bare `index`, so `#mediaFilterBar`
    does not match `#mediaFilterBar .media-nest` — every selector this
    file pins is a prefix of a longer one somewhere below it.
    """
    head = f"{selector} {{"
    assert head in css, f"missing rule: {selector}"
    body = css[css.index(head) + len(head) :]
    return body[: body.index("}")]


def _section_head(markup: str) -> str:
    """The title row alone — the title and whatever else has talked its
    way in there.

    Ends at the filter zone, the first thing after the head. It used to
    end at `id="libraryFilterBar"`, and that stopped being the same place
    the moment the back arrow moved down and took the bar into a wrapper
    with it: the slice then swallowed the very element it is used to
    prove has LEFT the head."""
    return markup[
        markup.index('<div class="section-head">') : markup.index('class="media-filter-zone"')
    ]


# ── "Alle Ereignisse" is gone, completely ────────────────────────────────


def test_alle_ereignisse_heading_is_gone_from_the_template():
    assert "Alle Ereignisse" not in _read(_MEDIATHEK)


def test_the_section_carries_exactly_one_heading():
    """No `.lib-subsection-head` at all any more.

    There were two: one framing #libraryBlock as its own always-visible
    section (dropped first), and „Kamera-Ansicht & Auswahl", which sat
    one line under #media's own H3 — with the same camera glyph — and
    named a section the content already announced: „doppel titel raus!".
    It had separated the filter bar from the camera tiles; the bar is not
    even on screen during a drilldown any more (mediathek/
    _view-toggle.js), so it separated nothing."""
    mediathek = _code(_MEDIATHEK)
    assert "lib-subsection-head" not in mediathek
    assert "Kamera-Ansicht" not in mediathek
    # And the rule went with the markup rather than lingering unused.
    assert "lib-subsection-head" not in _code(_CSS / "26-library-merge.css")


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


def test_one_back_control_serves_all_three_states():
    """Each state used to open with its own full-width bar — „← Alle
    Kameras", „← Übersicht", „← Übersicht" — three controls for one idea,
    each eating a row of a phone screen to restate what the arrow already
    says. There is one arrow now, and the toggle points it at whichever
    exit belongs to the state on screen."""
    mediathek = _code(_MEDIATHEK)
    assert mediathek.count("media-drill-back") == 0
    assert mediathek.count('id="mediaBackBtn"') == 1
    assert "← Alle Kameras" not in mediathek
    assert "← Übersicht" not in mediathek
    # NOT in the title row — „Nehm den zurück button vll runter weg vor
    # dem titel!". It heads the filter zone instead, level with the left
    # edge of the chips, and the title keeps its own line.
    assert 'id="mediaBackBtn"' not in _section_head(mediathek)
    zone = mediathek[mediathek.index('class="media-filter-zone"') :]
    zone = zone[: zone.index('id="mediaStorageBar"')]
    assert 'id="mediaBackBtn"' in zone
    assert zone.index('id="mediaBackBtn"') < zone.index(
        'id="libraryFilterBar"'
    ), "the arrow comes first — it is where the eye looks for where this view begins"
    # And still outside every one of the four state containers, so one
    # button serves all of them.
    assert mediathek.index('id="mediaBackBtn"') < mediathek.index('id="mediaOverview"')

    toggle = _read(_JS / "mediathek" / "_view-toggle.js")
    for action in ("closeMediaDrilldown", "closeMediaSpeciesGrid", "resetLibraryView"):
        assert action in toggle, f"{action} must be reachable from the one arrow"


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


def test_the_back_arrow_meets_the_44px_touch_target_floor():
    """36 px of paint, 44 px of target — the transparent-::after trick,
    so a small glyph in a title row stays hittable without making the row
    taller. `inset: -4px` is 36 + 2×4 = 44."""
    css = _read(_CSS / "04-coral-1.css")
    rule = css[css.index(".media-back-btn {") :]
    rule = rule[: rule.index("}")]
    assert "width: 36px" in rule and "height: 36px" in rule
    after = css[css.index(".media-back-btn::after {") :]
    after = after[: after.index("}")]
    assert "inset: -4px" in after


# ── „Abstände filter bitte gleich" ───────────────────────────────────────


def test_every_junction_in_the_mediathek_stack_uses_the_one_gap():
    """Title → class pills → grid. Three things, two junctions, ONE
    number — a stack where each seam carries its own hand-tuned margin is
    exactly what reads as uneven on a phone.

    It was four things: the species pills were a row of their own between
    the class pills and the grid, and `.media-species-bar` carried the
    same variable for that seam. They are inside the „Vogel" pill now
    (mediathek/_species-filter.js::speciesNestHtml), so the seam is gone
    and with it the entry in this list."""
    coral = _code(_CSS / "04-coral-1.css")
    settings = _code(_CSS / "08-settings.css")
    assert "--media-stack-gap: 10px;" in coral
    for block, css in (
        ("#media > .section-head {", coral),
        (".media-drill-head {", coral),
        (".media-storage-bar {", settings),
    ):
        rule = css[css.index(block) :]
        rule = rule[: rule.index("}")]
        assert "var(--media-stack-gap)" in rule, f"{block} must not carry its own number"
    # And the head that used to hold a back button beside the filter bar
    # is now a plain wrapper around the filter bar alone — no column
    # stack, no gap of its own to disagree with the one above.
    assert ".media-drill-head {" not in _code(_CSS / "25-mobile.css")


# ── „sortiere die elemente ein wenig - papierkorb oben kann weg" ─────────


def test_the_papierkorb_left_the_title_row():
    """The head was a title, a back arrow, an „Auswahl" button and a
    trash can — four controls in the row that names the section."""
    assert 'id="mediathekTrashBtn"' not in _section_head(_code(_MEDIATHEK))


def test_the_papierkorb_moved_rather_than_went():
    """It is the ONLY way into the bin — mediathek/trash-modal.js binds
    one delegated `[data-action="open-trash"]` and nothing else opens the
    modal — so „kann weg" can only mean „not here", never „nowhere". It
    sits in Mediathek-Verwaltung now, the panel that already owns the
    Papierkorb-Aufbewahrungsfrist, as the first of that panel's
    buttons."""
    mediathek = _code(_MEDIATHEK).replace('"', "'")
    assert "id='mediathekTrashBtn'" in mediathek
    assert "data-action='open-trash'" in mediathek
    assert (
        mediathek.index("panel_id='set-media-maint'")
        < mediathek.index("id='mediathekTrashBtn'")
        < mediathek.index("id='fixThumbsBtn'")
    )
    # The delegator keys on the attribute, not on where the button sits.
    assert "[data-action=\"open-trash\"]" in _read(_JS / "mediathek" / "trash-modal.js")


def test_the_header_only_rule_for_that_button_went_with_it():
    """It is an ordinary `.btn-action` in a row of them now, so the
    bespoke `.mediathek-trash-btn` (transparent 44 px glyph, tuned to sit
    beside a title) has nothing left to style."""
    assert "mediathek-trash-btn" not in _code(_CSS / "14-mediathek-1.css")
    assert "mediathek-trash-btn" not in _code(_MEDIATHEK)


# ── „die spezies … als unterelemente zu Vogel" ──────────────────────────


def test_the_species_row_is_gone_as_a_row():
    """Not gone as a filter — gone as a ROW. A second bar under the class
    bar gave a narrowing of ONE pill the same rank as the whole
    taxonomy."""
    mediathek = _code(_MEDIATHEK)
    assert 'id="mediaSpeciesFilterBar"' not in mediathek
    assert "media-species-bar" not in mediathek
    # …and nothing in the JS still paints a bar that isn't there.
    assert "mediaSpeciesFilterBar" not in _code(_JS / "mediathek" / "filters.js")


def test_the_species_chips_are_children_of_the_vogel_pill():
    src = _read(_JS / "mediathek" / "_species-filter.js")
    fn = src[src.index("export function speciesNestHtml") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "media-nest" in fn
    assert "speciesPillsHtml()" in fn
    # The head is passed IN, not rebuilt here: one pill, one builder, so
    # „Vogel" is the same button whether it stands alone or heads a
    # bubble (filters.js::_pillAttrs).
    assert "headHtml" in fn


def test_open_is_the_active_bird_filter_not_a_second_state():
    """Two states on one pill would mean two meanings for one tap. The
    bubble stands open exactly while „Vogel" is the active class filter —
    which is the same condition that used to decide whether the separate
    species row was painted at all."""
    src = _read(_JS / "mediathek" / "_species-filter.js")
    fn = src[src.index("export function speciesNestOpen") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "state.mediaLabels.has('bird')" in fn
    assert "hasSpeciesToNest()" in fn


def test_the_open_head_is_the_icon_alone():
    """„Vogel wird beim aufklappen nur noch das icon und hat die spezies
    drin!" — no word, no count chip; both stay in title/aria-label the way
    the camera chips keep their name on a phone."""
    src = _read(_JS / "mediathek" / "filters.js")
    fn = src[src.index("function _nestHeadHtml") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "mp-count" not in fn
    assert "aria-label=" in fn and "title=" in fn
    assert "aria-expanded=" in fn


def test_the_class_pill_wiring_cannot_grab_the_species_chips():
    """The chips wear `.media-pill` too, and carry no `data-val` — a
    selector that took every pill in the bar would toggle `undefined`
    into state.mediaLabels on every species tap (and on the read-only
    „alle Filter aus" hint, which is how the bug got in)."""
    src = _read(_JS / "mediathek" / "filters.js")
    fn = src[src.index("function _wireClassPillClicks") :]
    fn = fn[: fn.index("\n}") + 2]
    assert ".media-pill[data-val]" in fn
    fn = src[src.index("function _wireSpeciesPillClicks") :]
    fn = fn[: fn.index("\n}") + 2]
    assert ".media-pill[data-species]" in fn


def test_the_bubble_and_its_children_meet_the_44px_touch_floor():
    css = _read(_CSS / "14-mediathek-1.css")
    head = _rule(css, "#mediaFilterBar .media-pill--nest-head")
    assert "width: 44px" in head and "min-height: 44px" in head
    assert "content: none" in _rule(css, "#mediaFilterBar .media-pill--nest-head.active::before")
    assert "min-height: 44px" in _rule(css, "#mediaFilterBar .media-nest .media-pill")


# ── „schiebe die elemente nicht so unschön zusammen!" ────────────────────


def test_the_filter_row_wraps_instead_of_hiding_chips_in_a_side_scroller():
    """`.media-filter-bar` is a swipe strip on touch (25-mobile.css), and
    three of its parts have to be undone together or the row breaks:
    `overflow-x`, the `touch-action: pan-x` that would otherwise swallow
    the page's own vertical scroll under a wrapped row, and the
    right-edge mask that fades a row with no end to reach."""
    rule = _rule(_read(_CSS / "14-mediathek-1.css"), "#mediaFilterBar")
    assert "flex-wrap: wrap" in rule
    assert "overflow: visible" in rule
    assert "touch-action: manipulation" in rule
    assert "mask-image: none" in rule


def test_the_row_spends_the_space_it_has_on_a_desktop():
    """„schiebe die elemente nicht so unschön zusammen!" — wider gaps and
    one minimum width for every chip, so a 1600 px row reads as a band
    rather than a huddle at the left edge."""
    css = _read(_CSS / "14-mediathek-1.css")
    block = css[css.index("@media (min-width: 900px)") :]
    block = block[: block.index("\n}\n")]
    assert "#mediaFilterBar > .media-pill" in block
    assert "min-width: 132px" in block
    assert "gap: 14px" in block
    # …but NOT the „alle Filter aus" hint. It borrows .media-pill for the
    # shape and 18-telegram-2.css sizes it down on purpose („read-only,
    # never tappable"); an ID selector outranks that, so the one thing in
    # the row that must not invite a tap would end up sized most like a
    # button.
    assert "#mediaFilterBar > .media-pill:not(.media-pill--status)" in block


# ── the painted bar, rendered by the real module under node ─────────────
#
# Everything above reads source text. These three run
# mediathek/filters.js::renderMediaFilterPills for real (tests/_node_js.py)
# and look at what it puts into #mediaFilterBar, because „Vogel is a
# bubble now" is a claim about the painted row, not about a string in a
# file: a bird pill drawn twice, or drawn beside its own bubble, greps
# exactly the same as a correct one.

_STATS = [
    {
        "camera_id": "c1",
        "label_counts": {"bird": 330, "cat": 41, "motion": 12},
        "species_counts": {"Elster": 150, "Kohlmeise": 64},
    }
]


def _paint(labels, species=None):
    """#mediaFilterBar's innerHTML after one real render."""
    body = """
        const { renderMediaFilterPills } = await import(JS + '/mediathek/filters.js');
        const { state } = await import(JS + '/core/state.js');
        // The bar is the only DOM this render touches; querySelectorAll
        // answers [] because the click wiring is not what is under test.
        const bar = { innerHTML: '', querySelectorAll: () => [] };
        globalThis.document.getElementById = (id) => (id === 'mediaFilterBar' ? bar : null);
        state.mediaCamera = null;
        state.mediaPage = 0;
        state.mediaLabels = new Set(%s);
        state.mediaSpecies = %s;
        state.mediaStats = %s;
        renderMediaFilterPills();
        console.log(JSON.stringify({ html: bar.innerHTML }));
    """ % (json.dumps(labels), json.dumps(species), json.dumps(_STATS))
    return _js(body)["html"]


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_an_active_vogel_paints_a_bubble_instead_of_a_pill():
    html = _paint(["bird", "cat", "motion"])
    assert 'class="media-nest media-nest--species"' in html
    # ONCE. The bubble's head IS the Vogel pill — a second one beside it
    # would be the same filter offered twice.
    assert html.count('data-val="bird"') == 1
    head = html[html.index('data-val="bird"') :]
    head = head[: head.index("</button>")]
    assert "mp-count" not in head, "the open head is the icon alone"
    assert ">Vogel<" not in head
    assert 'title="Vogel (330)"' in head, "the word and the tally move into the title"
    # …and the species are inside the bubble, after that head.
    assert html.index('data-species="Elster"') > html.index("media-nest--species")


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_collapsed_it_is_the_ordinary_vogel_pill_again():
    html = _paint(["cat", "motion"])
    assert "media-nest" not in html
    assert 'data-val="bird"' in html
    assert ">Vogel<" in html
    assert ">330<" in html
    assert "data-species=" not in html, "no species chips without an open bubble"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_the_bubble_is_painted_last_whatever_the_count_sort_says():
    """„Vogel" is the busiest class on a bird feeder, so the count sort
    puts it first — and it takes a line of its own, which would cut the
    class row in two and strand the pills after it on a third line."""
    html = _paint(["bird", "cat", "motion"])
    assert html.index("media-nest--species") > html.index('data-val="cat"')
    assert html.index("media-nest--species") > html.index('data-val="motion"')
