"""The pre-provenance replay basis, and the promise its own note makes.

`recording_settings` is the snapshot events carried before the full
provenance block existed. It recovers six of the twenty-six tuning keys
(`_LEGACY_KEY_MAP`), and the descriptor tells the operator so:

    "…nachsimuliert mit den überlieferten Aufnahme-Settings (Schwellen
     und Objektfilter); die übrigen Regler stammen aus dem aktuellen
     Profil."

The other two arms that lay a partial set over a base — the override
dict and the archived revision — both do `cfg = project_settings(
current_cfg); cfg.update(projected)`. This arm handed `_from_legacy`
straight through, so the nineteen knobs it cannot recover fell back to
library defaults instead of the camera's profile, and a replay of an old
clip ran with a tracker the operator had never configured.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.replay._settings import _LEGACY_KEY_MAP, resolve_replay_settings  # noqa: E402

# A camera whose profile differs from the shipped defaults on knobs the
# legacy snapshot has no name for.
CURRENT = {
    "track_miss_grace_seconds": 4.0,
    "track_spawn_min_score": 0.62,
    "roi_mode": "hybrid",
    "wildlife_min_score": 0.55,
    "detection_min_score": 0.44,
    "object_filter": ["person", "cat"],
}

LEGACY_EVENT = {
    "recording_settings": {
        "conf_thresh_general": 0.30,
        "object_filter": ["bird"],
    }
}


def _resolve(event, current=None):
    return resolve_replay_settings(event, CURRENT if current is None else current, "stored")


def test_the_legacy_arm_keeps_the_cameras_other_knobs():
    """The note's promise, checked against the cfg it hands out."""
    got = _resolve(LEGACY_EVENT)["cfg"]

    assert got["track_miss_grace_seconds"] == 4.0
    assert got["track_spawn_min_score"] == 0.62
    assert got["roi_mode"] == "hybrid"
    assert got["wildlife_min_score"] == 0.55


def test_the_recovered_keys_still_win_over_the_current_profile():
    """The half that DID survive the round trip is the whole reason to
    replay off a legacy snapshot — it must not be overwritten by the
    profile it is laid onto."""
    got = _resolve(LEGACY_EVENT)["cfg"]

    assert got["detection_min_score"] == 0.30
    assert got["object_filter"] == ["bird"]


def test_the_arm_is_still_named_after_its_basis():
    desc = _resolve(LEGACY_EVENT)

    assert desc["source"] == "stored"
    assert desc["basis"] == "recording_settings"
    assert "aktuellen Profil" in (desc["note"] or "")


def test_the_recovered_keys_are_reported_as_the_overridden_ones():
    """`overridden` is what the UI marks as coming from the snapshot
    rather than from the profile — the same contract the override and
    revision arms already honour."""
    desc = _resolve(LEGACY_EVENT)

    assert desc["overridden"] == ["detection_min_score", "object_filter"]
    assert set(desc["overridden"]) <= set(_LEGACY_KEY_MAP.values())


def test_an_empty_current_profile_still_replays_off_the_snapshot():
    """A camera with nothing configured must not regress into an error."""
    got = resolve_replay_settings(LEGACY_EVENT, {}, "stored")["cfg"]

    assert got["detection_min_score"] == 0.30
    assert got["object_filter"] == ["bird"]


def test_a_full_provenance_snapshot_is_still_used_verbatim():
    """The stored-provenance arm is a COMPLETE set and must keep being
    replayed as-is — this fix is for the partial basis only."""
    event = {"provenance": {"tuning": {"detection_min_score": 0.7}}}
    got = resolve_replay_settings(event, CURRENT, "stored")["cfg"]

    assert got["detection_min_score"] == 0.7
    assert "track_miss_grace_seconds" not in got
