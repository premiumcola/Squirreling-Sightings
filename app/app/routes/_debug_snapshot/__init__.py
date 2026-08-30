"""SIMU-07 · the Live-Detect debug snapshot — one paste-able document.

Split out of ``coral_test_detection.py`` (which was 1378 lines) so the
snapshot has its own home and can be unit-tested without Flask.

Why it exists: the operator runs this system on an Unraid box and
diagnoses it from an iPhone over SSH. Typing ``docker logs … | grep …``
on a phone keyboard is what this document replaces, so the rule is
**everything a diagnosis needs goes into the copied text** — while the
on-screen view stays short (see ``live-detect-debug/_verdict.js``).
"""

from __future__ import annotations

from ...labels import COUNTED_LABELS
from ._blocks import assemble
from ._findings import build_findings, ladder_rows
from ._helpers import collect_log_lines
from ._machine import SCHEMA, SECTION_KEYS, build_document

__all__ = [
    "SCHEMA",
    "SECTION_KEYS",
    "build_snapshot",
    "build_document",
    "build_findings",
    "collect_log_lines",
    "ladder_rows",
]


def _relevant_labels(cam: dict, last: dict) -> list:
    """Classes worth showing a ladder for: the camera's filter, plus what
    the last tick saw — but only labels this project actually has a
    concept for. Sorted so two snapshots diff cleanly.

    The COUNTED_LABELS gate is the fix for a real readability failure: the
    detector's COCO label space contains ~80 classes, so a workshop camera
    pointed at a bench reports book / chair / suitcase / backpack / laptop
    every tick. Each one has no entry in TELEGRAM_PUSH_DEFAULTS, so
    `resolve_effective` returns push_enabled=False and _findings emitted a
    warn-tone "wird erkannt, aber nie gemeldet" line for every one of them.
    Those are not findings — nobody ever asked to be told about a book —
    and because warn sorts above info they pushed the REAL diagnostics off
    a phone screen that shows three lines.

    A label the camera explicitly filters for is always kept, even if it
    somehow left the vocabulary: that one the operator did ask about.
    """
    wanted = set(cam.get("object_filter") or [])
    labels = set(wanted)
    for det in last.get("detections") or []:
        label = det.get("label")
        if label and (label in COUNTED_LABELS or label in wanted):
            labels.add(label)
    return sorted(labels)


def build_snapshot(cam: dict, cam_id: str, tt: dict, runtime, eff_cfg: dict) -> dict:
    """Return ``{"markdown": str, "doc": dict, "findings": [...]}``.

    Two renderings of ONE extraction: ``doc`` is what "Debug kopieren"
    puts on the clipboard and what the SIMU log stores (machine-first,
    see :mod:`._machine`); ``markdown`` is what a human reads in a
    terminal. Both are built from the same ``last`` / ``diag`` /
    ``cluster_ev`` / ``ladder`` / ``findings`` values resolved here, so
    neither can report a threshold the other does not.

    Pure apart from the log ring-buffer read — every other input is
    passed in, so the whole document is unit-testable.
    """
    last = tt.get("last_tick") or {}
    cluster_ev = last.get("cluster_evidence") or {}
    diag = last.get("diag") or {}
    push_cfg = ((eff_cfg or {}).get("telegram") or {}).get("push") or {}
    ladder = ladder_rows(cam, push_cfg, _relevant_labels(cam, last))
    findings = build_findings(cam, last, cluster_ev, ladder)
    parts = dict(
        cam=cam,
        cam_id=cam_id,
        last=last,
        diag=diag,
        cluster_ev=cluster_ev,
        runtime=runtime,
        eff_cfg=eff_cfg or {},
        ladder=ladder,
        findings=findings,
        log_records=collect_log_lines(cam_id),
    )
    return {
        "markdown": assemble(**parts),
        "doc": build_document(**parts),
        "findings": findings,
    }
