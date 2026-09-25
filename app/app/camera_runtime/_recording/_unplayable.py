"""Ein Clip, der sich nicht abspielen lässt, wird nicht ausgeliefert.

„ffmpeg re-encode rc=1 … Cannot determine format of input stream 0:0
after EOF … Conversion failed! … solche Videos, wenn das passiert, dann
nehmt die bitte einfach raus. Löscht die einfach."

WAS DA PASSIERT WAR. Die Aufnahme lief nur rund drei Sekunden (Bewegung
vorbei plus Nachlauf), davon ging etwa eine Sekunde für den RTSP-
Verbindungsaufbau drauf. In den verbleibenden zwei kam kein Keyframe —
die Datei hatte einen Kopf, aber kein einziges dekodierbares Bild. Die
Rückfallschiene zeigte dann den Rohmitschnitt, weil er die 1024-Byte-
Hürde knapp nahm (1332 Byte), und in der Mediathek stand eine 1-KB-Kachel
mit Fehlermeldung. Gefunden am 2026-09-25: 18 davon auf der Gartenkamera,
14 auf der Nut Bar.

Gegen die Ursache steht eine Mindest-Aufnahmedauer im Aufnahmeschritt
(`MIN_LIVE_SEGMENT_S`). Dieses Modul ist das zweite Netz: kommt trotzdem
etwas Unabspielbares heraus, wandert es in den Papierkorb, statt als
kaputte Kachel stehenzubleiben. Papierkorb, nicht Löschen — wer es doch
sehen will, holt es dort zurück.
"""

from __future__ import annotations

from pathlib import Path

from .._consts import log


def has_decodable_frame(path: Path | None) -> bool:
    """Ob in der Datei mindestens ein Bild dekodierbar ist.

    Die Größe ist dafür kein Maß: ein MP4 mit Kopf und ohne Keyframe ist
    1332 Byte groß und nimmt jede Größen-Hürde, die niedrig genug ist,
    um einen echten Kurzclip nicht zu treffen.
    """
    if path is None or not Path(path).exists():
        return False
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        ok, frame = cap.read()
        return bool(ok and frame is not None)
    finally:
        cap.release()


def discard_unplayable(camera_id: str, event_id: str, reason: str | None) -> bool:
    """Den Clip in den Papierkorb legen. Gibt zurück, ob das gelang.

    Kein Telegram-Alarm, kein Tracking, kein Sichtungsbuch: es gibt nichts
    anzusehen, und eine Meldung mit einem Link auf ein Video, das nicht
    abspielt, ist schlechter als keine.
    """
    from ...trash import move_to_trash

    try:
        res = move_to_trash(camera_id, event_id)
    except Exception as e:
        log.warning("[%s] unplayable clip %s not trashed: %s", camera_id, event_id, e)
        return False
    log.warning(
        "[%s] clip %s unplayable, moved to trash (%s)",
        camera_id,
        event_id,
        (reason or "no decodable frame").splitlines()[-1][:120] if reason else "no decodable frame",
    )
    return bool(res.get("json_deleted"))
