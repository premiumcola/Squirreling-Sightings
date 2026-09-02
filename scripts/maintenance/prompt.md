# Wartungslauf: Fehlersuche, Logikprüfung, modulare Pflege

Du führst den regelmäßigen Wartungslauf für dieses Repository aus. Arbeite
eigenständig durch, ohne Rückfragen. Lies zuerst `CLAUDE.md` und halte dich
daran — die Regeln dort haben Vorrang vor allem hier.

## Was am Ende herauskommen soll

Ein Branch mit sauberen Commits und ein Bericht. **Nichts landet auf `main`.**
Der Betreiber sieht sich den Branch an und führt ihn selbst zusammen. Ein
unbeaufsichtigter Lauf, der direkt auf `main` schreibt, ist genau die Art
Automatik, die man nachts nicht bemerkt.

## Rahmen — unverhandelbar

- Nur in einem isolierten Worktree arbeiten. Das Haupt-Checkout niemals
  anfassen: dort liegt unkommittierte Arbeit, die dem Betreiber gehört.
- `CLAUDE.md` nirgends ändern.
- Den alten Player-Code (`mediaview/`, alles hinter `?vplayer=off`) nicht
  löschen, solange dieser Schalter noch der Notausgang ist.
- Nie mit `--force` pushen.
- Vor jedem Commit der Prüfblock aus `CLAUDE.md`, mit echten Zahlen im
  Bericht. Eine gefallene Testzahl bei einem reinen Umbau heißt, dass sich
  Verhalten geändert hat — dem nachgehen, nicht hinnehmen.
- Geheimnis-Prüfung, bevor irgendetwas gepusht wird.

## Teil 1 — Fehlersuche, jeder Fund belegt

Suche echte Fehler, keine Stilfragen. Verteile die Suche auf getrennte
Bereiche, damit parallele Agenten sich nicht ins Gehege kommen:

- Erkennungs-Pipeline und Tracker
- Aufnahme, Ereignisse, Speicherung
- Wetterdienst und Sturm-Archiv
- Telegram und MQTT
- Web-Routen
- Frontend, je Feature-Paket getrennt

Muster, die in diesem Projekt wiederholt ergiebig waren:

- ein Wert wird geschrieben und nirgends gelesen
- eine Funktion wird angeboten und nie aufgerufen (der Abspielkopf im Player
  hing genau daran — die Funktion existierte vom ersten Commit an, niemand
  rief sie auf, und der Kopf stand ein halbes Jahr auf null)
- eine Ausnahme wird still verschluckt, sodass ein Fehlschlag wie ein totes
  Bedienelement aussieht
- eine Schnittstelle verliert unterwegs ein Feld, weil sie eine Positivliste
  führt, die niemand mitgepflegt hat
- zwei Quellen behaupten dasselbe und laufen auseinander
- ein Element sieht aus wie ein Bedienelement und tut nichts

**Erst belegen, dann beheben.** Ein Test, der vorher fehlschlägt und nachher
durchläuft, oder eine nachvollziehbare Reproduktion. Was sich nicht belegen
lässt, wird im Bericht benannt und nicht geändert. Eine Korrektur auf
Verdacht hat dieses Projekt schon Monate gekostet.

## Teil 2 — Oberfläche ansehen, nicht nur lesen

    bash scripts/uishot/install-browser.sh   # einmalig
    node scripts/uishot/run.mjs

Rendert die erfassten Flächen bei 375/393/1440 px, legt PNGs unter
`.uishots/` ab und misst Überlappung, seitlichen Überlauf, Tippziele unter
44x44 und Textkontrast unter 4,5:1.

**Sieh dir die Bilder an, nicht nur die Zahlen.** Dieses Projekt hat eine
lange Reihe sichtbarer Fehler ausgeliefert, weil niemand hingeschaut hat.
Flächen, die noch fehlen, nimm auf.

## Teil 3 — modulare Pflege

Die Obergrenzen aus `CLAUDE.md` sind das Maß: Python 500 Zeilen je Datei und
80 je Funktion, JavaScript 400 und 60. Suche jede Überschreitung und teile
sie nach dem im Projekt üblichen Paketaufbau.

Zwei Fallen, in die dieses Projekt schon zweimal getappt ist:

1. Ein Re-Export bindet den Namen **nicht** im eigenen Modul. Wer die
   verschobene Konstante lokal benutzt, braucht einen echten Import.
2. Tests, die Quelltext als Text einlesen, hängen an Dateipfaden. Beim
   Verschieben mitziehen — und ihre Absicht dabei erhalten, nicht
   abschwächen.

Reiner Umzug ohne Verhaltensänderung, und das nicht behaupten, sondern
zeigen: gleiche Testzahl vorher und nachher, bei Routen die vollständige
Adressliste vorher und nachher vergleichen.

Doppelungen zusammenfassen, wo sie sich klar belegen lassen — aber nur mit
Beleg, nicht nach Gefühl.

## Bericht

Am Ende, kurz und schonungslos:

- welche Fehler gefunden und behoben wurden, jeweils mit dem Beleg
- was bewusst **nicht** angefasst wurde und warum
- welche Dateien geteilt wurden, mit Zeilenzahlen vorher/nachher
- die Prüfzahlen
- was offen bleibt

Beschönige nichts. Was nicht klappte, steht genauso drin wie das, was
klappte. Der Branchname und die Commits gehören in die erste Zeile, damit
der Betreiber sofort weiß, wo er nachsehen muss.
