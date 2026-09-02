"""Profile revisions the simulation can be pointed at.

The Erkennungsnetz archive already holds every net the operator ever
had. Letting the simulation ask "what would THIS revision have made of
the picture?" is worth having, and it is worth exactly nothing if
asking can change the answer — so the property this file guards hardest
is not what a revision produces but what it must never touch:

  · the camera's stored settings, which only the archive's own restore
    endpoint is allowed to write;
  · the running camera's live config dict, which the simulation is
    handed by reference and must treat as read-only.

A revision that leaked into either would turn a diagnostic into a
silent reconfiguration of a live camera — the failure mode the whole
simulation panel exists to avoid.
"""

from __future__ import annotations

import pytest

from app import net_archive
from app.replay import (
    REVISION_CURRENT,
    REVISION_FACTORY,
    list_revisions,
    resolve_replay_settings,
    revision_overrides,
    simulation_cfg,
)

CAM = "cam_garten"
OTHER_CAM = "cam_hof"
EID = "20260830-120000-000001"

#: A camera mid-life: the operator has dragged two axes and the learner
#: has proposed a third. None of it may survive into a revision.
CURRENT = {
    "id": CAM,
    "name": "Garten",
    "rtsp_url": "rtsp://cam.lan/stream",
    "roi_mode": "2x2",
    "label_thresholds": {"person": 0.70, "cat": 0.60},
    "push_thresholds": {"person": 0.95},
    "net_pin": {"person": {"E": 80, "by": "manual"}},
    "net_adapted": {"cat": {"E": 62}},
    "zones": [{"id": "z1", "points": [[0, 0], [10, 0], [10, 10]]}],
}


def _capture(root, eid, *, cam_id=CAM, e=30, kind=None):
    net_archive.capture(
        root,
        event_id=eid,
        cam_id=cam_id,
        cam_name="Garten",
        kind=kind or net_archive.KIND_FRAGE,
        detection={"label": "person", "score": 0.62, "all": []},
        net_state={
            "person": {
                "E": e,
                "spawn": 0.30,
                "push": 0.70,
                "source": {"push": "camera"},
                "provenance": "manual",
                "evidence": {"judged": 3, "ready": False},
            }
        },
        rails={"push": [0.45, 0.98]},
        asked=True,
    )


@pytest.fixture
def root(tmp_path):
    return tmp_path


# ── the catalogue ─────────────────────────────────────────────────────────


def test_every_camera_offers_current_and_factory_even_with_no_archive(root):
    """A camera nobody has ever answered a question for still has two
    revisions worth simulating."""
    revs = list_revisions(root, CAM)

    assert [r["id"] for r in revs] == [REVISION_CURRENT, REVISION_FACTORY]
    assert revs[0]["label"] == "Aktuelles Profil"
    assert revs[1]["label"] == "Werkseinstellung"


def test_archived_revisions_carry_their_timestamp(root):
    _capture(root, EID)

    revs = list_revisions(root, CAM)

    archived = [r for r in revs if r["id"] == EID]
    assert len(archived) == 1, "the archived net is offered as a revision"
    assert archived[0]["ts"], "a revision without a timestamp cannot be chosen from a list"
    assert archived[0]["label"] == "person"


def test_another_cameras_archive_is_not_offered(root):
    _capture(root, EID, cam_id=OTHER_CAM)

    assert [r["id"] for r in list_revisions(root, CAM)] == [REVISION_CURRENT, REVISION_FACTORY]


def test_a_camera_wide_tuning_record_is_not_a_profile_revision(root):
    """A ``kamera_aenderung`` records ONE field's before/after and no net
    at all, so it cannot describe a whole revision. Offering it would
    put an entry in the picker that resolves to nothing."""
    net_archive.record_tuning_changes(
        root,
        cam_id=CAM,
        cam_name="Garten",
        changes=[{"field": "roi_mode", "before": "off", "after": "2x2"}],
    )

    assert [r["id"] for r in list_revisions(root, CAM)] == [REVISION_CURRENT, REVISION_FACTORY]


# ── the projection ────────────────────────────────────────────────────────


def test_a_revision_reproduces_the_archived_axes(root):
    _capture(root, EID, e=30)

    over = revision_overrides(root, CAM, EID, CURRENT)

    assert over["net_pin"]["person"]["E"] == 30, "the E on record, not the camera's current 80"
    # E = 30 is below the factory 50, so the spawn it resolves to must
    # sit below the camera's current 0.70 pin.
    assert over["label_thresholds"]["person"] < CURRENT["label_thresholds"]["person"]
    # An axis the revision does not name keeps the camera's value rather
    # than silently reverting to factory.
    assert over["label_thresholds"]["cat"] == CURRENT["label_thresholds"]["cat"]
    # The learner's CURRENT proposal must not blend into a picture of
    # the past.
    assert over["net_adapted"] == {}


def test_an_unknown_or_foreign_revision_resolves_to_nothing(root):
    _capture(root, EID, cam_id=OTHER_CAM)

    assert revision_overrides(root, CAM, "20260101-000000-000000", CURRENT) is None
    assert revision_overrides(root, CAM, EID, CURRENT) is None, "another camera's net"


def test_the_factory_revision_is_the_shipped_profile(root):
    cfg = resolve_replay_settings({}, CURRENT, REVISION_FACTORY)

    assert cfg["source"] == "factory"
    assert cfg["cfg"]["label_thresholds"]["person"] == 0.45, "the shipped default"
    assert "rtsp_url" not in cfg["cfg"], "projection still drops non-tuning keys"


def test_a_revision_rides_the_replays_own_settings_vocabulary(root):
    """Not a second mechanism: a revision is one more spec the SAME
    resolver understands, and it returns the same descriptor shape."""
    _capture(root, EID, e=30)

    got = resolve_replay_settings(
        {},
        CURRENT,
        {"revision": EID},
        revisions=lambda rid: revision_overrides(root, CAM, rid, CURRENT),
    )

    assert got["source"] == "revision"
    assert got["revision"] == EID
    assert set(got) >= {"cfg", "source", "basis", "hash", "note", "overridden"}
    assert got["hash"] != resolve_replay_settings({}, CURRENT, "current")["hash"]


def test_an_unresolvable_revision_refuses_rather_than_falling_back(root):
    """Silently running the current profile under a chip that says
    'Werkseinstellung' is worse than an error."""
    with pytest.raises(ValueError, match="Profil-Stand"):
        resolve_replay_settings({}, CURRENT, {"revision": "nope"}, revisions=lambda _rid: None)


# ── the safety property ───────────────────────────────────────────────────


def test_simulating_a_revision_never_touches_the_cameras_stored_settings(root):
    """THE assertion this feature is allowed to ship on.

    ``simulation_cfg`` is the only path from a chosen revision to a
    running tick, and it must be a pure function of its inputs: the
    camera dict it is handed is the LIVE runtime's config, shared by
    reference with the alarm loop.
    """
    _capture(root, EID, e=30)
    before = {
        "label_thresholds": dict(CURRENT["label_thresholds"]),
        "push_thresholds": dict(CURRENT["push_thresholds"]),
        "net_pin": dict(CURRENT["net_pin"]),
        "net_adapted": dict(CURRENT["net_adapted"]),
    }

    cfg, descriptor = simulation_cfg(root, CAM, CURRENT, EID)

    # The tick runs on the revision …
    assert cfg["net_pin"]["person"]["E"] == 30
    assert descriptor["source"] == "revision"
    # … and the camera's own dict is byte-for-byte what it was.
    for key, value in before.items():
        assert CURRENT[key] == value, f"{key} was mutated by a SIMULATION"
    assert CURRENT["net_pin"]["person"]["E"] == 80, "the operator's pin survives untouched"
    assert cfg is not CURRENT, "a revision tick must not alias the live config"


def test_a_revision_keeps_the_cameras_identity_and_geometry(root):
    """A revision changes tuning, not which camera this is. Dropping the
    zones would make the simulation gate on nothing and look like a
    revision that detects everything."""
    _capture(root, EID, e=30)

    cfg, _ = simulation_cfg(root, CAM, CURRENT, EID)

    assert cfg["id"] == CAM
    assert cfg["zones"] == CURRENT["zones"]
    assert cfg["roi_mode"] == "2x2"


def test_the_live_profile_is_passed_through_untouched(root):
    """The live view's case. No revision means no projection at all —
    the live view must always reflect the real running profile, not a
    round-trip through the whitelist that could drop a key."""
    for spec in (None, "", REVISION_CURRENT):
        cfg, descriptor = simulation_cfg(root, CAM, CURRENT, spec)
        assert cfg is CURRENT, "the live profile is the runtime's own dict"
        assert descriptor is None, "and reports no revision"
