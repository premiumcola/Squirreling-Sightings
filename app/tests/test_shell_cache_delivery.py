"""The deploy actually has to reach the browser.

Weeks of front-end work sat on the server without ever arriving in the
user's tab — „wieso kommt der neue player nicht bei mir an??". Three
independent causes, one test each, because each of them alone is enough
to strand a deploy:

1. ``/version.json`` hashed ``app.css`` only, so a JavaScript-only
   commit left the service-worker cache name untouched.
2. The SW resolved its cache name into a module global, which the
   browser resets every time it restarts the worker — so responses were
   written to one cache and read from another.
3. It answered every request stale-while-revalidate, i.e. served the old
   file and fetched the new one for next time. An online user was
   permanently one deploy behind.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "web" / "static"
SW = STATIC / "sw.js"


def _code() -> str:
    """sw.js with its comments removed.

    These tests scan for shapes like ``caches.match(`` — and this file's
    comments quote exactly those shapes when explaining why they are
    wrong. Scanning the raw text makes the documentation fail the test.
    """
    src = SW.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(re.sub(r"//.*$", "", line) for line in src.splitlines())


# ── 1. the hash has to move when JavaScript moves ────────────────────


def test_shell_hash_covers_javascript(tmp_path, monkeypatch):
    """A JS-only change must produce a different shell hash.

    This is the one that stranded the player: the whole rework was
    JavaScript, app.css never moved, and the hash the SW keys its cache
    on stayed byte-identical across every deploy.
    """
    from app import lifecycle

    before = lifecycle.shell_hash()

    victim = next(iter(sorted((STATIC / "js").rglob("*.js"))))
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n// cache-bust probe\n")
        after = lifecycle.shell_hash()
    finally:
        victim.write_bytes(original)

    assert after != before, (
        "shell_hash did not change after editing "
        f"{victim.name} — a JS-only deploy would reuse the old SW cache"
    )
    # …and it comes back when the edit is reverted, i.e. it is a hash of
    # the content and not a counter that drifts.
    assert lifecycle.shell_hash() == before


def test_shell_hash_covers_css_too():
    """The css half must not have been lost in the rewrite."""
    from app import lifecycle

    before = lifecycle.shell_hash()
    css = STATIC / "app.css"
    if not css.exists():
        pytest.skip("app.css is built at boot and absent in this checkout")
    original = css.read_bytes()
    try:
        css.write_bytes(original + b"\n/* probe */\n")
        lifecycle._static_hashes.pop("app.css", None)
        assert lifecycle.shell_hash() != before
    finally:
        css.write_bytes(original)
        lifecycle._static_hashes.pop("app.css", None)


def test_version_endpoint_uses_the_shell_hash():
    """/version.json must serve the JS-aware hash, not the css one."""
    src = (
        Path(__file__).resolve().parents[1] / "app" / "routes" / "bootstrap" / "_shell.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def app_version") :]
    assert "shell_hash" in body
    assert 'hasher("app.css")' not in body, "version.json fell back to the css-only hash"


# ── 2. the cache name must survive a worker restart ──────────────────


def test_sw_resolves_cache_name_per_request():
    """No module-global cache name.

    A service worker is torn down and restarted constantly, and neither
    install nor activate re-runs on a restart. A `let _activeCache =
    CACHE_PREFIX + 'init'` is therefore live in production far more
    often than the resolved name is.
    """
    src = _code()
    assert "function activeCacheName" in src
    # Every cache open must go through the resolver.
    for open_call in re.findall(r"caches\.open\(([^)]*)\)", src):
        assert "activeCacheName" in open_call, (
            f"caches.open({open_call}) bypasses the resolver — "
            "this is how responses land in a cache nothing reads"
        )


def test_sw_never_matches_across_all_caches_first():
    """`caches.match(req)` searches EVERY cache, including ones the
    activate handler is about to delete. It is allowed only as the last
    resort inside the offline fallback, never as the primary read."""
    src = _code()
    fallback = src[
        src.index("async function _fallback") : src.index("async function _networkFirst")
    ]
    assert "caches.match(request)" in fallback
    outside = src.replace(fallback, "")
    assert "caches.match(" not in outside, "unscoped caches.match outside the offline fallback"


# ── 3. online users get the new code, not the previous one ───────────


def test_sw_is_network_first_for_code():
    src = _code()
    assert "async function _networkFirst" in src
    net = src[src.index("async function _networkFirst") : src.index("async function _cacheFirst")]
    # The network response is what gets returned; the cache is only
    # touched in the catch.
    assert "const net = await fetch(request)" in net
    assert "return net" in net
    cached_return = net.index("if (cached) return cached")
    assert net.index("catch") < cached_return, "cache is consulted before the network fails"


def test_sw_does_not_stale_while_revalidate_code():
    """The exact shape of the old bug, pinned so it cannot come back."""
    src = _code()
    assert "return cached || fetchPromise" not in src


def test_code_paths_route_through_network_first():
    """JS/CSS/HTML use network-first; only genuinely immutable assets
    may be served cache-first."""
    src = _code()
    dispatch = src[src.index("evt.respondWith") :]
    assert "_networkFirst(evt.request)" in dispatch
    immutable = re.search(r"const _IMMUTABLE = /(.+)/[a-z]*;", src)
    assert immutable, "no immutable-asset pattern found"
    pattern = re.compile(immutable.group(1), re.I)
    for code_path in ("/static/js/main.js", "/static/js/vplayer/index.js", "/static/app.css", "/"):
        assert not pattern.search(code_path), f"{code_path} would be served cache-first"
    for asset in ("/static/icons/icon-192.png", "/static/manifest.json"):
        assert pattern.search(asset), f"{asset} should be cache-first"


def test_sw_does_not_cache_its_own_version_probe():
    """activeCacheName() fetches /version.json; routing that through the
    cache would be circular."""
    src = SW.read_text(encoding="utf-8")
    assert "url.pathname === '/version.json'" in src
