"""Stage 6 — Mediathek + Wetter-Ereignisse become one section.

The operator asked for the two separate libraries ("Mediathek" /
`#media`, "Wetter" / `#weather`) to become one browsable place, default
view "Alles gemischt". Stages 3-5 built the backend read model
(`GET /api/library`) and the unified card renderer
(`app/web/static/js/library/`); this stage wires those building blocks
into the real page and retires the second section.

What's pinned here:
  * exactly one nav entry / dock slot for the merged section, not two
  * the scrollspy id lists (desktop sidebar + mobile dock) dropped
    'weather'
  * the merged grid's own DEFAULT query-param builder never sends a
    `kinds` filter — "Alles gemischt" is the server's own default and
    stays the grid's view for everyone who never taps the
    "Wetterereignisse" quick tile. That tile (added later, mediathek/
    _overview.js) is the one deliberate, opt-in exception — see
    library/page.js::setLibraryKindFilter and
    test_media_overview_quick_tiles.py for that path
  * every maintenance action from BOTH old sections still renders
    somewhere in the merged section
  * an episode card in the merged grid still deep-links out to
    #/gewitter/<id> exactly the way weather/_feed.js::openStormEpisode
    already did
  * partials/weather.html is gone; nothing else still points at it
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_TPL = _REPO / "app" / "web" / "templates"
_JS = _REPO / "app" / "web" / "static" / "js"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


# ── one section, one nav entry, one dock slot ──────────────────────────


def test_weather_html_is_gone():
    assert not (_TPL / "partials" / "weather.html").exists()


def test_index_no_longer_includes_the_retired_partial():
    index = _read(_TPL / "index.html")
    assert "partials/weather.html" not in index
    assert "partials/mediathek.html" in index


def test_sidenav_has_exactly_one_entry_for_the_merged_section():
    nav = _read(_TPL / "partials" / "sidenav.html")
    assert nav.count('data-target="media"') == 1
    assert 'data-target="weather"' not in nav
    assert 'href="#weather"' not in nav


def test_mobile_dock_has_a_mediathek_slot_not_a_weather_one():
    dock = _read(_TPL / "partials" / "mobile_dock.html")
    assert dock.count('data-target="media"') == 1
    assert 'data-target="weather"' not in dock
    # Five slots total — a sixth breaks repeat(5, 1fr) at 375 px (see
    # test_storms_archive.py::test_mobile_dock_has_no_dedicated_storms_slot).
    assert dock.count("m-dock-btn") == 5


def test_media_section_has_its_own_dock_slot_not_the_statistik_fallback():
    """`data-dock-section` rides a section along with an unrelated dock
    tab when the section has no button of its own (see
    chrome/mobile-dock.js's own header comment). #media used to ride
    Statistik that way — now it has a real Mediathek button, so the
    override must be gone or the new button would never highlight."""
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    assert 'id="media"' in mediathek
    assert "data-dock-section" not in mediathek


# ── scrollspy id lists ──────────────────────────────────────────────────


def test_desktop_scrollspy_dropped_weather():
    src = _read(_JS / "chrome" / "sidebar.js")
    ids = src[src.index("const sectionIds") :]
    ids = ids[: ids.index("]")]
    assert "'media'" in ids
    assert "'weather'" not in ids


def test_mobile_dock_scrollspy_dropped_weather():
    src = _read(_JS / "chrome" / "mobile-dock.js")
    ids = src[src.index("const sectionIds") :]
    ids = ids[: ids.index("]")]
    assert "'media'" in ids
    assert "'weather'" not in ids


# ── the merged grid: /api/library query-param mapping ──────────────────


def test_the_merged_grid_never_sends_a_kinds_filter_by_default():
    """ "Alles gemischt" (no `kinds` filter) is the explicit default —
    `_filter-state.js`'s own param builder (every camera/label/category
    chip, plus the Wetterdaten-chart zoom) must never construct one.

    `page.js` DOES know the param now (the "Wetterereignisse" quick
    tile's `setLibraryKindFilter`, added after this stage) — but only
    behind the opt-in `_kinds` state variable that tile is the sole
    setter of, never unconditionally and never on the default boot path
    (`initLibraryPage` → `_loadPage`). See
    test_media_overview_quick_tiles.py for that path's own tests."""
    filter_state_src = _read(_JS / "library" / "_filter-state.js")
    assert '"kinds"' not in filter_state_src
    assert "'kinds'" not in filter_state_src
    page_src = _read(_JS / "library" / "page.js")
    assert page_src.count("params.set('kinds'") == 1
    assert "if (_kinds) params.set('kinds'" in page_src


def test_camera_chips_map_onto_camera_ids():
    src = _read(_JS / "library" / "_filter-state.js")
    assert "'camera_ids'" in src
    assert "filter.cameraIds" in src


def test_object_class_chips_map_onto_labels():
    src = _read(_JS / "library" / "_filter-state.js")
    assert "'labels'" in src
    assert "filter.labels" in src


def test_weather_category_chips_map_onto_categories():
    src = _read(_JS / "library" / "_filter-state.js")
    assert "'categories'" in src
    assert "filter.categories" in src


def test_filter_bar_wires_all_three_chip_groups_to_the_shared_state():
    """The DOM half (_filter-bar.js) must actually mutate the same three
    sets _filter-state.js maps — a chip that toggles a set nothing reads
    would be a dead click."""
    src = _read(_JS / "library" / "_filter-bar.js")
    assert "filter.cameraIds" in src
    assert "filter.labels" in src
    assert "filter.categories" in src


# ── maintenance actions from both old sections stay reachable ──────────


def test_every_mediathek_maintenance_action_is_still_rendered():
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    for btn_id in (
        "fixThumbsBtn",
        "rescanMediaBtn",
        "reindexTrackingBtn",
        "mediaIntegrityBtn",
        "mediathekTrashBtn",
    ):
        assert f'id="{btn_id}"' in mediathek, f"{btn_id} missing from the merged section"


def test_every_weather_maintenance_action_is_still_rendered():
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    for btn_id in ("weatherRescanBtn", "weatherThumbRegenBtn"):
        assert f'id="{btn_id}"' in mediathek, f"{btn_id} missing from the merged section"
    assert 'data-action="openRetentionPanel"' in mediathek


def test_both_verwaltung_panels_are_present_not_collapsed_into_one():
    """The task asked for ONE retention element (already done, Stage 8),
    not one maintenance panel — Mediathek-Verwaltung and Wetter-Wartung
    stay two separate accordions since their Sonderaktionen don't
    collide."""
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    assert 'panel_id=\'set-media-maint\'' in mediathek.replace('"', "'")
    assert 'panel_id=\'set-weather-maint\'' in mediathek.replace('"', "'")


def test_the_camera_drilldown_and_its_bulk_tooling_still_render():
    """The per-camera deep tool (bulk-select, QA pill, processing poll)
    stays reachable — it isn't replaced by the merged grid, since
    /api/library's reduced item shape can't drive any of it (see
    library/_timelapse-card.js's own header)."""
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    for needle in (
        'id="mediaOverview"',
        'id="mediaDrilldown"',
        'id="mediaSelectBar"',
        'data-action="bulkDeleteSelectedMedia"',
        'id="mediaStorageBar"',
    ):
        assert needle in mediathek, f"{needle} missing from the merged section"


def test_the_weather_stats_chart_still_renders_unchanged():
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    for needle in (
        'id="weatherStatsBlock"',
        'id="weatherStatsChartWrap"',
        'id="weatherZoomActions"',
        'id="weatherZoomSavePanel"',
        'id="weatherStatsLegend"',
    ):
        assert needle in mediathek, f"{needle} missing from the merged section"


# ── the merged grid's own mount points ──────────────────────────────────


def test_the_merged_grid_has_its_own_host_ids():
    mediathek = _read(_TPL / "partials" / "mediathek.html")
    assert 'id="libraryFilterBar"' in mediathek
    assert 'id="libraryGrid"' in mediathek
    # Stage 11: page-numbered pagination (library/_pagination.js) replaced
    # the old "Mehr laden" accumulate control at this same mount point.
    assert 'id="libraryPagination"' in mediathek


def test_library_page_is_wired_into_boot():
    main_src = _read(_JS / "main.js")
    assert "library/page.js" in main_src
    live_update_src = _read(_JS / "live-update.js")
    assert "window.initLibraryPage" in live_update_src


# ── episode deep-link into the Gewitter-Archiv survives the move ───────


def test_the_merged_grid_binds_episode_cards_to_openStormEpisode():
    bind_src = _read(_JS / "library" / "_bind.js")
    assert "openStormEpisode" in bind_src
    assert "data-ep-id" in bind_src
    assert "from '../weather/_feed.js'" in bind_src


def test_open_storm_episode_itself_is_unchanged():
    """weather/_feed.js::openStormEpisode is reused as-is by the merged
    grid — it must still navigate to storms/index.js's own hash route."""
    feed_src = _read(_JS / "weather" / "_feed.js")
    assert "export function openStormEpisode" in feed_src
    assert "#/gewitter/" in feed_src


def test_the_merged_grid_installs_window_open_media_item_itself():
    """Regression: a motion card's onclick (mediathek/_cards.js::
    mediaCardHTML, reused unchanged by this grid) calls
    `window._openMediaItem` inline. Before this fix its ONLY definition
    lived inside mediathek/_paging.js::renderMediaGrid — reassigned every
    time the PER-CAMERA DRILLDOWN painted, never when this grid did. A
    motion card here could render and be tapped before the operator ever
    opened a single camera's drilldown, and the inline onclick called a
    function that plain did not exist yet — silently, since a broken
    inline onclick has nowhere to report to. "Today's bird clip does
    nothing when tapped" was exactly that.

    _bind.js must now install its OWN `window._openMediaItem` too,
    reassigned on every render of THIS grid same as the drilldown does
    for its own — whichever grid painted most recently is the one whose
    click behaviour is live, which is the correct invariant, not an
    accidental one."""
    bind_src = _read(_JS / "library" / "_bind.js")
    assert "window._openMediaItem" in bind_src, (
        "the merged grid's motion cards must install their own opener, "
        "not rely on the drilldown having rendered first"
    )
    assert "resolveMotionItem" in bind_src
    assert "from './_motion-open.js'" in bind_src


def test_resolve_motion_item_is_a_leaf_module_reusable_without_the_lightbox():
    """resolveMotionItem is split into its own file specifically so the
    resolution ORDER (this page's items, then the cross-grid registry)
    is unit-testable without lightbox.js's whole import tree — verified
    directly (not just asserted) in library/_tests/bind.test.js."""
    src = _read(_JS / "library" / "_motion-open.js")
    assert "export function resolveMotionItem" in src
    assert "from '" not in src, "must stay a leaf module — no lightbox.js weight"


# ── router.js's Telegram deep links still land on the merged section ───


def test_router_scrolls_sighting_and_recap_deep_links_to_media_not_weather():
    router_src = _read(_JS / "router.js")
    assert "querySelector('#weather')" not in router_src
    assert router_src.count("querySelector('#media')") >= 2
