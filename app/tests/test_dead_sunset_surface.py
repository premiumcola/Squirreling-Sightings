"""No operator control may exist for an event that cannot fire.

The score-based `sunset` weather event was retired deliberately —
sunrise/sunset content lives only in the sun-timelapse pipeline, and
`_detect` documents why it no longer dispatches `_detect_sunset`. The
retirement was half-finished: `EVENT_LABEL_DE` and `WEATHER_TYPES` both
dropped `sunset`, so the poll loop can never evaluate it and no clip can
ever carry `event_type == "sunset"` — but `weather.events.sunset` was
still seeded into settings.json with five tunables, and the Telegram
"Was senden" tab still rendered a push toggle for it. Because
`WEATHER_TYPES.sunset` was gone, that row fell through to the raw
English key and rendered a chip reading "sunset" with no icon.

`_detect_sunset` itself stays — the comment above `_detect` says a
future toggle may re-enable it, and deleting a documented parked
feature is not this task's call. What goes is the operator-facing
surface: a switch nobody's flip can reach.

Two invariants:

* every event key the settings defaults seed is one the poll loop
  actually iterates (`EVENT_LABEL_DE`), and every push toggle default
  names a real event;
* every row the push panel renders resolves against `WEATHER_TYPES`, so
  a retired type cannot leave behind an untranslated ghost chip.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.settings._consts import TELEGRAM_PUSH_DEFAULTS, WEATHER_DEFAULTS
from app.weather_service._consts import EVENT_LABEL_DE

_JS_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "js"


def test_every_seeded_weather_event_is_one_the_poll_loop_iterates():
    """`_lifecycle` walks EVENT_LABEL_DE. A configured event outside it
    is a block of tunables no code path can ever read."""
    assert set(WEATHER_DEFAULTS["events"]) <= set(EVENT_LABEL_DE)


def test_no_push_toggle_for_a_retired_event():
    assert set(TELEGRAM_PUSH_DEFAULTS["weather"]["events"]) <= set(EVENT_LABEL_DE)


def test_sunset_is_gone_from_both_settings_surfaces():
    assert "sunset" not in WEATHER_DEFAULTS["events"]
    assert "sunset" not in TELEGRAM_PUSH_DEFAULTS["weather"]["events"]


def test_detect_sunset_is_kept_as_a_parked_feature():
    """Explicitly pinned so a later cleanup pass reads the intent rather
    than guessing: the detector body stays, only its controls went."""
    from app.weather_service._detection import DetectionMixin

    assert hasattr(DetectionMixin, "_detect_sunset")


def _js_list(source: str, name: str) -> list[str]:
    m = re.search(rf"const {name} = \[(.*?)\];", source, re.S)
    assert m, f"{name} not found"
    return re.findall(r"'([^']+)'", m.group(1))


def test_push_panel_renders_no_type_missing_from_weather_types():
    push_src = (_JS_DIR / "push.js").read_text(encoding="utf-8")
    types_src = (_JS_DIR / "core" / "weather-types.js").read_text(encoding="utf-8")
    known = set(re.findall(r"^  ([a-z_]+): \{", types_src, re.M))
    assert known, "WEATHER_TYPES keys not parseable"
    order = _js_list(push_src, "_PUSH_WEATHER_ORDER")
    assert order, "_PUSH_WEATHER_ORDER is empty"
    assert set(order) <= known
