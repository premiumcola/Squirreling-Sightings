"""Forecast detectors for the weather event timelapse.

Split out of ``_event_tl.py`` when the pre-roll ring landed — the module
was already past the 500-line ceiling and the detectors are the natural
seam: pure functions over ``minutely_15`` slices with no I/O, no threads
and no filesystem.

Two tiers live here:

* the three **triggers** (``thunder_rising`` / ``front_passing`` /
  ``storm_front``) — "start capturing now", unchanged behaviour;
* the **watch** predicate — "this could become one of the above", the
  cheaper condition that arms the pre-roll ring. Same slices, same
  forecast horizon, roughly a third of each trigger's threshold.
"""

from __future__ import annotations

from datetime import datetime

from ._consts import _safe_dt, _safe_subset

# Watch thresholds. Each sits at roughly a third of the trigger it
# guards, so the ring starts filling well before the trigger can fire.
# The forecast horizon does the heavy lifting: thunder_rising reads a
# peak up to 90 min out, so an elevated lightning potential is usually
# visible hours before the trigger condition is met — which is why
# "armed" is the shipped mode rather than "always".
WATCH_LP_MIN = 500.0  # thunder_rising fires on a peak >= 1500
WATCH_GUST_MIN = 40.0  # storm_front fires on a peak >= 60
WATCH_CC_SWING_MIN = 30.0  # front_passing fires on a swing > 50
WATCH_HORIZON_MIN = 180


class EventTLDetectorsMixin:
    """Slice-window helpers + the trigger and watch predicates.

    Mixin for WeatherService; carries no state of its own.
    """

    @staticmethod
    def _slices_window(payload: dict, past_min: int = 60, future_min: int = 180) -> list:
        """Return all 15-min slices within [-past_min, +future_min] of now,
        each as a dict {time, ...measurements}. Times beyond the API's
        returned array are simply absent — caller must handle empty lists."""
        m = (payload or {}).get("minutely_15") or {}
        times = m.get("time") or []
        if not times:
            return []
        keys = [k for k in m if k != "time"]
        now = datetime.now()
        out = []
        for i, t_iso in enumerate(times):
            t = _safe_dt(t_iso)
            if not t:
                continue
            delta_min = (t - now).total_seconds() / 60.0
            if delta_min < -past_min or delta_min > future_min:
                continue
            slot = {"time": t_iso, "_dt": t}
            for k in keys:
                arr = m.get(k) or []
                slot[k] = arr[i] if i < len(arr) else None
            out.append(slot)
        return out

    @staticmethod
    def _slice_at_or_after(slices: list, minutes_from_now: int):
        for s in slices:
            dt = s.get("_dt")
            if dt and (dt - datetime.now()).total_seconds() / 60.0 >= minutes_from_now:
                return s
        return None

    def _evaluate_event_tl_detectors(self, slices: list, evt_cfg: dict) -> list:
        """Run all 3 detectors that are enabled for this camera. Returns a
        list of (trigger_kind, score, forecast_snapshot) tuples for any
        that fired. Caller picks one — typically the first."""
        triggers_cfg = evt_cfg.get("triggers") or {}
        results: list = []
        if triggers_cfg.get("thunder_rising", True):
            r = self._detect_thunder_rising(slices)
            if r:
                results.append(("thunder_rising", r[0], r[1]))
        if triggers_cfg.get("front_passing", True):
            r = self._detect_front_passing(slices)
            if r:
                results.append(("front_passing", r[0], r[1]))
        if triggers_cfg.get("storm_front", True):
            r = self._detect_storm_front(slices)
            if r:
                results.append(("storm_front", r[0], r[1]))
        return results

    def _detect_thunder_rising(self, slices: list):
        """Lightning-potential climbs from <500 to >1500 within the next
        60–90 min → trigger NOW. Score = peak_LP / 3000 (capped 0..1)."""
        now_slice = self._slice_at_or_after(slices, 0) or (slices[0] if slices else {})
        lp_now = now_slice.get("lightning_potential")
        # Look for the peak in the next 90 min.
        peak = 0.0
        peak_slot = None
        for s in slices:
            t = s.get("_dt")
            if not t:
                continue
            delta = (t - datetime.now()).total_seconds() / 60.0
            if delta < 0 or delta > 90:
                continue
            v = s.get("lightning_potential")
            if v is None:
                continue
            if float(v) > peak:
                peak = float(v)
                peak_slot = s
        if peak_slot is None:
            return None
        if (lp_now is None or float(lp_now) < 500.0) and peak >= 1500.0:
            score = min(1.0, peak / 3000.0)
            return score, _safe_subset(
                peak_slot,
                [
                    "time",
                    "lightning_potential",
                    "cloud_cover",
                    "wind_gusts_10m",
                    "precipitation",
                ],
            )
        return None

    def _detect_front_passing(self, slices: list):
        """Cloud-cover swing > 50 percentage-points across any 60-min window
        AND wind-gust climb > 20 km/h within the same window."""
        seq = self._cc_gust_sequence(slices)
        # Slide a 60-min window and check cloud-swing + gust-climb.
        for i in range(len(seq)):
            t0, cc0, g0 = seq[i]
            for j in range(i + 1, len(seq)):
                tj, ccj, gj = seq[j]
                if (tj - t0).total_seconds() / 60.0 > 60:
                    break
                if abs(ccj - cc0) > 50 and (gj - g0) > 20:
                    score = min(1.0, abs(ccj - cc0) / 100.0 + (gj - g0) / 100.0)
                    return score, {
                        "time_start": t0.isoformat(timespec="minutes"),
                        "time_end": tj.isoformat(timespec="minutes"),
                        "cloud_cover_delta": ccj - cc0,
                        "wind_gust_delta": gj - g0,
                    }
        return None

    @staticmethod
    def _cc_gust_sequence(slices: list) -> list:
        """(dt, cloud_cover, gust) triples for slices in [-30, +120] min.
        Shared by front_passing and the watch predicate."""
        seq = []
        for s in slices:
            dt = s.get("_dt")
            if not dt:
                continue
            delta = (dt - datetime.now()).total_seconds() / 60.0
            if delta < -30 or delta > 120:
                continue
            cc = s.get("cloud_cover")
            g = s.get("wind_gusts_10m")
            if cc is None or g is None:
                continue
            seq.append((dt, float(cc), float(g)))
        return seq

    def _detect_storm_front(self, slices: list):
        """Forecast peak wind gusts > 60 km/h in next 60 min AND
        cloud_cover > 70 in the same window."""
        peak_g = 0.0
        peak_slot = None
        for s in slices:
            dt = s.get("_dt")
            if not dt:
                continue
            delta = (dt - datetime.now()).total_seconds() / 60.0
            if delta < 0 or delta > 60:
                continue
            g = s.get("wind_gusts_10m")
            cc = s.get("cloud_cover")
            if g is None or cc is None:
                continue
            if float(g) > peak_g and float(cc) > 70.0:
                peak_g = float(g)
                peak_slot = s
        if peak_slot is None or peak_g < 60.0:
            return None
        score = min(1.0, peak_g / 120.0)
        return score, _safe_subset(
            peak_slot,
            [
                "time",
                "wind_gusts_10m",
                "cloud_cover",
                "precipitation",
                "lightning_potential",
            ],
        )

    def _event_tl_watch_active(self, slices: list, evt_cfg: dict) -> tuple:
        """Is this camera's weather "interesting enough" to keep a
        pre-roll ring rolling? Returns (active, reason).

        Only the triggers the camera actually has enabled are consulted —
        a camera that only wants thunder shouldn't burn its ring on a
        windy afternoon.
        """
        if not slices:
            return False, ""
        triggers_cfg = evt_cfg.get("triggers") or {}
        want_thunder = bool(triggers_cfg.get("thunder_rising", True))
        want_front = bool(triggers_cfg.get("front_passing", True))
        want_storm = bool(triggers_cfg.get("storm_front", True))
        now = datetime.now()
        peak_lp = 0.0
        peak_gust = 0.0
        for s in slices:
            dt = s.get("_dt")
            if not dt:
                continue
            delta = (dt - now).total_seconds() / 60.0
            if delta < 0 or delta > WATCH_HORIZON_MIN:
                continue
            lp = s.get("lightning_potential")
            if lp is not None:
                peak_lp = max(peak_lp, float(lp))
            g = s.get("wind_gusts_10m")
            if g is not None:
                peak_gust = max(peak_gust, float(g))
        if want_thunder and peak_lp >= WATCH_LP_MIN:
            return True, "lightning_potential %.0f J/kg" % peak_lp
        if want_storm and peak_gust >= WATCH_GUST_MIN:
            return True, "wind_gusts %.0f km/h" % peak_gust
        if want_front:
            seq = self._cc_gust_sequence(slices)
            for i in range(len(seq)):
                t0, cc0, _g0 = seq[i]
                for j in range(i + 1, len(seq)):
                    tj, ccj, _gj = seq[j]
                    if (tj - t0).total_seconds() / 60.0 > 60:
                        break
                    if abs(ccj - cc0) >= WATCH_CC_SWING_MIN:
                        return True, "cloud_cover swing %.0f pp" % abs(ccj - cc0)
        return False, ""
