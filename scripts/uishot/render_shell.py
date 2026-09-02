#!/usr/bin/env python3
"""Render the REAL index.html (all Jinja partials) to a plain HTML file.

The screenshot harness must photograph the markup that ships, not a
hand-written stand-in. Every surface it shoots is JS-generated into a
container that lives in ``app/web/templates/partials/*.html``, so the
containers have to come from the real templates or the layout under
test is not the layout that ships.

This uses the SAME Jinja2 that Flask uses, with the same template
folder, so ``{% include %}`` resolves exactly as it does at runtime.
The one Flask-provided global is ``static_v`` (a cache-bust hash,
``server.py:81``); a stub is enough because the harness serves the
files itself and wants no cache-busting.

No Flask app, no config, no storage, no network.

Usage from repo root::

    python3 scripts/uishot/render_shell.py <out.html>
"""

from __future__ import annotations

import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = REPO_ROOT / "app" / "web" / "templates"


def render_shell() -> str:
    """Render ``index.html`` with every partial included."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # Flask installs this as a file-hash cache buster. The harness wants
    # no cache-busting at all, so a constant is the honest stub.
    env.globals["static_v"] = lambda _path: "uishot"
    return env.get_template("index.html").render()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: render_shell.py <out.html>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_shell(), encoding="utf-8")
    print(f"[uishot] shell rendered -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
