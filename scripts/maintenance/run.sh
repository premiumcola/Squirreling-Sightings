#!/usr/bin/env bash
# Regelmäßiger Wartungslauf: Fehlersuche, Logikprüfung, modulare Pflege.
#
# Gedacht für die Nacht, per crontab, NACH dem Zurücksetzen des
# Nutzungslimits — frühestens 2 Uhr. Siehe docs/maintenance-runs.md.
#
# Der Lauf schreibt NICHT auf main. Er legt einen Branch an und pusht den;
# der Betreiber sieht ihn sich an und führt ihn selbst zusammen. Eine
# unbeaufsichtigte Automatik, die direkt auf main schreibt, ist genau die
# Sorte, die man nachts nicht bemerkt.
set -uo pipefail

REPO="${SQ_REPO:-$HOME/projects/Squirreling-Sightings}"
PROMPT="$REPO/scripts/maintenance/prompt.md"
LOG_DIR="${SQ_MAINT_LOG_DIR:-$REPO/storage/logs/maintenance}"
STAMP="$(date +%Y%m%d-%H%M)"
LOG="$LOG_DIR/run-$STAMP.log"

die() {
  echo "[maint] $*" >&2
  exit 1
}

command -v claude >/dev/null 2>&1 || die "claude nicht im PATH — Cron erbt kein Login-Profil, PATH in der crontab setzen"
[ -d "$REPO/.git" ] || die "kein Repository unter $REPO (SQ_REPO setzen)"
[ -f "$PROMPT" ] || die "Auftragsdatei fehlt: $PROMPT"

mkdir -p "$LOG_DIR"

# Nur die letzten 20 Protokolle behalten — ein Lauf alle paar Tage füllt
# sonst über Monate die Platte, auf der auch die Aufnahmen liegen.
ls -1t "$LOG_DIR"/run-*.log 2>/dev/null | tail -n +21 | xargs -r rm -f

BRANCH="maint/$(date +%Y-%m-%d)"

{
  echo "[maint] Start $(date --iso-8601=seconds)"
  echo "[maint] Repo: $REPO"
  echo "[maint] Branch: $BRANCH"
  echo
} >>"$LOG"

cd "$REPO" || die "cd $REPO fehlgeschlagen"

# Frischer Stand, ohne das Arbeitsverzeichnis des Betreiders anzufassen:
# nur holen, nie auschecken oder zurücksetzen.
git fetch --quiet origin >>"$LOG" 2>&1 || echo "[maint] fetch fehlgeschlagen" >>"$LOG"

BRIEF="$(cat "$PROMPT")

ZUSATZ FÜR DIESEN LAUF (unbeaufsichtigt):
- Arbeite in einem isolierten Worktree, niemals im Haupt-Checkout.
- Pushe am Ende auf den Branch '$BRANCH', NICHT auf main.
- Wenn nichts Belegbares zu tun ist, pushe nichts und sag das im Bericht.
- Läuft ohne Zuschauer: brich lieber ab und berichte, als etwas Halbes
  zu hinterlassen."

claude -p "$BRIEF" >>"$LOG" 2>&1
STATUS=$?

{
  echo
  echo "[maint] Ende $(date --iso-8601=seconds), exit=$STATUS"
} >>"$LOG"

# Bericht per Telegram. Nur der Schluss des Protokolls: dort steht die
# Zusammenfassung, und die Nachricht muss unter Telegrams Längengrenze
# bleiben. Das vollständige Protokoll liegt auf der Platte.
#
# Ein gescheiterter Lauf MUSS gemeldet werden, nicht nur ein gelungener —
# ein Wartungslauf, der still ausfällt, ist schlimmer als keiner, weil man
# ihn für erledigt hält. Deshalb wird auch bei exit != 0 gesendet.
if [ "$STATUS" -eq 0 ]; then
  TITLE="Wartungslauf $STAMP"
else
  TITLE="Wartungslauf $STAMP FEHLGESCHLAGEN (exit $STATUS)"
fi

tail -c 3000 "$LOG" | python3 "$REPO/scripts/maintenance/report.py" --title "$TITLE"
REPORT_STATUS=$?
case "$REPORT_STATUS" in
  0) : ;;
  2) echo "[maint] kein Telegram eingerichtet — Bericht nur im Protokoll" >>"$LOG" ;;
  *) echo "[maint] Telegram-Versand fehlgeschlagen (exit $REPORT_STATUS)" >>"$LOG" ;;
esac

echo "[maint] Protokoll: $LOG"
exit "$STATUS"
