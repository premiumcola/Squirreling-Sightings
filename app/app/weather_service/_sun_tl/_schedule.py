"""Registration of the daily sunrise/sunset capture jobs.

Split out of ``_sun_tl/__init__.py``: the registration sweep had grown
past the per-function budget, and the day/night override — two jobs that
merely frame the capture window — is an orthogonal sub-concern that was
inlined in the middle of it.

The behavioural change made here is that every branch now records WHY it
did what it did (see ``_tl_activity``). The scheduling conditions
themselves are untouched: same order, same comparisons, same job ids.
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta

from .._consts import log
from .._tl_activity import (
    SKIP_DISABLED,
    SKIP_NO_LOCATION,
    SKIP_NO_SUN_EVENT,
    SKIP_WINDOW_PASSED,
    SUN_CAPTURE_PREFIX,
    SUN_PHASES,
    sun_capture_job_id,
)
from ._window import _SUN_TL_LOCKED_WINDOW_MIN, _sun_window_bounds


class SunScheduleMixin:
    """Daily registration of the sun-timelapse jobs. Mixin for WeatherService."""

    def _sun_jobs_keys(self) -> list[str]:
        if not self._scheduler:
            return []
        try:
            return [
                j.id
                for j in self._scheduler.get_jobs()
                if (
                    j.id.startswith(SUN_CAPTURE_PREFIX)
                    or j.id.startswith("sun_tl_dnov_")
                    or j.id.startswith("sun_tl_dnrev_")
                )
            ]
        except Exception:
            return []

    def _register_sun_jobs(self):
        """Cancel any previously-registered sunrise/sunset capture jobs and
        re-register for today's events. Skips windows that have already
        started (no rückwirkende triggers). Idempotent — safe at every
        service start, every reload, and on the daily 00:05 re-compute."""
        if not self._scheduler:
            return
        # Drop stale capture jobs first so a phase-toggle change actually
        # takes effect (and so we don't keep yesterday's jobs after the
        # daily recompute).
        for k in self._sun_jobs_keys():
            with contextlib.suppress(Exception):
                self._scheduler.remove_job(k)
        self.reset_sun_decisions()
        today = date.today()
        loc = self.server_cfg.get("location") or {}
        if loc.get("lat") is None or loc.get("lon") is None:
            self._note_all_sun_phases(SKIP_NO_LOCATION)
            log.info("[weather] Standort fehlt — keine Sun-Jobs registriert")
            return
        registered: list[str] = []
        for cam in self._cfg_cameras():
            for phase in SUN_PHASES:
                self._register_sun_phase(cam, phase, today, registered)
        if registered:
            log.info("[weather] Jobs registered: %s", " · ".join(registered))
        else:
            log.info("[weather] Keine Sun-Jobs heute (alle aus oder Fenster vorbei)")

    def _note_all_sun_phases(self, skip: str) -> None:
        """Record the same skip for every camera and phase.

        Used for the location check, which rejects the whole sweep before
        any camera is looked at. Recording it per camera anyway is what
        lets the UI answer "why is nothing scheduled" for the camera the
        operator is actually looking at.
        """
        for cam in self._cfg_cameras():
            cam_id = cam.get("id")
            if not cam_id:
                continue
            for phase in SUN_PHASES:
                self.note_sun_decision(cam_id, phase, skip=skip)

    def _register_sun_phase(self, cam: dict, phase: str, today: date, registered: list) -> None:
        """Register (or deliberately skip) one camera's capture for one phase."""
        from apscheduler.triggers.date import DateTrigger

        cam_id = cam.get("id")
        if not cam_id:
            return
        cam_name = cam.get("name") or cam_id
        pcfg = ((cam.get("weather") or {}).get("sun_timelapse") or {}).get(phase) or {}
        if not pcfg.get("enabled"):
            self.note_sun_decision(cam_id, phase, skip=SKIP_DISABLED)
            return
        sun_dt = self.sun_event_today(phase, today)
        if sun_dt is None:
            self.note_sun_decision(cam_id, phase, skip=SKIP_NO_SUN_EVENT)
            return
        # Window locked to a known-good range — the previous
        # user-tunable slider let mis-configurations land at
        # 10 min, far too short to capture civil twilight.
        # See _SUN_TL_LOCKED_WINDOW_MIN for sizing rationale.
        window = _SUN_TL_LOCKED_WINDOW_MIN
        start_dt, end_dt, _pre, _post = _sun_window_bounds(sun_dt, window)
        if start_dt <= datetime.now():
            self.note_sun_decision(
                cam_id,
                phase,
                skip=SKIP_WINDOW_PASSED,
                sun_dt=sun_dt,
                window_start=start_dt,
                window_end=end_dt,
            )
            log.info(
                "[weather] %s %s @ %s already passed — skipping today",
                cam_name,
                phase,
                sun_dt.strftime("%H:%M"),
            )
            return
        key = sun_capture_job_id(cam_id, phase, today)
        self._scheduler.add_job(
            self._run_sun_capture_safe,
            DateTrigger(run_date=start_dt),
            id=key,
            replace_existing=True,
            args=[cam_id, phase, sun_dt, dict(pcfg)],
        )
        self.note_sun_decision(
            cam_id,
            phase,
            job_id=key,
            sun_dt=sun_dt,
            window_start=start_dt,
            window_end=end_dt,
        )
        registered.append(f"{cam_name} {phase} {sun_dt.strftime('%H:%M')} (window {window} min)")
        self._register_daynight_jobs(cam, phase, pcfg, start_dt, end_dt, today, registered)

    def _register_daynight_jobs(
        self,
        cam: dict,
        phase: str,
        pcfg: dict,
        start_dt: datetime,
        end_dt: datetime,
        today: date,
        registered: list,
    ) -> None:
        """Optional day/night override framing one capture window.

        Two scheduled jobs frame the capture window symmetrically:
          - LEAD-IN at (start_dt - lead_min): force "Color" so the
            camera's internal IR-cut doesn't sit in Black&White when
            capture begins.
          - REVERT at (end_dt + lead_min): restore "Auto" /
            "Black&White" only AFTER the window has closed plus the same
            lead buffer.

        Hard invariant: no day/night flip may fire inside the active
        recording window. Anchoring both jobs to window bounds (NOT to
        the sun event itself) is what guarantees this — anchoring to
        sun_dt would bracket only a 30-min slice of a 60-min window and
        let the camera flip mid-recording.
        """
        from apscheduler.triggers.date import DateTrigger

        dnov = pcfg.get("daynight_override") or {}
        if not dnov.get("enabled"):
            return
        cam_id = cam.get("id")
        cam_name = cam.get("name") or cam_id
        lead_min = max(1, min(15, int(dnov.get("lead_min", 5) or 5)))
        override_at = start_dt - timedelta(minutes=lead_min)
        revert_at = end_dt + timedelta(minutes=lead_min)
        revert_mode = "Black&White" if dnov.get("revert", "auto") == "off" else "Auto"
        if not (cam.get("rtsp_url") or "").strip():
            log.warning(
                "[weather] %s %s: no rtsp_url, cannot infer Reolink host — daynight override skipped",
                cam_name,
                phase,
            )
            return
        if override_at <= datetime.now():
            log.info(
                "[weather] %s %s: daynight override window already passed, capture-only",
                cam_name,
                phase,
            )
            return
        dn_key = f"sun_tl_dnov_{cam_id}_{phase}_{today.isoformat()}"
        self._scheduler.add_job(
            self._apply_daynight_override,
            DateTrigger(run_date=override_at),
            id=dn_key,
            replace_existing=True,
            args=[cam_id, "Color", phase, lead_min],
        )
        registered.append(f"{cam_name} {phase} daynight→Color @{override_at.strftime('%H:%M')}")
        # Revert job anchored to window-end + lead_min.
        rv_key = f"sun_tl_dnrev_{cam_id}_{phase}_{today.isoformat()}"
        self._scheduler.add_job(
            self._apply_daynight_override,
            DateTrigger(run_date=revert_at),
            id=rv_key,
            replace_existing=True,
            args=[cam_id, revert_mode, phase, lead_min],
        )
        registered.append(
            f"{cam_name} {phase} daynight→{revert_mode} @{revert_at.strftime('%H:%M')}"
        )
