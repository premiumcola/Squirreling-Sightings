"""Hänger werden aufgeräumt, WÄHREND es läuft — nicht erst beim Neustart.

Den Boot-Sweep gab es immer, und er ist der Grund, warum ein beim
Neustart abgebrochener Clip überhaupt je wieder heil wird. Was er nicht
konnte: ihn VOR dem nächsten Neustart heil machen. An dieser Anlage
gemessen: 71 fertige Clips, Median 24 s vom Ereignis bis fertig — und
ein Ausreißer bei 24 087 s, also 6,7 Stunden. Das ist keine Last, das
ist die Wartezeit auf den nächsten Start.

Der periodische Sweep benutzt dasselbe Prädikat mit einem WANDERNDEN
Stichtag. Diese Tests halten genau das fest: was sich gerade bewegt,
bleibt unangetastet; was stillsteht, bekommt seinen Endzustand.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.clip_recovery import sweep_orphaned_clips


def _event(tmp: Path, eid: str, stage: str, stage_since: datetime) -> Path:
    day = tmp / "motion_detection" / "cam_a" / "2026-09-06"
    day.mkdir(parents=True, exist_ok=True)
    p = day / f"{eid}.json"
    p.write_text(
        json.dumps(
            {
                "event_id": eid,
                "camera_id": "cam_a",
                "stage": stage,
                "status": stage,
                "stage_since": stage_since.isoformat(timespec="seconds"),
                "time": stage_since.isoformat(timespec="seconds"),
            }
        ),
        encoding="utf-8",
    )
    return p


def _stage_of(p: Path) -> str:
    return json.loads(p.read_text(encoding="utf-8")).get("stage")


def test_ein_frisch_gestempelter_clip_wird_nicht_angefasst(tmp_path):
    # Der Encoder arbeitet gerade daran und stempelt beim Fortschritt neu.
    now = datetime(2026, 9, 6, 12, 0, 0)
    p = _event(tmp_path, "evt_frisch", "encoding", now - timedelta(minutes=2))
    res = sweep_orphaned_clips(tmp_path, started_at=now - timedelta(minutes=15), now=now)
    assert res == {"recovered": 0, "failed": 0}
    assert _stage_of(p) == "encoding"


def test_ein_stillstehender_clip_bekommt_seinen_endzustand(tmp_path):
    # Seit 40 Minuten kein Fortschritt: der Besitzer ist weg. Ohne Video
    # daneben ist „fehlgeschlagen" die ehrliche Antwort — nicht ein
    # Kärtchen, das weiter behauptet, es werde daran gearbeitet.
    now = datetime(2026, 9, 6, 12, 0, 0)
    p = _event(tmp_path, "evt_haenger", "encoding", now - timedelta(minutes=40))
    res = sweep_orphaned_clips(tmp_path, started_at=now - timedelta(minutes=15), now=now)
    assert res["failed"] == 1
    assert _stage_of(p) == "failed"


def test_ein_fertiger_clip_bleibt_unberuehrt(tmp_path):
    now = datetime(2026, 9, 6, 12, 0, 0)
    p = _event(tmp_path, "evt_fertig", "ready", now - timedelta(hours=5))
    res = sweep_orphaned_clips(tmp_path, started_at=now - timedelta(minutes=15), now=now)
    assert res == {"recovered": 0, "failed": 0}
    assert _stage_of(p) == "ready"


def test_der_sweep_schreibt_beim_zweiten_lauf_nichts_mehr(tmp_path):
    # Er läuft alle fünf Minuten. Ein Sweep, der jedes Mal schreibt, wäre
    # eine Schreiblast auf einer Anlage, die ohnehin knapp ist.
    now = datetime(2026, 9, 6, 12, 0, 0)
    _event(tmp_path, "evt_zweimal", "encoding", now - timedelta(minutes=40))
    first = sweep_orphaned_clips(tmp_path, started_at=now - timedelta(minutes=15), now=now)
    second = sweep_orphaned_clips(tmp_path, started_at=now - timedelta(minutes=15), now=now)
    assert first["failed"] == 1
    assert second == {"recovered": 0, "failed": 0}
