"""THR-2 recommendations, rendered for ``corpus_report.py``.

Its own module because the report and the advice answer different
questions. The report says what the corpus CONTAINS; this says what
could be done about it — and, far more often, that nothing can be yet.
Keeping them apart also keeps ``corpus_report.py`` under the file
ceiling now that it has two jobs.

Read-only, like everything else in this folder: it prints a proposal and
never writes a setting.
"""

import json
from pathlib import Path


def _settings(root) -> dict:
    """``settings.json`` parsed, or {} when it is absent or unreadable.

    Deliberately a plain JSON read and NOT a ``SettingsStore``: the store
    saves during ``load()`` (defaults backfill, migrations, backup
    rotation), and an operator report has no business rewriting the one
    file in this project that carries the user's credentials. Read-only
    means read-only.

    Without a settings file the recommendations compare against the
    shipped defaults, which is the correct behaviour on a fresh checkout.
    """
    try:
        return json.loads(Path(root, "settings.json").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _push_cfg(data: dict) -> dict:
    """The saved ``telegram.push`` block."""
    return ((data.get("telegram") or {}).get("push")) or {}


def _cameras(data: dict) -> dict:
    """``camera_id -> {the two fields a recommendation may read}``.

    Narrowed on purpose. A camera dict also carries the RTSP URL with
    its password in it, and nothing downstream of here needs that, so it
    is not carried into a report that gets pasted into a chat.
    """
    out = {}
    for cam in data.get("cameras") or []:
        cam_id = cam.get("id")
        if cam_id:
            out[cam_id] = {
                "class_severity": cam.get("class_severity") or {},
                "push_thresholds": cam.get("push_thresholds") or {},
            }
    return out


def build(df, root, stats: dict) -> list:
    """One :class:`PushRecommendation` per stratum, in report order."""
    from app.thresholds import recommend_push

    data = _settings(root)
    push_cfg = _push_cfg(data)
    cams = _cameras(data)
    out = []
    for stratum in stats.get("strata") or []:
        cam_id, label = stratum.get("cam"), stratum.get("label")
        # The score lists cost a full ledger pass each, so only fetch
        # them where a number will actually be computed.
        pairs = df.judged_alerts(root, cam_id=cam_id, label=label) if stratum.get("ready") else None
        out.append(
            recommend_push(stratum, pairs, cam_cfg=cams.get(cam_id) or {}, push_cfg=push_cfg)
        )
    return out


def _one(rec) -> list:
    """The advice for a single stratum, as report lines."""
    if rec.recommended is None:
        return [
            "- **recommendation:** none — {}".format(rec.reason),
        ]
    arrow = {"lower": "LOWER", "raise": "RAISE", "hold": "HOLD"}.get(rec.verdict, rec.verdict)
    # `rec.reason` already carries the ladder-vs-live-gate warning when
    # there is one — it has to, because the API only ships the dataclass.
    # Repeating it as its own bullet here would print it twice.
    return [
        "- **recommendation: {} {:.2f} -> {:.2f}** (confidence: {})".format(
            arrow, rec.current, rec.recommended, rec.confidence
        ),
        "  - {}".format(rec.reason),
    ]


def block(recs: list) -> list:
    """The standalone recommendations section for the report."""
    proposed = [r for r in recs if r.recommended is not None]
    lines = [
        "## Recommended push thresholds — ADVISORY ONLY",
        "",
        "Nothing in this section is applied. It is a proposal for a human to accept or "
        "ignore, and there is no code path anywhere that acts on it. A recommender that "
        "could also write the setting would have to be right every time; one that only "
        "prints has to be merely useful.",
        "",
    ]
    if not recs:
        lines += ["_no (camera, label) stratum on record yet — nothing to advise on._", ""]
        return lines
    if not proposed:
        lines += [
            "**No stratum has enough judged alerts for a recommendation.** That is the "
            "expected state until the user has actually judged alerts in Telegram or the "
            "web archive; the per-stratum lines below say what each one is still short of.",
            "",
        ]
    else:
        lines += [
            "**{} of {} stratum/strata have a proposal.** Every one of them is a "
            "suggestion to type in by hand, not a change that happened.".format(
                len(proposed), len(recs)
            ),
            "",
        ]
    for rec in recs:
        lines.append("### `{}` · `{}`".format(rec.cam, rec.label))
        lines.append("")
        lines += _one(rec)
        lines.append("")
    lines += [
        "**Two rules the proposals obey**, whatever the data says:",
        "",
        "- A proposal never leaves the hard range. Below the detector floor a threshold is "
        "indistinguishable from off; above the ceiling it IS off, and switching a label off "
        "is the operator's decision, not a calibration's.",
        "- A label marked `alarm` in that camera's `class_severity` can only ever be "
        "proposed DOWNWARD. Adaptation may lower the bar on a security label and never "
        "raise it: a missed intruder costs more than a false alarm, so the error the data "
        "cannot see is the one to protect against.",
        "",
    ]
    return lines


def summary(recs: list) -> str:
    """The one-line stdout tail for the operator."""
    proposed = [r for r in recs if r.recommended is not None]
    if not proposed:
        return "[corpus] no threshold recommendation — not enough judged alerts."
    return "[corpus] {} advisory recommendation(s): {}".format(
        len(proposed),
        ", ".join(
            "{}/{} {:.2f}->{:.2f}".format(r.cam, r.label, r.current, r.recommended)
            for r in proposed
        ),
    )
