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

from ._blocks import assemble
from ._findings import build_findings, ladder_rows
from ._helpers import collect_log_lines

__all__ = ["build_snapshot", "build_findings", "collect_log_lines", "ladder_rows"]


def _relevant_labels(cam: dict, last: dict) -> list:
    """Classes worth showing a ladder for: the filter plus whatever the
    last tick actually saw. Sorted so two snapshots diff cleanly."""
    labels = set(cam.get("object_filter") or [])
    for det in last.get("detections") or []:
        if det.get("label"):
            labels.add(det["label"])
    return sorted(labels)


def build_snapshot(cam: dict, cam_id: str, tt: dict, runtime, eff_cfg: dict) -> dict:
    """Return ``{"markdown": str, "findings": [...]}`` for one camera.

    Pure apart from the log ring-buffer read — every other input is
    passed in, so the whole document is unit-testable.
    """
    last = tt.get("last_tick") or {}
    cluster_ev = last.get("cluster_evidence") or {}
    diag = last.get("diag") or {}
    push_cfg = ((eff_cfg or {}).get("telegram") or {}).get("push") or {}
    ladder = ladder_rows(cam, push_cfg, _relevant_labels(cam, last))
    findings = build_findings(cam, last, cluster_ev, ladder)
    markdown = assemble(
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
    return {"markdown": markdown, "findings": findings}
