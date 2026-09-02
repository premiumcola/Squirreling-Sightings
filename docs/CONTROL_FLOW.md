# CONTROL_FLOW — die Steuerlogik von der Aufnahme bis zum Alarm

Stand: HEAD `125c746`, Zeilennummern dagegen verifiziert.
Geltungsbereich: **nur die Entscheidungskette**, nicht die Algorithmen.
Wer entscheidet was, auf welchem Zustand, in welcher Reihenfolge — und
hält das Ganze zusammen.

Was hier **nicht** steht, weil es bereits erfasst ist: `BACKLOG.md`
(THR-1 Schwellen-Landkarte, CLASS-1 Bbox-Spender, CLASS-2/T2 Wildtier
ohne Spur, SMALL-1/2/3 kleine Objekte, DIAG-1/2/3 Messbarkeit, HYG-1/2
Größenbudgets, CORP-1 Ledger) und `TASKS.md` (S1–S3 reine
Einstellungen). Wo ein Befund an eines dieser Pakete grenzt, steht die
Paket-ID und sonst nichts.

Lesehinweis zur Kennzeichnung:

- **BESTÄTIGT** — im Code gelesen, Aufruferkette nachverfolgt.
- **ABGELEITET** — aus dem Code plausibel, aber ohne Laufzeitbeleg;
  der zugehörige Prüfbefehl steht in Abschnitt 7.

---

## 1 · Die Entscheidungskette, einmal von oben nach unten

Ein Frame, eine Kamera, ein Durchlauf von `_loop`
(`app/app/camera_runtime/_main_loop.py:60`). Jede Zeile ist ein Ort, an
dem etwas entschieden wird.

### 1.1 · Aufnahme

| # | Entscheidung | Ort | liest | Zweige |
|---|---|---|---|---|
| 1 | Zwangs-Reconnect angefordert? | `_main_loop.py:108` | `self._force_reconnect` (vom Zeitraffer-Thread und vom Watchdog gesetzt) | ja → Handle schließen, 2 s schlafen, Frame verworfen · nein → weiter |
| 2 | Watchdog: Capture seit > 20 s stumm? | `_main_loop.py:87-104` | `self._last_activity` | ja → `_force_reconnect = True` (greift erst im nächsten Durchlauf) |
| 3 | Frame lesbar, nicht pink? | `_capture.py:190-212` | `capture.read()`, R/B-Kanalmittel | nein → Ausnahme → Fehlerzweig `_main_loop.py:763` mit Backoff 2–30 s |
| 4 | Unterer Streifen korrupt? | `_main_loop.py:193` | `frame_helpers.has_corrupt_strip` | ja → Frame verwerfen, `sleep(interval)` |
| 5 | Frame gültig? | `_main_loop.py:198` → `_capture.py:224` | 6 Teilprüfungen (Mittelwert, Magenta, Uniformität, Quadranten-HSV, 8×8-Blockvarianz) | nein → verwerfen; zählt bei laufender Aufnahme als `_rec_corrupt_frames` |
| 6 | Stream-Aufwärmphase? | `_main_loop.py:204` | `connect_time`, 3 s hart | innerhalb → verwerfen |

Ab hier hat `self.frame` bereits den Rohframe (Zeile 140) — Snapshot,
Livebild und Status hängen daran und sind von den Toren 4–6 **nicht**
betroffen. Das ist bewusst so und richtig.

### 1.2 · Bewegung

| # | Entscheidung | Ort | liest | Zweige |
|---|---|---|---|---|
| 7 | Bewegungsmelder an? | `_motion.py:68` / `:71` | `cfg.motion_enabled`, `processing.motion.enabled` | aus → `([], None, False, [])`, Kette endet für dieses Frame bei Tor 16 |
| 8 | Vorgängerframe vorhanden? | `_motion.py:81-83` | `self.prev_gray` | fehlt → Frame nur als Referenz gespeichert (nach jedem Reconnect ein Frame verloren) |
| 9 | Genug geänderte Pixel? | `_motion.py:154` | `sum(thresh > 0) < 0.005 · Bildfläche` | darunter → sofortiger Ausstieg **vor** jeder Konturprüfung |
| 10 | Normale Kontur groß genug? | `_motion.py:158` | `min_area = 0.005·Fläche / motion_sensitivity` | ja → `["motion"]` + Vereinigungs-Bbox |
| 11 | Wildtier-Kontur groß genug? | `_motion.py:159` | `wl_min_area = 0.001·Fläche / wl_sens` | ja und Tor 10 nein → `wildlife_motion_low = True` |
| 12 | D1: kohärente Netto-Translation? | `_main_loop.py:217-224` → `motion_blob_tracker.py:146` | Blob-Spuren, `net_disp ≥ 0.04·Bildbreite`, `age ≥ 3` | Ergebnis geht **ausschließlich** in Tor 18 |
| 13 | Bewegung 2-von-3 bestätigt? | `_main_loop.py:229-236` | `_motion_confirm`, `_motion_confirm_wl` (je `maxlen=3`) | `motion_confirmed`, `wlmotion_confirmed`, `wildlife_motion_only` |

### 1.3 · Erkennung

| # | Entscheidung | Ort | liest | Zweige |
|---|---|---|---|---|
| 14 | Roh-Inferenz | `_main_loop.py:253` | `detect_frame_raw(threshold=self._tracker.floor)` — Default **0.20** | alles darunter existiert nie |
| 15 | Klassen-Filter | `_main_loop.py:261-263` | `cfg.object_filter` (Default `["person","cat","bird"]`) | nicht enthalten → verworfen |
| 16 | Ausschlussmasken | `_main_loop.py:267` → `_zones.py:228` | `cfg.masks` | Mittelpunkt in Maske → verworfen |
| 17 | Einschlusszonen | `_main_loop.py:272` → `_zones.py:370` | `cfg.zones`, label-bezogen | außerhalb → verworfen; innerhalb → `d.zone_flags` gesetzt |
| 18 | D2-Rettung | `_main_loop.py:283-333` | `not detections` **und** kohärenter Blob **und** `roi_mode ∈ {roi,2x2,3x3}` | feuert → `tiled_detect`, dann erneut 15/16/17; Zähler `_roi_rescue_attempts/_hits` |
| 19 | Zwei-Stufen-Tracker | `_main_loop.py:353` → `tracker_core` | `score ≥ spawn_for(label)` → darf Spur starten; darunter → darf nur eine bestehende Spur verlängern | unbestätigt + keine Spur → **fallen gelassen** |
| 20 | Vogelart | `_main_loop.py:369-381` | nur `label == "bird"` | setzt `species`, entscheidet nichts |
| 21 | Wildtier-Stufe | `_main_loop.py:387` → `_wildlife_stage.py:153` | Tor: `motion_confirmed or wildlife_motion_only`, kein Blocker (`bird/dog/person`, harte Katze ≥ 0.92) **im Crop-Bereich** | Treffer → neue Detection ans Ende der Liste; kann eine weiche Katze ersetzen |
| 22 | Identität Katze/Person | `_main_loop.py:396-409` | dHash-Registry | setzt `d.identity`, entscheidet später über `whitelisted` |
| 23 | MAD-Sprung zum Vorframe? | `_main_loop.py:414-419` | `mad > 60` | ja → **ganzes Frame verwerfen**, nachdem 14–22 bereits gerechnet haben |

### 1.4 · Bestätigung

| # | Entscheidung | Ort | liest | Zweige |
|---|---|---|---|---|
| 24 | Score ≥ Spawn-Schwelle? | `_main_loop.py:456` | `label_thresholds[label]` sonst `tracker.spawn_default` (0.50) | darunter → zählt **nicht** ins Fenster; Label nur, wenn `is_confirmed` bereits True |
| 25 | N-von-M-Fenster | `_main_loop.py:471` → `detection_confirmer.py:42` | `cfg.confirmation_window[label]` sonst hart `n=3, secs=5.0` | erfüllt → `confirmed_object_labels` |
| 26 | Auslösemodus | `_main_loop.py:503-519` | `cfg.detection_trigger` | `motion_and_objects` (Default): Bewegung **oder** bestätigtes Objekt |

An dieser Stelle wird `labels` neu gebaut
(`_main_loop.py:512/515/519`) — ausschließlich aus `effective_motion` +
`confirmed_object_labels`. Alles, was die Wildtier-Stufe in `labels`
hineingeschrieben hat, ist ab hier weg (siehe F-8).

### 1.5 · Aufnahme auf Platte

| # | Entscheidung | Ort | liest | Zweige |
|---|---|---|---|---|
| 27 | Archiv an? | `_main_loop.py:529` | `cfg.recording_enabled` | aus → `continue`; **kein Ereignis, keine Meldung** |
| 28 | Aufnahmefenster aktiv? | `_main_loop.py:532` | `cfg.schedule_record` | außerhalb → `continue` |
| 29 | Ereignis-Cooldown | `_main_loop.py:563` | `has_person or elapsed ≥ cooldown` (`processing.event_cooldown_seconds`, min. 10 s) | innerhalb → kein neues Ereignis |
| 30 | Zonenflag `save_video` | `_main_loop.py:571` | aggregiert in `_motion.py:261-279` | False → `continue` (siehe F-6) |
| 31 | ffmpeg-Start | `_recording/__init__.py:163` | `_FFMPEG_AVAILABLE` + Popen | Erfolg → Stream-Copy-Pfad · Fehlschlag → OpenCV-Puffer-Pfad |

`_build_event_meta` (`_motion.py:189`) läuft **genau einmal**, im selben
Moment wie Tor 29–30, und friert `labels`, `detections`,
`alarm_level`, `severity`, `notify`, `thumb_bytes` für das gesamte Clip
ein.

### 1.6 · Schweregrad und Benachrichtigungs-Entscheidung

Alles in `_build_event_meta`:

| # | Entscheidung | Ort | liest |
|---|---|---|---|
| 32 | Whitelist | `_motion.py:208-213` | `cfg.whitelist_names`, Personen-Profil |
| 33 | Hart-Modus aktiv? | `_motion.py:205` → `event_logic.py:42` | `cfg.schedule.actions.hard` + Fenster |
| 34 | Profil-Entscheidung | `event_logic.py:100` | `alarm_profile` → `(level, notify)` |
| 35 | Severity-Matrix überschreibt | `_motion.py:224-235` → `event_logic.py:65` | `cfg.class_severity`; `notify = severity != "off"` |
| 36 | Stumm-Schalter | `_motion.py:238` | `cfg.armed` → `notify = False` |

### 1.7 · Clip-Abschluss

Hier gabelt sich die Kette in **zwei Wege, die nicht dasselbe tun**:

```
Tor 31
 ├─ ffmpeg vorhanden (Produktion)
 │    _start_ffmpeg_recording  (_recording:163)
 │    → Stub-Event "recording"  (_recording:126)
 │    → _stop_ffmpeg_and_queue_reencode (_recording:218)
 │    → _reencode_motion_clip  (_recording:271)
 │        · Video-URL, Dauer, Thumb, status=ready
 │        · MQTT
 │        · Tracking-Sidecar
 │        · KEIN Telegram, KEIN severity, KEIN first_since,
 │          KEIN Achievement, KEIN Quest, KEIN Vogel-Dossier
 │
 └─ ffmpeg fehlt (nur lokale Entwicklung)
      _finalize_motion_clip    (_recording:536)
          · alles oben PLUS
          · first_since        (:728)
          · Achievement-Unlock (:763)
          · Quest-Neubewertung (:781)
          · Vogel-Dossier      (:794)
          · Telegram           (:816-876)
```

### 1.8 · Push-Tore

Nur erreichbar über `_finalize_motion_clip` →
`TelegramService.send_event_alert` (`_outbound/__init__.py:410`):

| # | Entscheidung | Ort | Default |
|---|---|---|---|
| 37 | `notify` aus Meta | `_recording:821` | aus Tor 34/35 |
| 38 | `armed` (erneut) | `_recording:822` | True |
| 39 | Zonenflag `send_telegram` | `_recording:824` | True |
| 40 | `cfg.telegram_enabled` | `_recording:841` | True |
| 41 | `push.enabled` | `_outbound:419` | True |
| 42 | globaler Mute | `_outbound:446` | aus |
| 43 | Kamera-Mute | `_outbound:455` | aus |
| 44 | `push.labels[primary].push` | `_outbound:461` | person/dog/car/squirrel True · **cat/bird/motion False** · fox/hedgehog fehlen ⇒ False |
| 45 | Score ≥ Push-Schwelle | `_outbound:492` | person 0.85 · squirrel 0.80 · car 0.85 · dog 0.80 · bird 0.90 |
| 46 | Suppress-Fenster | `_outbound:501` | leer |
| 47 | Rate-Limit pro Kamera | `_outbound:504` | 30 s, **labelübergreifend** |
| 48 | Cooldown pro Klasse | `_outbound:518` | person 60 · cat/dog 120 · bird/squirrel 300 · car/motion 30 |
| 49 | `schedule_notify`-Fenster | `_outbound:544` | leer ⇒ Rückfall auf `schedule.actions.telegram` |
| 50 | Bot lebt / `enabled` | `_outbound:136` | — |

`silent`/`dark` (Ruhezeiten, Nachtweckung) entscheiden danach nur noch
über die *Art* des Pushs, nicht mehr über das Ob
(`_outbound:553-574`).

---

## 2 · Die Torliste: was ein echtes Ereignis überleben muss

Gezählt wird ein **korrekt erkannter Mensch** auf einer RTSP-Kamera mit
Auslieferungsdefaults, von der Frame-Ankunft bis zur Telegram-Bubble.
Nicht gezählt sind Fehlerpfade (Netzabbruch, ffmpeg-Absturz) — nur
Stellen, an denen eine *richtige* Erkennung planmäßig verworfen wird.

Von den 50 Entscheidungspunkten in Abschnitt 1 sind

- **35 Tore**, an denen eine echte Erkennung verworfen wird:
  4–10, 13–17, 19, 23–30 (21 Stück vor der Meldung) und 37–50
  (14 Stück in der Meldung). Nicht mitgezählt: 1–3 und 31
  (Fehler-/Wiederanlaufpfade), 11, 12, 18, 20–22, 31–36
  (Zustands-, Anreicherungs- oder Formatentscheidungen).
- **20 davon schreiben beim Verwerfen keine Zeile oberhalb von DEBUG**:
  4, 5, 6, 7, 8, 9, 10, 13, 14, 15, 16, 17, 19, 24, 26, 27, 28, 29, 30
  und 41.

Nach Motiv unterschieden:

| Motiv | wirksame Tore |
|---|---|
| Person, Modus `motion_and_objects` (Default) | **30** — die reinen Bewegungstore 7–10 und 13 verwerfen sie nicht, weil ein bestätigtes Objekt allein auslöst |
| Person, Modus `motion_only` | **35** |
| Eichhörnchen / Fuchs / Igel | **35** — die Wildtier-Stufe sitzt hinter dem Bewegungstor (`_wildlife_stage.py:140`), also greifen 7–10 und 13 immer |

**Von den 35 Wegen, auf denen eine echte Erkennung verschwinden kann,
sind 20 im Betrieb unsichtbar.** Die gesamte vordere Hälfte der Kette —
Aufnahme, Bewegung, Filter, Tracker, Zeitpläne, Cooldown — schweigt.
Erst ab Tor 37 (`[trigger] alert routing`) wird protokolliert. Das ist
der Grund, warum sich das System „unzuverlässig" anfühlt statt „falsch
konfiguriert": für 20 der 35 Abbrüche gibt es keinen Beleg.
(DIAG-1/DIAG-3 im Backlog adressieren genau das; diese Liste ist, was
dort einzutragen ist.)

Und der Nachsatz, der den Rest relativiert: **die Tore 37–50 sind in der
Produktion gar nicht erreichbar** (F-1). Effektiv endet die Kette heute
bei Tor 31 — bei 21 Toren, von denen 19 schweigen.

---

## 3 · Befunde

Sortiert nach Schwere. Jeder Befund: Ort, was bricht, konkretes
Szenario, Behebung.

---

### F-1 · Der Produktionspfad ruft den Melder nie auf — **KRITISCH, BESTÄTIGT**

**Ort** — `app/app/camera_runtime/_recording/__init__.py:423-427`
(der Kommentar), `:536` (`_finalize_motion_clip`), `_main_loop.py:656`
(einziger Aufrufer), `app/docker/Dockerfile:17` (ffmpeg ist im Image).

**Was bricht** — `send_event_alert` hat im gesamten Repository **genau
einen** Aufrufer: `_finalize_motion_clip`. `_finalize_motion_clip` hat
**genau einen** Aufrufer: `_main_loop.py:655-659`, im
`else`-Zweig von `if self._ffmpeg_proc is not None`. Dieser Zweig läuft
nur, wenn `_start_ffmpeg_recording` fehlgeschlagen ist oder
`_FFMPEG_AVAILABLE` False ist. Im Container ist ffmpeg installiert
(`Dockerfile:17`). Der Produktionspfad ist also
`_start_ffmpeg_recording → _stop_ffmpeg_and_queue_reencode →
_reencode_motion_clip` — und `_reencode_motion_clip` sendet nichts.

Der Kommentar bei `:423-427` behauptet das Gegenteil:

```python
# Telegram alert is fired once, by the modern push pipeline in
# _finalize_motion_clip via TelegramService.send_event_alert. The
# legacy send_alert_sync alert that used to live here was a duplicate
```

Eingeführt in `bd21b64` („fix: alert footer buttons (livebild+clip5)
work", 2026-04-27). Die Deduplizierung war korrekt gedacht — nur wurde
der falsche der beiden Aufrufe entfernt: der auf dem Pfad, der
tatsächlich läuft.

**Mit derselben Ursache tot:** `severity` im Event-JSON,
`first_since` (`:728`), Achievement-Unlock (`:763`),
Quest-Neubewertung (`:781` — der Stundenjob in `maintenance.py:61`
fängt das auf), Vogel-Dossier (`:794`), `achievement`-Block (`:696`).
Für ffmpeg-Clips trägt das Event-JSON keinen `severity`-Schlüssel.

**Szenario** — Person betritt die Werkstatt. Bewegung bestätigt, Person
bestätigt, `notify=True`, `armed=True`, `push.labels.person.push=True`,
Score 0.91 über der 0.85er Schwelle, kein Mute, kein Cooldown, Fenster
offen. Der Clip landet auf der Platte, das Event erscheint in der
Mediathek, MQTT feuert. Telegram bleibt still. Im Log gibt es dazu
**keine einzige Zeile** — nicht einmal `[tg] notify-attempt`, weil der
Melder nie betreten wird.

**Warum es niemandem auffiel** — die Testsuite (495 Tests) enthält
keinen einzigen Test über `_reencode_motion_clip` oder den
Melder-Übergabepunkt. `grep -rl "reencode\|finalize_motion\|
send_event_alert" app/tests/` liefert nichts.

**Behebung** — `_reencode_motion_clip` muss denselben Block wie
`_finalize_motion_clip:816-876` ausführen. Sauberer als Kopieren:
den Abschluss-Block (Event-JSON-Anreicherung, `first_since`,
Achievements, Quests, Dossier, Telegram-Übergabe) in eine eigene
Methode `_publish_finalized_event(event, meta, thumb_rel)` ziehen und
aus **beiden** Pfaden aufrufen. Das ist zugleich der HYG-1-Schnitt für
`_recording` und beseitigt die Divergenz dauerhaft. Regressionstest:
ein Stub-Notifier, der `send_event_alert` zählt, muss nach einem
simulierten ffmpeg-Reencode genau 1 sehen.

**Vorrang** — vor S1. Solange F-1 offen ist, ändert das Absenken der
Push-Schwellen von 0.85 auf 0.45 exakt nichts: es gibt kein
Push-Tor, das erreicht würde.

---

### F-2 · Die Ereignis-Labels frieren eine Frame zu früh ein — **KRITISCH, BESTÄTIGT**

**Ort** — `_main_loop.py:560-566` (Auslösung + `_build_event_meta`),
`_motion.py:189` (das eingefrorene Meta), `_outbound:458-463`
(Konsument).

**Was bricht** — `_build_event_meta` wird **nur** im Zweig
`if has_motion and not self._recording` gerufen. Danach ist
`self._recording = True` und `self._rec_event_meta` wird bis zum
Clip-Ende nicht mehr angefasst. Ein Objekt, das erst *während* des
Clips bestätigt wird, kommt nie in `meta["labels"]`.

Und die Reihenfolge garantiert genau das: Bewegung braucht 2 von 3
Frames (`_main_loop.py:234`), eine Person braucht 3 Treffer in 5 s
(`settings/_consts.py:124`). Bei 350 ms Takt ist Bewegung nach ~0,7 s
bestätigt, die Person frühestens nach ~1,05 s. Im Standardmodus
`motion_and_objects` löst Bewegung allein aus (`_main_loop.py:518`).
**Die Bewegung gewinnt praktisch immer um mindestens ein Frame.**

Ergebnis: `meta["labels"] == ["motion"]`. Daraus folgt in Kaskade:

1. `compute_severity_from_matrix(class_severity, ["motion"])` — bei
   Profil `hard`/`medium`/`info` ist `motion: "off"`
   (`settings/_consts.py:173-210`) → `notify = False`
   (`_motion.py:230`). Das Ereignis ist schon vor Telegram tot.
2. Bei Profil `soft` ist `motion: "info"` → `notify = True`, aber
   `most_specific_label(["motion"]) == "motion"` und
   `push.labels.motion.push == False` (`settings/_consts.py:34`) →
   Tor 44 verwirft.
3. `has_person = "person" in labels` (`_main_loop.py:561`) ist False —
   die Ausnahme, die eine Person vom 10-s-Cooldown befreien soll,
   greift für Personen nie.

Kurios und diagnostisch irreführend: `top_label` im selben Meta wird
aus `detections` gebildet (`_motion.py:194`), also **inklusive
unbestätigter** Erkennungen. Das Event-JSON sagt daher oft
`top_label: "person"` bei `labels: ["motion"]`. Die Mediathek zeigt
„Person", der Push-Pfad sieht „Bewegung".

**Szenario mit Arithmetik** — Werkstatt, Profil `medium`, Takt 350 ms.

| t | Frame | `_motion_confirm` | Confirmer person | `motion_confirmed` | Aktion |
|---|---|---|---|---|---|
| 0,00 s | N | [1] | 1 Treffer | nein | — |
| 0,35 s | N+1 | [1,1] | 2 Treffer | **ja** | `has_motion=True`, `_build_event_meta(labels=["motion"])`, ffmpeg startet, `_recording=True` |
| 0,70 s | N+2 | [1,1,1] | **3 Treffer → BESTÄTIGT** | ja | `confirmed_object_labels=["person"]` — aber `_recording` ist bereits True, Meta wird nicht neu gebaut |
| … | | | | | Clip läuft 12 s mit Person im Bild |
| Ende | | | | | Event: `labels=["motion"]`, `severity="off"`, `notify=False` |

Im Log steht `[det][cam:…] ✅ BESTÄTIGT: person` — und danach nichts
mehr. Genau die Kombination, die als „er erkennt es doch, meldet aber
nicht" wahrgenommen wird.

**Behebung** — zwei Teile, beide klein:

1. **Meta nachziehen.** Solange `self._recording` läuft und neue
   Labels bestätigt werden, `self._rec_event_meta["labels"]` additiv
   ergänzen und `alarm_level`/`severity`/`notify` neu auflösen. Ein
   Aufruf von `choose_alarm_level` + `compute_severity_from_matrix`
   auf der erweiterten Labelmenge, nicht mehr. Das ist der
   *richtige* Ort — nicht der Push-Pfad, weil auch MQTT, Mediathek
   und Statistik dieselben Labels lesen.
2. **`_build_event_meta` erst mit Anlauf.** Alternativ die Auslösung
   um genau ein Bestätigungsfenster verzögern, wenn ein Objekt sich im
   Confirmer bereits sammelt. Teurer und fehleranfälliger als (1);
   nur nötig, wenn (1) nicht reicht.

Regressionstest: Clip startet auf Bewegung, zwei Frames später wird
`person` bestätigt → `meta["labels"]` enthält `person`, `notify` ist
True. Schlägt gegen den heutigen Stand fehl.

---

### F-3 · Der Wind-Filter schützt den Pfad nicht, den er zu schützen behauptet — **HOCH, BESTÄTIGT**

**Ort** — `_motion.py:132-147` (die Begründung),
`_main_loop.py:283-288` (der einzige Verbraucher von `_coherent_blob`),
`_wildlife_stage.py:140` (das Tor der Wildtier-Stufe).

**Was bricht** — Der Kommentar in `_motion.py:137-141` begründet die
Absenkung des Wildtier-Flächenbodens von 0,005 auf 0,001 so:

> „A LOW area floor is safe because the D1 motion-blob tracker
> (coherent net translation) is the real wind filter, not area."

Der D1-Blob-Tracker wird aber ausschließlich in der Bedingung der
D2-ROI-Rettung gelesen (`_main_loop.py:286`). Das Tor der
Wildtier-Stufe lautet:

```python
if not (motion_confirmed or wildlife_motion_only):
    return False
```

`_wildlife_stage.py:140-141` — **kein `_coherent_blob`**. Der
Wildtier-Klassifikator läuft also auf jedem Frame, dessen
Wildtier-Fläche zweimal in drei Frames über dem abgesenkten Boden lag,
ganz gleich ob sich der Blob bewegt hat. Der Schutz, mit dem die
Absenkung gerechtfertigt wurde, existiert auf diesem Pfad nicht.

Zusätzlich ist `roi_mode` laut `TASKS.md:93` auf allen drei Kameras
`off` — damit ist D1 heute **überhaupt nirgends** wirksam. Der Tracker
läuft (`_main_loop.py:217`), sammelt Zustand, und sein Ergebnis wird von
einer Bedingung gelesen, die durch `det_mode in ("roi","2x2","3x3")`
immer False ergibt.

**Szenario** — Futterhaus, windiger Nachmittag, Haselnussstrauch im
Bild. Blätterschwingen erzeugt eine Kontur über
`wl_min_area = 0,001·Fläche / 0,7 ≈ 5 300 px` auf 2560×1440. Zwei von
drei Frames reichen → `wildlife_motion_only = True` → die Wildtier-Stufe
läuft. Sie schneidet den Bewegungskasten aus, klassifiziert Blätter,
liefert gelegentlich „squirrel" knapp über `wildlife_min_score`
(Default 0,35, `detectors/wildlife.py:73`), und `_refine_wildlife_bbox`
(`_consts.py:85`) startet dafür **eine zweite vollständige
COCO-Inferenz auf dem HD-Frame**. Bei 350 ms Takt sind das im
Dauerwind bis zu 3 Zusatzinferenzen pro Sekunde, plus Fehlalarme.

**Behebung** — `_coherent_blob` bis in `_apply_wildlife_stage`
durchreichen und das Tor auf
`motion_confirmed or (wildlife_motion_only and coherent_blob is not
None)` erweitern. Damit gilt die Begründung aus `_motion.py:137` wieder,
und D1 bekommt seinen zweiten Verbraucher — den, für den er beschrieben
wurde. Grenzt an SMALL-2/SMALL-3 (dort geht es um die Empfindlichkeit
von D1, hier um seinen Anschluss); der Anschluss ist unabhängig davon
und sollte zuerst kommen.

---

### F-4 · Ein Tor beherrscht das andere: der Wildtier-Boden ist wirkungslos — **HOCH, BESTÄTIGT**

**Ort** — `_motion.py:154-155` gegen `_motion.py:147`.

**Was bricht** — Vor jeder Konturprüfung steht:

```python
if int(np.sum(thresh > 0)) < int(h_f2 * w_f2 * 0.005):
    return [], None, False, []
```

Das verlangt **0,5 % der Bildfläche** an geänderten (bereits dilatierten)
Pixeln. Drei Zeilen darüber wird der Wildtier-Flächenboden auf
**0,1 %** gesetzt:

```python
wl_min_area = int(frame_area * 0.001 / max(0.1, wl_sens))
```

Auf 2560×1440 (3 686 400 px):

| Größe | Wert |
|---|---|
| Vorprüfung Tor 9 | 18 432 px |
| `wl_min_area` bei `wl_sens = 0,7` (auto aus `motion_sensitivity = 0,5`) | 5 266 px |
| Verhältnis | **3,5×** |

Ein Blob muss also mindestens das 3,5-Fache seines eigenen
konfigurierten Bodens erreichen, damit die Kette ihn überhaupt
betrachtet. Der Boden bei 0,1 % ist damit **tot** — er kann unter dieser
Vorprüfung nie greifen. Der Kommentar bei `_motion.py:148-152` beschreibt
die Vorprüfung als „0.5% floor (down from 1%) so a single squirrel/fox
can still trigger the wildlife threshold"; danach wurde der
Wildtier-Boden noch einmal um den Faktor 5 gesenkt, die Vorprüfung aber
nicht. Zwei Schwellen, die sich widersprechen — eine davon wirkungslos.

**Szenario** — das Eichhörnchen aus dem B4-Inventar (≈ 11 000 px, 0,3 %
der Fläche) sitzt am Futterbrett. `wl_min_area` würde es durchlassen
(11 000 > 5 266). Tor 9 lässt es nicht durch (11 000 < 18 432). Ergebnis:
`_motion_detect` gibt `([], None, False, [])` zurück — keine Bewegung,
kein Wildtier-Flag, **keine Blobs für D1**. Weder die Wildtier-Stufe
noch die D2-Rettung bekommen den Fall je zu sehen. SMALL-3 im Backlog
will D1 empfindlicher machen; das hilft nicht, solange D1 den Blob nicht
angeboten bekommt.

**Behebung** — die Vorprüfung an den *niedrigsten* aktiven Boden
koppeln statt an eine unabhängige Konstante:
`min(min_area, wl_min_area) · 0,5` als Pixelsumme, mit einem harten
Mindestwert gegen Sensorrauschen. Der Zweck der Vorprüfung (globale
Helligkeitsschübe abfangen, die viele kleine Pixel aber keine große
Kontur erzeugen) bleibt erhalten, weil die Konturprüfung darunter die
eigentliche Arbeit macht. Test: 2560×1440-Frame mit einem einzelnen
11 000-px-Blob ⇒ `wildlife_motion_low is True` und `wl_blobs` hat einen
Eintrag. Schlägt gegen den heutigen Stand fehl.

---

### F-5 · Fuchs und Igel können systembedingt nie melden — **HOCH, BESTÄTIGT**

**Ort** — `detectors/_wildlife_rules.py:15-23` (die Labels werden
erzeugt), `settings/_consts.py:27-35`, `:114-119`, `:123-128`,
`:173-210` (nirgends vorhanden), `schema.py` (nicht erwähnt).

**Was bricht** — Der Wildtier-Klassifikator kennt drei Ausgabeklassen:
`squirrel`, `fox`, `hedgehog`. `squirrel` existiert in allen
Konfigurationsflächen. `fox` und `hedgehog` existieren in **keiner**:

| Fläche | `squirrel` | `fox` / `hedgehog` |
|---|---|---|
| `TELEGRAM_PUSH_DEFAULTS["labels"]` | `{push: True, threshold: 0.80}` | **fehlt** |
| `LABEL_THRESHOLD_DEFAULTS` | 0.45 | fehlt → Spawn 0.50 |
| `CONFIRMATION_WINDOW_DEFAULTS` | n=2 / 3 s | fehlt → hart n=3 / 5 s |
| `ALARM_PROFILE_TO_SEVERITY` (alle 4 Profile) | `info`/`off` | **fehlt** |
| `default_camera.object_filter` | nein (nachzutragen) | nein |

Drei voneinander unabhängige Sperren:

1. `compute_severity_from_matrix(class_severity, ["fox"])` →
   `class_severity.get("fox")` ist None → `"off"`
   (`event_logic.py:78`) → `notify = False`. Und `class_severity` ist
   seit `migrate_class_severity` (`settings/migrations.py:160-175`) auf
   **jeder** Kamera nicht-leer, der Matrix-Zweig greift also immer.
2. Ohne Matrix käme `choose_alarm_level` zum Zug — auch dort taucht
   `fox` in keiner Label-Liste auf (`event_logic.py:123-136`), Ergebnis
   `("logged", False)` außer bei Profil `soft`.
3. `push.labels.get("fox", {}).get("push", False)` → False
   (`_outbound:461`).

**Szenario** — Ein Fuchs quert nachts den Garten. Die Wildtier-Stufe
erkennt ihn mit 0,71. Die Erkennung steht im Event-JSON, die Mediathek
zeigt „Fuchs", das Achievement `fuchs` existiert
(`camera_runtime/_consts.py:56`). Telegram meldet nichts — und wird
nie etwas melden, egal welchen Schieberegler man bewegt, weil es für
diese Klasse keinen Schieberegler gibt.

**Behebung** — `fox` und `hedgehog` in alle vier Tabellen in
`settings/_consts.py` nachtragen (Schwellen analog `squirrel`), mit
additiver Migration im Muster von `migrate_telegram_push_defaults`.
Reine Datenpflege, kein Logikeingriff. Gehört fachlich in THR-1 (das
ohnehin `settings/defaults.py` + `_consts.py` + `migrations.py` +
`schema.py` als FILE SCOPE hat) — dort als Teilschritt aufnehmen, statt
einen zweiten Migrationslauf über dieselben Dateien zu legen.

---

### F-6 · `save_video: false` verwirft das ganze Ereignis und dreht die Schleife frei — **MITTEL, BESTÄTIGT**

**Ort** — `_main_loop.py:571-577`.

```python
if not rec_meta.get("save_video", True):
    log.debug(...)
    continue
```

Zwei Fehler in fünf Zeilen:

1. **Zu breit.** Die Zonenflags kennen drei getrennte Kanäle
   (`save_photo`, `save_video`, `send_telegram`,
   `_zones.py:449-452`). Auf dem RTSP-Pfad führt `save_video: false`
   dazu, dass gar kein Ereignis entsteht: kein JSON, kein MQTT, kein
   Telegram, kein Zähler. `save_photo` wird auf dem RTSP-Pfad
   überhaupt nie gelesen — nur der Snapshot-Zweig
   (`_main_loop.py:690`) wertet ihn aus. Wer eine Zone auf „kein
   Video, aber melden" stellt, bekommt Stille.
2. **Ohne Pause.** Dieses `continue` überspringt das
   `time.sleep(interval)` am Schleifenende (`_main_loop.py:818`). Alle
   anderen Abbrüche (`:195`, `:201`, `:205`, `:418`, `:530`, `:533`)
   schlafen vorher. Solange die Bewegung anhält, dreht die Schleife mit
   voller Geschwindigkeit — inklusive Coral-Inferenz je Umlauf.

**Szenario** — Zone „Straße" mit `save_video: false` (üblicher Wunsch:
Verkehr nicht archivieren, aber Personen melden). Ein Auto fährt 8 s
durchs Bild. Die Schleife läuft in dieser Zeit statt ~23 Umläufen so
viele, wie die TPU hergibt — bei 25 ms Inferenz rund 320 — und hält
dabei den Coral-Lock. Die beiden anderen Kameras warten.

**Behebung** — `continue` durch das Auslassen **nur** des Clip-Starts
ersetzen: Meta bauen, Event-JSON schreiben, MQTT und Telegram normal
durchlaufen lassen, nur `_start_ffmpeg_recording` überspringen. Und in
jedem Fall vorher `time.sleep(interval)`.

---

### F-7 · Der Klassen-Cooldown wird scharfgestellt, bevor die letzten Tore geprüft sind — **MITTEL, BESTÄTIGT**

**Ort** — `_outbound/__init__.py:518-531` gegen `:542-550`.

**Was bricht** — Der Cooldown-Block schreibt
`self._last_notify[key] = now_mono` (`:531`) und **danach** kommt noch
das `schedule_notify`-Tor (`:544`), das mit `return` abbrechen kann.
Ein Push, den der Zeitplan verwirft, hat den Cooldown trotzdem
gestartet.

Der Kontrast im selben Modul ist aufschlussreich: `record_alert`
(`:480-491`) steht bewusst **über** allen Toren, mit einem
ausführlichen Kommentar warum. `_record_rate_limit` (`:650`) steht
korrekt **nach** dem Senden. Nur `_last_notify` sitzt in der Mitte.

**Szenario mit Arithmetik** — Werkstatt, `schedule_notify` 07:00–22:00,
`notification_cooldown.person` = 60 s (Default).

| Uhrzeit | Ereignis | Tor | Wirkung |
|---|---|---|---|
| 06:59:30 | Person, Score 0.91 | Cooldown (`:518`): `last = 0` → passiert, **`_last_notify = t0`** | — |
| 06:59:30 | dieselbe | `schedule_notify` (`:544`): 06:59 < 07:00 → `return` | kein Push, Log: `[tg] skip: schedule_notify blocks` |
| 07:00:15 | dieselbe Person, immer noch im Bild, neuer Clip | Cooldown: `elapsed = 45 s < 60 s` → `return` | kein Push, Log: `[tg] skip: cooldown active (15s remaining)` |
| 07:00:30 | Person ist weg | — | — |

Der erste echte Alarm des Tages wird von einem Cooldown geschluckt, den
ein verworfener Push gestartet hat. Beide Log-Zeilen sind für sich
plausibel; zusammen ergeben sie ein verpasstes Ereignis, das im Log wie
zwei normale Vorgänge aussieht.

**Behebung** — den Schreibvorgang `self._last_notify[key] = now_mono`
ans Ende von `send_event_alert` verschieben, unmittelbar neben
`self._record_rate_limit(camera_id)` (`:650`). Der Lesevorgang bleibt,
wo er ist. Test: ein Aufruf, der am `schedule_notify`-Tor scheitert,
darf `_last_notify` nicht verändern.

---

### F-8 · Zustand, den niemand liest, und ein Regler, der nirgends wirkt — **MITTEL, BESTÄTIGT**

Drei Fälle derselben Art.

**(a) `labels` aus der Wildtier-Stufe.** `_apply_wildlife_stage` gibt
`(detections, labels)` zurück (`_wildlife_stage.py:251`) und pflegt
`labels` sorgfältig: entfernt `"cat"` beim cat→squirrel-Override
(`:233`), filtert unterdrückte Labels (`:243-247`), hängt `cat` an
(`:250`). Zwischen `_main_loop.py:387` (Rückgabe) und
`_main_loop.py:512` (Neuzuweisung) wird diese Liste **nie gelesen**.
Die Wirkung entsteht ausschließlich über `detections`. Der ganze
Label-Zweig der Funktion ist Dekoration — und irreführende: er
suggeriert, der Override entferne „Katze" aus dem Ereignis, während
das in Wahrheit die Detection-Entfernung tut. Behebung: `labels` aus
Signatur und Rückgabe streichen, Funktion gibt nur noch `detections`
zurück. Der Aufrufer baut `labels` ohnehin neu.

**(b) `confirmation_window.global`.** Die Oberfläche schreibt den
Schlüssel (`camedit/detection-perclass.js:176`), hydriert ihn zurück
(`hydration/erkennung.js:69,74`), das Event-JSON meldet ihn als
`recording_settings.confirm_n/confirm_seconds`
(`_recording:468,477-478`), und der Ghost-Pruner des Nachlauf-Trackers
liest ihn (`tracking_worker/__init__.py:589,1096`). **Der Live-Confirmer
liest ihn nicht** — `_main_loop.py:452` macht
`cw_cfg.get(d.label) or {}` und fällt für jedes Label ohne eigenen
Eintrag auf hart kodierte `n=3, seconds=5.0` zurück (`:453-454`).
Wer den globalen Regler auf 2/3 s stellt, ändert damit nur das
Nachlauf-Verhalten und das, was das Event-JSON über sich behauptet.
Behebung: `_main_loop.py:452` auf
`cw_cfg.get(d.label) or cw_cfg.get("global") or {}` erweitern — eine
Zeile, und der Regler tut, was er verspricht.

**(c) `detection_min_score` — inzwischen NIRGENDS angewendet.** Der
Live-Pfad ignoriert das Feld bewusst (`_main_loop.py`, `detect_frame_raw`
bekommt `setup.floor`). Die beiden Leser, die hier früher standen, sind
seit dem Threshold-Umbau weg: `routes/coral_test_detection.py` liest
`min_score` überhaupt nicht mehr, und der Ghost-Pruner geht über
`thresholds.resolve_effective(...).spawn` (`_ghosts.py`). Ein `grep` über
`app/` findet heute kein Gate, das den Wert konsultiert —
`test_sim_production_parity.py::test_the_global_min_score_is_carried_but_never_a_gate`
hält das als Vertrag fest („no gate may consult min_score").

Der Schieberegler ist ebenfalls verschwunden: der Kamera-Editor pinnt
den Wert beim Speichern auf `0.0` (`camedit/discovery.js`). Übrig sind
drei reine Anzeigen — die Netz-Liste „Werte, die fest bleiben"
(`routes/_netz_helpers.py`), die SCHWELLEN-Zeile im Simulieren-Panel
(`mediaview/live-detect-tabs.js`) und die archivierten
`conf_thresh_general`-Werte in der Mediathek.

Entscheidung (2026-09): **markieren statt verdrahten.** Verdrahten würde
den obigen Vertragstest brechen, die Erkennung für JEDE Kamera
verändern und über `replay/_settings.py` auch archivierte Werte in
Nachsimulationen scharf schalten — drei Verhaltensänderungen als
Nebenwirkung einer Anzeige-Korrektur. Die beiden nicht-archivierten
Anzeigen sagen jetzt „ohne Wirkung"; die archivierten Werte bleiben, was
sie sind: ein historischer Eintrag.

---

### F-9 · Dieselbe Schwellenfrage, drei verschiedene Antworten — **MITTEL, BESTÄTIGT**

**Ort** — Live: `_main_loop.py:253` + `:341-347` + `:456`.
Simulation: `routes/coral_test_detection.py:440-445`. Nachlauf-Tracker:
`tracking_worker/__init__.py:560-586`.

| Pfad | Auflösungsreihenfolge für „ab wann zählt eine Erkennung" |
|---|---|
| Live | `label_thresholds[label]` → `track_spawn_min_score` → **0.50** |
| Simulation („Erkennung jetzt simulieren") | `setup.floor` — dieselbe Auflösung wie live (`_sim_pipeline.py`) |
| Ghost-Pruner (Sidecar) | `thresholds.resolve_effective(...).spawn` — dieselbe Leiter wie live |

**Stand 2026-09: die drei Antworten sind inzwischen EINE.** Die Tabelle
oben beschreibt den Zustand nach dem Threshold-Umbau; die frühere
Divergenz (Simulation 0.55 gegen Live 0.50 über `detection_min_score`)
existiert nicht mehr, weil kein Pfad den Wert noch liest. Der Abschnitt
bleibt als Beleg stehen, warum `detection_min_score` heute nur noch
angezeigt und nicht angewendet wird — siehe F-8c.

Für ein Label ohne eigenen Eintrag — `dog`, `car`, `fox`, `hedgehog` —
liegen Live (0.50) und Simulation (0.55) auseinander. Eine
0.52er-„dog"-Erkennung erscheint im Simulationspanel rot als
„unterhalb der Schwelle" und löst live eine Spur aus. Das Werkzeug, mit
dem man die Kette prüft, widerspricht der Kette.

THR-1 im Backlog baut mit `app/app/thresholds.py` genau den Ort, an dem
diese Reihenfolge einmal steht. Dieser Befund ist die
Vollständigkeitsliste der Konsumenten, die dort umzustellen sind — es
sind drei, nicht einer, und der Simulationsknopf gehört ausdrücklich
dazu.

---

### F-10 · Zwei Melde-Pfade mit völlig verschiedenen Toren — **MITTEL, BESTÄTIGT**

**Ort** — `_main_loop.py:734-761` (Snapshot-Kameras) gegen
`_recording:816-876` + `_outbound:410` (RTSP-Kameras).

**Was bricht** — Eine Snapshot-Kamera (kein `rtsp_url`) meldet über
`send_alert_sync` (`_outbound:184`). Dieser Weg kennt **keines** der
Tore 41–49: keinen Mute, keine Push-Schwelle, kein Rate-Limit, keinen
Klassen-Cooldown, kein `schedule_notify`, keine Ruhezeiten, keinen
Ledger-Eintrag. Er prüft `notify`, `armed`, `send_telegram` — und
sendet. Eine RTSP-Kamera durchläuft alle neun.

Heute laufen alle drei Kameras auf RTSP, der Befund ist also latent.
Er wird akut, sobald eine Snapshot-Quelle dazukommt (die
Reolink-HTTP-CGI-Felder in `schema.py` deuten darauf hin, dass das
vorgesehen ist).

**Behebung** — der Snapshot-Zweig soll dieselbe Übergabe benutzen:
`meta` bauen (tut er bereits, `_main_loop.py:681`) und
`send_event_alert(meta=…, camera_id=…, snapshot_path=…)` rufen statt
`send_alert_sync`. Fällt zusammen mit F-1: wenn der Abschluss-Block
einmal als `_publish_finalized_event` existiert, ruft der Snapshot-Zweig
ihn genauso.

---

### F-11 · Die teuerste Stufe läuft vor dem Tor, das sie verwirft — **MITTEL, BESTÄTIGT**

**Ort** — `_main_loop.py:414-419`.

Der MAD-Sprungtest (`mad > 60` gegen das letzte akzeptierte Frame)
steht **nach** der Coral-Inferenz (`:253`), dem Tracker-Schritt
(`:353`), dem Vogel-Klassifikator (`:369`), der Wildtier-Stufe (`:387`)
und beiden Identitäts-Registries (`:396-409`). Wird er ausgelöst, ist
die gesamte Arbeit verloren — und, wichtiger als die Kosten: die
Confirmer-Treffer dieses Frames werden nie gebucht, weil die
Confirmer-Schleife erst bei `:446` beginnt. Ein Frame, das die
MAD-Prüfung nicht besteht, zählt also weder für noch gegen die
Bestätigung; es fällt aus dem Fenster heraus.

Die verwandten Frame-Güte-Tore (`:193`, `:198`) stehen korrekt vorne.
Nur dieses eine steht hinten, vermutlich weil es `_prev_good_frame`
setzt und das früher an den Zeichenschritt gekoppelt war.

**Szenario** — Kamera mit gelegentlichen H.265-Sprüngen (im Projekt
belegt: der Kommentar bei `_capture.py:227-230` nennt eine der drei
Kameras namentlich als Dauerfall bei Wolken-/Sonnenübergängen). Person
läuft durchs Bild, jedes zweite Frame
springt über MAD 60. Der Confirmer sieht statt 3 Treffern in 5 s nur
1–2 → die Person wird nie bestätigt, obwohl jede zweite Inferenz sie
gefunden hat. Im Log erscheint abwechselnd
`Frame MAD>60 (glitch/corrupt), skipped` und `⏳ wartend: person`.

**Behebung** — den MAD-Test unmittelbar hinter `_is_frame_valid`
(`:198`) verschieben, vor `_motion_detect`. `_prev_good_frame` wird
dann dort gesetzt. Kein Verhaltensrisiko: der Test vergleicht nur zwei
Frames, er hängt an nichts aus den Zeilen 207–412.

---

### F-12 · Der Bestätigt-Merker verfällt nur, wenn ihn jemand anfasst — **NIEDRIG bis MITTEL, BESTÄTIGT**

**Ort** — `detection_confirmer.py:56-59` (Verfall) gegen `:74`
(`is_confirmed`), Verbraucher `_main_loop.py:448`, `:460`, `:482`.

Der Verfall („2 × Fenster still → Merker zurücksetzen") steht **im
Rumpf von `check()`**. `is_confirmed()` prüft nichts, es liest nur das
Dictionary. Die Confirmer-Schleife ruft `check()` aber nur für
Erkennungen **auf oder über** der Spawn-Schwelle (`_main_loop.py:456`
springt vorher mit `continue` heraus). Eine Klasse, die einmal
bestätigt wurde und danach nur noch unterschwellig auftaucht, bleibt
also unbegrenzt „bestätigt" und wird über `:460` weiter in
`confirmed_object_labels` geschrieben.

Die Reichweite ist durch den Tracker begrenzt (eine unterschwellige
Erkennung ohne passende aktive Spur wird bei
`tracker_core/__init__.py:648` fallen gelassen, Spuren sterben nach
`grace 8 s`), deshalb nicht kritisch. Aber innerhalb dieses Fensters
verlängert jede schwache Erkennung ein bestätigtes Ereignis, ohne dass
je wieder drei Treffer nötig wären.

**Behebung** — den Verfall aus `check()` in eine eigene
`_decay(key, window_s)` ziehen und auch aus `is_confirmed()` rufen.
`is_confirmed` braucht dazu `window_s` als Parameter; die Aufrufer
haben ihn zur Hand (`secs` in `_main_loop.py:454`).

---

### F-13 · Kleinkram, der die Diagnose verfälscht — **NIEDRIG, BESTÄTIGT**

- **`today_events` zählt nicht heute.** `event_counter_today` wird nur
  in `runtime.py:162` auf 0 gesetzt, nie um Mitternacht.
  `_status.py:151` liefert es als „today_events". Nach zwei Wochen
  Laufzeit zeigt die Oberfläche den Zwei-Wochen-Wert.
- **`post_motion_seconds` im Event-JSON ist falsch.**
  `_recording:493` schreibt `int(cfg.post_motion_tail_s or 0)` = 0,
  während der tatsächlich verwendete Wert `_main_loop.py:550-553` den
  globalen Default 3.0 nimmt (weil der Kamera-Default 0.0 falsy ist).
  Das Event behauptet 0 s Nachlauf bei 3 s tatsächlichem Nachlauf.
  Nebeneffekt: ein Nachlauf von *echten* 0 s ist nicht einstellbar.
- **`_BlobTrack.centroids` wächst unbegrenzt.**
  `motion_blob_tracker.py:47` hängt an, ohne `maxlen`.
  `net_displacement` (`:58-60`) misst vom **allerersten** Schwerpunkt.
  Eine Spur, die im Dauerwind fortlaufend per Nachbarschaftsmaß
  weitergereicht wird (`:128-131`, Schwelle 0.25), lebt beliebig lange,
  driftet langsam und überschreitet irgendwann die 4 %-Marke — sie
  wird dann als „kohärent" gemeldet, obwohl sie in keinem Zeitfenster
  kohärent war. Zugleich wächst die Liste. ABGELEITET, weil `roi_mode`
  derzeit `off` ist und der Pfad nicht läuft; wird mit S3 akut.
  Behebung: `deque(maxlen=…)` und `net_displacement` über ein
  gleitendes Fenster statt über die Gesamtspur.

---

## 4 · Drei Kameras, drei Aufgaben

**Die Frage.** Ein Futterhaus (kleine Tiere, hohe Ereignisrate,
Fehlalarme sind billig) und zwei Sicherheitskameras (Personen, geringe
Rate, ein verpasster Einbrecher ist teuer). Kann die Kette diese
gegensätzlichen Risikohaltungen heute ausdrücken?

**Antwort: teilweise — und ausgerechnet die Stellen, an denen sich die
beiden Haltungen unterscheiden müssen, sind global.**

### Was bereits pro Kamera einstellbar ist

`motion_sensitivity`, `wildlife_motion_sensitivity`,
`wildlife_min_score`, `object_filter`, `label_thresholds`,
`confirmation_window`, `detection_trigger`, `frame_interval_ms`,
`roi_mode`, `roi_min_net_disp_frac`, alle vier `track_*`-Felder,
`zones`/`masks` inkl. Kanalflags, `class_severity`, `armed`,
`recording_enabled`, `schedule_record`, `schedule_notify`,
`notification_cooldown`, `post_motion_tail_s`, `whitelist_names`.

Das ist eine gute Ausstattung. Die Erkennungs- und Bestätigungsseite
lässt sich sauber trennen: das Futterhaus kann auf `n=2 / 3 s` und
Schwelle 0.45 stehen, die Werkstatt auf `n=3 / 5 s` und 0.45 mit
engerem Zonenzuschnitt.

### Was global ist und pro Kamera sein müsste

| Regler | Ort | Warum das ein Kompromiss erzwingt |
|---|---|---|
| `push.labels[*].threshold` | `_outbound:473` | **Der wichtigste.** Werkstatt (Person auf 15 m) und Futterhaus (Person auf 3 m) teilen sich eine Personen-Schwelle. Bereits als THR-1 erfasst — hier nur als Bestätigung: es ist der Regler mit der größten Hebelwirkung. |
| `push.labels[*].push` | `_outbound:461` | „Vögel melden" ist am Futterhaus erwünscht und an der Werkstatt Lärm. Heute nur ein globales An/Aus (TASKS S2). |
| `push.rate_limit_seconds` | `_outbound:216` | 30 s pro Kamera, aber **ein globaler Wert für alle drei**. Am Futterhaus ist 30 s zu kurz (Spam), an der Werkstatt zu lang: ein zweiter Eindringling innerhalb von 30 s wird verworfen — labelübergreifend, also auch wenn zuvor nur ein Vogel gemeldet wurde. |
| `push.quiet_hours` / `push.night_alert` | `_outbound:231-234` | Ruhezeiten sind eine Eigenschaft des *Empfängers*, nicht der Kamera — das ist vertretbar global. `night_alert.armed_only` dagegen entscheidet, ob eine Kamera nachts durchklingelt, und das ist eine Kamera-Eigenschaft. |
| `processing.event_cooldown_seconds` | `_main_loop.py:74`, Minimum hart 10 s | Am Futterhaus sollen 20 Eichhörnchen-Besuche 20 Ereignisse sein; an der Werkstatt sollen 20 Frames einer Person ein Ereignis sein. Ein Wert, zwei gegensätzliche Wünsche. Das Minimum von 10 s ist zusätzlich nicht unterschreitbar. |
| `processing.clip_max_duration_s` | `_main_loop.py:548` | 120 s Deckel für alle. |
| `processing.motion.enabled`, `blur_size`, Diff-Schwelle 28 | `_motion.py:71,74,94` | Der Diff-Schwellwert 28 ist eine nackte Konstante, keine Einstellung. |
| Vorprüfung 0,5 % geänderte Pixel | `_motion.py:154` | Konstante, kein Regler — und laut F-4 der bindende Boden für kleine Tiere. |
| D1-Defaults `min_age = 3` | `motion_blob_tracker.py:30` | `min_net_frac` ist pro Kamera überschreibbar, `min_age` nicht. |

### Die konkrete Empfehlung

Drei Felder, in dieser Reihenfolge:

1. **`cameras[i].push_thresholds`** — steht bereits als THR-1
   Schritt 1 im Backlog. Ohne dieses Feld kann keine der beiden
   Haltungen sauber eingestellt werden.
2. **`cameras[i].push_rate_limit_seconds`** — analog, Default 0 =
   „globalen Wert nehmen". Gehört in denselben Migrationslauf wie (1),
   sonst zwei Migrationen über `settings.json`.
3. **`cameras[i].event_cooldown_seconds`** — mit einem
   Kamera-Minimum von 2 s statt der harten 10 s. Das Futterhaus
   braucht 3–5 s, die Werkstatt 30–60 s.

Alles drei sind reine Konfigurationsflächen ohne Logikänderung im
Sinne von „neue Entscheidung". Sie ersetzen jeweils **einen** globalen
Wert durch einen Kamera-Wert mit globalem Rückfall — die Anzahl der
Entscheidungen in der Kette bleibt gleich.

### Umgekehrt: was NICHT pro Kamera sein sollte

`quiet_hours` und die Existenz von `daily_report`/`highlight` sind
Empfänger-Eigenschaften und gehören global. Ebenso `push.enabled` als
Notaus. Hier nichts hinzufügen.

---

## 5 · Empfohlene Vereinfachung

Die Kette hat 50 Entscheidungspunkte. Das ist zu viel für ein System
mit drei Kameras — und die Zahl wächst nicht durch Absicht, sondern
durch Schichten, die sich nie gegenseitig abgelöst haben. Vier
Streichungen, alle ohne Funktionsverlust.

### 5.1 · Einen Abschlussweg statt zwei — der Kernvorschlag

Der ffmpeg-Pfad und der OpenCV-Pfad tun heute unterschiedlich viel
(F-1). Die Antwort ist nicht, den zweiten Pfad nachzupflegen, sondern
**den gemeinsamen Teil einmal zu schreiben**:

```
_publish_finalized_event(event: dict, meta: dict, thumb_rel: str|None)
    · first_since
    · store.add_event / update_event
    · Tracking-Sidecar
    · MQTT
    · Achievement / Quest / Dossier
    · Telegram-Übergabe (die vier Kamera-Tore + send_event_alert)
```

`_reencode_motion_clip`, `_finalize_motion_clip` und der
Snapshot-Zweig in `_main_loop.py:711-761` rufen dieselbe Methode. Das
behebt F-1 und F-10 in einem Schnitt, halbiert die
Divergenz-Angriffsfläche und ist zugleich der HYG-1-Schnitt für
`_recording` (932 Zeilen, Budget 500).

**Damit entfällt** der Sonderweg `send_alert_sync` für
Ereignis-Meldungen. Er bleibt nur noch, wozu er heute schon dient:
Achievement-Push und Testknopf.

### 5.2 · Zwei tote Schwellenebenen streichen

- **`detection_min_score`** ist auf dem Live-Pfad seit der Einführung
  des Zwei-Stufen-Trackers wirkungslos (F-8c). Entweder in
  `thresholds.resolve_effective` als offizieller Rückfall hinter
  `label_thresholds` verdrahten — **oder** aus Schema, Defaults und
  Oberfläche entfernen und Simulation wie Ghost-Pruner auf dieselbe
  Auflösung wie live umstellen. Nicht beides halb.
- **`alarm_profile`** ist seit `migrate_class_severity` nur noch die
  Quelle einer einmaligen Ableitung. `choose_alarm_level`
  (`event_logic.py:100-137`) läuft aber weiterhin bei **jedem**
  Ereignis (`_motion.py:215`) — und sein `notify`-Ergebnis wird drei
  Zeilen später von der Matrix überschrieben (`:230`). Der einzige
  Rest, der noch trägt, ist `alarm_level` als Anzeigewert. Vorschlag:
  `alarm_level` direkt aus `severity` ableiten
  (`alarm → "alarm"`, `info → "info"`, `off → "logged"`) und
  `choose_alarm_level` samt Hart-Modus-Sonderfall streichen. **Eine**
  Stelle entscheidet dann den Schweregrad statt zwei, die
  gegeneinander laufen.

### 5.3 · Den `hard`-Sonderfall im Zeitplan aufgeben

`schedule.actions.hard` (`event_logic.py:42`) existiert nur, um
nachts `person → alarm` zu erzwingen. Genau das drückt die
Severity-Matrix bereits aus (`class_severity.person = "alarm"`), und
die Nachtweckung im Push (`_outbound:556-560`) macht den zweiten Teil.
`after_hours` im Event-JSON ist laut eigenem Kommentar
(`_motion.py:308-309`) nur noch aus Kompatibilitätsgründen da. Mit 5.2
fällt der Sonderfall ersatzlos weg.

### 5.4 · `_motion_confirm_wl` gegen `_motion_confirm` prüfen

Zwei parallele Deques (`_main_loop.py:229-235`), deren zweite per
Konstruktion eine Obermenge der ersten ist (`_motion.py:160`:
`wildlife_motion_low = bool(big_wl) and not big_normal`). Nach
Behebung von F-3 (D1 gatet die Wildtier-Stufe) und F-4 (der
Wildtier-Boden wirkt überhaupt) wäre zu prüfen, ob die zweite Deque
dann noch etwas Eigenes leistet oder ob
`motion_confirmed or coherent_blob is not None` reicht. **Nicht vorab
entscheiden** — erst F-3 und F-4 beheben, dann eine Woche
`roi_rescue=<hits>/<attempts>` im Heartbeat mitlesen.

### Netto

| | heute | nach 5.1–5.3 |
|---|---|---|
| Abschlusswege | 3 (ffmpeg, OpenCV, Snapshot) | 1 |
| Schweregrad-Entscheider | 2 (`choose_alarm_level` + Matrix) | 1 |
| Schwellenauflösungen | 3 (live / Simulation / Sidecar) | 1 |
| Melde-Einstiegspunkte für Ereignisse | 2 | 1 |

Keine neue Konfiguration. Vier Regler weniger
(`alarm_profile`, `schedule.actions.hard`, `detection_min_score`,
`confirmation_window.global` — letzterer wird stattdessen verdrahtet,
siehe F-8b), und drei neue Kamera-Felder aus Abschnitt 4, die je einen
globalen ersetzen.

---

## 6 · Was gut gebaut ist

Das ist nicht Höflichkeit — es ist die Liste dessen, wo eine Suche
nach Ursachen Zeit verschwenden würde.

- **`_zones.py`.** Die Trennung „globale Zonen backen ins
  Bewegungsbild, label-bezogene Zonen pro Erkennung auswerten"
  (`:315-330`, `:379-388`) ist sauber begründet und konsequent
  umgesetzt. Masken vor Zonen (`_main_loop.py:264-272`) ist die
  richtige Reihenfolge und im Kommentar belegt. Die
  `source_w`/`source_h`-Skalierung ist an beiden Stellen identisch.
- **`event_logic.py`.** Kleine, reine Funktionen mit
  Selbsttests am Dateiende (`:140-201`), inklusive der
  Mitternachtsüberlappung und des `start == end`-Sonderfalls.
  `is_schedule_window_active` und `schedule_action_active` haben
  klare, dokumentierte Semantik für „nicht gesetzt = 24/7".
- **Die Frame-Gütekette** (`_capture.py:224-294`). Sechs unabhängige
  Prüfungen, jede mit einer belegten Fehlbild-Ursache im Kommentar.
  Nichts davon wirkt wie Rateraten. Einziger Einwand ist der
  *Einbauort* des MAD-Tests (F-11), nicht der Test selbst.
- **Der Watchdog und die Reconnect-Buchhaltung**
  (`_main_loop.py:87-104`, `:108-128`). Der Kommentar bei `:96-100`
  erklärt genau, warum `release()` aus dem Watchdog-Thread einen
  Segfault erzeugt und die Übergabe per Flag nötig ist. Das ist teuer
  erkauftes Wissen, korrekt festgehalten.
- **`record_alert` über allen Push-Toren** (`_outbound:474-491`).
  Vorbildlich: der Kommentar erklärt, warum die Aufzeichnung *vor* die
  Tore gehört, und die Begründung stimmt. F-7 ist genau der Fall, in
  dem dieselbe Sorgfalt einmal gefehlt hat.
- **Der Zwei-Stufen-Tracker** (`tracker_core`). Die
  Floor/Spawn-Trennung, das Verwerfen unbestätigter Erkennungen ohne
  Spur, NMS am Eingang, die Rückgabe von Objekten statt Indizes
  (nach D1) — die Stufe ist durchdacht und mit 20+ Tests belegt.
- **`SettingsStore`-Migrationen.** Additiv, idempotent, jede mit
  Begründung. `_deep_merge_defaults` (`migrations.py:29`) überschreibt
  nie Benutzerwerte.

---

## 7 · Was aus dem Code allein nicht zu klären ist

Vier Fragen brauchen den laufenden Container. Alle Befehle laufen auf
der **Unraid-root-Shell**, nicht im devbox-Checkout.

**(1) Bestätigt F-1: kommt der Melder je an die Reihe?**
Wenn `send_event_alert` nie läuft, existiert weder die
`notify-attempt`-Zeile noch ein `alert`-Satz im Ledger:

```bash
docker logs squirreling-sightings --since 48h 2>&1 \
  | grep -cE '\[tg\] notify-attempt|\[trigger\].*handed off to notifier'
```

Erwartung bei zutreffendem F-1: **0**, obwohl im selben Zeitraum
`Re-encode complete` mehrfach auftaucht. Gegenprobe:

```bash
docker logs squirreling-sightings --since 48h 2>&1 | grep -c 'Re-encode complete'
wc -l /mnt/cache-ssd/appdata/squirreling-sightings/storage/_diag/detection_feedback.jsonl
```

Viele Re-encodes bei leerem oder nur historisch gefülltem Ledger
schließt die Sache.

**(2) Bestätigt F-2: sind die Ereignisse bewegungsetikettiert?**

```bash
find /mnt/cache-ssd/appdata/squirreling-sightings/storage/motion_detection \
  -name '*.json' -mtime -7 -exec \
  jq -r '[(.labels|join("+")), (.top_label//"-")] | @tsv' {} + \
  | sort | uniq -c | sort -rn | head -20
```

Erwartung bei zutreffendem F-2: die Zeile `motion` mit
`top_label = person` dominiert; `labels` mit `person` ist selten oder
fehlt.

**(3) Der globale `processing`-Block.** `config/config.yaml` liegt
nicht im Repository; `event_cooldown_seconds`,
`processing.detection.min_score`, `processing.wildlife.min_score`,
`clip_max_duration_s` und `processing.motion.*` sind damit aus dem
Code nur als Rückfallwerte bekannt. Für die Abschnitte 4 und 5:

```bash
cat /mnt/cache-ssd/appdata/squirreling-sightings/config/config.yaml \
  | sed -n '/^processing:/,/^[a-z]/p'
```

**(4) F-13c, unbegrenzte Blob-Spuren.** Nur beobachtbar, sobald
`roi_mode` eingeschaltet ist (S3). Danach:

```bash
docker exec squirreling-sightings python3 -c \
  "import json,collections;\
   f=open('/app/storage/_diag/motion_samples.jsonl');\
   c=collections.Counter(json.loads(l)['age'] for l in f);\
   print(sorted(c.items())[-10:])"
```

Ein Schwanz mit `age` in den Hunderten belegt den Befund; Werte unter
~30 entkräften ihn.

---

## 8 · Reihenfolge

Wenn nur eine Sache passiert, dann F-1. Danach:

```
F-1  (Melder auf dem Produktionspfad)       ── ohne das ist alles andere folgenlos
 └─ F-2  (Labels nachziehen)                ── ohne das meldet der Melder "Bewegung"
     ├─ F-7  (Cooldown-Reihenfolge)         ── eine Zeile verschieben
     └─ F-5  (fox/hedgehog nachtragen)      ── Teilschritt von THR-1
F-4  (Vorprüfung an den Boden koppeln)      ── unabhängig, Voraussetzung für SMALL-3
 └─ F-3  (D1 an die Wildtier-Stufe)         ── unabhängig, Voraussetzung für S3
F-11 (MAD-Test nach vorne)                  ── unabhängig, eine Verschiebung
F-6  (save_video + fehlender sleep)         ── unabhängig
F-8b (confirmation_window.global lesen)     ── eine Zeile
5.1  (ein Abschlussweg)                     ── enthält F-1 und F-10 sauber
5.2/5.3 (Schweregrad entrümpeln)            ── nach 5.1
```

Die linke Spalte ist der kritische Pfad: **F-1 → F-2**. Alles davor
oder danach verbessert eine Kette, deren letztes Glied fehlt.
