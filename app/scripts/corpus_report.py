"""Operator report on the alert/verdict corpus. READ-ONLY.

The ledger (``storage/_diag/detection_feedback.jsonl``) has been writing
alerts and verdicts since C4 and nothing has ever read it back. This is
the read side: per camera and label, how many alerts fired, how many a
human judged, how the confirmed-true and confirmed-false scores are
distributed — and, the part that matters most, whether that is ENOUGH to
do anything with yet.

It is built to be able to say **no**. A tool that always prints a number
invites acting on eight samples, so the sample-size policy lives in
``app.detection_feedback._consts`` (MIN_* with the reasoning attached)
and this report, a future API and any calibration all apply the same bar.

Three downstream uses, three different bars, reported separately because
they are three different statistical questions — see "What has enough
data" below.

Writes ``storage/_diag/corpus_report_<ts>.md``. Touches nothing else — no
settings, no events, no network, and it never compacts the ledger.

From the repo checkout:
    python3 app/scripts/corpus_report.py
Inside the container (where the real ledger lives):
    docker exec -w /app -e PYTHONPATH=/app squirreling-sightings \\
        python3 -m scripts.corpus_report
"""

from __future__ import annotations

import time
from pathlib import Path

try:  # package invocation: python3 -m scripts.corpus_report
    from ._common import add_app_to_path, storage_root
except ImportError:  # direct path: python3 app/scripts/corpus_report.py
    from _common import add_app_to_path, storage_root

_DAY = 86400.0


def _ledger():
    """Import the ledger package — sys.path has to be fixed up first."""
    add_app_to_path()
    from app import detection_feedback

    return detection_feedback


def _policy(df) -> dict:
    return {
        "per_class": df.MIN_JUDGED_PER_CLASS,
        "per_stratum": df.MIN_JUDGED_PER_STRATUM,
        "answer_rate": df.MIN_ANSWER_RATE,
        "veto_judged": df.MIN_JUDGED_FOR_VETO,
        "veto_lower": df.MIN_VETO_WRONG_RATE_LOWER,
        "veto_corrections": df.MIN_AGREEING_CORRECTIONS,
        "centroid_per_class": df.MIN_EXAMPLES_PER_CLASS,
        "centroid_classes": df.MIN_CLASSES_FOR_CENTROID,
    }


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.2f} MB"


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _span(df, root):
    """Oldest and newest record timestamp, or (0, 0) on an empty ledger."""
    stamps = [r.get("ts") or 0.0 for r in df.iter_records(root)]
    return (min(stamps), max(stamps)) if stamps else (0.0, 0.0)


def _pace_line(stats: dict, policy: dict, span) -> str:
    """How fast the corpus is actually filling — the basis for "come back"."""
    first, last = span
    days = max((last - first) / _DAY, 0.0)
    if days < 1.0 or not stats["n_judged"]:
        return "- pace: too short a history to estimate one yet."
    per_day = stats["n_judged"] / days
    line = "- pace: **{:.1f} judged/day** over {:.0f} day(s) ({} judgement(s) total).".format(
        per_day, days, stats["n_judged"]
    )
    needs = [max(policy["per_stratum"] - s["n_total"], 0) for s in stats["strata"]]
    needs = [n for n in needs if n]
    if needs:
        line += (
            f" The closest stratum needs **{min(needs)}** more, so roughly **{min(needs) / per_day:.0f} day(s)** away — "
            "optimistic, because every one of those judgements has to land in that one "
            "stratum."
        )
    return line


def _verdict_block(stats: dict, policy: dict, span) -> list:
    ready = [s for s in stats["strata"] if s["ready"]]
    lines = ["## Verdict", ""]
    if not stats["strata"]:
        lines += ["**EMPTY CORPUS.** No alert has been recorded yet — nothing to report.", ""]
        return lines
    if not ready:
        lines += [
            "**NOT ENOUGH DATA — no threshold should be moved on this corpus yet.**",
            "",
            "None of the {} (camera, label) stratum/strata clears the bar of {} judged "
            "alerts with at least {} of each verdict and an answer rate of {}. Come back "
            "once the counts below have grown; the per-stratum blockers say exactly what "
            "is missing.".format(
                len(stats["strata"]),
                policy["per_stratum"],
                policy["per_class"],
                _pct(policy["answer_rate"]),
            ),
        ]
    else:
        lines += [
            "**{} of {} strata have enough data to calibrate a threshold.**".format(
                len(ready), len(stats["strata"])
            ),
            "",
            "Ready: " + ", ".join("`{}`/`{}`".format(s["cam"], s["label"]) for s in ready) + ".",
            "Everything else below is still under the bar and must not be acted on.",
        ]
    lines += [
        "",
        "- {} alert(s) ever recorded, {} judged ({} answer rate).".format(
            stats["n_alerts"], stats["n_judged"], _pct(stats["answer_rate"])
        ),
        _pace_line(stats, policy, span),
        "",
    ]
    return lines


def _thresholds_block(policy: dict) -> list:
    """The bars, stated up front so no number below can be read out of context."""
    return [
        "## What has enough data — the three bars",
        "",
        "| Downstream use | Needs | Why that number |",
        "|---|---|---|",
        "| Threshold calibration (per camera+label) | **{n} judged** alerts, **{c} "
        "confirmed-true** and **{c} confirmed-false**, answer rate **{r}** | a proportion "
        "from n judgements has a 95% interval of ~+/-1/sqrt(n): +/-20pp at 25, +/-14pp at "
        "50. The chance the next false alert outscores every false alert seen so far is "
        "~1/(n+1), still 5% at n=20. |".format(
            n=policy["per_stratum"], c=policy["per_class"], r=_pct(policy["answer_rate"])
        ),
        "| Per-camera label veto | **{n} judged** and a wrong-rate whose 95% **lower** "
        "bound clears **{r}**; a redirect additionally needs **{k} agreeing corrections** "
        "| a wrong veto silences real alerts, so the point estimate is not enough. At "
        "n=30 with 80% wrong the Wilson lower bound is ~63%; at n=10 it is ~49%, a coin "
        "flip. |".format(
            n=policy["veto_judged"], r=_pct(policy["veto_lower"]), k=policy["veto_corrections"]
        ),
        "| Nearest-centroid classifier | **{n} confirmed examples per class**, at least "
        "**{k} classes** | a centroid's own sampling noise is sigma/sqrt(n) of the "
        "within-class spread: 32% at n=10, 16% at n=40. Below ~40 the centroid wobbles by "
        "an appreciable fraction of the distance it is meant to measure. |".format(
            n=policy["centroid_per_class"], k=policy["centroid_classes"]
        ),
        "",
        "Conservative on purpose. Being told \"not yet\" costs a week of waiting; acting "
        "on eight samples costs a threshold that is wrong in a direction nobody can see.",
        "",
    ]


def _centroid_block(centroid: dict, policy: dict) -> list:
    lines = [
        "### Nearest-centroid classifier — {}".format("READY" if centroid["ready"] else "NOT YET"),
        "",
        "Confirmed examples per class (a confirmed-true alert counts for its own label, a "
        "correction counts for the label it was corrected TO), across all cameras:",
        "",
    ]
    counts = centroid["examples"]
    if not counts:
        lines.append("- _none yet_")
    for label, n in list(counts.items())[:10]:
        mark = "OK" if n >= policy["centroid_per_class"] else "short"
        lines.append("- `{}`: {} ({}/{})".format(label, mark, n, policy["centroid_per_class"]))
    for blocker in centroid["blockers"]:
        lines.append("- **blocker:** " + blocker)
    lines += [
        "",
        "Hard caveat regardless of the counts: **the ledger holds no pixels.** A centroid "
        "is computed over crops, and crop persistence is CORP-2, which is not built. These "
        "counts say the LABELS would suffice; they do not say the classifier can be "
        "trained today.",
        "",
    ]
    return lines


def _health_block(stats: dict) -> list:
    health = stats["health"]
    lines = [
        "## Ledger health and what retention guarantees",
        "",
        "- live `detection_feedback.jsonl`: **{}** of {} ({} full)".format(
            _mb(health["live_bytes"]), _mb(health["rotate_at_bytes"]), _pct(health["live_fill"])
        ),
        "- compacted archive `.1`: **{}** ({})".format(
            _mb(health["archive_bytes"]),
            "written" if health["compacted"] else "not created yet",
        ),
        "- total on disk: **{}**".format(_mb(health["total_bytes"])),
        "- {} alert(s) retained, {} evicted by a past compaction and counted in the "
        "census.".format(stats["n_alerts_retained"], stats["n_alerts_evicted"]),
        "",
        "**The retention invariant:** an automatic sweep may delete only an *unjudged "
        "alert*, and it evicts per (camera, label) so a busy camera cannot push a rare "
        "class out. Judged alerts, their verdicts, verdicts with no alert record and "
        "records of a kind this version does not recognise are never deleted by the sweep. "
        "Every eviction is counted, which is why the answer rate above is against alerts "
        "that ever happened rather than alerts still on disk.",
        "",
        "- {} record(s) are protected from eviction; the soft budget is {}.{}".format(
            stats["protected_records"],
            health["max_retained_records"],
            "  **The corpus is over budget — it is growing rather than losing "
            "judgements. That is deliberate; watch the size above.**"
            if stats["over_record_budget"]
            else "",
        ),
    ]
    if stats["orphan_verdicts"]:
        lines.append(
            "- {} verdict(s) have no alert record. Expected, not a bug: `record_alert` "
            "sits below the mute and push-flag gates, so a muted camera or a label with "
            "`push: false` produces none — and the web surfaces judge those events "
            "anyway. They are kept (their `corrected_label` feeds a label veto) but they "
            "carry no score and cannot join a threshold calibration.".format(
                stats["orphan_verdicts"]
            )
        )
    if stats["unknown_kind_records"]:
        lines.append(
            "- {} record(s) of a kind this version does not know, carried through "
            "compaction untouched.".format(stats["unknown_kind_records"])
        )
    if stats["unjoinable_records"]:
        lines.append(
            "- {} record(s) carry no `event_id` and can never be joined; they are "
            "dropped at compaction.".format(stats["unjoinable_records"])
        )
    return lines + [""]


def _stratum_block(s: dict, policy: dict) -> list:
    scores = "- scores: no judged alerts yet"
    if s["n_total"]:
        scores = (
            "- scores: confirmed-true min `{}` / med `{}` · confirmed-false max `{}` / "
            "med `{}`".format(s["true_min"], s["true_median"], s["false_max"], s["false_median"])
        )
    lines = [
        "### `{}` · `{}` — {}".format(s["cam"], s["label"], "READY" if s["ready"] else "NOT YET"),
        "",
        "- alerts **{}** ({} retained, {} evicted) · judged **{}** ({}) · true {} / "
        "false {}".format(
            s["n_alerts"],
            s["n_alerts_retained"],
            s["n_alerts_evicted"],
            s["n_total"],
            _pct(s["answer_rate"]),
            s["n_true"],
            s["n_false"],
        ),
        scores,
        "- below its own threshold: {} alert(s), {} judged".format(
            s["n_below"], s["n_judged_below"]
        ),
    ]
    if s["n_true"] and s["n_false"] and s["false_max"] >= s["true_min"]:
        lines.append(
            "- the classes **overlap** in this sample: confirmed-false reaches `{}`, "
            "confirmed-true starts at `{}` — no threshold separates what has been seen "
            "so far".format(s["false_max"], s["true_min"])
        )
    if s["corrections"]:
        lines.append("- corrections: " + ", ".join(f"`{lab}` x{n}" for lab, n in s["corrections"]))
    lines += _stratum_gates(s, policy)
    return lines + [""]


def _stratum_gates(s: dict, policy: dict) -> list:
    """The three per-stratum verdicts, each with what is missing."""
    lines = []
    if s["blockers"]:
        lines.append("- **threshold calibration blocked:** " + " · ".join(s["blockers"]))
        need = max(policy["per_stratum"] - s["n_total"], 0)
        if need:
            lines.append(f"- needs **{need}** more judged alert(s) before any number here counts")
    if not s["can_lower"]:
        lines.append(
            "- cannot justify LOWERING the threshold: only {} judged sub-threshold "
            "candidate(s), {} needed".format(s["n_judged_below"], policy["per_class"])
        )
    veto = s["veto"]
    if veto["ready"]:
        lines.append(
            "- **label veto available:** {} of judgements call this wrong (95% lower "
            "bound {}){}".format(
                _pct(veto["wrong_rate"]),
                _pct(veto["wrong_rate_lower"]),
                ", redirect to `{}`".format(veto["redirect_to"]) if veto["redirect_to"] else "",
            )
        )
    else:
        lines.append("- label veto blocked: " + " · ".join(veto["blockers"]))
    return lines


def _caveats_block(policy: dict) -> list:
    return [
        "## What this corpus cannot tell you",
        "",
        "- **Verdicts are volunteered, not sampled.** People judge what looks wrong. Below "
        "an answer rate of {} the judged alerts are the conspicuous ones and their scores "
        "are not the population's.".format(_pct(policy["answer_rate"])),
        "- **Muted cameras and push-disabled labels produce no alert record.** The alert "
        "is written above the threshold gate but below the mute and push-flag gates, so "
        "those events never enter the score side of the corpus at all — only their "
        "verdicts do, if someone judges them in the web UI.",
        "- **Raising a threshold and lowering one need different evidence.** A blocked "
        "alert is rarely judged, so the sub-threshold side fills far more slowly; "
        "`can_lower` is reported separately for exactly that reason.",
        "- **A bulk delete is a weak verdict.** `web_delete` books \"false alarm\" for "
        "every event in the selection; a bulk sweep of an old day is not the same evidence "
        "as a deliberate tap on one picture. The `source` field is in the ledger for a "
        "future weighting; this report does not weight it.",
        "- This report recommends nothing and changes nothing. It reports what is there.",
        "",
    ]


def _render(df, stats: dict, policy: dict, span, ts: str) -> str:
    lines = [
        "# Detection corpus report",
        "",
        f"Generated {ts} · source `{df.ledger_path(storage_root())}` · read-only.",
        "",
    ]
    lines += _verdict_block(stats, policy, span)
    lines += _thresholds_block(policy)
    lines += _centroid_block(stats["centroid"], policy)
    lines += _health_block(stats)
    lines += ["## Per camera and label", ""]
    if not stats["strata"]:
        lines += ["_nothing recorded yet_", ""]
    for s in stats["strata"]:
        lines += _stratum_block(s, policy)
    lines += _caveats_block(policy)
    return "\n".join(lines) + "\n"


def main():
    df = _ledger()
    root = storage_root()
    stats = df.corpus_stats(root)
    policy = _policy(df)
    ts = time.strftime("%Y%m%d_%H%M%S")

    diag = Path(root) / "_diag"
    diag.mkdir(parents=True, exist_ok=True)
    out_path = diag / f"corpus_report_{ts}.md"
    out_path.write_text(_render(df, stats, policy, _span(df, root), ts), encoding="utf-8")

    ready = sum(1 for s in stats["strata"] if s["ready"])
    print(f"[corpus] {out_path}")
    print(
        "[corpus] {} alert(s), {} judged, {} stratum/strata, {} ready to calibrate.".format(
            stats["n_alerts"], stats["n_judged"], len(stats["strata"]), ready
        )
    )
    if not ready:
        print("[corpus] NOT ENOUGH DATA — no threshold should be moved on this corpus yet.")
    return out_path


if __name__ == "__main__":
    main()
