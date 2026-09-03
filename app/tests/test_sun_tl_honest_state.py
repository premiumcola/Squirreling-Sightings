"""The sun timelapse must be able to say whether it is actually running.

Before this, it could not. ``_register_sun_jobs`` walks away silently on
three separate conditions — no location, phase not enabled, window start
already passed — and the only thing the UI showed was a preview line
computed from the location alone. That line reads identically whether a
job was registered or never created, which is exactly why "it doesn't
feel like the sun timelapses are running" had no answer.

What is pinned here is where the answer comes from, not just its shape:

* a skip reason is the branch the scheduler actually took, recorded at
  that branch — never re-derived afterwards from the same inputs;
* "registered" is checked against the scheduler's live job list, so a
  record whose job is gone stops claiming to be scheduled;
* "running" comes only from the in-flight registry the capture thread
  writes, never from comparing the clock to a window.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.weather_service._sun_tl import SunTimelapseMixin
from app.weather_service._tl_activity import (
    SKIP_DISABLED,
    SKIP_NO_LOCATION,
    SKIP_NO_SUN_EVENT,
    SKIP_WINDOW_PASSED,
    STATE_FINISHED,
    STATE_RUNNING,
    STATE_SCHEDULED,
    STATE_SKIPPED,
    STATE_UNKNOWN,
    SUN_CAPTURE_PREFIX,
    TimelapseActivityMixin,
    resolve_sun_state,
    sun_capture_job_id,
)


# ── Pure helpers ───────────────────────────────────────────────────────────
def test_the_job_id_carries_the_prefix_the_scheduler_scans_for():
    """`_sun_jobs_keys` finds capture jobs by prefix. If the builder and
    the scanner disagree the report silently reads an empty job list and
    calls every registered phase finished."""
    jid = sun_capture_job_id("cam1", "sunset", date(2026, 9, 3))
    assert jid.startswith(SUN_CAPTURE_PREFIX)
    assert jid == "sun_tl_capture_cam1_sunset_2026-09-03"


def test_a_live_capture_outranks_every_other_signal():
    now = datetime(2026, 9, 3, 20, 0)
    dec = {"skip": SKIP_DISABLED}
    state, reason = resolve_sun_state(dec, set(), {"started_at": now}, now)
    assert (state, reason) == (STATE_RUNNING, None)


def test_no_recorded_decision_admits_to_not_knowing():
    """Before the first registration sweep nothing is known. Reporting
    'skipped' there would be an invention."""
    now = datetime(2026, 9, 3, 20, 0)
    assert resolve_sun_state(None, set(), None, now) == (STATE_UNKNOWN, None)


def test_a_recorded_skip_is_reported_with_its_reason():
    now = datetime(2026, 9, 3, 20, 0)
    for reason in (SKIP_NO_LOCATION, SKIP_DISABLED, SKIP_NO_SUN_EVENT, SKIP_WINDOW_PASSED):
        out = resolve_sun_state({"skip": reason}, set(), None, now)
        assert out == (STATE_SKIPPED, reason)


def test_scheduled_requires_the_job_to_still_exist():
    now = datetime(2026, 9, 3, 20, 0)
    dec = {"job_id": "j1", "window_end_dt": now + timedelta(minutes=30)}
    assert resolve_sun_state(dec, {"j1"}, None, now)[0] == STATE_SCHEDULED
    # Same record, job gone, window still ahead: a DateTrigger cannot
    # have fired yet, so something removed it — do not claim success.
    assert resolve_sun_state(dec, set(), None, now)[0] == STATE_UNKNOWN


def test_a_closed_window_with_no_job_left_reads_as_finished():
    now = datetime(2026, 9, 3, 20, 0)
    dec = {"job_id": "j1", "window_end_dt": now - timedelta(minutes=1)}
    assert resolve_sun_state(dec, set(), None, now)[0] == STATE_FINISHED


# ── Registration sweep + report ────────────────────────────────────────────
class _Job:
    def __init__(self, jid):
        self.id = jid


class _Scheduler:
    """Minimal APScheduler stand-in — add/remove/list by id."""

    def __init__(self):
        self.jobs: dict[str, object] = {}

    def add_job(self, func, trigger, id=None, replace_existing=False, args=None):
        self.jobs[id] = args

    def remove_job(self, jid):
        self.jobs.pop(jid)

    def get_jobs(self):
        return [_Job(j) for j in self.jobs]


class _Svc(SunTimelapseMixin, TimelapseActivityMixin):
    """Just enough WeatherService for the registration sweep."""

    def __init__(self, cams, *, located=True, sun_at=None):
        self.server_cfg = {"location": {"lat": 49.45, "lon": 11.08} if located else {}}
        if not located:
            self.server_cfg = {"location": {"lat": None, "lon": None}}
        self._cams = cams
        self._scheduler = _Scheduler()
        self._sun_at = sun_at

    def _cfg_cameras(self):
        return self._cams

    def _cam_name(self, cam_id):
        return next((c["name"] for c in self._cams if c["id"] == cam_id), cam_id)

    def sun_event_today(self, phase, when=None):
        return self._sun_at

    def _run_sun_capture_safe(self, *a):  # never called in these tests
        raise AssertionError("capture must not run during registration")

    def _apply_daynight_override(self, *a):
        raise AssertionError("daynight override must not run during registration")


def _cam(cam_id="cam1", name="Garten", *, sunrise=True, sunset=False):
    return {
        "id": cam_id,
        "name": name,
        "weather": {
            "enabled": True,
            "sun_timelapse": {
                "sunrise": {"enabled": sunrise},
                "sunset": {"enabled": sunset},
            },
        },
    }


def _row(report, cam_id, phase):
    return next(r for r in report["sun"] if r["camera_id"] == cam_id and r["phase"] == phase)


def _future_sun():
    """A sun event whose 75-min window has not opened yet (52 min pre-bias)."""
    return datetime.now() + timedelta(hours=3)


def _past_sun():
    return datetime.now() - timedelta(hours=3)


def test_a_registered_phase_reports_scheduled_with_its_window():
    svc = _Svc([_cam()], sun_at=_future_sun())
    svc._register_sun_jobs()
    row = _row(svc.timelapse_activity(), "cam1", "sunrise")
    assert row["state"] == STATE_SCHEDULED
    assert row["job_registered"] is True
    assert row["job_id"] in svc._sun_jobs_keys()
    assert row["window_start"] and row["window_end"] and row["sun_event"]
    assert row["starts_in_s"] > 0
    assert row["skip_reason"] is None


def test_a_phase_that_is_off_says_so_instead_of_showing_a_window():
    """The old preview drew a window for a disabled phase just as
    confidently as for an enabled one."""
    svc = _Svc([_cam(sunrise=False)], sun_at=_future_sun())
    svc._register_sun_jobs()
    row = _row(svc.timelapse_activity(), "cam1", "sunrise")
    assert (row["state"], row["skip_reason"]) == (STATE_SKIPPED, SKIP_DISABLED)
    assert row["skip_text"] == "nicht aktiviert"
    assert row["job_registered"] is False


def test_a_window_that_already_passed_is_named_as_such():
    svc = _Svc([_cam()], sun_at=_past_sun())
    svc._register_sun_jobs()
    row = _row(svc.timelapse_activity(), "cam1", "sunrise")
    assert (row["state"], row["skip_reason"]) == (STATE_SKIPPED, SKIP_WINDOW_PASSED)
    # The window is still reported — the operator wants to see WHICH
    # window was missed, not just that one was.
    assert row["window_start"] and row["window_end"]
    assert svc._sun_jobs_keys() == []


def test_a_missing_location_is_reported_per_camera_not_just_logged():
    svc = _Svc([_cam(), _cam("cam2", "Hof")], located=False, sun_at=_future_sun())
    svc._register_sun_jobs()
    rows = svc.timelapse_activity()["sun"]
    assert len(rows) == 4
    assert {r["skip_reason"] for r in rows} == {SKIP_NO_LOCATION}
    assert {r["skip_text"] for r in rows} == {"Standort fehlt"}


def test_no_sun_event_today_is_distinct_from_being_switched_off():
    """Polar day/night and 'the operator disabled it' produced the same
    silence before."""
    svc = _Svc([_cam()], sun_at=None)
    svc._register_sun_jobs()
    row = _row(svc.timelapse_activity(), "cam1", "sunrise")
    assert (row["state"], row["skip_reason"]) == (STATE_SKIPPED, SKIP_NO_SUN_EVENT)


def test_two_cameras_with_identical_previews_get_different_verdicts():
    """The load-bearing case. Both cameras sit at the same location with
    the same sun event, so the settings preview line is character-for-
    character identical — yet only one of them has a job."""
    svc = _Svc([_cam("cam1", "Garten"), _cam("cam2", "Hof", sunrise=False)], sun_at=_future_sun())
    svc._register_sun_jobs()
    rep = svc.timelapse_activity()
    assert _row(rep, "cam1", "sunrise")["state"] == STATE_SCHEDULED
    assert _row(rep, "cam2", "sunrise")["state"] == STATE_SKIPPED


def test_running_comes_from_the_capture_registry_not_from_the_clock():
    svc = _Svc([_cam()], sun_at=_future_sun())
    svc._register_sun_jobs()
    assert svc.timelapse_activity()["running_count"] == 0
    svc.sun_capture_started("cam1", "sunrise", datetime.now() + timedelta(minutes=75))
    rep = svc.timelapse_activity()
    row = _row(rep, "cam1", "sunrise")
    assert row["state"] == STATE_RUNNING
    assert 0 < row["remaining_s"] <= 75 * 60
    assert rep["running_count"] == 1
    svc.sun_capture_finished("cam1", "sunrise")
    assert svc.timelapse_activity()["running_count"] == 0


def test_a_re_sweep_drops_yesterdays_verdict():
    """Without the reset a camera switched off would keep reporting the
    job it had this morning."""
    svc = _Svc([_cam()], sun_at=_future_sun())
    svc._register_sun_jobs()
    assert _row(svc.timelapse_activity(), "cam1", "sunrise")["state"] == STATE_SCHEDULED
    svc._cams[0]["weather"]["sun_timelapse"]["sunrise"]["enabled"] = False
    svc._register_sun_jobs()
    row = _row(svc.timelapse_activity(), "cam1", "sunrise")
    assert (row["state"], row["skip_reason"]) == (STATE_SKIPPED, SKIP_DISABLED)


def test_a_vanished_job_stops_claiming_to_be_scheduled():
    """Cross-check against the scheduler, not against the record alone."""
    svc = _Svc([_cam()], sun_at=_future_sun())
    svc._register_sun_jobs()
    svc._scheduler.jobs.clear()
    assert _row(svc.timelapse_activity(), "cam1", "sunrise")["state"] == STATE_UNKNOWN


def test_the_report_survives_a_service_that_never_registered_anything():
    svc = _Svc([_cam()], sun_at=_future_sun())
    rep = svc.timelapse_activity()
    assert [r["state"] for r in rep["sun"]] == [STATE_UNKNOWN, STATE_UNKNOWN]
    assert rep["running_count"] == 0
