"""Camera-overview quick-jump tiles — "Tiere" / "Menschen".

The operator asked for two shortcuts next to the per-camera overview
tiles that jump straight into the merged library grid (library/page.js)
filtered to every animal species at once, or to person sightings, across
ALL cameras and every item kind — a question the per-camera drilldown
cannot answer at all (it has no concept of grouping several object
labels into one tap), which is why these target the merged grid and not
mediathek/_drilldown.js's openAllMediaDrilldown.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_JS = _REPO / "app" / "web" / "static" / "js"

_OVERVIEW = _JS / "mediathek" / "_overview.js"
_PAGE = _JS / "library" / "page.js"


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _slice_array(src: str, name: str) -> str:
    """Extract a top-level `const NAME = [ ... ];` array literal's body,
    matched by bracket depth — good enough for this file's own arrays,
    which carry no unbalanced brackets inside string literals."""
    m = re.search(rf"const\s+{re.escape(name)}\s*=\s*\[", src)
    assert m, f"{name} not found"
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "[":
            depth += 1
        elif src[i] == "]":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"unbalanced brackets in {name}")


def test_the_animals_tile_covers_every_wildlife_species_not_just_the_common_ones():
    """core/icons.js::OBJ_LABEL is the full species vocabulary (cat, bird,
    dog, squirrel, fox, hedgehog, marten, deer) — mediathek/filters.js's
    own MEDIA_FILTER_LABELS is a SHORTER, older list that still omits
    fox/hedgehog/marten/deer, so this deliberately does not reuse it."""
    tiles = _slice_array(_read(_OVERVIEW), "_QUICK_LABEL_TILES")
    for species in ("cat", "bird", "dog", "squirrel", "fox", "hedgehog", "marten", "deer"):
        assert f"'{species}'" in tiles, f"Tiere tile is missing {species}"
    # person belongs to the OTHER tile, not folded into "Tiere".
    animals_block = tiles[: tiles.index("__people__")]
    assert "'person'" not in animals_block


def test_the_people_tile_is_exactly_person_not_a_wider_net():
    tiles = _slice_array(_read(_OVERVIEW), "_QUICK_LABEL_TILES")
    people_block = tiles[tiles.index("__people__") :]
    assert "'person'" in people_block
    assert "'car'" not in people_block


def test_quick_tiles_jump_to_the_merged_grid_not_the_drilldown():
    src = _read(_OVERVIEW)
    assert "window.setLibraryLabelFilter" in src
    assert (
        "openAllMediaDrilldown"
        not in src.split("_bindQuickLabelTiles")[1].split("function _fmtMb")[0]
    ), "the quick tiles must not reuse the per-camera drilldown opener"


def test_set_library_label_filter_is_exported_and_bridged():
    src = _read(_PAGE)
    assert "export function setLibraryLabelFilter" in src
    assert "window.setLibraryLabelFilter = setLibraryLabelFilter" in src


def test_set_library_label_filter_replaces_rather_than_merges_the_filter():
    """A predictable, single-purpose jump — leftover camera/category
    chips from an earlier visit must not silently narrow the "Tiere"/
    "Menschen" view the operator just asked for."""
    src = _read(_PAGE)
    fn = src[src.index("export function setLibraryLabelFilter") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "_filter.cameraIds.clear()" in fn
    assert "_filter.categories.clear()" in fn
    assert "_filter.labels = new Set(" in fn


def test_set_library_label_filter_scrolls_the_now_filtered_grid_into_view():
    """The merged grid renders BELOW the camera overview these tiles live
    in (see the Stage-6 reorder) — without a scroll, tapping a tile would
    silently change something off-screen below the fold."""
    src = _read(_PAGE)
    fn = src[src.index("export function setLibraryLabelFilter") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "scrollIntoView" in fn


# ── "Wetterereignisse" — the third tile, a `kinds` filter not `labels` ──


def test_the_weather_tile_maps_to_kinds_not_labels():
    """A weather sighting/recap/episode/manual-event carries no object
    label at all — filtering it by `labels` would always match zero, so
    this tile has to be the one exception that names `kinds` instead."""
    tiles = _slice_array(_read(_OVERVIEW), "_QUICK_LABEL_TILES")
    weather_block = tiles[tiles.index("__weather__") :]
    for kind in ("sighting", "recap", "episode", "manual"):
        assert f"'{kind}'" in weather_block, f"Wetterereignisse tile is missing kind {kind}"
    assert "kinds:" in weather_block
    # Never confused with the object-label vocabulary the other two
    # tiles use — a weather record carries no `labels` filter value.
    assert "labels:" not in weather_block


def test_the_weather_tile_is_wired_to_set_library_kind_filter():
    src = _read(_OVERVIEW)
    assert "window.setLibraryKindFilter" in src
    assert "data-quick-kinds" in src


def test_set_library_kind_filter_is_exported_and_bridged():
    src = _read(_PAGE)
    assert "export function setLibraryKindFilter" in src
    assert "window.setLibraryKindFilter = setLibraryKindFilter" in src


def test_set_library_kind_filter_replaces_rather_than_merges_the_filter():
    """Same replace-not-merge contract as the label tiles: leftover
    camera/label/category chips from an earlier visit must not silently
    narrow the "Wetterereignisse" view the operator just asked for."""
    src = _read(_PAGE)
    fn = src[src.index("export function setLibraryKindFilter") :]
    fn = fn[: fn.index("\n}") + 2]
    assert "_filter.cameraIds.clear()" in fn
    assert "_filter.categories.clear()" in fn
    assert "_filter.labels.clear()" in fn


def test_default_boot_never_sends_a_kinds_param():
    """`kinds` is set ONLY inside `setLibraryKindFilter` — `_loadPage`
    guards the param behind the `_kinds` state variable, which starts
    `null` and nothing on the default boot path (`initLibraryPage` →
    `_loadPage`) ever touches. Anyone who never taps the
    "Wetterereignisse" tile keeps "Alles gemischt" as the default —
    that is the whole point of `kinds` being a NEW, opt-in param rather
    than something `libraryQueryParams` composes for every caller."""
    src = _read(_PAGE)
    assert "let _kinds = null;" in src
    # Only one call site ever puts `kinds` on the wire, and it is
    # guarded by the state variable, not unconditional.
    assert src.count("params.set('kinds'") == 1
    guarded = src[src.index("if (_kinds)") : src.index("if (_kinds)") + 80]
    assert "params.set('kinds'" in guarded
