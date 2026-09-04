"""Both finalize paths must publish the event. Neither may go silent.

The bug this locks out ran for four months on every real deployment:

`send_event_alert` had exactly one caller, `_finalize_motion_clip`, which
in turn had exactly one caller — the OpenCV frame-buffer branch. ffmpeg
is installed in the container, so production always took the *other*
branch, `_reencode_motion_clip`, which called nothing. Clips recorded,
events in the library, MQTT firing, and not one Telegram alert. Not even
a log line saying an alert was blocked, because the push gates were
never reached.

A comment in the ffmpeg path stated the opposite — that the alert "is
fired once, by the modern push pipeline in _finalize_motion_clip". It
had been deleted there as a duplicate. It was the only one that ran.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REC = Path(__file__).resolve().parent.parent / "app" / "camera_runtime" / "_recording"

# Where each finalize path actually lives since the __init__.py split
# (_ffmpeg_clip.py = production ffmpeg stream-copy path, _opencv_fallback.py
# = the legacy in-memory frame-buffer path). Kept as one map so a future
# move only needs updating here, not at every call site below.
_FINALIZE_FILE = {
    "_reencode_motion_clip": "_finalize.py",
    "_finalize_motion_clip": "_opencv_fallback.py",
}


def _src(name: str) -> str:
    return (REC / name).read_text(encoding="utf-8")


def _function_body(src: str, name: str) -> str:
    """Crude but sufficient: from `def name(` to the next top-level def.

    Still used by the assertions that care about the ORDER of statements
    inside one method, where the call graph says nothing.
    """
    start = src.index(f"    def {name}(")
    nxt = src.find("\n    def ", start + 10)
    return src[start : nxt if nxt != -1 else len(src)]


def _reaches(src: str, entry: str, target: str) -> bool:
    """Does ``entry`` reach ``target``, directly or through helpers?

    Was a flat "is the call in this function's text" check, which is the
    same assertion only as long as nobody extracts a step. When the
    post-recording chain was split for CLAUDE.md's size ceilings the
    publish moved one call deep and the test went red without a single
    behaviour changing — a test that fails on a refactor stops being
    read as a real signal.

    So it now walks the call graph inside the file: from the entry
    method, into every ``self._x()`` it calls that is defined in the same
    class, until the target is reached or the graph is exhausted. That is
    strictly STRONGER than the text match — it still catches a dropped
    call, and it additionally catches one that is only reachable from a
    method nobody calls.
    """
    tree = ast.parse(src)
    bodies = {
        n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    seen: set[str] = set()

    def walk(name: str) -> bool:
        if name in seen or name not in bodies:
            return False
        seen.add(name)
        for node in ast.walk(bodies[name]):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            called = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if called == target:
                return True
            if called and walk(called):
                return True
        return False

    return walk(entry)


def test_both_finalize_paths_publish():
    """The load-bearing assertion. If either path stops calling the
    shared publisher, that recording mode goes silent again."""
    for fn, filename in _FINALIZE_FILE.items():
        assert _reaches(_src(filename), fn, "_publish_finalized_event"), (
            f"{fn} does not reach the publisher — that recording mode will "
            "record clips and never alert, exactly as before"
        )


def test_the_alert_has_exactly_one_call_site():
    """Two call sites is how the duplicate was 'fixed' by deleting the
    wrong one. One site cannot be half-removed."""
    publish = _src("_publish.py")
    assert publish.count("send_event_alert(") == 1
    for filename in (
        "__init__.py",
        "_ffmpeg_clip.py",
        "_finalize.py",
        "_opencv_fallback.py",
        "_preroll.py",
    ):
        assert "send_event_alert(" not in _src(filename), (
            f"the alert must live only in _publish.py, reachable from both paths "
            f"(found a second call site in {filename})"
        )


@pytest.mark.parametrize(
    "consequence",
    [
        "_apply_first_since",
        "_publish_mqtt",
        "_publish_achievement",
        "_publish_quests",
        "_publish_dossiers",
        "_publish_alert",
    ],
)
def test_every_consequence_runs_from_the_shared_step(consequence):
    body = _function_body(_src("_publish.py"), "_publish_finalized_event")
    assert consequence in body


def test_ffmpeg_path_stamps_first_since():
    """It updates an existing stub, so the marker is applied in the
    publish step rather than before a first write.

    Read over the whole finalize module rather than one method: the
    chain was split across several of them for the size ceilings, and
    the statement being made — this path never opts OUT of the marker —
    is about the path, not about which method holds the call."""
    assert "apply_first_since=False" not in _src("_finalize.py")


def test_opencv_path_stamps_first_since_before_add_event():
    """Its add_event is the FIRST write of the JSON, so the marker has to
    be on the dict already — hence apply_first_since=False downstream."""
    body = _function_body(_src("_opencv_fallback.py"), "_finalize_motion_clip")
    stamp = body.index("_apply_first_since(")
    add = body.index("self.store.add_event(")
    assert stamp < add, "the marker must be stamped before the JSON is first written"
    assert "apply_first_since=False" in body, "and must not be applied a second time"


def test_publish_is_reachable_on_the_runtime():
    from app.camera_runtime._recording._publish import PublishMixin
    from app.camera_runtime.runtime import CameraRuntime

    assert PublishMixin in CameraRuntime.__mro__
    for m in ("_publish_finalized_event", "_publish_alert", "_apply_first_since"):
        assert hasattr(CameraRuntime, m)


def test_routing_line_is_logged_before_the_notifier_gate():
    """That log line's absence is what hid this for four months. It must
    sit above the early return, not after it."""
    body = _function_body(_src("_publish.py"), "_publish_alert")
    log_at = body.index("alert routing:")
    gate_at = body.index("if not (notify and")
    assert log_at < gate_at


def test_no_lazy_logging_violations_in_the_new_module():
    """CLAUDE.md: logging uses % args, never f-strings."""
    for line in _src("_publish.py").splitlines():
        stripped = line.strip()
        if re.match(r"log\.(debug|info|warning|error)\(f[\"']", stripped):
            raise AssertionError(f"f-string in a log call: {stripped}")
