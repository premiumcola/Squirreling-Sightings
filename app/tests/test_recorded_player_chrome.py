"""Regression guards for the native-look recorded player chrome.

The operator watches clips on an iPhone. Until now `openLightbox` sniffed
the UA and handed EVERY video item straight to Safari's native player —
which means the SVG detection overlay (svg-boxes.js) was never visible on
the one device it was built for: a native fullscreen `<video>` is an
AVPlayer view outside the web page, so no DOM overlay can exist there.

The fix is a choice rather than a platform rule: our in-page player,
restyled to the native player's visual language (black ground, circular
translucent controls, centre transport, elapsed / −remaining pair,
auto-hiding chrome), plus an explicit control that hands the clip to the
real native player — honestly labelled, because the boxes go away there.

What is pinned here is the set of decisions that are expensive to
rediscover and cheap to break:

  · The handoff is FEATURE-DETECTED (requestFullscreen /
    webkitEnterFullscreen), never UA-sniffed. A UA sniff is what made
    the boxes unreachable on iOS in the first place.
  · The overlay is torn down entering the native player and restored on
    the way back. Both directions have a named failure mode: a stale SVG
    layer left painting over a hidden video, and — the subtle one — a
    RAF loop that stays dead after the return, because a clip that kept
    playing through the handoff never emits a fresh `play` event for
    bbox-overlay/index.js's listener to restart it.
  · The native control carries a German warning about the boxes.
  · The choice is remembered in localStorage, every access in try/catch
    (overlay-toggles.js's precedent) so a private window cannot break
    playback.
  · The iOS checklist items that have actually regressed before in this
    codebase: 44 px targets, hover behind a media query, no fixed
    element sized in vh, safe-area insets, reduced-motion.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._node_js import NODE_AVAILABLE, NODE_MISSING_REASON
from ._node_js import run_js as _js

_REPO = Path(__file__).resolve().parents[2]
_JS = _REPO / "app" / "web" / "static" / "js"
_CSS = _REPO / "app" / "web" / "static" / "css"
_PLAYER = _JS / "mediaview" / "player"
_PLAYER_CSS = _CSS / "30h-mediaview-player.css"

_EXPECTED_MODULES = {"index.js", "_pref.js", "_native.js", "_transport.js", "_autohide.js"}


def _read(path: Path) -> str:
    assert path.exists(), f"missing: {path}"
    return path.read_text(encoding="utf-8")


def _player_sources() -> dict[str, str]:
    return {p.name: _read(p) for p in sorted(_PLAYER.glob("*.js"))}


def _rule(css: str, selector: str) -> str:
    """Body of the first CSS rule whose selector list contains `selector`."""
    m = re.search(re.escape(selector) + r"[^{}]*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


# ── 1 · package shape ────────────────────────────────────────────────


def test_player_package_exists_with_the_expected_modules():
    assert _PLAYER.is_dir(), "mediaview/player/ package is missing"
    assert set(_player_sources()) == _EXPECTED_MODULES


def test_player_modules_stay_under_the_js_ceiling():
    srcs = _player_sources()
    assert srcs, "no player modules found"
    for name, src in srcs.items():
        n = len(src.splitlines())
        assert n <= 400, f"{name} is {n} lines — over the 400-line JS ceiling"


def test_shell_mounts_the_player_chrome_for_recorded_modes():
    shell = _read(_JS / "mediaview" / "shell.js")
    assert "player/index.js" in shell
    assert "mountPlayerChrome" in shell


# ── 2 · the transport we lacked ──────────────────────────────────────


def test_transport_offers_ten_second_skips_in_both_directions():
    src = _read(_PLAYER / "_transport.js")
    assert 'data-skip="-10"' in src
    assert 'data-skip="10"' in src


def test_transport_has_a_centre_play_pause_and_the_time_pair():
    src = _read(_PLAYER / "_transport.js")
    for cls in ("mv-player-center", "mv-player-play", "mv-player-elapsed", "mv-player-remain"):
        assert cls in src, f"{cls} missing from the transport markup"


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_remaining_time_reads_as_a_negative_like_the_native_player():
    out = _js(
        """
        const m = await import(JS + '/mediaview/player/_transport.js');
        console.log(JSON.stringify({
          zero: m.clockLabel(0),
          minute: m.clockLabel(61),
          long: m.clockLabel(3599),
          nan: m.clockLabel(NaN),
          remain: m.remainingLabel(1, 6),
          remainEnd: m.remainingLabel(6, 6),
        }));
        """
    )
    assert out == {
        "zero": "0:00",
        "minute": "1:01",
        "long": "59:59",
        "nan": "0:00",
        # U+2212 MINUS SIGN, as the native player renders it.
        "remain": "−0:05",
        "remainEnd": "−0:00",
    }


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_chrome_never_auto_hides_while_the_clip_is_paused():
    out = _js(
        """
        const m = await import(JS + '/mediaview/player/_autohide.js');
        console.log(JSON.stringify({
          none: m.shouldHideChrome(null),
          paused: m.shouldHideChrome({ paused: true, ended: false }),
          ended: m.shouldHideChrome({ paused: false, ended: true }),
          playing: m.shouldHideChrome({ paused: false, ended: false }),
        }));
        """
    )
    assert out == {"none": False, "paused": False, "ended": False, "playing": True}


# ── 3 · the native handoff ───────────────────────────────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_native_handoff_is_feature_detected():
    out = _js(
        """
        const m = await import(JS + '/mediaview/player/_native.js');
        console.log(JSON.stringify({
          nothing: m.canNativeFullscreen(null),
          plain: m.canNativeFullscreen({}),
          standard: m.canNativeFullscreen({ requestFullscreen() {} }),
          ios: m.canNativeFullscreen({ webkitEnterFullscreen() {} }),
          legacy: m.canNativeFullscreen({ webkitRequestFullscreen() {} }),
        }));
        """
    )
    assert out == {
        "nothing": False,
        "plain": False,
        "standard": True,
        "ios": True,
        "legacy": True,
    }


def test_player_package_never_sniffs_the_user_agent():
    srcs = _player_sources()
    assert srcs, "no player modules found"
    for name, src in srcs.items():
        for needle in ("userAgent", "iPhone", "iPad", "IS_IOS", "isIOS", "navigator.platform"):
            assert needle not in src, (
                f"{name} references {needle} — the fullscreen handoff must be "
                "feature-detected, never UA-sniffed"
            )


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_overlay_and_raf_loop_survive_the_round_trip():
    """The named failure modes, both directions.

    Entering: the RAF loop must stop and the SVG box layer must be
    cleared — nothing may keep painting over a video the page cannot
    see. Returning: the loop must come back for a clip that is still
    playing. That is the subtle one — the clip never paused, so
    bbox-overlay/index.js's `play` listener never fires again.
    """
    out = _js(
        """
        globalThis.requestAnimationFrame = () => 7;
        globalThis.cancelAnimationFrame = () => {};
        const m = await import(JS + '/mediaview/player/_native.js');
        const { _state } = await import(JS + '/mediathek/bbox-overlay/_state.js');
        const wrap = { dataset: {} };
        const video = { paused: false, ended: false, controls: false, closest: () => wrap };
        _state.rafHandle = 42;
        m.suspendOverlayForNative(video);
        const entered = { raf: _state.rafHandle, flag: wrap.dataset.nativeFs,
                          controls: video.controls };
        m.resumeOverlayAfterNative(video);
        const back = { raf: _state.rafHandle, flag: wrap.dataset.nativeFs || null,
                       controls: video.controls };
        m.suspendOverlayForNative(video);
        video.paused = true;
        m.resumeOverlayAfterNative(video);
        const paused = { raf: _state.rafHandle };
        console.log(JSON.stringify({ entered, back, paused }));
        """
    )
    assert out["entered"] == {"raf": 0, "flag": "1", "controls": True}
    assert out["back"] == {"raf": 7, "flag": None, "controls": False}
    # A paused clip comes back without a loop — the pause listener owns
    # that state, and a loop started here would spin on a still frame.
    assert out["paused"] == {"raf": 0}


def test_the_return_trip_listens_for_every_exit_event():
    src = _read(_PLAYER / "_native.js")
    for ev in ("webkitendfullscreen", "webkitbeginfullscreen", "fullscreenchange"):
        assert ev in src, f"{ev} is not handled — the return trip would strand the overlay"
    assert "webkitfullscreenchange" in src


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_native_control_warns_in_german_that_the_boxes_are_gone():
    out = _js(
        """
        const m = await import(JS + '/mediaview/player/_native.js');
        console.log(JSON.stringify({ warn: m.NATIVE_WARNING }));
        """
    )
    warn = out["warn"]
    assert "Bbox" in warn
    assert "nicht sichtbar" in warn
    # And the control itself carries it — a tooltip the operator can
    # reach before they lose the overlay, not only a toast afterwards.
    transport = _read(_PLAYER / "_transport.js")
    assert "NATIVE_WARNING" in transport
    assert "title=" in transport and "aria-label=" in transport


def test_player_teardown_cannot_strand_the_hidden_overlay():
    """The native-fs flag lives on #lightboxMediaWrap, which is REUSED
    across clips (recorded-mode.js reparents it rather than rebuilding
    it). Closing the modal while the flag is set would hide the boxes on
    the next clip too, with nothing left on screen to explain why."""
    src = _read(_PLAYER / "index.js")
    teardown = src.split("teardown:", 1)[-1]
    assert "resumeOverlayAfterNative" in teardown


# ── 4 · remembering the choice ───────────────────────────────────────


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_player_preference_round_trips_through_localstorage():
    out = _js(
        """
        const store = {};
        globalThis.localStorage = {
          getItem: (k) => (k in store ? store[k] : null),
          setItem: (k, v) => { store[k] = String(v); },
        };
        const m = await import(JS + '/mediaview/player/_pref.js');
        const first = m.getPlayerPref();
        m.setPlayerPref(m.PLAYER_NATIVE);
        const remembered = m.prefersNativePlayer();
        m.setPlayerPref(m.PLAYER_INLINE);
        console.log(JSON.stringify({
          first, remembered, back: m.prefersNativePlayer(),
          keys: Object.keys(store),
        }));
        """
    )
    assert out["first"] == "inline", "the box player is the default — that is the whole point"
    assert out["remembered"] is True
    assert out["back"] is False
    assert out["keys"] == ["tamspy.playerPref.v1"]


@pytest.mark.skipif(not NODE_AVAILABLE, reason=NODE_MISSING_REASON)
def test_a_private_window_cannot_break_playback():
    out = _js(
        """
        globalThis.localStorage = {
          getItem() { throw new Error('private mode'); },
          setItem() { throw new Error('private mode'); },
        };
        const m = await import(JS + '/mediaview/player/_pref.js');
        let threw = false;
        try { m.setPlayerPref(m.PLAYER_NATIVE); } catch { threw = true; }
        console.log(JSON.stringify({ pref: m.getPlayerPref(), threw }));
        """
    )
    assert out == {"pref": "inline", "threw": False}


def test_lightbox_routes_on_the_preference_not_on_the_user_agent():
    src = _read(_JS / "lightbox.js")
    assert "prefersNativePlayer" in src
    assert "IS_IOS" not in src, (
        "openLightbox must not hand video items to the native player by UA — "
        "that is what hid the detection boxes on the one device that needed them"
    )


def test_the_remembered_native_route_offers_a_way_back():
    """A preference that can only be set is a trap: once the grid opens
    the native player straight away, there is no surface left to change
    your mind on. The exit toast is that surface."""
    src = _read(_JS / "mediathek" / "ios-video.js")
    assert "PLAYER_INLINE" in src and "setPlayerPref" in src
    assert "Box-Player" in src, "the way back needs a visible German label"
    assert "prefersNativePlayer" in src, (
        "the offer belongs to the remembered route only — a one-off handoff "
        "from inside our player already has the switch on screen"
    )


# ── 5 · CSS + the iOS checklist ──────────────────────────────────────


def test_player_css_partial_is_registered_in_the_build():
    builder = _read(_REPO / "app" / "app" / "css_builder.py")
    assert '"30h-mediaview-player.css"' in builder
    order = re.findall(r'"([0-9][^"]*\.css)"', builder)
    assert order.index("30h-mediaview-player.css") > order.index("30g-mediaview-shell.css")


def test_player_touch_targets_meet_the_ios_minimum():
    css = _read(_PLAYER_CSS)
    for cls in (".mv-player-btn", ".mv-player-native"):
        body = _rule(css, cls)
        assert "44px" in body, f"{cls} is below the 44 px touch target"


def test_player_hover_states_sit_behind_a_hover_query():
    css = _read(_PLAYER_CSS)
    for m in re.finditer(r"\.mv-player[^{}]*:hover", css):
        before = css[: m.start()]
        assert "@media (hover: hover)" in before.rsplit("\n}\n", 2)[-1] or (
            before.rfind("@media (hover: hover)") > before.rfind("\n}\n")
        ), "a .mv-player hover rule is not inside a (hover: hover) query"


def test_player_css_avoids_vh_units_and_fixed_positioning():
    # Comments stripped — this file's header names both anti-patterns to
    # say it avoids them, and a prose mention is not a rule.
    css = re.sub(r"/\*.*?\*/", "", _read(_PLAYER_CSS), flags=re.DOTALL)
    assert not re.search(r"\b\d+(\.\d+)?vh\b", css), "use dvh, never vh"
    assert "position: fixed" not in css, "no fixed positioning in the stage chrome"


def test_player_css_respects_the_notch_and_reduced_motion():
    css = _read(_PLAYER_CSS)
    assert (
        "env(safe-area-inset-left" in css and "env(safe-area-inset-right" in css
    ), "landscape on a notched iPhone puts the stage under the sensor housing"
    m = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.+?)\n\}", css, re.DOTALL)
    assert m, "reduced motion must disable the auto-hide fade"
    assert "transition: none" in m.group(1)
