"""Shared plumbing for the operator scripts in this folder.

Every script here has to answer the same two questions before it can do
anything: where is the ``app`` package, and where is the storage root.
Both answers were about to be copy-pasted a second time, so they live
here.
"""

from __future__ import annotations

import sys
from pathlib import Path


def add_app_to_path() -> Path:
    """Put the directory holding the ``app`` package on ``sys.path``.

    Derived from ``__file__`` rather than hardcoding ``/app`` so the same
    script runs from the dev checkout and from inside the container:
    ``<root>/scripts/x.py`` -> ``<root>``, which is ``/app`` there.
    """
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def storage_root() -> Path:
    """The configured storage root, or ``./storage`` when config is absent."""
    try:
        add_app_to_path()
        from app.config_loader import load_config  # type: ignore

        return Path(load_config()["storage"]["root"])
    except Exception:
        return Path("storage")
