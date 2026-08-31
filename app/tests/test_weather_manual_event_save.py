"""weather/_manual-event-save.js — the drag-zoom save form.

Two concerns, both run against the real module under node because
getting either wrong mis-files a save the operator never reviewed:

* the default-category guess. The operator explicitly asked for their
  OWN input here, not automatic pattern recognition (see the German
  refinement this feature was built from) — the heuristic only picks a
  starting point among the four fields with an unambiguous 1:1 category
  mapping (precipitation, snowfall, lightning_potential, visibility).
* the multi-select chips + the payload they collect. The chips used to
  be mutually exclusive; an event is genuinely more than one thing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_JS_DIR = Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js"

_SAMPLE = """
function sample(vals) {{
  return {{ ts: '2026-08-29T12:00:00', values: {{
    precipitation: null, snowfall: null, lightning_potential: null,
    visibility: null, wind_gusts_10m: null, cloud_cover: null,
    sun_altitude: null, ...vals }} }};
}}
{body}
"""


def test_a_precipitation_swing_defaults_to_heavy_rain():
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [sample({ precipitation: 0 }), sample({ precipitation: 12 })];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] == "heavy_rain"


def test_a_lightning_swing_defaults_to_thunder():
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [
          sample({ lightning_potential: 0, precipitation: 0.5 }),
          sample({ lightning_potential: 1.2, precipitation: 0.6 }),
        ];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] == "thunder"


def test_the_biggest_relative_swing_wins_not_the_biggest_absolute_number():
    """visibility swings from 8000 to 3000 (5000 m, exactly its own
    reference span — a full swing); precipitation swings 0→1 mm/h (a
    fifth of its 5 mm/h span) — visibility must win despite the smaller
    raw sample values."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [
          sample({ visibility: 8000, precipitation: 0 }),
          sample({ visibility: 3000, precipitation: 1 }),
        ];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] == "fog"


def test_only_unmapped_fields_moving_yields_no_default():
    """wind_gusts_10m and cloud_cover have no 1:1 category — the operator
    must pick one themselves rather than get a guess that isn't real."""
    out = _js(
        _SAMPLE.format(
            body="""
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const samples = [
          sample({ wind_gusts_10m: 10, cloud_cover: 20 }),
          sample({ wind_gusts_10m: 60, cloud_cover: 90 }),
        ];
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory(samples) }));
        """
        )
    )
    assert out["category"] is None


def test_an_empty_range_yields_no_default():
    out = _js(
        """
        const mod = await import(JS + '/weather/_manual-event-save.js');
        console.log(JSON.stringify({ category: mod._deriveDefaultCategory([]) }));
        """
    )
    assert out["category"] is None


# ── multi-select category chips ─────────────────────────────────────────
# The operator asked to tick more than one ("Vielleicht zwei oder so") —
# a thunderstorm that also brings heavy rain is genuinely both. The chips
# stopped being mutually exclusive; the selected state must be carried by
# aria-pressed, not colour alone (CLAUDE.md's iOS/a11y checklist).


def test_chips_carry_aria_pressed_for_every_selection():
    out = _js(
        """
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const html = mod._categoryChipsHTML(new Set(['thunder', 'heavy_rain']));
        console.log(JSON.stringify({
          pressed: (html.match(/aria-pressed="true"/g) || []).length,
          unpressed: (html.match(/aria-pressed="false"/g) || []).length,
          active: (html.match(/ws-zsave-cat is-active/g) || []).length,
        }));
        """
    )
    assert out["pressed"] == 2
    assert out["active"] == 2
    # Every remaining chip is explicitly unpressed — no chip without state.
    assert out["unpressed"] == 7


def test_no_selection_leaves_every_chip_unpressed():
    out = _js(
        """
        const mod = await import(JS + '/weather/_manual-event-save.js');
        const html = mod._categoryChipsHTML(new Set());
        console.log(JSON.stringify({
          pressed: (html.match(/aria-pressed="true"/g) || []).length,
          active: (html.match(/is-active/g) || []).length,
        }));
        """
    )
    assert out["pressed"] == 0
    assert out["active"] == 0


# _collectPayload walks the panel DOM (CLAUDE.md's collector rule), so a
# hand-rolled stub answering the two selectors it uses is enough — no
# jsdom, same trick as the rest of this harness.
_PANEL_STUB = """
function panel(cats, curves) {
  return {
    querySelector: (s) =>
      s === '#wsZsaveName' ? { value: 'Gewitter' } : { value: 'Blitze und Regen' },
    querySelectorAll: (s) =>
      s === '.ws-zsave-cat.is-active'
        ? cats.map((c) => ({ dataset: { category: c } }))
        : (curves || ['precipitation']).map((v) => ({ value: v })),
  };
}
const RANGE = { start: '2026-08-29T14:00:00', end: '2026-08-29T18:00:00' };
const mod = await import(JS + '/weather/_manual-event-save.js');
"""


def _collect(cats_js: str):
    return _js(
        _PANEL_STUB
        + "console.log(JSON.stringify(mod._collectPayload(panel({}), RANGE)));".format(cats_js)
    )


def test_the_payload_carries_every_ticked_category():
    out = _collect("['thunder', 'heavy_rain']")
    assert out["payload"]["categories"] == ["thunder", "heavy_rain"]
    assert "category" not in out["payload"]
    assert out["payload"]["curves"] == ["precipitation"]


def test_a_single_ticked_category_still_produces_a_one_element_list():
    out = _collect("['snow']")
    assert out["payload"]["categories"] == ["snow"]


def test_saving_without_a_category_is_still_refused():
    out = _collect("[]")
    assert "Kategorie" in out["error"]
    assert "payload" not in out


# ── the save flow: panel closes, the new card lands in the list ─────────
# "wenn ich speicher, dann sollte es in dem Editscreen weggehen und eben
# runter in die History direkt kommen. Aktuell bleibt der Editscreen
# einfach komplett offen und es kommt diese komische Speichermeldung
# unten." Driven end-to-end with a stubbed fetch: the whole point is that
# every step after the POST actually happens.

_FLOW_STUB = """
const posted = [];
globalThis.fetch = (url, init) => {
  const method = (init && init.method) || 'GET';
  posted.push({ url, method, body: init && init.body });
  const item = { id: 'manual_new', name: 'Gewitter', categories: ['thunder', 'heavy_rain'],
                 range_start: '2026-08-29T14:00:00', range_end: '2026-08-29T18:00:00',
                 curves: ['precipitation'] };
  const json = method === 'POST' ? { ok: true, item } : { items: [item] };
  return Promise.resolve({
    ok: OK, status: OK ? 201 : 500, statusText: 'x',
    headers: { get: () => 'application/json' },
    text: () => Promise.resolve('kaputt'),
    json: () => Promise.resolve(json),
  });
};
const card = { dataset: { manualId: 'manual_new' }, added: [], scrolled: false,
               classList: { add(c) { card.added.push(c); } },
               scrollIntoView() { card.scrolled = true; } };
const grid = { querySelectorAll: () => [card] };
const origById = globalThis.document.getElementById;
globalThis.document.getElementById = (id) =>
  id === 'libraryGrid' ? grid : origById(id);
let rendered = 0;
globalThis.window.reloadLibraryPage = () => { rendered += 1; return Promise.resolve(); };
const panel = {
  hidden: false,
  querySelector: (s) =>
    s === '#wsZsaveName' ? { value: 'Gewitter mit Starkregen' } : { value: 'Blitze und Regen' },
  querySelectorAll: (s) =>
    s === '.ws-zsave-cat.is-active'
      ? [{ dataset: { category: 'thunder' } }, { dataset: { category: 'heavy_rain' } }]
      : [{ value: 'precipitation' }],
};
const mod = await import(JS + '/weather/_manual-event-save.js');
await mod._submitSave(panel, { start: '2026-08-29T14:00:00', end: '2026-08-29T18:00:00' });
console.log(JSON.stringify({
  posted, hidden: panel.hidden, rendered,
  added: card.added, scrolled: card.scrolled,
}));
"""


def _run_flow(ok: str):
    return _js(_FLOW_STUB.replace("OK", ok))


def test_a_successful_save_closes_the_panel_and_reloads_the_list():
    out = _run_flow("true")
    assert out["hidden"] is True, "the edit panel must not stay open after a save"
    # POST, then the manual-event list re-fetch that feeds the grid.
    assert [p["method"] for p in out["posted"]] == ["POST", "GET"]
    assert '"categories":["thunder","heavy_rain"]' in out["posted"][0]["body"]
    # The merged library grid (library/page.js) owns the card now — one
    # reload via window.reloadLibraryPage, awaited before the reveal.
    assert out["rendered"] == 1


def test_the_saved_card_is_highlighted_where_it_landed():
    out = _run_flow("true")
    assert out["added"] == ["ws-manual-card--new"]
    assert out["scrolled"] is True


def test_a_failed_save_leaves_the_panel_open_and_does_not_pretend_it_worked():
    out = _run_flow("false")
    assert out["hidden"] is False
    assert out["rendered"] == 0
    assert out["added"] == []


def test_only_the_error_toast_survives_in_the_save_module():
    """The operator asked for the success toast ("diese komische
    Speichermeldung unten") to go; the failure toast must stay, or a save
    that fails looks exactly like a save that worked."""
    src = (_JS_DIR / "weather" / "_manual-event-save.js").read_text(encoding="utf-8")
    assert "'success'" not in src
    assert "Speichern fehlgeschlagen" in src
    assert "'error'" in src
