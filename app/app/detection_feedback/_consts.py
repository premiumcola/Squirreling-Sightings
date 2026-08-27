"""Retention quotas and the evidence policy, in one place.

Two unrelated families of number live here, and they sit together on
purpose: a retention rule and an evidence bar that disagree produce a
corpus that *looks* sufficient and is not. That is exactly the defect
this package was rewritten to remove — the old compaction evicted
unjudged alerts while keeping every judged one, so the computed answer
rate rose every time the ledger rolled over and the "do we have enough
data?" check could never honestly say no.

The retention quotas below therefore have a companion: every alert an
automatic sweep evicts is counted into a ``census`` record, so the
denominator of the answer rate stays the number of alerts that ever
happened, not the number that happen to still be on disk.
"""

from __future__ import annotations

# ── record kinds ──────────────────────────────────────────────────────
#
# A kind NOT in this tuple is passed through compaction untouched. A
# future writer must be able to add a record type without a stale
# retention pass silently deleting it — the previous implementation
# recognised alert/verdict and destroyed everything else.
KIND_ALERT = "alert"
KIND_VERDICT = "verdict"
KIND_CENSUS = "census"

# ── size + retention quotas ───────────────────────────────────────────

# Roll the live file over at ~8 MB. At a few hundred bytes per record
# that is well over a hundred thousand events while staying small enough
# to read fully in one pass.
MAX_BYTES = 8 * 1024 * 1024

# Budget, in records, for the compacted archive. It is a budget over the
# EVICTABLE pool only: unjudged alerts. Judged alerts, their verdicts,
# verdicts with no alert and records of an unknown kind are all outside
# it and are never evicted (see ``_retention.select_retained``). So this
# is a soft ceiling that a heavily-judged corpus may exceed, and
# ``corpus_stats`` reports when it does rather than quietly deleting the
# overflow. ~12000 records at ~250 bytes is ~3 MB.
MAX_RETAINED_RECORDS = 12000

# Per (camera, label) ceiling on UNJUDGED alerts kept through a
# compaction — the quota that makes the corpus representative and not
# merely bounded. A driveway firing `person` all day cannot push a
# garden camera's four `squirrel` records out, because eviction is per
# stratum, not global.
MAX_UNJUDGED_PER_STRATUM = 300

# ── evidence policy ───────────────────────────────────────────────────
#
# One policy, here, so the report script, a future API and any
# calibration apply the same bar instead of three guesses. Every number
# below is deliberately conservative: being told "not yet" costs a week
# of waiting, acting on eight samples costs a threshold that is wrong in
# a direction nobody can see.

# THRESHOLD CALIBRATION — moving a per-(camera, label) score threshold.
#
# PER_CLASS: the observed extreme of n samples is an unstable statistic.
#   The chance the next false alert outscores every false alert seen so
#   far is ~1/(n+1) — still 5% at n=20. That is the loosest defensible
#   bar for "the highest false score I have seen" to mean anything.
# PER_STRATUM: a proportion estimated from n judgements carries a 95%
#   interval of roughly +/-1/sqrt(n): +/-20pp at n=25, +/-14pp at 50,
#   +/-10pp at 100. Below 50 a precision figure is decoration.
# ANSWER_RATE: verdicts are volunteered, not sampled. Judge a sliver of
#   a stratum and you judged the conspicuous ones, whose scores are not
#   the population's. 20% is not "unbiased" — it is the point below
#   which the bias is certainly larger than the effect being measured.
MIN_JUDGED_PER_CLASS = 20
MIN_JUDGED_PER_STRATUM = 50
MIN_ANSWER_RATE = 0.20

# PER-CAMERA LABEL VETO — "this camera never really sees `dog`".
#
# This is a claim about a proportion, and a veto that fires wrongly
# suppresses real alerts, so the bar is on the 95% LOWER bound of the
# wrong-rate rather than on the point estimate. At n=30 with 80% judged
# wrong the Wilson lower bound is ~0.63, so 0.60 is the level a
# genuinely-80%-wrong stratum clears at the minimum sample size. At
# n=10, 80% wrong has a lower bound of ~0.49 — a coin flip, and not a
# basis for suppressing anything, which is why the count bar exists as
# well as the rate bar.
# A veto that REDIRECTS ("call it a cat instead") needs the corrections
# to agree, not merely to exist; 15 agreeing corrections is the bar.
MIN_JUDGED_FOR_VETO = 30
MIN_VETO_WRONG_RATE_LOWER = 0.60
MIN_AGREEING_CORRECTIONS = 15

# NEAREST-CENTROID CLASSIFIER — over the crops CORP-2 will persist.
#
# A centroid's own sampling noise is sigma/sqrt(n) of the within-class
# spread: 32% at n=10, 22% at n=20, 16% at n=40. Below ~40 the centroid
# wobbles by an appreciable fraction of the distance it is supposed to
# measure, and for visually similar classes (cat vs. fox at night) that
# wobble is the whole decision. Leave-one-out accuracy on fewer than 30
# examples also carries a +/-18pp interval, so the validation cannot
# even detect that the classifier is bad.
# Two classes is the floor for a *nearest*-anything to mean a choice.
MIN_EXAMPLES_PER_CLASS = 40
MIN_CLASSES_FOR_CENTROID = 2
