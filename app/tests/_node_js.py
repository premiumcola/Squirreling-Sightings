"""Shared harness for tests that run real frontend JS modules under node.

Extracted out of test_storms_frontend_logic.py when a second test file
needed the same DOM stub — a copy here and a copy there is exactly the
parallel implementation CLAUDE.md forbids, and the stub is finicky
enough (it has to satisfy every module-scope `window.x = …` bridge in
the import graph) that a second, slightly-different copy would drift.

No `test_` prefix, so pytest does not try to collect this file itself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

JS_URI = (Path(__file__).resolve().parents[2] / "app" / "web" / "static" / "js").as_uri()

NODE_MISSING_REASON = "node not installed"
NODE_AVAILABLE = shutil.which("node") is not None

# Enough of a DOM for the import graph: several modules publish a
# `window.x = …` bridge at module scope and a couple touch `document` on
# import. The element proxy answers any method with another proxy, and
# remembers assigned properties so `host.innerHTML` can be read back.
_STUB = """
const el = () =>
  new Proxy(
    { style: {}, dataset: {},
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false } },
    { get(t, k) { if (k in t) return t[k];
                  if (k === 'children' || k === 'childNodes') return [];
                  return typeof k === 'string' ? () => el() : undefined; },
      set(t, k, v) { t[k] = v; return true; } },
  );
// `location` is part of the stub because several modules read
// `window.location.hash` at IMPORT time (statistics.js's hash redirect,
// the weather + netz hash routers). Without it the import throws and
// the failure looks like the module under test is broken. Tests that
// care about navigation still set `globalThis.location` themselves.
globalThis.window = { addEventListener() {},
  location: { hash: '', href: '', search: '' },
  matchMedia: () => ({ matches: false, addEventListener() {} }) };
globalThis.document = { addEventListener() {}, querySelector: () => el(),
  querySelectorAll: () => [], getElementById: () => el(), createElement: () => el(),
  createElementNS: () => el(), body: el(), documentElement: el() };
globalThis.IntersectionObserver = class { observe() {} disconnect() {} };
globalThis.history = { replaceState() {} };
globalThis.fetch = () => Promise.reject(new Error('no network in tests'));
"""


def run_js(body: str):
    """Run `body` with the app's JS modules importable. Returns its JSON.

    `body` must end with exactly one `console.log(JSON.stringify(...))` —
    its last stdout line is parsed and returned.
    """
    script = "{}\nconst JS = '{}';\n{}\n".format(_STUB, JS_URI, body)
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, "node failed:\n{}".format(proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])
