"""GET /api/telemetry/inference — what the accelerator is doing and what
each tiling mode would cost.

Its own blueprint rather than a field on ``/api/status`` because the two
are scoped differently: status is per-camera and the dashboard polls it
constantly, while this is per-DEVICE — one stick, one duty cycle — and is
read by one panel. It is also not in `coral.py` or
`coral_test_detection.py`; both are already past the file ceiling.

Cost of collection: none per frame. Every number here is already counted
by the camera loop (`InferenceTimingMixin`, `_main_fps`, the rescue ring);
the handler reads attributes and does arithmetic. The 1 s cache is not
there to save that work — it is microseconds — but to cap the pathological
case, where several open simulator tabs poll at their adaptive cadence and
the dashboard polls on top.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from flask import Blueprint, jsonify, request

from .. import app_state
from ..detectors._projection import (
    MAX_RESCUE_RATE_PER_S,
    MODE_TILES,
    affordable_invoke_ms,
    duty,
    duty_verdict,
    prod_invokes,
    stall_ms,
)
from ..lifecycle import classify_coral_usb

bp = Blueprint("telemetry", __name__)
log = logging.getLogger(__name__)

_CACHE_TTL_S = 1.0
_CACHE_GUARD = threading.Lock()
_CACHE: dict = {"ts": 0.0, "payload": None}

# lsusb is a subprocess with a 3 s timeout; the USB descriptor does not
# change between two polls a second apart. Probed once, then remembered.
_USB_GUARD = threading.Lock()
_USB_CACHE: list = [False, ""]

_MODES = ("off", "roi", "2x2", "3x3")


def _usb_line() -> str:
    """Raw ``lsusb`` verdict for the Coral stick, probed at most once."""
    with _USB_GUARD:
        if _USB_CACHE[0]:
            return _USB_CACHE[1]
        _USB_CACHE[0] = True
        try:
            import subprocess as _sp

            out = _sp.check_output(["lsusb"], text=True, timeout=3, stderr=_sp.DEVNULL)
            _USB_CACHE[1] = classify_coral_usb(out)
        except Exception:  # noqa: BLE001 — no lsusb in the image is not an error
            _USB_CACHE[1] = "not found"
        return _USB_CACHE[1]


def _versions() -> dict:
    """Which Python / tflite / pycoral is actually loaded.

    The whole TPU story on this box is an ABI mismatch between these three
    lines, so they belong next to the duty cycle rather than in a doc.
    """
    import platform

    out = {"python": platform.python_version(), "tflite_runtime": None, "pycoral": None}
    try:
        import tflite_runtime as _tfl  # type: ignore

        out["tflite_runtime"] = getattr(_tfl, "__version__", "unbekannt")
    except Exception:  # noqa: BLE001
        pass
    try:
        import pycoral  # type: ignore

        out["pycoral"] = getattr(pycoral, "__version__", "vorhanden")
    except Exception:  # noqa: BLE001
        pass
    return out


def _basename(path) -> str | None:
    return Path(str(path)).name if path else None


def _stage_row(stage: str, cam_id: str | None, obj, model, timing) -> dict:
    """One row of the stage table: which device, which API, which model.

    ``device`` and ``api`` are two columns on purpose. ``mode == "coral"``
    with ``_cpu_mode == True`` means "TPU, reached through the tflite
    delegate instead of pycoral" — collapsing that into one badge is how
    a working delegate ends up reported as a CPU fallback.
    """
    mode = getattr(obj, "mode", "none")
    cpu_api = bool(getattr(obj, "_cpu_mode", False))
    reason = getattr(obj, "reason", "disabled")
    if mode == "coral":
        device, api = "tpu", ("tflite-delegate" if cpu_api else "pycoral")
    elif mode == "cpu":
        device, api = "cpu", "tflite-cpu"
    else:
        device, api = "off", None
    return {
        "stage": stage,
        "cam_id": cam_id,
        "device": device,
        "api": api,
        # A classifier on the CPU is the SHIPPED design, not a fault: the
        # TPU caches model parameters in ~8 MB of on-chip SRAM and the live
        # path switches models inside one frame, so keeping the detector
        # resident beats making the classifiers fast. The UI paints this
        # neutral; only cpu_fallback earns a warning colour.
        "deliberate": reason == "cpu_requested",
        "fallback": str(reason).startswith("cpu_fallback"),
        "model": _basename(model),
        "reason": reason,
        "timing_ms": timing or {},
    }


def _stages(runtimes: dict) -> list[dict]:
    """Four rows per camera — the detector plus the three classifier
    interpreters (wildlife holds two)."""
    rows: list[dict] = []
    for cam_id, rt in runtimes.items():
        det = getattr(rt, "detector", None)
        if det is not None:
            rows.append(
                _stage_row(
                    "detector",
                    cam_id,
                    det,
                    getattr(det, "active_model_path", None),
                    det.timing_breakdown() if hasattr(det, "timing_breakdown") else {},
                )
            )
        bird = getattr(rt, "bird_classifier", None)
        if bird is not None:
            rows.append(
                _stage_row(
                    "bird",
                    cam_id,
                    bird,
                    getattr(bird, "active_model_path", None),
                    bird.timing_breakdown() if hasattr(bird, "timing_breakdown") else {},
                )
            )
        wild = getattr(rt, "wildlife_classifier", None)
        if wild is not None:
            rows.append(
                _stage_row(
                    "wildlife",
                    cam_id,
                    wild,
                    getattr(wild, "active_model_path", None),
                    wild.timing_breakdown() if hasattr(wild, "timing_breakdown") else {},
                )
            )
            inat = getattr(wild, "_inat_timing", None)
            if getattr(wild, "_inat_interpreter", None) is not None:
                rows.append(
                    {
                        **_stage_row(
                            "wildlife_inat",
                            cam_id,
                            wild,
                            getattr(wild, "active_inat_model_path", None),
                            inat.timing_breakdown() if inat is not None else {},
                        ),
                        "device": "cpu" if getattr(wild, "_inat_cpu_mode", True) else "tpu",
                        "api": "tflite-cpu" if getattr(wild, "_inat_cpu_mode", True) else "pycoral",
                    }
                )
    return rows


def _cameras(runtimes: dict) -> list[dict]:
    """Per-camera analysis rate, rescue rate and loop occupancy."""
    out = []
    for cam_id, rt in runtimes.items():
        cfg = getattr(rt, "cfg", {}) or {}
        interval_ms = float(cfg.get("frame_interval_ms") or 350)
        fps = float(getattr(rt, "_main_fps", 0.0) or 0.0)
        det = getattr(rt, "detector", None)
        timing = det.timing_breakdown() if hasattr(det, "timing_breakdown") else {}
        total_ms = float(timing.get("total") or 0.0)
        rate = 0.0
        getter = getattr(rt, "_roi_rescue_rate_60s", None)
        if callable(getter):
            rate = float(getter() or 0.0)
        out.append(
            {
                "id": cam_id,
                "analysed_fps": round(fps, 2),
                "configured_fps_max": round(1000.0 / interval_ms, 2) if interval_ms > 0 else None,
                "roi_mode": cfg.get("roi_mode") or "off",
                # Share of the camera's own loop thread spent inside the
                # detector. This — not a device duty cycle — is the honest
                # number on the CPU tier, where interpreters run parallel
                # and there is no single denominator to divide by.
                "loop_occupancy": round(total_ms / 1000.0 * fps, 3),
                "rescue": {
                    "attempts": int(getattr(rt, "_roi_rescue_attempts", 0) or 0),
                    "hits": int(getattr(rt, "_roi_rescue_hits", 0) or 0),
                    "rate_per_s": round(rate, 4),
                    "max_rate_per_s": round(MAX_RESCUE_RATE_PER_S, 4),
                },
            }
        )
    return out


def _projection(stage_rows: list[dict], cams: list[dict], tpu_active: bool) -> dict:
    """Per-mode cost projection from the measured detector timings."""
    det_rows = [r for r in stage_rows if r["stage"] == "detector" and r["timing_ms"]]
    invoke_ms = (
        sum(float(r["timing_ms"].get("invoke") or 0.0) for r in det_rows) / len(det_rows)
        if det_rows
        else 0.0
    )
    prep_ms = (
        sum(float(r["timing_ms"].get("pre") or 0.0) for r in det_rows) / len(det_rows)
        if det_rows
        else 0.0
    )
    load = [{"fps": c["analysed_fps"], "rescue_rate": c["rescue"]["rate_per_s"]} for c in cams]
    modes = []
    for mode in _MODES:
        lo_n, hi_n = prod_invokes(mode)
        d_lo, d_hi = duty(load, invoke_ms / 1000.0, mode)
        s_lo, s_hi = stall_ms(mode, invoke_ms, prep_ms)
        modes.append(
            {
                "mode": mode,
                "tiles": list(MODE_TILES.get(mode, (0, 0))),
                "invokes": [lo_n, hi_n],
                "duty": [d_lo, d_hi],
                "stall_ms": [s_lo, s_hi],
                # Only meaningful where one lock serialises everything.
                "verdict": duty_verdict(d_hi) if tpu_active else None,
            }
        )
    return {
        "basis": "tpu" if tpu_active else "cpu",
        "model": det_rows[0]["model"] if det_rows else None,
        # Which mode the numbers were MEASURED in — every other row of the
        # table is an extrapolation from it and must be labelled as one.
        "measured_mode": cams[0]["roi_mode"] if cams else "off",
        "invoke_ms": round(invoke_ms, 1),
        "prep_ms": round(prep_ms, 1),
        "samples": int(det_rows[0]["timing_ms"].get("samples") or 0) if det_rows else 0,
        "wait_ms": round(
            sum(float(r["timing_ms"].get("wait") or 0.0) for r in det_rows) / len(det_rows), 2
        )
        if det_rows
        else 0.0,
        "wait_p95_ms": round(max(float(r["timing_ms"].get("wait_p95") or 0.0) for r in det_rows), 2)
        if det_rows
        else 0.0,
        "affordable_invoke_ms": {m: affordable_invoke_ms(load, m) for m in _MODES},
        "modes": modes,
        # Named so the UI can spell each one out rather than hiding them
        # in a footnote. Every one of them can move the answer.
        "caveats": [
            "rescue_rate_upper_bound",
            "roi_tiles_variable",
            "model_dependent",
            "fps_feedback",
        ],
    }


def _build_payload() -> dict:
    runtimes = app_state.runtimes or {}
    stage_rows = _stages(runtimes)
    cams = _cameras(runtimes)
    tpu_active = any(r["device"] == "tpu" for r in stage_rows)
    return {
        "ok": True,
        "ts": time.time(),
        "device": {
            "tpu_active": tpu_active,
            "usb": _usb_line(),
            "runtime": _versions(),
            "duty_basis": "tpu" if tpu_active else "cpu",
        },
        "stages": stage_rows,
        "cameras": cams,
        "projection": _projection(stage_rows, cams, tpu_active),
    }


@bp.get('/api/telemetry/inference')
def api_telemetry_inference():
    """Device + per-stage inference telemetry and the per-mode projection.

    ``?cam=<id>`` narrows ``stages`` and ``cameras``; ``device`` and
    ``projection`` stay global, because the accelerator is global.
    """
    now = time.time()
    with _CACHE_GUARD:
        payload = _CACHE["payload"]
        if payload is None or (now - _CACHE["ts"]) > _CACHE_TTL_S:
            payload = _build_payload()
            _CACHE["ts"] = now
            _CACHE["payload"] = payload
        age_ms = int(round((now - _CACHE["ts"]) * 1000))
    out = dict(payload)
    out["cache_age_ms"] = age_ms
    cam_id = (request.args.get("cam") or "").strip()
    if cam_id:
        out["stages"] = [r for r in out["stages"] if r.get("cam_id") == cam_id]
        out["cameras"] = [c for c in out["cameras"] if c.get("id") == cam_id]
    return jsonify(out)
