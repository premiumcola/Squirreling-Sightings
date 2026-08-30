"""The Meldeschwellen live on the SAME net as the camera-wide settings.

„Die Meldeschwelle für die Personen muss ja ins Netz mit rein." — and
still only one net per camera, because the two-radar version was already
rejected once ("ich will nicht zwei Netze").

Two things break silently if this regresses, so both are pinned here:

* **the spoke count is per camera.** It comes from that camera's
  Klassen-Filter, so Werkstatt (person/cat/dog) draws 13 spokes and
  Squirrel Town (+bird/squirrel) draws 15. The label layout has to
  survive that — at 15 spokes the old radial placement put two 104 px
  boxes 74 px apart, which is why _tune_labels.js exists.
* **the per-camera isolation.** Two nets on screen, one pointer layer:
  a class axis dragged on camera B must not resolve against camera A.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

pytestmark = pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)

_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js"

_TUNING = """{
  frame_interval_ms: 500, motion_sensitivity: 0.5, post_motion_tail_s: 0,
  track_miss_grace_seconds: 0, track_iou_match_threshold: 0,
  roi_mode: 'off', wildlife_motion_sensitivity: 0, roi_min_net_disp_frac: 0,
}"""


def _axes(*labels):
    rows = ", ".join(
        "{{ label: '{}', E: 50, push: 0.8, push_enabled: true, provenance: 'werk' }}".format(lab)
        for lab in labels
    )
    return f"[{rows}]"


_SETUP = f"""
  const cards = await import(JS + '/netz/_cards.js');
  const S = await import(JS + '/netz/_state.js');
  const host = {{ innerHTML: '' }};
  S.netzState.view = 'netz';
  S.netzState.cameras = [
    {{ id: 'cam_a', name: 'Werkstatt' }},
    {{ id: 'cam_b', name: 'Squirrel Town' }},
  ];
  S.netzState.states = {{
    cam_a: {{ cam_id: 'cam_a', cam_name: 'Werkstatt', role: 'security', frozen: [],
             axes: {_axes('person', 'cat', 'dog')}, tuning: {_TUNING} }},
    cam_b: {{ cam_id: 'cam_b', cam_name: 'Squirrel Town', role: 'wildlife', frozen: [],
             axes: {_axes('person', 'cat', 'dog', 'bird', 'squirrel')}, tuning: {_TUNING} }},
  }};
"""


# ── one net, both concerns ────────────────────────────────────────────


def test_each_card_carries_its_own_class_axes_on_one_net():
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        const html = String(host.innerHTML);
        console.log(JSON.stringify({{
          a: (S.netzState.tuneAxes.cam_a || []).map((x) => x.key),
          b: (S.netzState.tuneAxes.cam_b || []).map((x) => x.key),
          nets: (html.match(/netz-tune-svg/g) || []).length,
        }}));
        """
    )
    # 10 camera-wide settings + the camera's own classes.
    assert len(out["a"]) == 13, out["a"]
    assert len(out["b"]) == 15, out["b"]
    assert out["a"][-3:] == ["cls:person", "cls:cat", "cls:dog"]
    assert "cls:squirrel" in out["b"] and "cls:squirrel" not in out["a"]
    assert out["nets"] == 2, "one net per camera — a second chart per card is the rejected layout"


def test_the_class_axes_are_appended_so_each_colour_group_stays_one_arc():
    """A group scattered around the circle cannot be read as a group —
    _settings_axes.js's TUNE_AXIS_ORDER comment, still in force."""
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        const groups = (S.netzState.tuneAxes.cam_b || []).map((x) => x.group);
        const runs = groups.filter((g, i) => g !== groups[i - 1]);
        console.log(JSON.stringify({{ runs, unique: [...new Set(groups)].length }}));
        """
    )
    assert len(out["runs"]) == out["unique"], f"a colour group is split across the circle: {out}"
    assert out["runs"][-1] == "meldung"


def test_the_meldung_group_reaches_the_legend():
    out = _js(
        """
        const radar = await import(JS + '/netz/_tune_radar.js');
        const html = radar.tuneGroupLegendHtml();
        console.log(JSON.stringify({ hasMeldung: html.includes('Meldung') }));
        """
    )
    assert out["hasMeldung"] is True


def test_a_class_drag_resolves_against_its_own_camera():
    """THE multi-camera invariant, for the new axes. `axisFor` is exactly
    the lookup `_tune_drag.js` performs on pointerdown."""
    out = _js(
        f"""
        {_SETUP}
        cards.renderCards(host);
        console.log(JSON.stringify({{
          bHasSquirrel: !!S.axisFor('cam_b', 'cls:squirrel'),
          aHasSquirrel: !!S.axisFor('cam_a', 'cls:squirrel'),
          aPerson: (S.axisFor('cam_a', 'cls:person') || {{}}).E,
        }}));
        """
    )
    assert out["bHasSquirrel"] is True
    assert out["aHasSquirrel"] is False, "camera A resolved an axis only camera B has"
    assert out["aPerson"] == 50


def test_a_class_axis_never_joins_the_staging_bar():
    """Class axes commit on release. If one were staged, „Übernehmen"
    would PATCH it through the camera-tuning route, which does not know
    the key and does not write the archive record."""
    out = _js(
        f"""
        {_SETUP}
        S.stageValue('cam_a', 'roi_mode', '2x2');
        cards.renderCards(host);
        console.log(JSON.stringify({{
          staged: Object.keys(S.stagedFor('cam_a')),
        }}));
        """
    )
    assert out["staged"] == ["roi_mode"]
    assert not any(k.startswith("cls:") for k in out["staged"])


# ── the label rail survives the extra spokes ──────────────────────────


_RAIL = """
  const L = await import(JS + '/netz/_tune_labels.js');
  const R = await import(JS + '/netz/_tune_radar.js');
  const geo = R.tuneGeometry();
  const mk = (n) => Array.from({ length: n }, (_, i) => ({
    axis: { key: 'k' + i, label: 'Wildtier-Empfindlichkeit', display: '50 %', color: '#fff' },
    ...R.tunePolar(i, n, 1, geo),
  }));
  const boxes = (n) => {
    const { rows, rowH } = L.placeLabels(mk(n), geo, R.TUNE_H);
    return rows.map((r) => ({ side: r.side, top: r.y - rowH / 2, bot: r.y + rowH / 2, x: r.x }));
  };
"""


@pytest.mark.parametrize("n", [10, 13, 15, 21])
def test_no_two_label_boxes_overlap_at_any_axis_count(n):
    """The whole reason _tune_labels.js exists. Boxes on the same rail are
    laid out top-down and must not intersect — at 15 spokes the old
    on-circle placement overlapped by ~30 px around the bottom."""
    out = _js(
        f"""
        {_RAIL}
        console.log(JSON.stringify(boxes({n})));
        """
    )
    for side in ("l", "r"):
        rail = sorted((b for b in out if b["side"] == side), key=lambda b: b["top"])
        for prev, cur in zip(rail, rail[1:]):
            assert cur["top"] >= prev["bot"] - 0.01, f"labels overlap on rail {side}: {prev} {cur}"


@pytest.mark.parametrize("n", [10, 15, 21])
def test_every_label_box_stays_inside_the_viewbox(n):
    """A label pushed off the bottom by the de-collision pass is a label
    the operator cannot read — and the viewBox height is fixed on purpose,
    because a taller one would shrink every glyph in a fixed-width card."""
    out = _js(
        f"""
        {_RAIL}
        const H = R.TUNE_H;
        console.log(JSON.stringify({{
          boxes: boxes({n}),
          h: H,
          w: R.TUNE_W,
          labelW: L.LABEL_W,
        }}));
        """
    )
    for b in out["boxes"]:
        assert b["top"] >= -0.01, b
        assert b["bot"] <= out["h"] + 0.01, b
        assert b["x"] >= 0, b
        assert b["x"] + out["labelW"] <= out["w"], b


def test_the_rail_sides_split_the_axes_evenly():
    """`i < n / 2` and not `x >= cx`: with an odd count the spoke pointing
    straight down sits exactly on the centre line, and a sign test would
    pile it onto the same rail as the one pointing straight up."""
    out = _js(
        f"""
        {_RAIL}
        const b = boxes(15);
        console.log(JSON.stringify({{
          r: b.filter((x) => x.side === 'r').length,
          l: b.filter((x) => x.side === 'l').length,
        }}));
        """
    )
    assert out == {"r": 8, "l": 7}
