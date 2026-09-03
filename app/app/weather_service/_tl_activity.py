"""What is actually capturing right now — and, when nothing is, why not.

The sun timelapse had no self-report at all. Settings showed a preview
line ("Heute: 19:57 · Fenster 19:05–20:20") computed straight from the
location, so it read identically whether a capture job existed or had
never been created. Three separate conditions in ``_register_sun_jobs``
can silently produce nothing — missing location, phase not enabled, and
a window whose start already passed — and none of them were visible
anywhere. The operator's "it doesn't feel like the sun timelapses are
running" was correct and unanswerable at the same time.

This module answers it, and the answer is assembled from two facts
rather than from a second copy of the scheduling arithmetic:

1. **The decision, recorded where it is made.** ``_register_sun_jobs``
   calls :meth:`TimelapseActivityMixin.note_sun_decision` on every
   camera/phase it considers, including the ones it walks away from.
   A skip reason is therefore the reason the scheduler actually used,
   not a re-derivation that can disagree with it.
2. **The scheduler's own job list.** Whether a job exists right now is
   read back from APScheduler via ``_sun_jobs_keys()``. A recorded
   "registered" that no longer has a live job is reported as such — it
   fired, or something removed it — instead of repeating yesterday's
   boast.

"Running" is never inferred from clock arithmetic. Both capture paths
claim an entry in an in-flight registry for exactly as long as their
worker thread lives, so an empty registry means nothing is capturing,
full stop.
"""

from __future__ import annotations

import threading
from datetime import datetime

from ._consts import log

# The two solar phases, in the order the UI lists them. Imported by the
# scheduler so the loop and the reporter can never disagree on the set.
SUN_PHASES = ("sunrise", "sunset")

# Phase -> the archive's kind name, which is where the German labels for
# these two already live (`weather_episodes._footage.KIND_LABEL_DE`).
SUN_PHASE_KIND = {
    "sunrise": "sun_timelapse_rise",
    "sunset": "sun_timelapse_set",
}

# Job-id prefix and format — the single source. `_sun_jobs_keys` matches
# on the prefix, `_register_sun_jobs` builds ids with the function below,
# and the reporter looks ids up in the list the first one returns. One
# literal, three readers.
SUN_CAPTURE_PREFIX = "sun_tl_capture_"

# Why no job was created. Recorded by the scheduler at the exact branch
# that walked away, so these are decisions, not diagnoses.
SKIP_NO_LOCATION = "no_location"
SKIP_DISABLED = "disabled"
SKIP_NO_SUN_EVENT = "no_sun_event"
SKIP_WINDOW_PASSED = "window_passed"

SKIP_LABEL_DE = {
    SKIP_NO_LOCATION: "Standort fehlt",
    SKIP_DISABLED: "nicht aktiviert",
    SKIP_NO_SUN_EVENT: "kein Sonnenereignis heute",
    SKIP_WINDOW_PASSED: "Fenster war schon vorbei",
}

# Lifecycle states of one camera/phase for today.
STATE_RUNNING = "running"  # a capture thread is alive right now
STATE_SCHEDULED = "scheduled"  # job registered, window still ahead
STATE_FINISHED = "finished"  # was registered, job gone, window over
STATE_SKIPPED = "skipped"  # considered and rejected — see reason
STATE_UNKNOWN = "unknown"  # never considered (no registration run yet)

STATE_LABEL_DE = {
    STATE_RUNNING: "läuft",
    STATE_SCHEDULED: "geplant",
    STATE_FINISHED: "erledigt",
    STATE_SKIPPED: "übersprungen",
    STATE_UNKNOWN: "unbekannt",
}


def sun_capture_job_id(cam_id: str, phase: str, day) -> str:
    """The APScheduler id of one camera's capture job for one day.

    Single source of the format. Registration builds ids with it and the
    reporter looks them up with it, so a change here cannot leave the
    two halves searching for different strings.
    """
    return f"{SUN_CAPTURE_PREFIX}{cam_id}_{phase}_{day.isoformat()}"


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def _delta_s(now: datetime, target: datetime | None) -> int | None:
    """Whole seconds from ``now`` to ``target``, floored at 0, or None."""
    if target is None:
        return None
    return max(0, int((target - now).total_seconds()))


def resolve_sun_state(
    decision: dict | None,
    live_job_ids: set[str],
    running: dict | None,
    now: datetime,
) -> tuple[str, str | None]:
    """Classify one camera/phase into (state, skip_reason).

    Pure — every input is passed in, so the classification is testable
    without a scheduler, a service or a clock. The precedence is
    deliberate: an in-flight capture outranks everything (it is the one
    fact that is directly observed), then the live job list, then the
    recorded decision. Only when nothing was ever recorded do we admit
    to not knowing rather than guessing from the window times.
    """
    if running:
        return STATE_RUNNING, None
    if not decision:
        return STATE_UNKNOWN, None
    skip = decision.get("skip")
    if skip:
        return STATE_SKIPPED, skip
    job_id = decision.get("job_id")
    if job_id and job_id in live_job_ids:
        return STATE_SCHEDULED, None
    # Registered earlier, no live job and no worker: APScheduler drops a
    # DateTrigger job once it has fired. Before the window even opens
    # that combination cannot happen, so a missing job that early means
    # something removed it — say so instead of claiming success.
    end = decision.get("window_end_dt")
    if end is not None and now < end:
        return STATE_UNKNOWN, None
    return STATE_FINISHED, None


class TimelapseActivityMixin:
    """Honest per-camera activity for the sun and event timelapses.

    Mixin for WeatherService. Owns the two registries the report reads:
    the scheduling decisions (written by ``_register_sun_jobs``) and the
    sun in-flight set (written by the capture entry point). The event
    timelapse already kept its own in-flight registry, so this only
    reads that one.
    """

    # ── Registries ──────────────────────────────────────────────────────
    def _sun_activity_state(self) -> dict:
        # Lazy attr — same pattern as `_event_tl_ring_state`, keeps
        # WeatherService.__init__ untouched and survives a reload().
        if not hasattr(self, "_sun_activity_dict"):
            self._sun_activity_dict = {
                "decisions": {},  # (cam_id, phase) -> decision record
                "running": {},  # (cam_id, phase) -> capture record
                "registered_at": None,  # when the last sweep ran
                "lock": threading.Lock(),
            }
        return self._sun_activity_dict

    def reset_sun_decisions(self) -> None:
        """Clear the recorded decisions before a fresh registration sweep.

        Called at the top of ``_register_sun_jobs``. Without this a
        camera that was switched off would keep yesterday's "registered"
        record forever, because nothing would overwrite it.
        """
        st = self._sun_activity_state()
        with st["lock"]:
            st["decisions"] = {}
            st["registered_at"] = datetime.now()

    def note_sun_decision(
        self,
        cam_id: str,
        phase: str,
        *,
        skip: str | None = None,
        job_id: str | None = None,
        sun_dt: datetime | None = None,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> None:
        """Record what the scheduler decided for one camera/phase."""
        st = self._sun_activity_state()
        with st["lock"]:
            st["decisions"][(cam_id, phase)] = {
                "skip": skip,
                "job_id": job_id,
                "sun_dt": sun_dt,
                "window_start_dt": window_start,
                "window_end_dt": window_end,
            }

    def sun_capture_started(self, cam_id: str, phase: str, ends_at: datetime) -> None:
        """Mark a sun capture as in flight. Paired with `sun_capture_finished`."""
        st = self._sun_activity_state()
        with st["lock"]:
            st["running"][(cam_id, phase)] = {
                "started_at": datetime.now(),
                "ends_at": ends_at,
            }

    def sun_capture_finished(self, cam_id: str, phase: str) -> None:
        st = self._sun_activity_state()
        with st["lock"]:
            st["running"].pop((cam_id, phase), None)

    # ── Report ──────────────────────────────────────────────────────────
    @staticmethod
    def _phase_label(phase: str) -> str:
        """German name of a solar phase, from the archive's label map.

        Imported lazily: ``weather_episodes`` imports back into
        ``weather_service``, so a module-level import here would close a
        cycle. The map is reused rather than copied because the frontend
        would otherwise carry a fourth hand-written pair of these two
        strings.
        """
        from ..weather_episodes._footage import KIND_LABEL_DE

        return KIND_LABEL_DE.get(SUN_PHASE_KIND.get(phase, ""), phase)

    def _sun_activity_rows(self, now: datetime) -> list[dict]:
        """One row per camera and phase, cross-checked against the scheduler."""
        st = self._sun_activity_state()
        with st["lock"]:
            decisions = dict(st["decisions"])
            running = dict(st["running"])
            swept_at = st["registered_at"]
        live = set(self._sun_jobs_keys())
        rows = []
        for cam in self._cfg_cameras():
            cam_id = cam.get("id")
            if not cam_id:
                continue
            for phase in SUN_PHASES:
                dec = decisions.get((cam_id, phase))
                run = running.get((cam_id, phase))
                state, reason = resolve_sun_state(dec, live, run, now)
                dec = dec or {}
                end_dt = run["ends_at"] if run else dec.get("window_end_dt")
                rows.append(
                    {
                        "camera_id": cam_id,
                        "camera_name": cam.get("name") or cam_id,
                        "phase": phase,
                        "phase_text": self._phase_label(phase),
                        "state": state,
                        "state_text": STATE_LABEL_DE[state],
                        "skip_reason": reason,
                        "skip_text": SKIP_LABEL_DE.get(reason) if reason else None,
                        "job_id": dec.get("job_id"),
                        "job_registered": bool(dec.get("job_id") and dec.get("job_id") in live),
                        "sun_event": _iso(dec.get("sun_dt")),
                        "window_start": _iso(
                            run["started_at"] if run else dec.get("window_start_dt")
                        ),
                        "window_end": _iso(end_dt),
                        "starts_in_s": (None if run else _delta_s(now, dec.get("window_start_dt"))),
                        "remaining_s": _delta_s(now, end_dt) if run else None,
                        "swept_at": _iso(swept_at),
                    }
                )
        return rows

    def _event_activity_rows(self, now: datetime) -> list[dict]:
        """One row per event timelapse that is capturing right now.

        Reads the in-flight registry the capture claim already
        maintained — there is no second bookkeeping to drift from it.
        """
        try:
            st = self._event_tl_ring_state()
            with st["lock"]:
                inflight = dict(st["inflight"])
        except Exception:
            return []
        rows = []
        for cam_id, rec in inflight.items():
            if not isinstance(rec, dict):
                # A bare claim with no descriptor still means "running".
                rec = {}
            ends_at = rec.get("ends_at")
            rows.append(
                {
                    "camera_id": cam_id,
                    "camera_name": self._cam_name(cam_id),
                    "trigger": rec.get("trigger"),
                    "trigger_text": rec.get("trigger_text"),
                    "state": STATE_RUNNING,
                    "state_text": STATE_LABEL_DE[STATE_RUNNING],
                    "started_at": _iso(rec.get("started_at")),
                    "window_end": _iso(ends_at),
                    "remaining_s": _delta_s(now, ends_at),
                }
            )
        return rows

    def timelapse_activity(self) -> dict:
        """The weather-side timelapse truth, for `/api/timelapse/status`."""
        now = datetime.now()
        try:
            sun = self._sun_activity_rows(now)
        except Exception as e:
            log.warning("[weather] sun activity report failed: %s", e)
            sun = []
        event = self._event_activity_rows(now)
        running = [r for r in sun if r["state"] == STATE_RUNNING]
        return {
            "available": True,
            "sun": sun,
            "event": event,
            "running_count": len(running) + len(event),
        }
