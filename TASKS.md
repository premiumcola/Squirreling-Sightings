# TASKS

Laufende Aufgabenverfolgung. Ergänzt das Tuning-Board (Artifact) um die
arbeitsfähige Liste. Board = wo wir stehen, diese Datei = was zu tun ist.

## Ziel

**Alle Board-Kategorien auf > 80.** Nicht eine Kategorie perfekt, sondern
alle über die Linie — der schwächste Wert bestimmt, wie zuverlässig sich
das System anfühlt. Nach jeder erledigten Aufgabe den Reifegrad im Board
nachziehen und begründen, warum er gestiegen ist.

Board: https://claude.ai/code/artifact/0825e233-df25-4703-9101-1e43213e530b

Stand 2026-08-26 früh (Ausgangswerte): Tracking 62 · TPU 60 · Hybrid 45 ·
Kleine Objekte 45 · Einstufung 40 · Code-Hygiene 40 · Messbarkeit 45 ·
Datenhaltbarkeit 25 · User-Einstufungen 18 · Schwellen-Dynamik 15 ·
Rückfragen 15 · Lernen 14.

Die vier untersten (Lernen, Rückfragen, Schwellen-Dynamik,
User-Einstufungen) hängen alle am selben Fundament: **C4, der
Feedback-Ledger.** Ohne ihn ist dort kein Fortschritt möglich, mit ihm
werden alle vier gleichzeitig beweglich. Deshalb hat C4 Vorrang vor allem
anderen im unteren Feld.

Reihenfolge-Prinzip: erst messen (V2, M1), dann bauen. Eine Verbesserung,
die sich nicht am Replay oder an einer Log-Zahl zeigen lässt, zählt nicht.

## Arbeitsrhythmus

**Board nach jeweils 2–3 erledigten Aufgaben aktualisieren** — nicht nach
jedem Commit (Rauschen) und nicht erst am Schluss (dann ist der Stand
tagelang falsch). Aktualisiert wird nur, wenn sich fachlich etwas bewegt
hat: neuer Reifegrad mit Begründung, Protokolleintrag, geänderte
Reihenfolge. Reine Doku-Commits lösen keine Aktualisierung aus.

Das Board ist dieselbe Datei und dieselbe URL wie bisher — im Scratchpad
neu schreiben und mit demselben Pfad erneut veröffentlichen, damit der
Link stabil bleibt. Liegt der Scratchpad-Pfad nach einem Reset nicht mehr
vor: Inhalt per `action: "read"` von der URL holen, bearbeiten, mit `url`
zurückschreiben.

Status: `[ ]` offen · `[~]` in Arbeit · `[x]` erledigt · `[!]` blockiert
· `[-]` verworfen

Reihenfolge = Wirkung ÷ Risiko. IDs bleiben stabil, auch nach Erledigung.

---

## Sofort · reine Einstellungen, kein Code

Bestätigt am 2026-08-26 gegen die Live-`settings.json`.

- [ ] **S1 · Push-Schwellen senken** — der bewiesene Hauptblocker.
      Live steht exakt der Auslieferungsstand: `person 0.85`, `squirrel 0.80`.
      Die Erkennung bestätigt aber schon ab `0.45`, und eine klar sichtbare
      Person misst real `0.28–0.84` (Projektkommentar `settings/defaults.py:68`).
      Ergebnis: Clip wird gespeichert, Nachricht nie gesendet.
      → `person` und `squirrel` auf `0.45`.
- [ ] **S2 · `push` für `bird` und `cat` entscheiden** — beide stehen auf
      `false`, senden also nie, unabhängig vom Score. Für ein Projekt, das
      Vögel am Futterplatz zählt, vermutlich ungewollt — aber es ist eine
      Geschmacksfrage (Spam-Schutz), deshalb deine Entscheidung.
- [ ] **S3 · `roi_mode` auf Squirrel Town einschalten** — steht auf allen
      drei Kameras auf `off`/`None`, die Kachelung ist damit komplett inert.
      `roi` (Motion-Crop) ist der richtige Modus, nicht `2x2`/`3x3`
      (siehe N3).
- [x] **S4 · `wildlife.enabled`** — steht bereits auf `True`. Erledigt.
- [x] **S5 · `squirrel` im `object_filter` von Squirrel Town** — bereits
      enthalten. Erledigt.

## Code · hoher Wert, überschaubares Risiko

- [x] **C1 · Crop vor der Wildlife-Klassifikation** — `21932c5`.
      Der Klassifikator bekam das **volle 4-MP-Bild** auf 224×224 gequetscht.
      Jetzt: gepaddeter Crop um die Bewegungsbox (30 % Rand, min. 96 px),
      Rückfall auf das Vollbild nur ohne Bewegungsbox. Bei typischer
      Motivgröße sieht das Modell jetzt <5 % der Bildfläche statt 100 %.
      Enthielt zugleich den R1-Teilschritt: Block als eigenes
      `_wildlife_stage.py`-Mixin extrahiert, `_main_loop.py` 885→807 Zeilen.
      19 neue Tests.
- [ ] **C2 · Klassifikatoren auf die CPU** — `prefer_cpu` existiert seit
      `cbfb174`. Drei Modelle auf einer TPU mit 8 MB SRAM schreiben bei jedem
      Wechsel den Parameter-Cache über USB neu; im Live-Pfad passiert das
      mehrfach pro Wildtier-Frame. CPU ist zu ~98 % frei (Ryzen 9 5950X,
      32 Threads, Load 1,55).
- [ ] **C3 · Kachel-Pass dauerhaft auf der CPU** — `detection_tiling.py` ist
      bereits detektor-agnostisch (`tiled_detect(detector, …)`), lässt sich
      also ohne Umbau mit einem CPU-Detektor bestücken. Heute feuert die
      Kachelung nur, wenn der Vollbild-Pass **null** Treffer hatte — eine
      schwache Fehlerkennung („Katze" 0.30) verhindert die Rettung komplett.
      Liefert nebenbei das Uneinigkeits-Signal für A2.
- [ ] **C4 · Feedback-Ledger** (`storage/_diag/detection_feedback.jsonl`)
      Beim **Senden** der Telegram-Meldung Kamera, Label und Score
      denormalisiert mitschreiben. Heute speichert das Verdikt nichts davon —
      ohne diesen Datensatz ist jede Schwellen-Automatik unmöglich.
      Append-only, außerhalb `events_dir` (siehe C5).
- [ ] **C5 · Bestätigte Events vor `cleanup_old` schützen**
      (`storage.py:610`) — löscht nach Alter, **ohne Ausnahme für bestätigte
      Events**. Ein Urteilskorpus im Event-Ordner löst sich im 14-Tage-Fenster
      selbst auf. Entweder Ausnahme einbauen oder den Ledger (C4) als das
      haltbare Artefakt festlegen und Events explizit als vergänglich
      dokumentieren.
- [ ] **C6 · Telegram-Sendepfad härten** — `send_alert` schluckt jede
      Exception, `RetryAfter` (429) wird nirgends behandelt, alle echten
      Aufrufer verwerfen das zurückgegebene Future. Ein Netzaussetzer löscht
      die Meldung endgültig.
- [ ] **C7 · Conflict-Quarantäne mit Backoff statt Dauer-Aus**
      `_conflict_quarantine` (`telegram_bot/_lifecycle.py:406`) wird
      **nirgends** wieder auf `false` gesetzt. Kein Auto-Recovery, entgegen
      der eigenen Log-Meldung. Gedeckelter exponentieller Backoff + sichtbarer
      Zustand in `/api/telegram/status`.
      *Risiko: mittel — fasst die Lebenszyklus-Zustandsmaschine an. Erst mit
      einem Test, der drei schnelle Konflikte simuliert.*
- [ ] **C8 · Send-Loop-Gesundheit sichtbar machen** —
      `get_polling_status()` prüft nur den Polling-Thread. Stirbt der
      Sende-Thread, laufen alle Meldungen ins Leere, während Status und
      Heartbeat weiter „active" melden.
- [ ] **C9 · `routes/telegram.py:161`** — matcht `("polling","running",
      "active")`; die ersten beiden gibt `get_polling_status` nie zurück.
      Heute harmlos, aber irreführend.

## Verifikation

- [x] **V1 · Replay-Werkzeug** — `1a8976b`,
      `app/scripts/replay_tracking.py`. Spielt vorhandene Clips offline durch
      denselben `tracker_core`, rendert annotierte Standbilder und gibt
      Kennzahlen aus (Spuren, Frames mit Treffern, Spuren mit Label-Wechsel).
      Erzwingt `prefer_cpu`, nimmt der Live-Instanz also nie die TPU weg;
      schreibt ausschließlich nach `storage/_replay/`.
      → Aufruf siehe unten unter „Nächster Lauf".
- [ ] **V2 · Vorher/Nachher-Vergleich fahren** — Replay gegen dieselben
      Clips vor und nach `833cf74`/`21932c5`, Kennzahlen diffen. Belegt
      oder widerlegt die behaupteten Verbesserungen an echten Daten.

## Messbarkeit — Voraussetzung für alles Weitere

- [x] **M1 · Inferenz-Timing aufgesplittet** — `e2ca294`. pre / lock-wait /
      invoke / post getrennt, im Status und im Heartbeat sichtbar
      (`det[pre=8 wait=1 inv=21 post=2]ms`). Trennt jetzt "TPU langsam" von
      "Kamera-Threads streiten um den Lock" von "Letterboxing teuer" — drei
      Ursachen mit gegensätzlichen Gegenmaßnahmen. 6 Tests.
- [x] **M2 · Zähler für den D2-Rettungspfad** — `a4b12e9`. Versuche UND
      Treffer, im Status und als `roi_rescue=<hits>/<attempts>` im Heartbeat.
      Vorher wurde nur der Erfolg geloggt, womit "feuert nie" und "feuert und
      findet nichts" ununterscheidbar waren. 6 Tests, alle schlagen gegen den
      alten Stand fehl.
- [x] **M3 · Tests für `detection_tiling.py`** — `f3e8c11`. 20 Tests über
      Kachel-Geometrie, Koordinaten-Rücktransformation und Naht-Duplikate.
      Absicherungs-Tests, keine Regressionstests — sie machen C3 gefahrlos.
      Halten fest, warum `roi` dem Raster vorzuziehen ist: 2×2 bringt auf
      2560×1440 nur ~1,7× lineare Vergrößerung.

## Struktur — vor dem nächsten Feature in diesen Dateien

- [ ] **R1 · `_main_loop.py` zerlegen** — 885 Zeilen mit **einer Methode von
      ~826 Zeilen**; CLAUDE.md-Budget ist 500 pro Datei und 80 pro Funktion.
      Naht entlang: Grab/Validate · Motion+D1 · Detect+D2 · Tracker+Confirmer
      · Klassifikatoren · Recording/Alert. **Muss vor C1/C3 passieren**,
      sonst landet neuer Code in einer 826-Zeilen-Methode.
- [ ] **R2 · `tracker_core` (1114) und `tracking_worker` (1203)** — ebenfalls
      über Budget. Niedrigere Dringlichkeit als R1.

## Lernen — gestaffelt, nach Datenlage

- [ ] **A1 · Schwellen-Kalibrierung, beratend** — erst ein Skript, das sagt,
      ob überhaupt genug Urteile für Statistik existieren. Nicht bauen, bevor
      gemessen ist. Hängt an C4.
- [ ] **A2 · Gezielte Rückfragen (Active Learning)** — nur zu schweren
      Fällen fragen. Bestes Signal: **Uneinigkeit zwischen CPU- und
      TPU-Modell** (fällt bei C3 nebenbei ab), besser als Score-Nähe.
      Telegram-Buttons existieren bereits. Hängt an C3 + C4.
- [ ] **A3 · Label-Veto pro Kamera** — „Hund ist an der Werkstatt nie echt".
      Braucht kein Modell, wirkt sofort, ab wenigen Korrekturen.
- [ ] **A4 · Saubere Crops für die Wiedererkennung** — die Katzen-/
      Personen-Registry schneidet aus dem falschen Frame in falscher
      Skalierung (`routes/sichtungen.py:64`) und nutzt einen 64-Bit-Bildhash
      statt Embeddings. Voraussetzung für jede spätere Lernstufe.
- [ ] **A5 · Zweitklassifikator auf Merkmalsvektoren** — nächster Nachbar
      auf Embeddings, trainiert aus deinen Korrekturen. Ab ~10 Korrekturen je
      Klasse nützlich. Hängt an A4.

## Tracking

- [ ] **T1 · Bewegungsmodell** — die Zuordnung ist rein positional
      (IoU-Überlappung), ohne Geschwindigkeits-Vorhersage. Bei 350 ms Takt
      verliert ein schnelles Eichhörnchen die Überlappung mit sich selbst.
      Konstant-Geschwindigkeits-Prädiktor.
- [ ] **T2 · Wildlife-Treffer laufen am Tracker vorbei**
      (`_main_loop.py:344` vs `:461`) — sie bekommen nie eine Spur.

## Nächster Lauf — Startbefehle

Replay auf echten Clips (läuft im Container, nimmt der Live-Instanz nie
die TPU weg, schreibt nur nach `storage/_replay/`):

```bash
docker exec squirreling-sightings python3 /app/scripts/replay_tracking.py \
    --cam reolink_rlc811a_squirreltownnutbar_183 --latest 5 --stills 6
```

Die annotierten JPEGs liegen danach unter
`/mnt/cache-ssd/appdata/squirreling-sightings/storage/_replay/`.

## Blockiert / wartet

- [!] **B1 · Browser-Smoke MediaView** — 375 px und 393 px, Tab-Wechsel,
      Scroll-Memory, Vollbild, Mode-Chips, STREAM-Toggle. Nur am Gerät
      prüfbar, nicht headless.
- [!] **B2 · Container-Boot gegen die heutigen Commits** — noch nicht
      verifiziert. `docker compose pull && up -d`, dann Logs auf Traceback.

---

## Nicht möglich — mit dem, was stattdessen geht

- [-] **N1 · „Im Hintergrund nachtrainieren"** (neuronales Netz lernt aus
      Umklassifizierung). EdgeTPU-Modelle sind eingefroren und quantisiert;
      Corals On-Device-Lernen betrifft nur die letzte Schicht, gilt nur für
      Klassifikation und braucht `pycoral` — für Python 3.11 gibt es kein
      Wheel. → **Stattdessen A3 + A5.**
- [-] **N2 · Schwellen sofort automatisch nachziehen.** Technisch möglich,
      aber die Datengrundlage fehlt (siehe C4), und Statistik auf drei
      Beispielen schwingt nur. → **Erst C4, dann A1.**
      Für die Sicherheitskameras zusätzlich: Schwellen dürfen **sinken,
      nicht steigen** — ein verpasster Einbrecher wiegt schwerer als ein
      Fehlalarm.
- [-] **N3 · 2×2/3×3-Kachelung als Lösung für kleine Objekte.** Auf
      2560×1440 vergrößert 2×2 nur um **1,74×**, 3×3 um **2,61×** —
      dimensional zu wenig. → **Stattdessen `roi` (S3), Motion-Crop.**

---

## Erledigt

- [x] **D1 · Tracker gab die falschen Detections zurück** — `833cf74`.
      Nach der NMS-Entduplizierung indizierten die Aufrufer die alte,
      nach Label umsortierte Liste. Bei zwei Labels im Bild reicht das
      schon, ganz ohne unterdrückte Box. Folge: falsche Crops für die
      Klassifikatoren, falsche Labels, falsche Track-Nummern, und
      unterdrückte Boxen kamen zurück. 5 neue Tests.
- [x] **D2 · Boot meldete `coral tpu: not found` am laufenden Stick** —
      `e0b9f6b`. Die Prüfung verlangte „Google" **und** die Unichip-USB-ID
      gleichzeitig; der Stick wechselt die ID nach der Initialisierung.
- [x] **D3 · `prefer_cpu`, Tracking-Worker zurück auf CPU** — `cbfb174`.
      Eigene Regression aus `ad7a601`: der Delegate nimmt ohne Device-Option
      das Standardgerät, `device=None` genügte nicht mehr.
- [x] **D4 · `.trash` wird wieder geleert** — `8aa9f43`. Die Funktion war
      fertig, nur der im Docstring versprochene Aufrufer kam nie.
- [x] **D5 · `settings.json` konnte sich selbst zerstören** — `95c990d`.
      Speichern ohne Lock über gemeinsamen Temp-Pfad; bei kaputtem JSON
      überschrieb der Boot mit Defaults und verbrauchte beide Backups.
- [x] **D6 · Telegram-Doppelinstanz (T61)** — `ac9dc7e`. Zwölf Stellen
      importierten `server.py` namentlich; unter `python -m app.server`
      führt das die Boot-Datei ein zweites Mal aus. Vier davon in den
      Bot-Modulen — der Bot brachte sich beim Öffnen seines Menüs um.
- [x] **D7 · Pfad-Traversal über `cam_id`** — `e90cc9e`. Zentral als
      `before_request`.
- [x] **D8 · Coral-TPU ohne pycoral** — `ad7a601`. Über den
      tflite-EdgeTPU-Delegate; kein Python-3.9-Image nötig.
- [x] **D9 · T61-Diagnose entfristet** — `876efc8`. Das 120-s-Fenster
      verfehlte den Vorfall, der ~4 min nach Boot feuerte.
