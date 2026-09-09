"""The rare-species override — one axis where a class-level gate is
provably wrong.

Split out of ``_question.py`` on the same principle ``_question_budget.py``
already established for the day/class counters: a self-contained,
orthogonal concern gets its own file rather than pushing the host past
CLAUDE.md's 500-line ceiling. This one decides WHETHER a question is
forced through despite the ordinary gates; the gates themselves (gap,
budget, mute, quiet hours) stay in ``_question.py`` — see that module's
docstring for the two blind spots this override closes.

Uses ``most_specific_label`` directly rather than importing
``_question.event_subject`` (score is not needed here, only the label)
— that import would run into ``_question.py`` importing THIS module at
its own top, before ``event_subject`` is defined in it.
"""

from __future__ import annotations

from ...settings._consts import BIRD_SPECIES_ASK_UNTIL_DEFAULT
from ...species_video_count import confirmed_video_count
from ...telegram_helpers import most_specific_label


class QuestionSpeciesMixin:
    """The rare-species force-ask decision. Mixin — state via ``self.*``."""

    def _species_rare_override(self, meta: dict, camera_id: str) -> bool:
        """True when this bird's species has fewer than the configured
        number of CONFIRMED videos — forces a Telegram question through
        regardless of the class-level budget/gap, and regardless of
        which band the raw score would otherwise have routed to.

        See ``_question``'s module docstring for the second blind spot
        this closes: the ALARM band cannot be trusted to notify on its
        own for a class shipping ``push: false`` by default — ``bird``
        is exactly that class, so a confident first-ever sighting is
        otherwise the one case that reaches nobody at all.

        ``camera_id`` is unused today — the setting is global, not
        per-camera — and kept for symmetry with ``band_for`` /
        ``send_question``, whose call sites all carry it.
        """
        del camera_id
        label = most_specific_label(meta.get("labels") or [])
        if label != "bird":
            return False
        species = (meta.get("bird_species") or "").strip()
        if not species:
            return False
        storage_cfg = self._cfg().get("storage") or {}
        raw = storage_cfg.get("bird_species_ask_until_count")
        # `None`-check, not `or` — an explicit 0 must read as "off", not
        # silently fall back to the default. The same bug already bit
        # `post_motion_tail_s` once this session (see CLAUDE.md's note
        # on `resolve_pre_motion_seconds`); mirrors the identical guard
        # in `camera_runtime/_recording_step.py::_species_over_cap`.
        n = int(raw) if raw is not None else BIRD_SPECIES_ASK_UNTIL_DEFAULT
        if n <= 0:  # operator turned the override fully off
            return False
        return confirmed_video_count(self._storage_root(), species) < n
