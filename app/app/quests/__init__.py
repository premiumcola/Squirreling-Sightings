"""Seasonal quests — progress-based achievements layered on the existing
species `achievements.json` file.

Why a separate package:
    The legacy achievement system in `routes/sichtungen.py` is binary
    (species seen yes/no). Quests need a counter, a window, and richer
    criteria (label sets, hour windows, distinct-species counts, weather
    overlap). Putting that next to the species code would either bloat the
    route file or muddy the data shape. Instead, the route file owns
    persistence (`_load_achievements` / `_save_achievements`) and this
    package owns the evaluation logic; the on-disk JSON gains a `quests`
    top-level key alongside the existing per-species entries.

Evaluation runs at three trigger points (see CLAUDE.md feature doc F09):
    a) inline after every motion event finalize (best-effort, full eval)
    b) hourly background timer in server.py
    c) manual "Re-Eval" button → POST /api/achievements/quests/reevaluate

`evaluate_quests` is idempotent — running it twice in a row produces the
same dict — so trigger (a) and (b) cannot diverge.

Was a single 650-line module; split at its own seams to get back under
CLAUDE.md's 500-line file and 80-line function ceilings.

  _catalogue.py — the hardcoded quest list + the persistence shape
  _windows.py   — when a window is open, opens next, and is historical
  _matching.py  — which stored events count towards a quest
  _evaluate.py  — evaluate_quests
  _archive.py   — archive_closed_quests + preview_upcoming_quests
  _service.py   — reevaluate_and_save, the entry point the app calls
"""

from __future__ import annotations

from ._archive import archive_closed_quests, preview_upcoming_quests
from ._catalogue import QUESTS
from ._evaluate import evaluate_quests
from ._service import reevaluate_and_save

__all__ = [
    "QUESTS",
    "archive_closed_quests",
    "evaluate_quests",
    "preview_upcoming_quests",
    "reevaluate_and_save",
]
