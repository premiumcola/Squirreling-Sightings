# Regelmäßiger Wartungslauf

Dreimal pro Woche, nachts: Fehlersuche mit Beleg, Logikprüfung, modulare
Pflege. Der Auftrag steht versioniert in `scripts/maintenance/prompt.md`,
der Starter in `scripts/maintenance/run.sh`.

**Der Lauf schreibt nicht auf `main`.** Er legt einen Branch `maint/<datum>`
an und pusht den. Der Betreiber sieht ihn sich an und führt ihn selbst
zusammen — eine unbeaufsichtigte Automatik, die direkt auf `main` schreibt,
ist genau die Sorte, die man nachts nicht bemerkt.

## Einrichten

`crontab -e` auf der Devbox, dann:

```cron
# Cron erbt kein Login-Profil: PATH muss stehen, sonst findet es `claude` nicht.
PATH=/usr/local/bin:/usr/bin:/bin:/home/roman/.local/bin

# Mo / Mi / Fr um 01:33 — nach dem nächtlichen Zurücksetzen des
# Nutzungslimits, und auf einer krummen Minute, damit der Lauf nicht mit
# allem anderen zur halben Stunde zusammenfällt.
33 1 * * 1,3,5 /home/roman/projects/Squirreling-Sightings/scripts/maintenance/run.sh
```

Prüfen, ob der Eintrag steht: `crontab -l`.

Der Lauf verbraucht das normale Claude-Nutzungsvolumen des Betreibers —
`claude -p` ist dieselbe Anmeldung wie im Terminal, kein zweiter Dienst und
kein API-Schlüssel. Eine laufende Sitzung oder ein tmux braucht es nicht:
Cron startet den Aufruf, er arbeitet, er beendet sich.

## Bericht

Nach jedem Lauf geht eine kurze Nachricht per Telegram an den Betreiber —
über den Kanal, den die App ohnehin benutzt, also ohne neue Zugangsdaten
(`scripts/maintenance/report.py`). Auch ein FEHLGESCHLAGENER Lauf meldet
sich: ein Wartungslauf, der still ausfällt, ist schlimmer als keiner, weil
man ihn für erledigt hält.

Die Nachricht trägt den Schluss des Protokolls, gestutzt auf Telegrams
Längengrenze. Das vollständige Protokoll bleibt unter
`storage/logs/maintenance/`. Ist kein Telegram eingerichtet, ist das kein
Fehler — der Lauf vermerkt es im Protokoll und läuft weiter.

## Von Hand starten

```bash
bash scripts/maintenance/run.sh
```

Protokolle landen unter `storage/logs/maintenance/`, die letzten zwanzig
bleiben liegen.

## Was der Lauf ansehen kann — und was nicht

Er rendert die Oberfläche wirklich (`scripts/uishot/run.mjs`, Chromium
außerhalb des Repos) und misst Überlappungen, seitlichen Überlauf,
Tippziele und Kontrast bei 375/393/1440 px. Das ist eine **Layoutprüfung,
keine iOS-Prüfung**: es ist Chromium auf Linux, kein Safari, also ohne
`dvh`-Verhalten und ohne die einklappende Adressleiste — genau die Familie,
die `CLAUDE.md` als häufigste Rückfall-Ursache nennt. Der Blick aufs echte
iPhone bleibt nötig.

## Warum kein Zeitplan innerhalb von Claude

Claude Code kann Aufgaben planen, aber diese Pläne leben nur in der
laufenden Sitzung und laufen nach sieben Tagen aus. Für „dauerhaft dreimal
pro Woche" muss der Auslöser außerhalb liegen — deshalb crontab. Der Lauf
selbst ist dann wieder Claude (`claude -p` mit dem Auftrag oben), das
Versionierte daran ist der Auftrag, nicht der Zeitplan.

## Stoppen

Zeile in `crontab -e` löschen oder auskommentieren.
