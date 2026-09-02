"""Runtime state: /api/status and /api/system."""

from __future__ import annotations

from flask import jsonify

from ... import app_state
from ...detectors._utilisation import fleet_tpu_utilisation
from ._blueprint import bp


def status_payload() -> dict:
    """The body of ``/api/status``, as a plain dict.

    Split out of the route so the debug bundle can snapshot the same
    state the dashboard polls, rather than growing a second, drifting
    idea of what "status" means.
    """
    settings = app_state.settings
    runtimes = app_state.runtimes
    return {
        "cameras": [
            runtimes[c["id"]].status()
            if c["id"] in runtimes
            else {"id": c["id"], "status": "disabled", "name": c.get("name", c["id"])}
            for c in app_state.get_effective_config().get("cameras", [])
        ],
        "cat_profiles": app_state.cat_registry.list_profiles(),
        "person_profiles": app_state.person_registry.list_profiles(),
        "telegram_actions": settings.data.get("telegram_actions", [])[:12],
        "tpu": fleet_tpu_utilisation(runtimes),
    }


@bp.get('/api/status')
def api_status():
    return jsonify(status_payload())


@bp.get('/api/system')
def api_system():
    # R01.6 · straight from lifecycle.py, where both constants actually
    # live. server.py only ever re-exported them, and importing it by
    # name re-executes the whole boot block (see app_state).
    from ...lifecycle import _BUILD_INFO, _PROCESS_START_ISO

    mem_total = mem_used = proc_mem_mb = uptime_s = 0.0
    try:
        mem: dict = {}
        with open('/proc/meminfo') as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    mem[parts[0].rstrip(':')] = int(parts[1]) * 1024
        mem_total = mem.get('MemTotal', 0)
        mem_available = mem.get('MemAvailable', 0)
        mem_used = mem_total - mem_available
    except Exception:
        pass
    try:
        with open('/proc/uptime') as f:
            uptime_s = float(f.read().split()[0])
    except Exception:
        pass
    try:
        import resource as _resource

        ru = _resource.getrusage(_resource.RUSAGE_SELF)
        proc_mem_mb = round(ru.ru_maxrss / 1024, 1)  # KB → MB on Linux
    except Exception:
        pass
    coral_device = None
    try:
        import subprocess as _sp

        lsusb = _sp.check_output(['lsusb'], text=True, timeout=3, stderr=_sp.DEVNULL)
        for line in lsusb.splitlines():
            # The stick enumerates as 1a6e:089a "Global Unichip" until its
            # firmware is uploaded and only then as 18d1:9302 "Google" —
            # both are the same device. Matching Google/18d1 alone reported
            # "kein Coral" for a stick that was plugged in and working.
            low = line.lower()
            if 'google' in low or 'coral' in low or '18d1' in low or '1a6e' in low:
                coral_device = line.strip()
                break
    except Exception:
        pass
    return jsonify(
        {
            "build": _BUILD_INFO,
            "process_start": _PROCESS_START_ISO,
            "mem_total_mb": round(mem_total / 1048576, 1),
            "mem_used_mb": round(mem_used / 1048576, 1),
            "proc_mem_mb": proc_mem_mb,
            "uptime_s": uptime_s,
            "storage_root": str(app_state.storage_root),
            "camera_count": len(app_state.runtimes),
            "coral_device": coral_device,
        }
    )
