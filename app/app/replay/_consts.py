"""Literals for the clip-replay feature. No logic, no sibling imports.

The replay re-runs a STORED clip through the post-clip detection
machinery with a chosen settings set, so an operator can ask "what
would this camera have seen if I had tuned it differently?" without
waiting for the animal to come back.
"""

from __future__ import annotations

# Shape of one entry in the event's ``replays`` list. Bump when the
# entry gains or loses a key; the UI reads the newest entry only, so a
# mixed-schema history is harmless.
REPLAY_SCHEMA = 2

# How many replay runs are kept under an event. Append-only, oldest
# dropped first. Five is enough to eyeball a small sweep (stored +
# current + three candidate tunings) without bloating the event JSON,
# which is read on every Mediathek card render.
REPLAY_HISTORY_CAP = 5

# Hard ceiling on sampled frames for ONE replay. The request thread
# runs this synchronously, so the work must be bounded by something
# the clip length cannot outgrow. At the standard ~1 Hz cadence 240
# samples is a four-minute clip; longer clips are truncated and the
# response says so (``frames_analysed`` vs ``frames_available``).
REPLAY_MAX_SAMPLES = 240

# Hard ceiling on SECOND-STAGE CLASSIFIER invocations for one replay.
# A separate budget from REPLAY_MAX_SAMPLES because the two costs are
# not the same shape: the detector runs once per sampled frame, while
# the classifier runs once per bird box within a frame, so a flock puts
# ten crops on one sample. Capping only frames would leave the
# expensive half unbounded. 480 is two bird boxes per frame across a
# full-length replay; past that the species list is already a settled
# answer and the run reports `classify_truncated` rather than spending
# more (see _species.py::SpeciesTally).
REPLAY_MAX_CROPS = 480

# Two detections are considered "the same object seen twice" when
# their boxes overlap at least this much. Deliberately loose: a
# threshold change moves a box slightly, and we would rather report
# "confidence changed" than a simultaneous appear + disappear.
MATCH_IOU_THRESHOLD = 0.3

# Confidence moves smaller than this are reported as unchanged. Below
# a couple of percent the difference is model noise, not a tuning
# effect, and a diff that flags every sample is a diff nobody reads.
SCORE_EPSILON = 0.05
