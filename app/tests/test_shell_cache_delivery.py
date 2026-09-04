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


@pytest.fixture
def fresh_hash():
    """`shell_hash` is memoised for the process's life (it costs ~350 ms
    and every open tab polls it). These tests edit files on purpose, so
    they need the computation, not the cached answer."""
    from app import lifecycle

    def compute():
        lifecycle._shell_hash_memo[0] = None
        return lifecycle.shell_hash()

    yield compute
    lifecycle._shell_hash_memo[0] = None


def test_shell_hash_covers_javascript(fresh_hash):
    """A JS-only change must produce a different shell hash.

    This is the one that stranded the player: the whole rework was
    JavaScript, app.css never moved, and the hash the SW keys its cache
    on stayed byte-identical across every deploy.
    """
    before = fresh_hash()

    victim = next(iter(sorted((STATIC / "js").rglob("*.js"))))
    original = victim.read_bytes()
    try:
        victim.write_bytes(original + b"\n// cache-bust probe\n")
        after = fresh_hash()
    finally:
        victim.write_bytes(original)

    assert after != before, (
        "shell_hash did not change after editing "
        f"{victim.name} — a JS-only deploy would reuse the old SW cache"
    )
    # …and it comes back when the edit is reverted, i.e. it is a hash of
    # the content and not a counter that drifts.
    assert fresh_hash() == before


def test_shell_hash_covers_css_too(fresh_hash):
    """The css half must not have been lost in the rewrite."""
    from app import lifecycle

    before = fresh_hash()
    css = STATIC / "app.css"
    if not css.exists():
        pytest.skip("app.css is built at boot and absent in this checkout")
    original = css.read_bytes()
    try:
        css.write_bytes(original + b"\n/* probe */\n")
        lifecycle._static_hashes.pop("app.css", None)
        assert fresh_hash() != before
    finally:
        css.write_bytes(original)
        lifecycle._static_hashes.pop("app.css", None)


def test_the_hash_is_memoised():
    """It walks ~400 files and measured 350 ms. Every open tab polls
    /version.json every five minutes and on every focus, and the value is
    stamped into every render — on the box that runs Coral inference.
    Recomputing it per call is not an option."""
    import time

    from app import lifecycle

    lifecycle._shell_hash_memo[0] = None
    t0 = time.perf_counter()
    first = lifecycle.shell_hash()
    cold_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    second = lifecycle.shell_hash()
    warm_ms = (time.perf_counter() - t0) * 1000

    assert first == second
    # Not a timing assertion on the cold path (CI machines vary wildly);
    # the claim is only that the second call does no work at all.
    assert warm_ms < max(
        1.0, cold_ms / 20
    ), f"second call took {warm_ms:.3f} ms against a {cold_ms:.1f} ms cold call — not memoised"


def test_the_stamp_and_the_endpoint_cannot_disagree():
    """Both go through the same memo. Two calls returning different
    values would make core/version-guard.js report a permanent phantom
    mismatch and train the operator to ignore the bar."""
    from app import lifecycle

    assert lifecycle.shell_hash() == lifecycle.shell_hash()


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
    assert "const net = await fetch(request" in net
    assert "return net" in net
    # And it must actually GO to the network. A plain fetch() inside a
    # service worker is answered by the browser's own HTTP cache, so
    # "network-first" without this reads stale and reports success.
    assert "cache: 'no-cache'" in net, "the network-first path can be served from the HTTP cache"
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


# ── 4. the last mile: headers nobody was asserting ───────────────────


def _configured_max_age() -> object:
    """The SEND_FILE_MAX_AGE_DEFAULT literal server.py actually sets.

    Read from the source rather than hardcoded, so this test measures the
    project's real choice: change that line to 31536000 and the header
    assertion below fails, which is the whole point — the value was
    previously not set at all and the correct behaviour was inherited
    from a library default nobody had pinned.
    """
    src = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(encoding="utf-8")
    # Anchored on the assignment, not the bare name: the comment above
    # that line names 31536000 as the value that would BREAK this, and a
    # looser pattern happily read the warning instead of the setting.
    m = re.search(r'app\.config\[\s*"SEND_FILE_MAX_AGE_DEFAULT"\s*\]\s*=\s*([0-9]+|None)', src)
    assert m, "server.py no longer states a static cache policy"
    return None if m.group(1) == "None" else int(m.group(1))


def test_unstamped_modules_are_revalidated():
    """index.html hash-stamps app.css and main.js and NOTHING else, so
    the several hundred ES modules behind them are fetched at URLs that
    never change between deploys. Their freshness rests entirely on the
    Cache-Control this policy produces.

    A bare Flask app over the real static folder, following the pattern
    the other route tests use — booting app.server would need the
    container's config file.
    """
    flask = pytest.importorskip("flask")

    app = flask.Flask(__name__, static_folder=str(STATIC))
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = _configured_max_age()

    resp = app.test_client().get("/static/js/core/dom.js")
    assert resp.status_code == 200
    cc = (resp.headers.get("Cache-Control") or "").lower()
    assert "no-cache" in cc or "max-age=0" in cc, (
        f"static modules would be served with Cache-Control: {cc!r} — a browser "
        "may hold them across deploys and rebuild the mixed-build symptom"
    )


def test_the_shell_document_is_never_stored():
    """The shell carries both ?v= stamps and the shell-version meta, and
    the service worker caches it. A cached shell hands out stale stamps
    for everything else, so one bad response propagates into a whole
    stale build."""
    src = (
        Path(__file__).resolve().parents[1] / "app" / "routes" / "bootstrap" / "_shell.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def index(") : src.index("def media_file")]
    assert "Cache-Control" in body, "the app shell is served with no cache directive at all"
    assert "no-store" in body, f"the shell is cacheable:\n{body}"


def test_the_static_cache_policy_is_stated_not_inherited():
    """It was correct only because of a library default that nothing in
    this repo asserted, and Werkzeug was not even pinned."""
    src = (Path(__file__).resolve().parents[1] / "app" / "server.py").read_text(encoding="utf-8")
    assert "SEND_FILE_MAX_AGE_DEFAULT" in src
    reqs = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
    assert "werkzeug==" in reqs.lower(), "werkzeug decides that header and is unpinned"


# ── 5. the CSS build cannot drop a partial in silence ────────────────


def test_every_partial_on_disk_is_registered():
    """LOAD_ORDER is an explicit list; a partial missing from it is not
    compiled, and app.css stays byte-identical so nothing looks wrong."""
    from app.css_builder import LOAD_ORDER

    css_dir = Path(__file__).resolve().parents[1] / "web" / "static" / "css"
    on_disk = {p.name for p in css_dir.glob("*.css")}
    orphans = sorted(on_disk - set(LOAD_ORDER))
    assert not orphans, f"partials on disk but not in LOAD_ORDER — never compiled: {orphans}"


def test_an_unregistered_partial_is_reported(tmp_path):
    """And when it does happen, it has to be audible."""
    from app.css_builder import _warn_unregistered

    (tmp_path / "99-orphan.css").write_text("/* x */", encoding="utf-8")
    said = []

    class _Log:
        def warning(self, msg, *args):
            said.append(msg % args)

    assert _warn_unregistered(tmp_path, _Log()) == ["99-orphan.css"]
    assert said and "99-orphan.css" in said[0]


# ── 6. the guard is actually wired in ────────────────────────────────


def test_the_guard_is_wired_end_to_end():
    """Three load-bearing connections, none of which fails loudly: the
    meta tag, the Jinja global behind it, and the start call."""
    web = Path(__file__).resolve().parents[1] / "web"
    app_dir = Path(__file__).resolve().parents[1] / "app"

    tpl = (web / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'name="shell-version"' in tpl
    assert "shell_v()" in tpl

    server = (app_dir / "server.py").read_text(encoding="utf-8")
    assert '"shell_v"' in server, "the template calls shell_v() but nothing registers it"

    main_js = (web / "static" / "js" / "main.js").read_text(encoding="utf-8")
    assert "startVersionGuard(" in main_js, "the guard is imported but never started"
