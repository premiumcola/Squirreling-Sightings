"""The Simulieren panel's verdict must be production's verdict.

The panel was trustworthy up to and including the tracker, and re-derived
everything after it. Caught on a live camera, in ONE report:

    ladder table  person … push=false → wird NIE gemeldet
    decision trace[push_threshold] person: 91 % ≥ 85 % → würde PASSIEREN
    decision trace[final] 1 Detektion(en) würden die Push-Pipeline erreichen

The camera's ``class_severity`` said ``person=off``. Production sends
nothing. The panel said it would send.

Four independent divergences produced that line, and each has its own
section below:

  S1  the push gate read ``telegram.push.labels[label]`` directly instead
      of ``thresholds.resolve_effective`` — so ``class_severity`` (which
      OUTRANKS the global flag, in BOTH directions), a per-camera
      ``push_thresholds`` override and the nightly learner's
      ``net_adapted`` layer were all invisible.
  S2  ``global_mute_until`` / ``cam_mute_until`` / ``suppress`` /
      ``rate_limit_seconds`` — four real gates — appeared nowhere at all,
      neither evaluated nor declared. A muted system dropped every alert
      while the panel reported the pipeline reachable.
  S4  ``_final_line`` branched on the push gate alone and dropped
      ``armed`` / ``telegram_enabled`` / ``schedule_notify``, which it had
      printed two lines above.
  S5  the Debug tab could claim "alle Tore offen" about gates it never
      opened.

The assertions are behavioural: the trace is generated and compared
against what ``resolve_effective`` — the function production calls —
says for the same camera.
"""

from __future__ import annotations

import ast
import threading
import time
from pathlib import Path

from app.routes import _sim_pipeline, _sim_routing
from app.settings._consts import TELEGRAM_PUSH_DEFAULTS
from app.telegram_bot._outbound._gates import GatesMixin
from app.thresholds import resolve_effective
from app.thresholds._apply import adapted_layer

APP = Path(__file__).resolve().parent.parent / "app"
CAM = "reolink_cx810_garten_172"
EFF_CFG = {"telegram": {"push": TELEGRAM_PUSH_DEFAULTS}}


class _Store:
    """Just the two runtime readers the mute gate uses."""

    def __init__(self, runtime: dict | None = None):
        self._rt = runtime or {}

    def runtime_get(self, key, default=None):
        return self._rt.get(key, default)

    def runtime_get_subkey(self, key, subkey, default=None):
        return (self._rt.get(key) or {}).get(subkey, default)


class _Notifier(GatesMixin):
    """The real gate predicates over a stub store — so the test exercises
    production's mute / suppress / rate-limit logic, not a copy of it."""

    _RATE_CACHE_MAX = 64

    def __init__(self, runtime: dict | None = None, push_cfg: dict | None = None):
        self.settings_store = _Store(runtime)
        self.push_cfg = push_cfg if push_cfg is not None else dict(TELEGRAM_PUSH_DEFAULTS)
        self._rate_lock = threading.Lock()
        self._rate_cache: dict = {}
        self._last_notify: dict = {}


def _sim(*rows) -> _sim_pipeline.SimPass:
    return _sim_pipeline.SimPass(
        rows=[
            {
                "label": label,
                "score": score,
                "verdict": _sim_pipeline.VERDICT_PASS,
                "reason": "",
                "track_num": 1,
            }
            for label, score in rows
        ]
    )


def _trace(cam: dict, *rows, notifier=None, eff_cfg: dict | None = None) -> list[str]:
    lines, _blocked = _sim_routing.routing_lines(
        cam=cam,
        cam_id=CAM,
        sim=_sim(*rows),
        eff_cfg=eff_cfg or EFF_CFG,
        notifier=notifier if notifier is not None else _Notifier(),
    )
    return lines


def _final(lines: list[str]) -> str:
    return next(ln for ln in lines if ln.startswith("[final]"))


def _reaches_push(lines: list[str]) -> bool:
    return "würden die Push-Pipeline erreichen" in _final(lines)


# ── S1 · the push gate is production's push gate ────────────────────────


def test_the_matrix_disables_what_the_global_flag_enables():
    """The operator's own snapshot. Shipped global: person push=true at
    0.85. This camera's matrix: person=off. Production sends nothing."""
    cam = {"class_severity": {"person": "off"}}
    assert resolve_effective(cam, TELEGRAM_PUSH_DEFAULTS, "person").push_enabled is False

    lines = _trace(cam, ("person", 0.91))

    assert not _reaches_push(lines), _final(lines)
    assert any("[push_flag] person" in ln and "push=false" in ln for ln in lines), lines
    assert "KEIN Alarm" in _final(lines)


def test_the_matrix_enables_what_the_global_flag_disables():
    """The other direction, and the one the shipped defaults make common:
    ``cat`` / ``bird`` / ``motion`` / ``fox`` / ``hedgehog`` all ship with
    push:false, so every feeder camera whose matrix says ``cat: info``
    was told its cats would be SKIPPED. Production pushes them."""
    cam = {"class_severity": {"cat": "info"}}
    assert resolve_effective(cam, TELEGRAM_PUSH_DEFAULTS, "cat").push_enabled is True

    lines = _trace(cam, ("cat", 0.92))

    assert not any("push=false" in ln for ln in lines), lines
    assert _reaches_push(lines), _final(lines)


def test_a_per_camera_push_threshold_is_applied():
    """``push_thresholds`` is exactly the key the Netz radar writes. Read
    off ``telegram.push.labels`` it was settable and inert — every vertex
    on the net would have been decoration in this panel."""
    cam = {"class_severity": {"person": "alarm"}, "push_thresholds": {"person": 0.50}}
    assert resolve_effective(cam, TELEGRAM_PUSH_DEFAULTS, "person").push == 0.50

    lines = _trace(cam, ("person", 0.60))

    assert _reaches_push(lines), _final(lines)
    assert any("50 %" in ln for ln in lines if ln.startswith("[push_threshold]")), lines


def test_the_learners_adapted_layer_is_applied():
    """``net_adapted`` is the nightly learner's own layer and reaches the
    live gate through ``adapted_layer``. Without it the panel reports the
    factory number for an axis the learner has moved."""
    cam = {"class_severity": {"squirrel": "alarm"}, "net_adapted": {"squirrel": {"E": 0}}}
    adapted = adapted_layer(cam, "squirrel")
    assert adapted, "the fixture must actually produce an adapted layer"
    bar = resolve_effective(cam, TELEGRAM_PUSH_DEFAULTS, "squirrel", adapted=adapted).push
    assert bar > TELEGRAM_PUSH_DEFAULTS["labels"]["squirrel"]["threshold"]

    lines = _trace(cam, ("squirrel", 0.85))

    assert not _reaches_push(lines), _final(lines)
    assert any(f"{int(round(bar * 100))} %" in ln for ln in lines), lines


def test_the_push_gate_is_not_re_derived():
    """ "No parallel implementations" — the direct read is what drifted.

    Checked on the AST, not the text: the module docstring has to be able
    to NAME the lookup it stopped doing.
    """
    src = (APP / "routes" / "_sim_routing.py").read_text(encoding="utf-8")

    assert "resolve_effective" in src and "adapted_layer" in src
    literals = {
        node.value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    docstrings = {
        ast.get_docstring(node) or ""
        for node in ast.walk(ast.parse(src))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
    }
    assert "labels" not in (literals - docstrings), (
        "the trace must not read telegram.push.labels itself — resolve_effective "
        "is the only reading that knows class_severity outranks the global flag"
    )


def test_the_debug_tab_ladder_passes_the_adapted_layer_too():
    """Same divergence, same fix: the snapshot's ladder resolved without
    ``adapted=`` and reported the factory push bar for a learned axis."""
    from app.routes._debug_snapshot._findings import ladder_rows

    cam = {"net_adapted": {"squirrel": {"E": 0}}}
    row = ladder_rows(cam, TELEGRAM_PUSH_DEFAULTS, ["squirrel"])[0]

    assert (
        row.push
        == resolve_effective(
            cam, TELEGRAM_PUSH_DEFAULTS, "squirrel", adapted=adapted_layer(cam, "squirrel")
        ).push
    )
    assert row.source["push"] == "adapted"


# ── S2 · the four invisible gates ───────────────────────────────────────


def test_a_global_mute_blocks_the_verdict():
    """The single most common cause of "I get no notifications", and the
    panel actively denied it: mute is production's FIRST gate."""
    cam = {"class_severity": {"person": "alarm"}}
    notifier = _Notifier({"global_mute_until": time.time() + 3600})

    lines = _trace(cam, ("person", 0.95), notifier=notifier)

    assert any(ln.startswith("[mute]") and "ÜBERSPRINGEN" in ln for ln in lines), lines
    assert not _reaches_push(lines), _final(lines)


def test_a_camera_mute_blocks_the_verdict():
    cam = {"class_severity": {"person": "alarm"}}
    notifier = _Notifier({"cam_mute_until": {CAM: time.time() + 600}})

    lines = _trace(cam, ("person", 0.95), notifier=notifier)

    assert any(ln.startswith("[mute]") and "ÜBERSPRINGEN" in ln for ln in lines), lines
    assert not _reaches_push(lines), _final(lines)


def test_an_expired_mute_does_not_block():
    cam = {"class_severity": {"person": "alarm"}}
    notifier = _Notifier({"global_mute_until": time.time() - 5})

    lines = _trace(cam, ("person", 0.95), notifier=notifier)

    assert any(ln.startswith("[mute]") and "PASSIEREN" in ln for ln in lines), lines
    assert _reaches_push(lines), _final(lines)


def test_suppression_blocks_the_verdict():
    cam = {"class_severity": {"person": "alarm"}}
    notifier = _Notifier({"suppress": {f"{CAM}|person": time.time() + 900}})

    lines = _trace(cam, ("person", 0.95), notifier=notifier)

    assert any(ln.startswith("[suppress]") and "ÜBERSPRINGEN" in ln for ln in lines), lines
    assert not _reaches_push(lines), _final(lines)


def test_the_rate_limit_blocks_the_verdict():
    cam = {"class_severity": {"person": "alarm"}}
    notifier = _Notifier()
    notifier._record_rate_limit(CAM)

    lines = _trace(cam, ("person", 0.95), notifier=notifier)

    assert any(ln.startswith("[rate_limit]") and "ÜBERSPRINGEN" in ln for ln in lines), lines
    assert not _reaches_push(lines), _final(lines)


def test_the_mute_state_has_exactly_one_owner():
    """The panel reads the mute through the notifier's own predicate, so
    the two can never disagree — and reading it must not write a
    "[tg] skip:" line for an alert nobody tried to send."""
    routing = (APP / "routes" / "_sim_routing.py").read_text(encoding="utf-8")
    gates = (APP / "telegram_bot" / "_outbound" / "_gates.py").read_text(encoding="utf-8")
    alert = (APP / "telegram_bot" / "_outbound" / "_event_alert.py").read_text(encoding="utf-8")

    assert "mute_state" in routing and "def mute_state" in gates
    assert "global_mute_until" not in routing, "the panel must not re-read the mute keys"
    assert "self.mute_state(" in alert, "production must use the same resolver"
    assert "def mute_state" in gates and "log." not in gates.split("def mute_state")[1]


# ── S4 · the verdict accounts for every gate it printed ─────────────────


def test_a_disarmed_camera_never_reports_a_reachable_pipeline():
    cam = {"armed": False, "class_severity": {"person": "alarm"}}

    lines = _trace(cam, ("person", 0.95))

    assert not _reaches_push(lines), _final(lines)
    assert "KEIN Alarm" in _final(lines)


def test_a_camera_with_telegram_off_never_reports_a_reachable_pipeline():
    cam = {"telegram_enabled": False, "class_severity": {"person": "alarm"}}

    lines = _trace(cam, ("person", 0.95))

    assert not _reaches_push(lines), _final(lines)


def test_a_closed_notify_window_blocks_the_verdict():
    """A window that is enabled and 00:00→00:00 wide is never open."""
    cam = {
        "class_severity": {"person": "alarm"},
        "schedule_notify": {"enabled": True, "from": "03:00", "to": "03:01"},
    }

    lines = _trace(cam, ("person", 0.95))
    schedule_line = next(ln for ln in lines if ln.startswith("[schedule_notify]"))

    if "aktiv=False" in schedule_line:
        assert not _reaches_push(lines), _final(lines)


def test_an_off_severity_blocks_the_verdict():
    """``compute_severity_from_matrix`` returning "off" means the event
    carries notify=False and never reaches the notifier at all."""
    cam = {"class_severity": {"cat": "off"}}

    lines = _trace(cam, ("cat", 0.95))

    assert not _reaches_push(lines), _final(lines)


def test_an_open_camera_still_reaches_the_pipeline():
    """The control: with every gate open the panel must still say so, or
    the fix has simply replaced one wrong answer with another."""
    cam = {"class_severity": {"person": "alarm"}}

    lines = _trace(cam, ("person", 0.95))

    assert _reaches_push(lines), _final(lines)
    assert "Bestätigungsfenster" in _final(lines), "the hedge must survive"


def test_the_verdict_still_hedges_on_the_gates_it_cannot_run():
    cam = {"class_severity": {"person": "alarm"}}

    lines = _trace(cam, ("person", 0.95))

    assert "nicht prüft" in _final(lines)


# ── S5 · the Debug tab does not vouch for gates it never checked ────────


def test_the_all_clear_names_what_it_actually_checked():
    """ "Keine Auffälligkeit — alle Tore offen." is a claim about ALL
    gates from a check that opens six of them. Nine are never evaluated
    here, and an all-clear that covers them is the same false confidence
    the decision trace just lost."""
    from app.routes._debug_snapshot._findings import build_findings

    findings = build_findings({}, {"ts": 1}, {}, [])
    ok = [f for f in findings if f["tone"] == "ok"]

    assert ok, "an all-clear line must still exist"
    text = ok[0]["text"]
    assert "alle Tore offen" not in text, "it cannot vouch for gates it never opened"
    assert "ungeprüft" in text or "nicht geprüft" in text, text


# ── budgets ─────────────────────────────────────────────────────────────


def test_the_routing_module_stays_inside_its_budget():
    src = (APP / "routes" / "_sim_routing.py").read_text(encoding="utf-8")

    assert len(src.splitlines()) <= 500
