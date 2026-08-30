"""The Erkennungsprofil has to load when it becomes visible.

Reported from the running system, on both desktop and phone:

    "die Erkennungsnetze werden zuerst nicht angezeigt, muss immer erst
     auf history drücken, wenn man zurückkommt, dann werden sie
     angezeigt … sagte, dass gar keine Kamera konfiguriert ist"

Cause: the IntersectionObserver that hydrates the panel called
`_routeFromHash()`, which returns early unless the address starts with
`#netz`. Scrolling the section into frame — the normal way to reach it —
therefore loaded nothing, and `renderCards` painted its own empty state,
"Keine Kamera konfiguriert.", which reads as a broken install rather
than as "not fetched yet".

Pressing the Verlauf button called `showTab` directly, bypassing the
hash check, which is why a detour through the history made the nets
appear.

`storms/index.js` was the model for this observer and does NOT have the
hole: its `_route()` ends in an unconditional `_showList(host)`. These
tests pin the fixed shape and the storms parity, because the failure is
invisible in code review — both call "a routing function" on visibility.
"""

from __future__ import annotations

import re
from pathlib import Path

_JS = Path(__file__).resolve().parents[1] / "web" / "static" / "js"
_NETZ = (_JS / "netz" / "index.js").read_text(encoding="utf-8")
_STORMS = (_JS / "storms" / "index.js").read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    return src[start : src.index("\n}", start)]


def test_the_observer_does_not_hydrate_through_the_hash_router():
    """THE regression. `_routeFromHash` bails on a non-#netz hash, so it
    can never be the sole hydration path."""
    body = _fn_body(_NETZ, "initNetz")
    # Only the observer CALLBACK — the deep-link call after
    # `_observer.observe(sec)` is a separate, legitimate path and is
    # asserted by its own test below.
    observer = body[body.index("IntersectionObserver") : body.index("_observer.observe(sec)")]
    assert "_routeFromHash()" not in observer, (
        "the visibility observer calls the hash router, which returns early "
        "unless the URL is a #netz deep link — the panel will render empty"
    )
    assert "_hydrate()" in observer


def test_hydration_falls_through_to_a_view_when_the_hash_is_not_ours():
    """A deep link still wins; everything else must still load."""
    body = _fn_body(_NETZ, "_hydrate")
    assert "_routeFromHash()" in body, "a #netz deep link must still pick the view"
    assert "showTab(" in body, "no fallback — arriving without a #netz hash loads nothing"


def test_the_hash_router_keeps_its_early_return():
    """The guard is correct IN `_routeFromHash` — it must not start acting
    on hashes belonging to other sections. The fix belongs at the caller."""
    body = _fn_body(_NETZ, "_routeFromHash")
    assert "startsWith('#netz')" in body and "return;" in body


def test_the_deep_link_path_survives_a_section_that_never_scrolls_into_view():
    body = _fn_body(_NETZ, "initNetz")
    tail = body[body.index("_observer.observe(sec)") :]
    assert (
        "_routeFromHash()" in tail
    ), "a #netz deep link must render even if the observer never fires"


def test_storms_still_hydrates_unconditionally():
    """Parity guard. netz/ copied this observer from storms/; if storms
    ever grows the same early-return, this file's reasoning goes stale."""
    body = _fn_body(_STORMS, "_route")
    last = body.rstrip().splitlines()[-1].strip()
    assert re.match(
        r"_showList\(host\);?$", last
    ), f"storms/_route no longer ends in an unconditional list render: {last!r}"
