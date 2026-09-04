"""The Build row must identify the RUNNING IMAGE and nothing else.

The operator read that row twice on the same container and got `#1717`,
then `#1249`. A build number that goes backwards is not a weaker
identifier than none — it is an actively misleading one, and this panel
exists precisely to answer "what am I running?" during a deploy that
did not arrive.

The cause was a boot-time fetch that overwrote the baked-in build number
with `api.github.com/repos/premiumcola/cam-manager/commits` — a different
repository from this one's remote (`premiumcola/Squirreling-Sightings`).
Succeeding showed that count, failing showed BUILD_COUNT, so the value
depended on whether a network call worked.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
LIFECYCLE = (APP / "lifecycle.py").read_text(encoding="utf-8")
SERVER = (APP / "server.py").read_text(encoding="utf-8")


def _code(src: str) -> str:
    """Source with comments stripped — this module's own comments quote
    the removed function by name to explain why it went."""
    return "\n".join(re.sub(r"#.*$", "", line) for line in src.splitlines())


def test_no_network_call_decides_the_build_number():
    assert "_fetch_github_commit_count" not in _code(LIFECYCLE)
    assert "_fetch_github_commit_count" not in _code(SERVER)


def test_nothing_queries_the_github_api_at_boot():
    """A boot-time call to a hardcoded repo slug is how the number came
    from somewhere else in the first place."""
    for src, name in ((LIFECYCLE, "lifecycle.py"), (SERVER, "server.py")):
        assert "api.github.com" not in _code(src), f"{name} still reaches for the GitHub API"


def test_the_build_number_comes_from_the_image():
    """BUILD_COUNT is the CI run number, baked in by the Dockerfile ARG —
    it cannot move without a rebuild, which is the only property that
    makes it worth printing."""
    body = LIFECYCLE[LIFECYCLE.index("def _get_build_info") :]
    body = body[: body.index("\n_BUILD_INFO")]
    assert 'os.environ.get("BUILD_COUNT"' in body


def test_the_build_count_is_stamped_by_ci():
    wf = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )
    assert "BUILD_COUNT=${{ github.run_number }}" in wf
    # Both images, or the production one reports a different number from
    # the one CI thinks it published.
    assert wf.count("BUILD_COUNT=${{ github.run_number }}") >= 2


def test_the_build_number_is_stable_across_calls():
    """No hidden refresh anywhere: two reads of the same process must
    agree, which is the property the operator actually relies on."""
    from app.lifecycle import _get_build_info

    assert _get_build_info() == _get_build_info()


def test_the_coral_publish_is_never_cancelled():
    """The other half of the same story. `:coral` is the image the host
    pulls and it builds far slower than `:latest`; sharing a concurrency
    group with `cancel-in-progress: true` meant a second push to main
    killed the Coral publish while `:latest` was already out.

    This workflow has no pull_request trigger, so cancelling never saved
    a redundant run — it only dropped deploys.
    """
    wf = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )
    concurrency = wf[wf.index("concurrency:") :]
    concurrency = concurrency[: concurrency.index("\nenv:")]
    assert (
        "cancel-in-progress: false" in concurrency
    ), "a push to main can cancel the in-flight Coral publish again"
