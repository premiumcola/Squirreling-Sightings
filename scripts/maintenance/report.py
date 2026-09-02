#!/usr/bin/env python3
"""Schickt den Bericht eines Wartungslaufs per Telegram.

Bewusst NICHT über ``telegram_bot/_outbound`` gebaut: dessen ``send_alert``
komponiert Ereignis-Meldungen mit Inline-Tasten, Anker und Torprüfungen und
setzt eine laufende Anwendung voraus. Ein Wartungsbericht ist eine schlichte
Textnachricht aus einem Cron-Job, in dem keine App läuft. Geteilt wird
deshalb das, was wirklich geteilt gehört — woher Token und Chat-ID kommen —,
nicht der Versandweg für Alarme.

Reihenfolge der Quellen, erste gewinnt:

1. ``TELEGRAM_TOKEN`` / ``TELEGRAM_CHAT_ID`` aus der Umgebung
2. ``storage/settings.json`` (``telegram.token`` / ``telegram.chat_id``)
3. ``config/config.yaml`` als Saat, falls die Einstellungen noch nichts haben

Die Datei wird ausschließlich GELESEN. Ein Wartungsskript, das
``settings.json`` schreibt, wäre genau der Weg, auf dem dieses Projekt schon
einmal Zugangsdaten verloren hat.

Aufruf::

    python3 scripts/maintenance/report.py --title "Wartungslauf" --body-file <datei>
    echo "text" | python3 scripts/maintenance/report.py --title "Wartungslauf"

Rückgabe 0 bei Erfolg, 1 bei Fehler, 2 wenn kein Telegram eingerichtet ist —
das ist kein Fehler, sondern eine Anlage ohne Telegram.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SETTINGS = _REPO / "storage" / "settings.json"

#: Telegram lehnt alles über 4096 Zeichen ab. Der Bericht wird davor
#: gekürzt, mit einem Hinweis auf das vollständige Protokoll — eine
#: Nachricht, die wegen Länge gar nicht ankommt, ist schlechter als eine
#: gekürzte.
_MAX_CHARS = 3900


def _from_settings() -> tuple[str, str]:
    """(token, chat_id) aus settings.json, leer wenn nicht vorhanden."""
    try:
        data = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    tg = data.get("telegram") or {}
    if not isinstance(tg, dict):
        return "", ""
    return str(tg.get("token") or ""), str(tg.get("chat_id") or "")


def resolve_credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    file_token, file_chat = _from_settings()
    return (token or file_token).strip(), (chat_id or file_chat).strip()


def build_message(title: str, body: str) -> str:
    """Titel plus Rumpf, auf Telegrams Längengrenze gestutzt."""
    body = (body or "").strip() or "(kein Inhalt)"
    head = f"🛠 {title}\n\n"
    room = _MAX_CHARS - len(head)
    if len(body) > room:
        note = "\n\n… gekürzt · vollständig in storage/logs/maintenance/"
        body = body[: room - len(note)].rstrip() + note
    return head + body


def send(token: str, chat_id: str, text: str, timeout: float = 20.0) -> None:
    """Eine Textnachricht. Wirft bei Fehlschlag."""
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": "true"}
    ).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = urllib.request.Request(url, data=payload)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - feste Host-URL
        answer = json.loads(resp.read().decode("utf-8"))
    if not answer.get("ok"):
        raise RuntimeError(f"Telegram lehnte ab: {answer.get('description') or answer}")


def _read_body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8", errors="replace")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Wartungsbericht per Telegram")
    ap.add_argument("--title", default="Wartungslauf")
    ap.add_argument("--body-file", help="Datei mit dem Berichtstext; sonst stdin")
    args = ap.parse_args()

    token, chat_id = resolve_credentials()
    if not token or not chat_id:
        # Kein Fehler: eine Anlage ohne Telegram ist ein gültiger Zustand.
        # Der Fehlertext nennt bewusst nur die Schlüssel, nie ihren Wert.
        print("[report] kein Telegram eingerichtet (telegram.token/chat_id)", file=sys.stderr)
        return 2

    try:
        send(token, chat_id, build_message(args.title, _read_body(args)))
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as err:
        print(f"[report] Versand fehlgeschlagen: {err}", file=sys.stderr)
        return 1
    print("[report] Bericht verschickt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
