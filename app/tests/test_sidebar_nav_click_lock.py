"""Regression — the desktop sidebar's active-nav highlight kept
flashing "Gewitter-Archiv" no matter what was actually clicked
("egal was ich im menü anklicke es blinkt immer noch das gewitter
archiv auf"). Root cause: the click handler set the highlight eagerly,
but the scrollspy's own scroll-triggered tick() immediately re-picked
"whichever section the viewport is nearest right now" on every
intermediate frame of the resulting smooth-scroll animation — and
Gewitter-Archiv sits mid-list in DOM order, so it kept winning that
race until the animation finally settled on the real target.

chrome/mobile-dock.js already solved this exact race for the bottom
dock with a ~900 ms "click-lock" that re-asserts the clicked target on
every tick instead of just skipping it (so a slow frame mid-lock still
shows the right thing). This fix mirrors that pattern in
chrome/sidebar.js rather than inventing a second one — CLAUDE.md
forbids a parallel implementation of the same fix.

We don't ship a JS DOM test harness yet, so this stays a source-grep
regression, matching test_lightbox_weather_render.py's own pattern.
"""

from __future__ import annotations

from pathlib import Path

_SIDEBAR_JS = (
    Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js" / "chrome" / "sidebar.js"
)


def _read() -> str:
    assert _SIDEBAR_JS.exists()
    return _SIDEBAR_JS.read_text(encoding="utf-8")


def test_a_shared_lock_helper_exists_not_a_second_copy():
    src = _read()
    assert src.count("function _lockNavClickTo(") == 1


def test_the_main_click_loop_uses_the_lock_helper():
    src = _read()
    assert "a.addEventListener('click', () => _lockNavClickTo(a.dataset.target));" in src


def test_the_settings_nav_actions_also_use_the_lock_helper():
    """navScrollToSettings / navJumpToSetting are registered via
    registerAction, outside the main `.nav a[data-target]` click loop —
    they need the same lock or Einstellungen clicks would still be able
    to flash Gewitter-Archiv on the way there."""
    src = _read()
    settings_action = src[src.index("registerAction('navScrollToSettings'") :]
    settings_action = settings_action[: settings_action.index("\n});")]
    assert "_lockNavClickTo('settings')" in settings_action

    sub_action = src[src.index("registerAction('navJumpToSetting'") :]
    sub_action = sub_action[: sub_action.index("\n});")]
    assert "_lockNavClickTo('settings')" in sub_action


def test_tick_reasserts_the_locked_target_rather_than_only_skipping():
    """Re-asserting (not just returning early) matches mobile-dock's
    own fix exactly — a slow animation frame that lands mid-lock still
    shows the correct highlight instead of a brief gap."""
    src = _read()
    tick_body = src[src.index("const tick = () => {") :]
    tick_body = tick_body[: tick_body.index("\n  };")]
    assert "if (_navClickLockTarget) {" in tick_body
    assert "_setActiveNav(_navClickLockTarget);" in tick_body


def test_the_lock_clears_itself_after_a_timeout():
    src = _read()
    assert "_navClickLockTimer = setTimeout(() => {" in src
    assert "_navClickLockTarget = null;" in src
