"""Module-level constants for the bootstrap blueprint."""

from __future__ import annotations

# German user-facing strings for each (vendor, reason) pair.
_DETAIL_DE: dict[str, str] = {
    "auth_ok": "Zugangsdaten korrekt.",
    "auth_failed": "Passwort oder Benutzername ist falsch.",
    "unreachable": "Kamera ist nicht erreichbar (Port geschlossen oder Gerät offline).",
    "timeout": "Zeitüberschreitung — Kamera antwortet nicht rechtzeitig.",
    "auth_unknown": "Antwort konnte nicht eindeutig ausgewertet werden.",
    "error": "Unerwarteter Fehler beim Prüfen der Zugangsdaten.",
}
