"""The Netz's nightly threshold adaptation — its job body and its clock.

The 03:30 run used to be registered inside
``TelegramService.register_default_jobs``, behind two early returns:
``start()`` bails on ``not self.enabled`` and ``register_default_jobs``
bails on ``not push.enabled``. So turning Telegram off — or merely
switching pushes off while keeping the bot — silently switched off the
detection tuning too, and the comment beside the registration claimed
the opposite ("Both are unconditional"). Nothing about learning a
per-camera threshold from the stored verdict corpus needs a bot to be
running; the corpus is on disk either way.

The question RELEASE job stays with Telegram, because sending a message
is the entire job. This one moved here, next to ``_learner.run_pass``,
on a scheduler of its own — the two existing schedulers (Telegram's,
the weather service's) are each gated on their own service being
enabled, so neither can host a job that has to run regardless.

``register_nightly_jobs`` is idempotent: same job id, ``replace_existing``,
so ``rebuild_services()`` calling it on every settings reload re-registers
rather than stacking a second 03:30 firing.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

JOB_ID = "netz_learner"
JOB_HOUR = 3
JOB_MINUTE = 30

_scheduler = None


def run_nightly_pass() -> None:
    """One learner pass over every camera, then ONE runtime rebuild.

    Rebuilding per class would restart every camera a dozen times in a
    row for what is at most a handful of threshold changes.
    """
    from .. import app_state

    settings_store = app_state.settings
    storage_root = app_state.storage_root
    if settings_store is None or storage_root is None:
        log.warning("[det] Netz-Nachtlauf übersprungen — Stores noch nicht gebaut")
        return
    try:
        push_cfg = (app_state.get_effective_config().get("telegram") or {}).get("push") or {}
    except Exception:
        push_cfg = {}
    try:
        from ._learner import run_pass

        summary = run_pass(storage_root, settings_store, push_cfg)
    except Exception as e:
        log.warning("[det] Netz-Nachtlauf fehlgeschlagen: %s", e)
        return
    if not summary.get("changed"):
        return
    try:
        rebuild = getattr(app_state, "rebuild_runtimes", None)
        if callable(rebuild):
            rebuild()
    except Exception as e:
        log.warning("[det] rebuild_runtimes nach Netz-Lauf fehlgeschlagen: %s", e)


def register_nightly_jobs() -> None:
    """(Re-)register the 03:30 learner run. Safe to call on every reload."""
    global _scheduler
    if _scheduler is None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler

            _scheduler = BackgroundScheduler(daemon=True)
            _scheduler.start()
        except Exception as e:
            _scheduler = None
            log.error("[scheduler] Netz-Scheduler start failed: %s", e)
            return
    try:
        from apscheduler.triggers.cron import CronTrigger

        _scheduler.add_job(
            run_nightly_pass,
            CronTrigger(hour=JOB_HOUR, minute=JOB_MINUTE),
            id=JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info("[scheduler] netz: %s at %02d:%02d", JOB_ID, JOB_HOUR, JOB_MINUTE)
    except Exception as e:
        log.error("[scheduler] netz: %s registration failed: %s", JOB_ID, e)


def scheduled_job_ids() -> list[str]:
    """The job ids currently on the Netz scheduler — the boot inventory
    the weather service logs for its own, and what a test can assert on
    without waiting until 03:30."""
    if _scheduler is None:
        return []
    try:
        return [j.id for j in _scheduler.get_jobs()]
    except Exception:
        return []
