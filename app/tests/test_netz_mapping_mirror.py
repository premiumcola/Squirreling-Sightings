"""MANDATORY #1 (JS half) · the two mappings agree on every value.

``_mapping.js`` and ``thresholds/_apply.py`` are bit-for-bit mirrors. If
they drift, the panel draws a vertex at one threshold and the pipeline
enforces another — and nothing on either side would notice, because each
is internally consistent. That is precisely the class of bug this whole
feature exists to remove, so it gets a test that runs the real
JavaScript rather than a Python re-implementation of it.

Skipped, not failed, when node is unavailable: the mirror is checked in
CI (which has node for eslint) and a developer without it still gets the
rest of the suite.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
MAPPING_JS = REPO / "app" / "web" / "static" / "js" / "netz" / "_mapping.js"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "netz_mapping.json"

_HARNESS = """
import {{ spawnFor, pushFor, eFromRadius, clampE }} from '{mod}';
import {{ readFileSync }} from 'node:fs';
const fx = JSON.parse(readFileSync('{fixture}', 'utf8'));
const bad = [];
for (const [label, byE] of Object.entries(fx.values)) {{
  for (const [e, want] of Object.entries(byE)) {{
    const s = spawnFor(label, Number(e));
    const p = pushFor(label, Number(e));
    if (s !== want.spawn) bad.push(`${{label}} E=${{e}} spawn js=${{s}} py=${{want.spawn}}`);
    if (p !== want.push) bad.push(`${{label}} E=${{e}} push js=${{p}} py=${{want.push}}`);
  }}
}}
// The snap: within +/-2 of factory the drag must land exactly on Werk.
if (eFromRadius(51 * 1.25, 125) !== 50) bad.push('snap to 50 failed');
if (eFromRadius(60 * 1.25, 125) !== 60) bad.push('no-snap outside band failed');
if (clampE('abc') !== 50) bad.push('garbage E must be factory');
process.stdout.write(JSON.stringify(bad.slice(0, 12)));
"""


def _node():
    return shutil.which("node")


@pytest.mark.skipif(not _node(), reason="node not available")
def test_js_mapping_matches_python_on_every_value(tmp_path):
    assert FIXTURE.is_file(), "run test_netz_mapping.py first — it writes the fixture"
    harness = tmp_path / "mirror.mjs"
    harness.write_text(
        _HARNESS.format(mod=MAPPING_JS.as_posix(), fixture=FIXTURE.as_posix()),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [_node(), str(harness)], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    mismatches = json.loads(proc.stdout or "[]")
    assert mismatches == [], f"JS/Python mapping drift: {mismatches}"
