# BACKLOG

Arbeitspakete für das Tuning-Board. Zwölf Kategorien, Ziel **> 80 in
jeder**. Der schwächste Wert bestimmt, wie zuverlässig sich das System
anfühlt — deshalb Breite vor Tiefe.

Diese Datei ist der **Bauplan**, `TASKS.md` bleibt die laufende
Verfolgung. Jedes Paket ist so geschnitten, dass es in einem eigenen
Worktree laufen kann. Der **FILE SCOPE** ist dabei nicht Dekoration,
sondern die Kollisionsvermeidung: zwei gleichzeitig laufende Pakete, die
dieselbe Datei anfassen, kollidieren beim Merge. Wo sich zwei Pakete eine
Datei teilen **müssen**, steht das ausdrücklich dabei und eines ist
blockiert.

Alle Zeilennummern gegen `aebe799` (HEAD zum Zeitpunkt der Erstellung)
verifiziert.

---

## Vorab: was in TASKS.md nicht mehr stimmt

Beim Aufmachen des Codes sind sieben Annahmen aufgefallen, die nicht mehr
tragen. Wer ein Paket umsetzt, sollte das wissen, sonst baut er gegen ein
Bild, das es nicht gibt.

| Stelle | Annahme | Befund |
|---|---|---|
| `TASKS.md:200-204` (T1) | „Zuordnung rein positional, ohne Geschwindigkeits-Vorhersage" | **Falsch.** `predicted_bbox` (`app/app/tracker_core/__init__.py:367-451`) macht Median-Geschwindigkeit über 6 Detect-Samples, Stationär-Kurzschluss, lineares Decay und einen harten Clamp. Ein Prädiktor existiert — er ist nur stark gedämpft (`PRED_STEP_FRAC = 0.4`, `_consts.py:363`). |
| `TASKS.md:206` (T2) | `_main_loop.py:344` vs `:461` | Befund stimmt, Zeilen sind veraltet: `:352` (Tracker) vs `:384` (Wildlife-Stufe). |
| `TASKS.md:94-107` (C4) | „Modul fertig, **Verdrahtung offen**" | **Schreibseite ist verdrahtet** (`aebe799`): `record_alert` in `_outbound/__init__.py:623`, `record_verdict` in `_inbound.py:350`. Offen ist die **Leseseite** — `judged_alerts()` und `score_summary()` haben null Aufrufer außerhalb der Tests. Und die Schreibseite hat einen strukturellen Fehler, siehe CORP-1. |
| `TASKS.md:120,131,135` (C6/C8/C9) | offen | **Alle drei erledigt** — `7a412aa`, `4f847aa`, `b76eb8a`. C6 hat einen Rest (siehe HYG-2). Nur **C7 ist offen**, Zeile `_lifecycle.py:359` statt `:406`. |
| `TASKS.md:172` (R1) | „885 Zeilen, eine Methode von ~826" | Jetzt 815 / 756. Der Befund bleibt (Budget 500 / 80). |
| Auftrag | „Known-dead: `routes/_helpers.safe_cam_id`, `_log_decision`" | `safe_cam_id` ist tatsächlich tot (null Aufrufer). `_log_decision` (`coral_object.py:392`) hat einen Aufrufer bei `:286` — der greift nur, wenn `cam_id` gesetzt ist, und **kein einziger Aufrufer setzt es**. Der Live-Pfad nutzt ohnehin `detect_frame_raw`, das dort nie hinkommt. Richtiges Vorgehen: **verdrahten statt löschen** — die Verwerfungsgründe sind genau das Signal, das der Messbarkeit fehlt (TPU-1). Dritter Fund: `CatRegistry` (`cat_identity.py:112-113`) ist eine leere Unterklasse ohne Referenz. |
| CLAUDE.md „Known Limitations" | „Person / cat identity is a histogram match" | Es ist ein **64-Bit dHash** (`cat_identity.py:12-19`), kein Histogramm. |

Ebenfalls neu vermessen: **23 Python-Dateien über 500 Zeilen, 91
Funktionen über 80 Zeilen.** Größte Einzelposten:
`weather_service/_sun_tl/__init__.py` (2010 Zeilen, eine Funktion mit
**1068**), `routes/coral_test_detection.py` (1269 / 724),
`camera_runtime/_main_loop.py` (815 / 756).

---

## Vorab: was nur du entscheiden kannst

Drei Dinge im Board bewegen sich nicht durch Code.

- **S1/S2/S3 aus `TASKS.md:54-67`** sind reine Einstellungen. Solange
  `person`/`squirrel` bei 0.85/0.80 stehen und die Erkennung bei 0.45
  bestätigt, wird der Clip gespeichert und die Meldung nie gesendet.
  Kein Paket hier ändert das für dich — THR-1 macht die Lücke nur
  sichtbar und pro Kamera einstellbar.
- **`roi_mode` steht auf allen drei Kameras auf `off`.** SMALL-1 und
  SMALL-2 verbessern einen Pfad, der bis zu deinem Umschalten inert
  bleibt.
- **Die vier untersten Kategorien brauchen Daten, die nur durch Nutzung
  entstehen.** Siehe den Abschnitt „Wo 80 nicht durch Code erreichbar
  ist" am Ende.

---

# Messbarkeit & Diagnose · 78

Die höchste Kategorie, und trotzdem fehlt die eine Frage, die im Alltag
zählt: *warum kam keine Meldung?* Heute muss man dafür Logzeilen aus drei
Subsystemen von Hand zusammensuchen.

## DIAG-1 · Entscheidungs-Ring pro Kamera

**Warum jetzt** — Zwischen „Detektor hat etwas gesehen" und „Telegram hat
nichts gesendet" liegen neun unabhängige Tore, verteilt über drei Dateien:
Objekt-Filter (`_main_loop.py:261`), Masken (`:267`), Zonen (`:272`),
Tracker-Tier (`:352`), Confirmer (`:440-491`), dann push-Flag
(`_outbound/__init__.py:460`), push-Schwelle (`:473`), Suppress (`:483`),
Rate-Limit (`:486`), Cooldown (`:497`). Jedes Tor loggt einzeln, keines
schreibt einen verbundenen Datensatz. Es gibt keinen Ort, an dem
„Detektion X wurde von Tor Y verworfen" nachlesbar ist.

**Was tun** — Neues Modul `app/app/decision_trace.py` mit einem
`DecisionRing` (deque, maxlen 200, pro Kamera, reine RAM-Struktur, kein
Plattenzugriff). Eine Funktion `record(cam_id, **fields)`; ein Datensatz
pro Frame, der überhaupt Kandidaten hatte:
`{ts, dets_raw, after_object_filter, after_mask, after_zone, tracker_kept,
tracker_tier, confirm_state, trigger, notify, blocked_by}`. `blocked_by`
ist der Name des ersten Tors, das zugeschlagen hat, oder `None`.
Einhängen in `_stage_alert.py` (aus HYG-1). Neuer Endpunkt
`GET /api/camera/<cam_id>/trace` in `routes/streams.py`, gleiche
404-Semantik wie `/status` (`streams.py:45-54`). Kanten: Kamera ohne
Runtime → 404; leerer Ring → `{"records": []}`, kein Fehler; die
Telegram-seitigen Tore werden **nicht** von hier erfasst (anderer Prozeßpfad
und anderes Paket) — dafür trägt der Ring `notify: true/false` und der
Grund steht als `[tg] skip:` im Log, das DIAG-2 zusammenführt.

**FILE SCOPE** — `app/app/decision_trace.py` (neu),
`app/app/camera_runtime/_stage_alert.py`, `app/app/routes/streams.py`,
`app/tests/test_decision_trace.py` (neu).

**Depends on** — HYG-1.

**Acceptance** — Test, der einen Runtime-Stub durch drei Frames schickt
(einmal von Zonen verworfen, einmal vom Confirmer, einmal durchgelassen)
und für jeden das erwartete `blocked_by` prüft. Gegen den alten Stand
schlägt er fehl, weil `decision_trace` nicht existiert. Zusätzlich ein
Test, der `GET /api/camera/<id>/trace` gegen einen Flask-Testclient
aufruft.

**Risk** — niedrig. Additiv, reine Beobachtung, kein Pfad wird verändert.

**Size** — M

## DIAG-2 · Ein Befehl, der den ganzen Zustand ausgibt

**Warum jetzt** — Jedes andere Paket hier braucht in seiner Abnahme
Zahlen vom laufenden System, und heute heißt das: sechs Endpunkte per
Hand abfragen und Logzeilen greppen. `judged_alerts()` und
`score_summary()` (`detection_feedback.py:194`, `:226`) haben **null
Aufrufer außerhalb der Tests** — die Leseseite des Ledgers ist gebaut und
unbenutzt.

**Was tun** — `app/scripts/diag_bundle.py`, Muster von
`app/scripts/motion_calibration.py` (Ausgabe als Markdown nach
`storage/_diag/diag_bundle_<ts>.md`, nichts wird geschrieben außer diesem
Bericht). Abschnitte:
1. **Schwellen-Landkarte** — pro Kamera und Label nebeneinander:
   Detect-Floor (`tracker.floor`, 0.20), Spawn (`label_thresholds`, 0.45-0.55),
   Confirm-Fenster (`confirmation_window`), Push-Schwelle
   (`telegram.push.labels[*].threshold`, 0.80-0.90). Zeile fett markieren,
   wenn Push > Spawn — das ist die tote Zone.
2. **Ledger-Bilanz** — `score_summary()` pro Kamera/Label, plus
   Gesamtzahl Alerts, Gesamtzahl Urteile, Dateigröße.
3. **Detektor** — `timing_breakdown()` pro Kamera, `roi_rescue=<hits>/<attempts>`,
   Modell-Inventar aus `models/`.
4. **Speicher** — Größe von `motion_detection/`, `_diag/`, `.trash/`,
   freier Platz.
5. **Telegram** — `get_polling_status()` inklusive `send_loop_alive`.
Redigieren: RTSP-Passwörter, Bot-Token und Chat-IDs müssen maskiert sein
(`_camera_helpers.mask_password` existiert bereits) — der Bericht soll
teilbar sein.

**FILE SCOPE** — `app/scripts/diag_bundle.py` (neu),
`app/tests/test_diag_bundle.py` (neu).

**Depends on** — —

**Acceptance** — Test gegen ein Fixture-Storage-Verzeichnis mit einem
präparierten Ledger; prüft, dass die tote Zone erkannt und markiert wird
und dass ein eingeschleuster Token-String **nicht** in der Ausgabe steht.
Am Host anschließend einmal real:
`docker exec squirreling-sightings python3 /app/scripts/diag_bundle.py`

**Risk** — niedrig. Nur-lesend, eigenes Ausgabeverzeichnis.

**Size** — M

## DIAG-3 · Heartbeat vervollständigen (und ihn nicht wegdrosseln)

**Warum jetzt** — Drei konkrete Defekte in `_heartbeat_emit`
(`app/app/maintenance.py:129-252`, 124 Zeilen, Budget 80):
1. `:244-248` — ist irgendetwas ungesund, geht die **ganze Zeile** auf
   WARNING. WARNINGs laufen durch `BurstRateLimitFilter`
   (`logging_setup.py:106`). Ein dauerhaft ungesundes System bekommt also
   drei Heartbeats pro 30-s-Fenster und danach Sammelmeldungen — genau
   dann, wenn man ihn braucht, verschwindet er.
2. `:205-208` — das Detektor-Timing (`det[pre=… wait=… inv=… post=…]ms`)
   wird nur für die **erste** Kamera mit Samples ausgegeben, dann `break`.
   Bei drei Kameras sieht man eine.
3. `rt.status()` wird **viermal pro Kamera pro Tick** gebaut (`:144`,
   `:188`, `:200`, `:215`).

**Was tun** — `_heartbeat_emit` in `maintenance.py` auf mehrere Bausteine
zerlegen (Budget!): `_hb_cams`, `_hb_weather`, `_hb_detect`, `_hb_disk`,
`_hb_telegram`, die je ein Fragment liefern; `status()` einmal pro Kamera
holen und durchreichen. Zeile bleibt INFO, `unhealthy` wird als Token
`health=degraded` **im Text** geführt statt über den Loglevel; separat
eine WARNING nur beim **Wechsel** gesund→ungesund (Flankentriggerung, kein
Dauerfeuer). Detect-Timing pro Kamera statt nur der ersten. Neue Felder:
`events24h=<n>`, `judged=<n>/<n>` (aus dem Ledger), `trash=<GB>`.

**FILE SCOPE** — `app/app/maintenance.py`,
`app/app/logging_setup.py`, `app/app/camera_runtime/_status.py`,
`app/tests/test_heartbeat.py` (neu).
*Hinweis:* `test_roi_rescue_counters.py:57-62` prüft per Quelltext-Grep,
dass `"roi_rescue="` im Heartbeat vorkommt — diese Zusicherung muss
erhalten bleiben.

**Depends on** — —

**Acceptance** — Test, der `_heartbeat_emit` mit zwei gestubbten Runtimes
aufruft und prüft: (a) beide Kameras erscheinen im `det[...]`-Teil — das
schlägt gegen den alten Stand fehl; (b) `status()` wird pro Kamera genau
einmal aufgerufen (Zählstub); (c) bei `unhealthy` bleibt der Record-Level
INFO und enthält `health=degraded`.

**Risk** — niedrig. Reine Diagnose; ein Fehler hier bricht keinen
Aufnahmepfad.

**Size** — M

---

# Tracking von Objekten · 62

Der Tracker ist deutlich reifer als TASKS.md beschreibt (J1-J4, K2, K4,
N13 sind alle drin). Die Produktionsbeobachtung — **eine entfernte Person,
zehn Spuren, Spur läuft ~5 s hinterher** — steht also gegen ein System,
das die naheliegenden Gegenmaßnahmen bereits hat. Deshalb steht hier
Messen vor Bauen, und kein Paket setzt eine Ursache voraus.

## TRK-1 · Das Replay-Werkzeug eichen, bevor man ihm glaubt

**Warum jetzt** — `app/scripts/replay_tracking.py` ist das
Verifikationsinstrument des Projekts, und es reproduziert die Produktion
in zwei Punkten nicht:
- `:183` — `tracker.step(dets, t_s=frames_seen/sample_fps, fps=fps)`
  übergibt die **Video-fps** (z. B. 15), während mit `--sample-fps 3.0`
  abgetastet wird. `compute_miss_grace_samples(8.0, 15)` = 120 Samples
  Gnadenfrist statt 24. **Im Replay altern Spuren praktisch nie aus, das
  Werkzeug meldet also systematisch zu wenig Fragmentierung.**
- `:254` — `--iou` Default 0.30, Produktion 0.20
  (`tracker_core/_consts.py:27`).

**Was tun** — Beide Defaults an die Produktion angleichen: `fps=sample_fps`
übergeben, `--iou` Default 0.20. Zusätzlich Kennzahlen ausgeben, die
Fragmentierung überhaupt messbar machen: Spuren pro Label, Spuren pro
Sekunde Motivpräsenz, ID-Wechsel, Label-Umschwünge innerhalb einer Spur,
Histogramm der Schließgründe (`timeout` / `edge` / `merge` — der Grund
liegt bereits in `Track.close(reason, …)`, `tracker_core:281`), und
maximale sichtbare Parallelspuren. Neuer Schalter `--sweep
floor,spawn,iou` der ein kleines Kreuzprodukt fährt und eine Tabelle
ausgibt, damit ein Tuning-Vorschlag belegt statt geraten wird.
Kanten: `--sweep` darf niemals mit `--tpu` kombiniert werden (mehrere
Durchläufe, Single-Process-Regel) — mit klarer Fehlermeldung abweisen.

**FILE SCOPE** — `app/scripts/replay_tracking.py`,
`app/tests/test_replay_calibration.py` (neu).

**Depends on** — —

**Acceptance** — Test, der `main()` mit einem Argument-Stub aufruft und
prüft, dass der an `tracker.step` durchgereichte `fps`-Wert gleich
`sample_fps` ist und `--iou` auf 0.20 steht. Beides schlägt gegen den
alten Stand fehl. Danach am Host:
`docker exec squirreling-sightings python3 /app/scripts/replay_tracking.py --cam reolink_rlc811a_squirreltownnutbar_183 --latest 5 --stills 6`
und die neue Kennzahlentabelle als Ausgangswert in `TASKS.md` notieren.

**Risk** — niedrig. Offline-Werkzeug, schreibt nur nach `storage/_replay/`.

**Size** — M

## TRK-2 · Die Zeitbasis der Clips vermessen — dann erst korrigieren

**Warum jetzt** — Es gibt **drei unvereinbare Zeitbasen**: der Live-Pfad
übergibt `time.monotonic()` (absolute Sekunden seit Hostboot,
`_main_loop.py:354`), der Post-Clip-Worker `frame_idx / fps`
(clip-relativ, `tracking_worker/__init__.py:928`), das Replay
`frames_seen / sample_fps`. Drei Kandidaten für die ~5 s, ohne dass
heute einer davon messbar ist:
- **(a)** `_start_ffmpeg_recording` (`_recording/__init__.py:163-216`)
  öffnet zur Auslösezeit eine **neue** RTSP-Verbindung mit `-c copy`. Das
  erste geschriebene Bild ist der erste Keyframe nach dem Handshake — bei
  Reolink-GOP plus TCP-Setup typisch 1-5 s nach dem Trigger. `event["time"]`
  ist aber der Trigger (`:138`). `routes/detection_cloud.py:194` rechnet
  `ev_start + timedelta(seconds=t_off)` und ist damit systematisch zu früh.
- **(b)** Der Worker liest `CAP_PROP_FPS` der **re-enkodierten** Datei
  (`tracking_worker:130`). Stimmt deren Zeitbasis nicht, driftet `t`
  proportional — 0 am Anfang, wachsend zum Ende.
- **(c)** `pre_motion_seconds` wird im ffmpeg-Pfad hart auf 0 gesetzt
  (`_recording/__init__.py:160`), die synthetische Trigger-Spur im
  Frontend (`timeline-panel.js:235-258`) setzt das Motiv damit auf das
  allererste Bild.

**Was tun** — **Erst instrumentieren, nicht raten.** In das Event-JSON
drei Felder aufnehmen: `clip_start_lag_s` (Zeit zwischen `start_time` und
dem ersten tatsächlich geschriebenen Bild — bei ffmpeg über den ersten
Fortschritt auf stderr oder über `ffprobe` des fertigen Files),
`declared_fps` und `measured_fps` (aus `frame_count / duration` des
Containers, beide bereits bei `:316-319` zur Hand). Eine INFO-Logzeile
`[cam:<id>] clip lag=%.1fs fps decl=%.1f meas=%.1f` pro fertigem Clip.
**Erst wenn die Zahlen über mehrere Tage vorliegen**, im Folgeschritt
kompensieren — konstanter Versatz ⇒ (a), wachsender ⇒ (b). Die
Kompensation in `routes/detection_cloud.py:194` gehört in dieses Paket,
aber hinter ein Flag, das erst nach der Messung scharf gestellt wird.

**FILE SCOPE** — `app/app/camera_runtime/_recording/**`,
`app/app/routes/detection_cloud.py`,
`app/tests/test_clip_timebase.py` (neu).

**Depends on** — —

**Acceptance** — Test, der `_finalize_motion_clip` gegen ein Fixture-mp4
laufen lässt und prüft, dass `clip_start_lag_s`, `declared_fps` und
`measured_fps` im Event-JSON stehen (schlägt gegen den alten Stand fehl).
Die eigentliche Beobachtung ist Betrieb, nicht Test: am Host
`docker logs squirreling-sightings 2>&1 | grep "clip lag"` über 24 h
sammeln und in `TASKS.md` notieren, ob der Versatz konstant oder wachsend
ist.

**Risk** — mittel. Fasst den Aufnahmepfad an, in dem der Verlust eines
Clips nicht rückholbar ist. Alle neuen Felder additiv, jede Messung in
`try/except`, das im Fehlerfall `None` schreibt und weitermacht.

**Size** — M

## TRK-3 · Die drei Fragmentierungs-Ursachen im Tracker

**Warum jetzt** — Drei benennbare Defekte, alle gegen die
Zehn-Spuren-Beobachtung plausibel:
1. **Rand-Gnadenfrist in Samples statt Sekunden.** `EDGE_GRACE_SAMPLES = 2`
   (`tracker_core/_consts.py:81`), angewandt bei `__init__.py:1008-1010`,
   greift für jede Spur, deren letzte Box innerhalb von 8 px am Bildrand
   liegt. Bei 350 ms Takt (`schema.py:114`, Default `frame_interval_ms=350`)
   sind das **0,7 Sekunden**. Die normale Gnadenfrist ist mit 8 s in
   Sekunden gedacht (`MISS_GRACE_DEFAULT_SECONDS`), diese nicht.
2. **Label-Umschwung schneidet die Spur ab.** `Track.add_sample`
   (`:264-279`) stimmt über die letzten 5 Samples über das Label ab und
   kann `tr.label` mitten in der Spur umschalten. Danach weist das strikte
   Label-Tor bei `:798` (`tr.label != d.label`) genau die Detektionen ab,
   die die Spur bis dahin gefüttert haben.
3. **`state.closed` wächst im Live-Pfad unbegrenzt** (`:1013`), während
   die Re-Identifikation nur `closed[-32:]` liest (`:505`). Speicherleck
   plus dauerhaft unerreichbare Historie über eine lange Session.

**Was tun** — (1) `EDGE_GRACE_SAMPLES` durch `EDGE_GRACE_SECONDS = 1.5`
ersetzen und wie die Hauptgnadenfrist über
`compute_miss_grace_samples(seconds, fps)` (`:91`) in Samples umrechnen.
(2) Das Label-Tor bei `:798` gegen die **jüngste Label-Menge** der Spur
prüfen statt gegen nur `tr.label` (die letzten 5 Sample-Labels stehen
bereits zur Verfügung); die Re-Identifikation bei `:506` analog. (3)
`state.closed` auf 64 Einträge deckeln (doppelt so groß wie das
Re-ID-Fenster, damit sich die Semantik nicht ändert).
`test_tracker_core.py:242` (`test_module_constants_match_defaults`) pinnt
die Konstanten und muss mitgezogen werden.

**FILE SCOPE** — `app/app/tracker_core/**`,
`app/tests/test_tracker_core.py`, `app/tests/test_tracker_nms_index.py`,
`app/tests/test_tracker_fragmentation.py` (neu).

**Depends on** — TRK-1 (sonst ist der Effekt nicht belegbar).

**Acceptance** — Drei Tests, jeder gegen den alten Stand rot: (a) eine
Spur am Bildrand überlebt bei 2,9 Hz eine Lücke von 1,0 s; (b) eine Spur,
deren Label einmal umschwingt, wird von der ursprünglichen Label-Detektion
weiter verlängert statt neu gespawnt; (c) nach 200 geschlossenen Spuren
hat `state.closed` höchstens 64 Einträge. Danach Replay aus TRK-1 auf
denselben Clips vorher/nachher, Spurenzahl diffen.

**Risk** — mittel. Der Tracker ist das Herz der Erkennungskette und hat
sichtbare UI-Folgen (Spurfarben, Swimlanes). Die vorhandenen 17 Tests
über `tracker_core` sind das Netz; keiner davon deckt heute
`predicted_bbox`-Mathematik, `_merge_active_duplicates`, `_try_reidentify`
oder den Rand-Pfad ab — die Lücke schließt dieses Paket mit.

**Size** — L

---

# TPU-Tuning · 60

## TPU-1 · Ein Lock für die eine TPU

**Warum jetzt** — Der Inferenz-Lock ist `self._infer_lock`, angelegt in
`CoralObjectDetector.__init__` (`app/app/detectors/coral_object.py:104`),
also **pro Instanz**. `runtime.py:199` baut **einen Detektor pro Kamera**.
Drei Kameras ⇒ drei Detektoren ⇒ drei getrennte Locks ⇒ **kein einziger
Mechanismus serialisiert den Zugriff auf die eine physische Edge TPU**.
Der Lock schützt heute nur Runtime-Loop gegen Simulate-Endpunkt derselben
Kamera. Genau deshalb ist die `wait`-Stufe aus M1 aussagekräftig — und
genau deshalb misst sie heute das Falsche.

Zweiter Befund an derselben Datei: `_record_timing` (`:204`) hat genau
**einen** Aufrufer, `:525` in `_detect_cpu`. `_detect_coral` (`:440-484`)
ruft es nie. Auf diesem Deployment fällt das nicht auf, weil der
EdgeTPU-Delegate `_cpu_mode=True` setzt (`:151`) und damit durch
`_detect_cpu` läuft — auf dem pycoral-Rückfallweg wäre der ganze
M1-Aufwand still wirkungslos.

**Was tun** —
1. Modulweites `_DEVICE_LOCKS: dict[str, threading.Lock]` in
   `coral_object.py`, geschlüsselt auf die Device-Kennung. Beim
   Konstruieren: läuft die Instanz auf der TPU (`mode == "coral"`), nimmt
   sie den geteilten Lock; läuft sie auf der CPU, bleibt es beim
   Instanz-Lock — CPU-Inferenz soll gerade **nicht** serialisiert werden,
   `invoke()` gibt das GIL frei.
2. `_record_timing` auch in `_detect_coral` aufrufen, mit denselben vier
   Marken.
3. `timing_breakdown()` um `wait_p95` erweitern (die deque hat 60 Werte,
   das reicht).
4. `_letterbox` (`:26-56`) nach `app/app/detectors/_preprocess.py`
   herausziehen und von `coral_object.py` importieren — TPU-2 braucht es
   dort, und zwei Kopien wären eine Parallelimplementierung.
5. Totes Diagnose-Gerüst: `cam_id` von `_main_loop`/`_stage_detect` bis
   `detect_frame` durchreichen ist **nicht** Teil dieses Pakets (anderer
   FILE SCOPE). Stattdessen hier: `_log_decision`, `_fmt_dets`,
   `_humanize_drop_reason`, `_fmt_drops` (`:344-421`, ~78 Zeilen) mit
   einer Notiz im Modul-Docstring versehen, dass sie erst über
   `detect_frame(cam_id=…)` erreichbar werden — **nicht löschen**, das
   sind die Verwerfungsgründe, die DIAG-1 braucht.

**FILE SCOPE** — `app/app/detectors/coral_object.py`,
`app/app/detectors/_edgetpu.py`, `app/app/detectors/_preprocess.py` (neu),
`app/tests/test_inference_timing.py`, `app/tests/test_tpu_lock.py` (neu).

**Depends on** — —

**Acceptance** — Test, der zwei `CoralObjectDetector`-Instanzen mit
`mode="coral"` und demselben Device baut und prüft, dass beide **dasselbe
Lock-Objekt** halten; ein zweiter, dass zwei CPU-Instanzen **verschiedene**
halten. Beide schlagen gegen den alten Stand fehl. Dritter Test:
`_detect_coral` füllt `_timings` (heute leer).
Betrieb: nach dem Deploy `docker logs squirreling-sightings --tail 200 |
grep heartbeat` — die `wait`-Zahl muss danach von nahe 0 auf einen
realistischen Wert springen; genau das war vorher unsichtbar.

**Risk** — **hoch.** Fasst jeden Inferenzaufruf an. Ein zu grober Lock
serialisiert die CPU-Klassifikatoren mit und kostet Durchsatz. Deshalb
die Trennung TPU-Lock / CPU-Lock explizit im Test verankern. Zuerst diesen
Test schreiben, dann den Code.

**Size** — M

## TPU-2 · Klassifikatoren sehen ein verzerrtes Bild

**Warum jetzt** — Der Detektor letterboxt (`coral_object.py:454`, `:511`),
und der Kommentar bei `:31-46` hält fest, warum: ein reines Verzerren
drückte eine klar sichtbare Person auf 0.28-0.44. Die **Klassifikatoren
tun genau dieses Verzerren** — `cv2.resize` ohne Seitenverhältnis:
`wildlife.py:326`, `:343`, `:396`, `:428`; `bird_species.py:139`, `:164`.
Ein Eichhörnchen-Crop im Format 3:1 landet als 1:1 im Modell.
Zusätzlich normalisieren die beiden CPU-Pfade **unterschiedlich**:
`bird_species.py:167` rechnet `/255.0`, `wildlife.py:346` rechnet
`(x-127.5)/127.5`. Eines von beiden ist für sein Modell falsch.

**Was tun** — `letterbox()` aus `detectors/_preprocess.py` (von TPU-1
dort angelegt) in beiden Klassifikatoren an allen sechs Stellen einsetzen,
Füllwert 114 wie beim Detektor. Die Normalisierung aus den
`input_details`-Quantisierungsparametern des jeweiligen Modells ableiten
statt hart zu kodieren, und als gemeinsamen Helfer
`quantize_input(interpreter, img)` nach `_preprocess.py` legen. Kante:
quantisierte uint8-Modelle brauchen **gar keine** Normalisierung — der
Helfer muss das am `dtype` erkennen.

**FILE SCOPE** — `app/app/detectors/wildlife.py`,
`app/app/detectors/bird_species.py`,
`app/app/detectors/_preprocess.py`,
`app/tests/test_classifier_preprocess.py` (neu).

**Depends on** — TPU-1 (legt `_preprocess.py` an).

**Acceptance** — Test mit einem 3:1-Eingabebild: der an den Interpreter
gereichte Tensor muss quadratisch sein und den Inhalt **unverzerrt**
enthalten (Prüfung über eine eingezeichnete Marke, deren Seitenverhältnis
erhalten bleiben muss). Schlägt gegen den alten Stand fehl. Zweiter Test:
ein uint8-Modell-Stub bekommt keine Fließkomma-Normalisierung.
Wirkungsnachweis am Host über das Coral-Testpanel
(`/api/coral/test-batch`) vorher/nachher auf demselben Bildsatz.

**Risk** — mittel. Verändert, was die Klassifikatoren sehen — Scores
verschieben sich, und die Konstanten in `_wildlife_stage.py`
(`_HARD_CAT_SCORE 0.92`, `_OVERRULE_SOFT_CAT 0.45`) sind darauf geeicht.
Das Testpanel-Ergebnis vorher/nachher gehört deshalb in die Abnahme.

**Size** — M

## TPU-3 · Die Modellbank offline vermessen

**Warum jetzt** — In `models/` liegen mehrere `*.tflite`
(`ssd_mobilenet_v2` 300×300, `efficientdet_lite0` 320×320, …). Welches auf
diesen Kameras besser trifft und was es kostet, ist nirgends gemessen. Die
Fragen „hilft ein größeres Modell bei kleinen Objekten" (Kategorie *Kleine
Objekte*) und „lohnt ein zweites Modell auf der CPU" (Kategorie *Hybrid*)
sind ohne diese Tabelle nicht beantwortbar.

**Was tun** — `app/scripts/bench_detectors.py`. Läuft über alle
`*.tflite` in `models/` (Kategorie `detection` per
`routes/_coral_helpers._categorize_tflite`) und einen festen Bildsatz
(`storage/test_images/`, existiert). Ausgabe je Modell: mittlere und p95
Latenz, Zahl der Detektionen über Schwelle, und die paarweise
Übereinstimmung mit dem aktuell aktiven Modell (IoU ≥ 0.5 und gleiches
Label). **Default CPU**, `--tpu` als ausdrücklicher Schalter mit demselben
Warnhinweis wie `replay_tracking.py` (`d5d1c98`): die TPU gehört einem
Prozess, ein zweiter bricht ab.

**FILE SCOPE** — `app/scripts/bench_detectors.py` (neu),
`app/tests/test_bench_detectors.py` (neu).

**Depends on** — —

**Acceptance** — Test mit zwei Detektor-Stubs, der prüft, dass die
Übereinstimmungsmatrix korrekt berechnet wird und dass ohne `--tpu`
`prefer_cpu=True` gesetzt wird. Am Host:
`docker exec squirreling-sightings python3 /app/scripts/bench_detectors.py`
— Tabelle in `TASKS.md` festhalten.

**Risk** — niedrig, solange der CPU-Default steht. Genau das prüft der
Test.

**Size** — M

---

# Code-Hygiene & Größenbudgets · 56

Harte Zahlen: **23 Dateien über 500 Zeilen, 91 Funktionen über 80.** Fünf
der sechs größten Dateien sind `__init__.py` in Paketen, die laut
CLAUDE.md „public re-exports only" enthalten sollten — die Verzeichnisse
wurden angelegt, der Inhalt zog nie um. Drei Pakete lösen das nicht
vollständig; sie lösen die zwei Dateien, die andere Pakete blockieren, und
stellen die Regression ab.

## HYG-1 · `_loop` zerlegen — das Nadelöhr

**Warum jetzt** — `app/app/camera_runtime/_main_loop.py`: 815 Zeilen, davon
**eine Methode `_loop` mit 756** (`:60-815`). Budget: 500 / 80. **Sechs
weitere Pakete in diesem Backlog müssen in diese Methode hinein** (TRK-2,
CLASS-2, SMALL-2, HYB-2, DIAG-1, LEARN-1). Solange sie nicht zerlegt ist,
kollidieren die alle miteinander und CLAUDE.md verbietet ohnehin, neuen
Code in eine Methode dieser Größe zu legen.

**Was tun** — Reine Extraktion, **kein Verhaltensunterschied**. Nähte
liegen im Code bereits sichtbar:

| neue Datei | heutige Zeilen | Inhalt |
|---|---|---|
| `_stage_capture.py` | `:78-206` | Watchdog, Reconnect, Grab, Frame-Validierung, Crop |
| `_stage_motion.py` | `:207-238` | Motion, Blob-Tracker, N-of-M-Motion-Bestätigung |
| `_stage_detect.py` | `:239-333` | Detect, Objekt-Filter, Masken, Zonen, D2-ROI-Rettung |
| `_stage_classify.py` | `:334-409` | Tracker-Schritt, Bird, Wildlife-Stufe, Identität, Draw |
| `_stage_alert.py` | `:410-524` | MAD-Glitch, Confirmer, Trigger-Entscheidung |
| `_stage_record.py` | `:525-815` | Pre-Buffer, Aufnahmestart/-ende, Event-Schreiben |

`_main_loop.py` behält nur den dünnen Orchestrator `_loop` (Ziel < 80
Zeilen): Schleife, `interval`-Sleep, `continue`-Pfade, Aufruf der sechs
Stufen. Jede Stufe ist ein Mixin mit **einer** öffentlichen Methode, die
einen expliziten Zustandscontainer entgegennimmt und zurückgibt — kein
verstecktes Durchreichen über `self` für Werte, die nur zwischen zwei
Stufen leben (`motion_labels`, `_coherent_blob`, `effective_bbox`,
`detections`, `labels`). Dafür eine `@dataclass FrameContext` in
`_stage_types.py`.
Der Sammelimport-Block bei `:3-6` mit `# ruff: noqa: F401` fällt dabei
weg — jede neue Datei importiert, was sie braucht.
Nach dem Umbau der Pflicht-Rauchtest aus CLAUDE.md:
`python3 -c "from app.app.camera_runtime import *"`.

**FILE SCOPE** — `app/app/camera_runtime/_main_loop.py`,
`app/app/camera_runtime/_stage_*.py` (neu),
`app/app/camera_runtime/runtime.py`,
`app/app/camera_runtime/__init__.py`,
`app/tests/test_main_loop_stages.py` (neu).
**Fasst NICHT an:** `_recording/**`, `_motion.py`, `_wildlife_stage.py`,
`_zones.py`, `_capture.py`, `_status.py` — die gehören anderen Paketen.

**Depends on** — —

**Acceptance** — Kein Verhaltenstest kann eine reine Extraktion beweisen;
deshalb: (a) die vollen 480 bestehenden Tests bleiben grün; (b) neuer
Test, der prüft, dass keine Datei in `camera_runtime/` über 500 Zeilen und
keine Funktion darin über 80 Zeilen liegt (per `ast`) — schlägt gegen den
alten Stand fehl; (c) der Import-Rauchtest oben.
Danach zwingend am Host: `docker compose pull && docker compose up -d`
und `docker logs squirreling-sightings --tail 50` auf Traceback prüfen.
Ein Fehler hier legt jede Kamera still.

**Risk** — **hoch.** Größte Einzelbewegung im Backlog, im heißesten Pfad,
und CLAUDE.md nennt „Python: Paketumwandlung verschiebt jeden relativen
Import" ausdrücklich als Wiederholungsfehler. Gegenmaßnahme: **keine**
Logikänderung im selben Commit, egal wie verlockend eine Kleinigkeit
unterwegs aussieht.

**Size** — L

## HYG-2 · `_outbound` zerlegen und das Handle-Leck schließen

**Warum jetzt** — `app/app/telegram_bot/_outbound/__init__.py`: 922
Zeilen; `send_event_alert` allein 247 (`:410-656`), `_best_frame_jpeg`
173 (`:236-408`). **CORP-1 und ASK-2 müssen beide in `send_event_alert`
hinein** — CLAUDE.md: erst extrahieren, dann hinzufügen.
Im selben Paket ein realer Defekt: `prepare_input`
(`telegram_bot/_outbound/_payload.py:22`, **ohne** führenden Unterstrich,
anders als im Auftrag notiert) gibt bei `:31` ein `open(str(src), "rb")`
blank zurück, ohne Kontextmanager, ohne `finally`. Der einzige Aufrufer
`dispatch_send` (`:46-62`) hängt in der `lambda` von `send_with_retry`
(`_retry.py:45-71`), die bis zu **drei Versuche** macht — bei
Pfad-Eingaben also bis zu drei offene Handles, davon mindestens zwei
sichere Waisen. Betroffen sind genau die heißen Pfade:
`_outbound/__init__.py:644-646` (Snapshot-Fallback im Event-Alert),
`:814-830` (Highlight), `:689` (Timelapse).
Dritter Rest aus C6: `send_alert` schluckt bei `:168-170` weiterhin alles
Nicht-Transiente, und **kein Produktionsaufrufer prüft das zurückgegebene
Future** (`_recording/__init__.py:847`, `:863` und neun `self.send(...)`).

**Was tun** — Zerlegen entlang der offensichtlichen Nähte:
`_send.py` (`:77-204`), `_gates.py` (`:206-235`, die fünf Prädikate),
`_best_frame.py` (`:236-408`), `_event_alert.py` (`:410-656`),
`_jobs.py` (`:658-922`). `__init__.py` behält nur die Mixin-Komposition
und die Re-Exports.
`dispatch_send` bekommt einen `contextlib.ExitStack`, der jeden von
`prepare_input` gelieferten Stream schließt — der Vertrag „pro Versuch neu
aufbauen" (`_payload.py:4-8`) bleibt unangetastet.
`send_event_alert` gibt ein Ergebnisobjekt zurück statt `None`, und der
Aufrufer in `_recording/__init__.py` wird **nicht** angefasst (fremder
Scope) — stattdessen loggt `send_alert` bei `:168-170` künftig mit
`log.error(..., exc_info=True)` und zählt Fehlschläge in einem Zähler, den
`get_polling_status()` ausweist.

**FILE SCOPE** — `app/app/telegram_bot/_outbound/**`,
`app/app/telegram_bot/_health.py`,
`app/tests/test_outbound_split.py` (neu),
`app/tests/test_payload_handle_leak.py` (neu).

**Depends on** — —

**Acceptance** — (a) Test, der `dispatch_send` mit einem Pfad füttert,
den Send zweimal scheitern lässt und prüft, dass am Ende **null** offene
Handles auf die Datei zeigen (über einen `open`-Stub, der Öffnen und
Schließen zählt) — schlägt gegen den alten Stand fehl. (b) `ast`-Test:
keine Datei in `telegram_bot/_outbound/` über 500 Zeilen, keine Funktion
über 80. (c) Die vorhandenen `test_telegram_send_retry.py` und
`test_telegram_send_loop_health.py` bleiben grün.

**Risk** — mittel. Telegram ist der einzige Ausgabekanal; ein Fehler hier
ist stumm. Das vorhandene Testpaar deckt den Retry-Pfad ab, der
Handle-Test kommt dazu.

**Size** — L

## HYG-3 · Budget-Wächter in CI, Basislinie darf nur schrumpfen

**Warum jetzt** — Die Budgets stehen seit langem in CLAUDE.md und werden
seit ebenso langem gerissen: 23 Dateien, 91 Funktionen. Ohne mechanische
Sperre wird jede Aufräumarbeit hier in drei Monaten wieder eingeholt. Ruff
hat keine Regel dafür.

**Was tun** — `scripts/check_budgets.py` (Repo-Wurzel, nicht `app/`):
zählt per `ast` Dateilängen und Funktionslängen für Python, Zeilen für JS,
vergleicht gegen `budgets.baseline.txt` (eine Zeile pro bekanntem
Überschreiter mit seiner heutigen Länge). Exit ≠ 0, wenn **eine neue**
Datei/Funktion das Budget reißt **oder** ein bestehender Eintrag *wächst*.
Schrumpfen ist erlaubt und aktualisiert die Basislinie nicht automatisch —
das macht der jeweilige Aufräum-Commit. Einhängen in
`.github/workflows/lint.yml` als **blockierender** Schritt.
Im selben Paket, weil kein anderes `routes/_helpers.py` anfasst: das tote
`safe_cam_id` samt `_CAM_ID_RE` (`routes/_helpers.py:20`, `:33`) löschen
und die zwei Docstrings anpassen, die es erklären
(`routes/__init__.py:40`, `test_cam_id_traversal_guard.py:3`). `safe_day_param`
in derselben Datei bleibt — der ist live (`routes/timelapse.py:20`).
Der dritte tote Fund, die leere Unterklasse `CatRegistry`
(`cat_identity.py:112-113`), gehört **nicht** hierher: `cat_identity.py`
ist LEARN-2s Scope und wird dort mit erledigt.

**Was das Paket ausdrücklich NICHT tut** — die restlichen 21 Dateien
aufräumen. Die zwei nächsten Kandidaten nach HYG-1/HYG-2 stehen als
oberste Einträge in der Basislinie und sind damit sichtbar:
`weather_service/_sun_tl/__init__.py` (2010 Zeilen, eine Funktion mit
1068) und `routes/coral_test_detection.py` (1269 / 724). Beide sind für
das Board irrelevant und blockieren kein Paket — deshalb kein eigenes
Arbeitspaket, sondern ein Eintrag in der Basislinie.

**FILE SCOPE** — `scripts/check_budgets.py` (neu),
`budgets.baseline.txt` (neu), `.github/workflows/lint.yml`,
`app/app/routes/_helpers.py`, `app/app/routes/__init__.py`,
`app/tests/test_cam_id_traversal_guard.py`,
`app/tests/test_budget_guard.py` (neu).

**Depends on** — läuft als **letztes** Paket, damit die Basislinie den
Stand nach allen Splits abbildet.

**Acceptance** — Test, der den Wächter gegen ein Fixture-Verzeichnis
laufen lässt: eine neue 600-Zeilen-Datei ⇒ Exit 1; ein bekannter Eintrag,
der um eine Zeile wächst ⇒ Exit 1; derselbe Eintrag geschrumpft ⇒ Exit 0.
Und `ruff check app/ --select F` bleibt sauber nach der `safe_cam_id`-
Löschung.

**Risk** — niedrig. Ein zu strenger Wächter blockiert CI — deshalb die
Basislinie, die den Ist-Zustand explizit duldet.

**Size** — M

---

# Verlässlichkeit der Objekt-Einstufung · 55

## CLASS-1 · Der Wildtier-Bbox-Spender kann nicht spenden

**Warum jetzt** — Findet die Wildlife-Stufe ein Tier, braucht sie eine
Box. `_refine_wildlife_bbox` (`camera_runtime/_consts.py:94`) fragt den
Detektor mit niedriger Schwelle nach einer tierförmigen Klasse und leiht
sich deren Geometrie. Die Kandidatenliste ist
`_WILDLIFE_BBOX_DONORS = ("cat","dog","bear","sheep","cow","teddy bear")`
(`_consts.py:74`). **`bear`, `sheep` und `cow` stehen in
`IMPOSSIBLE_LABELS`** (`detectors/_types.py:18-51`) und werden vom
Regionsfilter entfernt, **bevor** `_refine_wildlife_bbox` sie je sieht
(`coral_object.py:484`, `:543`). Es können also nur `cat`, `dog` und
`teddy bear` spenden — die Hälfte der Liste ist Dekoration, und ein
Eichhörnchen, das COCO als „bear" liest, verliert seine Box und fällt auf
die Motion-Box oder das Vollbild zurück.

**Was tun** — In `_refine_wildlife_bbox` den Regionsfilter für **diesen
einen Aufruf** abschalten und danach wiederherstellen. Das Muster ist im
Projekt etabliert: `WildlifeClassifier.classify_crop` macht genau das mit
`min_score` (`wildlife.py:270-277`). Kanten: der Wiederhersteller gehört
in ein `try/finally`, sonst bleibt der Filter bei einer Ausnahme aus;
und die geliehene Box wird nur als **Geometrie** übernommen, das Label
bleibt das der Wildlife-Stufe (steht schon so im Kommentar bei `:204-207`).

**FILE SCOPE** — `app/app/camera_runtime/_consts.py`,
`app/tests/test_wildlife_bbox_donor.py` (neu).

**Depends on** — —

**Acceptance** — Test mit einem Detektor-Stub, der auf dem
Verfeinerungs-Aufruf ausschließlich ein `bear` liefert: die zurückgegebene
Box muss die des `bear` sein, nicht die Motion-Box. Schlägt gegen den
alten Stand fehl. Zweiter Test: nach einer Ausnahme im Detektor ist
`region_filter_enabled` wieder auf dem Ausgangswert.

**Risk** — niedrig. Eng begrenzt, ein Aufruf, ein `finally`.

**Size** — S

## CLASS-2 · Wildtier-Treffer bekommen eine Spur

**Warum jetzt** — T2, bestätigt mit aktuellen Zeilen: `self._tracker.step`
läuft bei `_main_loop.py:352`, die Wildlife-Stufe erst bei `:384`, und sie
hängt ihre Detektion bei `_wildlife_stage.py:249` einfach an die Liste an.
Fuchs, Eichhörnchen und Igel bekommen damit **nie** eine Track-ID, nie
eine Farbe, nie eine Spur, nie eine Swimlane. Schlimmer: die Stufe
**entfernt** bei `:232` (cat→squirrel) und `:241` (`_suppress_overlap`)
Detektionen, die der Tracker gerade verarbeitet hat — die zugehörige Spur
bleibt verwaist am Leben und produziert weiter vorhergesagte Samples mit
dem alten Label.

**Was tun** — Die Wildlife-Stufe **vor** `tracker.step` ziehen. Ihr Tor
(`_wildlife_gate_open`, `_wildlife_stage.py:123`) liest nur Label, Score
und Bbox der Detektionen — Werte, die der Tracker nicht verändert. Die
Reihenfolge im Klassifikations-Stadium wird damit: Wildlife-Stufe →
Bird-Klassifikator → `tracker.step` → Identitäten → Draw. Das löst beide
Probleme in einem Zug: das Wildtier läuft durch den Tracker, und die
Überschreibungen passieren, bevor eine Spur davon existiert, also ohne
Waisen.
Kante: `_apply_wildlife_stage` liefert `labels` mit zurück, das bei
`_main_loop.py:365` aus `effective_motion + [d.label for d in detections]`
gebaut wird — die Reihenfolge dieser Konstruktion muss mitwandern, sonst
enthält `labels` die Tracker-Ausgabe nicht mehr.

**FILE SCOPE** — `app/app/camera_runtime/_stage_classify.py`,
`app/app/camera_runtime/_wildlife_stage.py`,
`app/tests/test_wildlife_stage.py`,
`app/tests/test_wildlife_track.py` (neu).

**Depends on** — HYG-1.

**Acceptance** — Test: ein Frame ohne COCO-Treffer, aber mit einem
Wildlife-Squirrel; nach dem Stadium muss die Squirrel-Detektion eine
`track_id` tragen. Schlägt gegen den alten Stand fehl. Zweiter Test: ein
weicher `cat` (0.60), den die Wildlife-Stufe zu `squirrel` überschreibt,
hinterlässt **keine** aktive Cat-Spur im Tracker. Die 282 Zeilen
`test_wildlife_stage.py` bleiben grün.

**Risk** — mittel. Reihenfolgeänderung im heißen Pfad. Der bestehende
Testbestand für die Stufe ist substanziell und ist das Netz.

**Size** — M

## CLASS-3 · Herkunft und Zweitplatzierter ins Event

**Warum jetzt** — Im Event steht heute nur das Endergebnis
(`detectors/_types.py:82-96`): Label, Score, Bbox, Spezies, Identität,
`raw_cls_id`, `via_roi`. Es steht **nicht** drin, welche Stufe das Label
erzeugt hat (COCO / ROI-Rettung / Wildlife / Bird) und was der
Zweitplatzierte war. Damit ist „warum hat er das Katze genannt" ohne
Nachstellen nicht beantwortbar — und genau dieses Feld braucht jeder
Trainings-Korpus und jede Kalibrierung. `via_roi` (`_types.py:80`) ist die
Vorlage: ein Provenienzfeld, das bereits durch die ganze Kette bis in die
UI läuft.

**Was tun** — `Detection` um `origin: str = "coco"` und
`runner_up: tuple[str, float] | None = None` erweitern, beides in
`to_dict()`. Setzen: `"roi"` bei `_stage_detect` (heute
`_main_loop.py:309`), `"wildlife"` in `_wildlife_stage.py:209`, `"bird"`
wenn der Bird-Klassifikator eine Spezies setzt. `runner_up` aus der
zweitbesten Klasse des jeweiligen Klassifikators (beide liefern bereits
Top-3: `wildlife.py:332`, `bird_species.py:142`).
`_build_event_meta` (`camera_runtime/_motion.py:189-317`) reicht die
Felder durch — die Funktion ist mit 129 Zeilen über Budget, also im selben
Zug den Detektions-Teil als `_meta_detections()` herausziehen.

**FILE SCOPE** — `app/app/detectors/_types.py`,
`app/app/camera_runtime/_motion.py`,
`app/app/camera_runtime/_stage_classify.py`,
`app/tests/test_detection_origin.py` (neu).
**Geteilte Datei:** `_stage_classify.py` gehört in Welle 3 CLASS-2 und
`_motion.py` in Welle 3 CORP-2 — CLASS-3 läuft deshalb **nach** beiden.

**Depends on** — CLASS-2, CORP-2.

**Acceptance** — Test, der ein Event mit einer ROI-geretteten und einer
Wildlife-Detektion baut und prüft, dass `origin` in beiden Event-JSON-
Einträgen korrekt steht und `runner_up` beim Wildlife-Treffer gefüllt ist.
Schlägt gegen den alten Stand fehl (`origin` existiert nicht).

**Risk** — niedrig. Rein additive Felder; `to_dict()` ist der einzige
Serialisierungspunkt.

**Size** — M

---

# Hybrid CPU + TPU · 45

Der Rechner ist zu ~98 % unbeschäftigt (Ryzen 9 5950X, 32 Threads,
Container ~0,76 Kerne), und `tflite.Interpreter.invoke()` gibt das GIL
frei — CPU-Inferenz in einem Thread parallelisiert also wirklich. Es fehlt
schlicht ein zweiter Detektor.

## HYB-1 · Zweiter Detektorlauf auf der CPU (nur Modul)

**Warum jetzt** — Das Konstruktionsprinzip steht schon: `tiled_detect`
(`detection_tiling.py:90`) nimmt „irgendein Objekt mit
`detect_frame_raw`" entgegen, und `tracking_worker/__init__.py:840-843`
zeigt, wie man einen Detektor zwingend auf die CPU stellt. Was fehlt, ist
das Zusammenführen zweier Läufe **und** das daraus abfallende
Uneinigkeits-Signal, das ASK-1 als bestes Auswahlkriterium braucht.

**Was tun** — `app/app/detectors/dual_pass.py` mit
`DualPassDetector(tpu_detector, cpu_detector, *, timeout_s=0.25)`, das
selbst `detect_frame_raw(frame, threshold=…)` anbietet. Ablauf: den
CPU-Lauf über einen prozessweiten `ThreadPoolExecutor(max_workers=2)`
starten, den TPU-Lauf im aufrufenden Thread fahren, dann per
`nms_merge` (existiert, `detection_tiling.py:57`) zusammenlegen. Auf jede
Detektion `origin`-Ergänzung `via_cpu: bool` und auf das Ergebnis ein
`agreement: float` (Anteil der TPU-Detektionen, für die es einen
CPU-Partner mit IoU ≥ 0.5 und gleichem Label gibt).
Kanten, alle testpflichtig: CPU-Lauf überschreitet `timeout_s` ⇒ Ergebnis
verwerfen, nur TPU zurückgeben, Zähler hochzählen — **niemals** den
Kamerapfad blockieren; CPU-Detektor nicht verfügbar ⇒ transparent zum
Einzelbetrieb degradieren; Executor wird beim Herunterfahren geschlossen.
**Kein Einbau in die Pipeline** — den macht HYB-2.

**FILE SCOPE** — `app/app/detectors/dual_pass.py` (neu),
`app/tests/test_dual_pass.py` (neu).

**Depends on** — —

**Acceptance** — Tests mit zwei Detektor-Stubs: (a) einig ⇒
`agreement == 1.0`, zusammengeführte Liste ohne Duplikate; (b) uneinig ⇒
`agreement < 1.0`, beide Detektionen überleben; (c) der CPU-Stub schläft
über `timeout_s` ⇒ Rückgabe binnen `timeout_s + ε`, nur TPU-Treffer,
Timeout-Zähler auf 1. Alles neu, gegen den alten Stand existiert das
Modul nicht.

**Risk** — niedrig. Freistehendes Modul, kein Aufrufer.

**Size** — M

## HYB-2 · Einbau hinter `hybrid_mode`, standardmäßig aus

**Warum jetzt** — Ein Modul ohne Aufrufer ist Halbfertiges; genau daran
hing C4 wochenlang (`TASKS.md:94-107`). Dieses Paket schließt es.

**Was tun** — Pro Kamera `hybrid_mode: "off" | "shadow" | "merge"`
(Schlüssel legt THR-1 an, Default `"off"`). `shadow` läuft den CPU-Pass
mit, **verwendet aber nur die TPU-Detektionen** und schreibt lediglich
`agreement` ins Event — der risikofreie Messmodus. `merge` nutzt die
zusammengeführte Liste. Aufbau des `DualPassDetector` im Konstruktor der
Runtime, CPU-Detektor über `cpu_model_path` mit `prefer_cpu=True`
(`coral_object.py:160-164` leitet den Pfad bereits her). Einbau an genau
einer Stelle in `_stage_detect.py` (heute `_main_loop.py:253-256`).
`agreement` und `via_cpu` wandern über `_build_event_meta` ins Event.

**FILE SCOPE** — `app/app/camera_runtime/_stage_detect.py`,
`app/app/camera_runtime/runtime.py`,
`app/tests/test_hybrid_wiring.py` (neu).
**Geteilte Dateien:** `_stage_detect.py` gehört zuvor SMALL-2,
`runtime.py` zuvor HYG-1 — beide sind vorher fertig.

**Depends on** — HYB-1, SMALL-2, THR-1, HYG-1.

**Acceptance** — Test: `hybrid_mode="off"` ⇒ `DualPassDetector` wird gar
nicht gebaut (Konstruktor-Stub zählt null); `"shadow"` ⇒ er läuft, aber
die zurückgegebene Detektionsliste ist bit-identisch mit dem reinen
TPU-Ergebnis und das Event trägt `agreement`; `"merge"` ⇒ die
zusammengeführte Liste kommt durch. Alle drei neu.
Betrieb: eine Woche `shadow` auf Squirrel Town, dann
`grep agreement` über die Event-JSONs — liegt die Übereinstimmung
dauerhaft über 0,95, ist `merge` den Aufwand nicht wert und das Signal
für ASK-1 schwach. Das ist ein legitimes Ergebnis und gehört so notiert.

**Risk** — mittel. Berührt den Detektionspfad, aber der Default `off`
macht die Auslieferung folgenlos, und `shadow` ist per Konstruktion
wirkungsfrei.

**Size** — M

---

# Erkennung kleiner Objekte · 45

`N3` in TASKS.md hat recht: 2×2 bringt auf 2560×1440 nur 1,74× lineare
Vergrößerung, `roi` ist der richtige Modus. Nur hilft das nichts, solange
das Tor davor zu bleibt.

## SMALL-1 · Der ROI-Modus muss wirklich vergrößern

**Warum jetzt** — `tiled_detect` im `roi`-Modus schneidet die Motion-Box
mit `int(0.25*max(mw,mh)) + 8` Rand aus (`detection_tiling.py:113-120`)
und gibt den Ausschnitt an `detect_frame_raw`, der auf 300×300 letterboxt.
Ob dabei überhaupt eine Vergrößerung herauskommt, hängt allein von der
Größe der Motion-Box ab: eine 120 px breite Box wird 2,5× vergrößert, eine
600 px breite gar nicht. Das steht nirgends im `diag`, ist also weder
sichtbar noch abstimmbar — und die ganze Kategorie hängt genau an dieser
Zahl.

**Was tun** —
1. `tiled_detect` gibt in `diag` zusätzlich `magnification` zurück
   (Zielkantenlänge des Modells geteilt durch die längere Kante des
   Ausschnitts) sowie `crop_px`.
2. Neuer Parameter `min_magnification: float = 1.5`. Erreicht ein
   `roi`-Ausschnitt das nicht, wird er entlang seiner längeren Achse in
   überlappende Teilstücke zerlegt (dieselbe `tile_regions`-Mechanik,
   `:26`), bis jedes die Vorgabe erfüllt, gedeckelt auf 4 Teilstücke.
3. `VALID_MODES` (`:23`) beim **Lesen** durchsetzen: ein unbekannter Wert
   für `roi_mode` schaltet die Rettung heute still ab
   (`_main_loop.py:287`) — künftig eine WARNING und Rückfall auf `roi`.
Kante: das Zusammenführen läuft weiterhin über `nms_merge` (`:57`, IoU
0.45); zwei Teilstücke, die dasselbe Tier zerschneiden, dürfen nicht zwei
Detektionen ergeben — Naht-Duplikate sind in
`test_detection_tiling.py` bereits abgedeckt und müssen grün bleiben.

**FILE SCOPE** — `app/app/detection_tiling.py`,
`app/tests/test_detection_tiling.py`.

**Depends on** — —

**Acceptance** — Test: ein 800×600-Ausschnitt auf einem 2560×1440-Frame
bei `min_magnification=1.5` erzeugt mehr als einen Aufruf am
Detektor-Stub, und `diag["magnification"]` ist für jeden ≥ 1.5. Schlägt
gegen den alten Stand fehl (der Schlüssel existiert nicht, es gibt genau
einen Aufruf). Die vorhandenen 20 Tiling-Tests bleiben grün.

**Risk** — niedrig. Isolierte, gut getestete Datei; der Pfad ist in der
Produktion derzeit ohnehin inert (`roi_mode: off`).

**Size** — M

## SMALL-2 · Das Rettungs-Tor öffnen

**Warum jetzt** — Die Bedingung lautet heute wörtlich
(`_main_loop.py:283-288`):

```python
det_mode = (self.cfg.get("roi_mode") or "off").strip().lower()
if (
    not detections
    and _coherent_blob is not None
    and det_mode in ("roi", "2x2", "3x3")
):
```

`detections` ist an dieser Stelle nach Objekt-Filter, Masken und Zonen,
aber **vor** dem Tracker. Eine einzige schwache Fehlerkennung — „Katze"
mit 0.21, weit unter jedem Spawn-Wert — lässt `detections` nicht-leer
werden und **unterdrückt die Rettung vollständig**. Das ist der Fall, der
bei kleinen, entfernten Motiven am häufigsten eintritt: der Detektor sieht
*etwas*, benennt es falsch und schwach, und genau deshalb kommt die
Vergrößerung nicht zum Zug.

**Was tun** — Bedingung ersetzen durch: Rettung feuert, wenn **keine**
überlebende Detektion (a) die Spawn-Schwelle ihres Labels erreicht **und**
(b) den kohärenten Blob mit IoU ≥ 0.3 überdeckt. Formal: es gibt keine
Detektion `d` mit `d.score >= spawn_for(d.label)` und
`iou(d.bbox, blob.last_bbox) >= 0.3`. Damit rettet der Pfad auch dort, wo
eine schwache Fehlerkennung im Bild steht.
Kostenbremse bleibt: der kohärente Blob ist weiterhin Vorbedingung, die
Rettung feuert also nie pro Frame.
Zähler erweitern (M2-Muster): neben `_roi_rescue_attempts` und
`_roi_rescue_hits` ein `_roi_rescue_suppressed_by_weak` für genau den
Fall, der bisher still verschluckt wurde — sonst ist der Nutzen dieses
Pakets nicht belegbar. Die drei Zahlen in `_status.py` (gehört DIAG-3
nicht — `_status.py` ist dort im Scope; deshalb hier **nur** die
Runtime-Zähler setzen und DIAG-3 zeigt sie an; bis dahin reicht die
Logzeile).

**FILE SCOPE** — `app/app/camera_runtime/_stage_detect.py`,
`app/tests/test_roi_rescue_gate.py` (neu).
**Nicht anfassen:** `_status.py` (DIAG-3), `detection_tiling.py` (SMALL-1).

**Depends on** — HYG-1, SMALL-1.

**Acceptance** — Test: ein Frame mit genau einer 0.21-„cat"-Detektion und
einem kohärenten Blob, der von dieser Box **nicht** überdeckt wird ⇒
`tiled_detect` wird aufgerufen. Schlägt gegen den alten Stand fehl (heute:
kein Aufruf). Gegentest: eine 0.80-„person" **auf** dem Blob ⇒ kein
Aufruf, `_roi_rescue_suppressed_by_weak` bleibt 0.
Betrieb nach Aktivierung von `roi_mode: roi`: `roi_rescue=<hits>/<attempts>`
im Heartbeat über 24 h beobachten.

**Risk** — mittel. Öffnet einen Pfad, der zusätzliche Inferenz kostet.
Der kohärente Blob als Vorbedingung ist die Bremse; der neue Zähler macht
die Häufigkeit sofort sichtbar.

**Size** — M

## SMALL-3 · Der Bewegungsmelder muss kleine Blobs überhaupt anbieten

**Warum jetzt** — Die Rettung kann nur feuern, wenn D1 einen kohärenten
Blob meldet. `MotionBlobTracker.coherent_track` verlangt
`min_net_frac = 0.04` der Bildbreite und `min_age = 3`
(`motion_blob_tracker.py:29-30`, angewandt `:146`). 4 % von 2560 px sind
**102 px Nettoverschiebung**. Ein Eichhörnchen, das am Futterhaus sitzt
und sich um seine eigene Körperlänge bewegt, erreicht das nie — der Blob
gilt als inkohärent und die Rettung wird gar nicht erst angeboten. Die
Schwelle ist absolut gedacht, das Problem ist relativ.

**Was tun** — `min_net_frac` an die Blobgröße koppeln: gefordert wird
`max(min_net_frac * frame_w, k * max(bw, bh))` mit `k ≈ 1.0` — ein Motiv
muss sich um seine eigene Größe bewegt haben, nicht um einen festen
Bildanteil. Für große Blobs bleibt die alte Schranke wirksam, für kleine
sinkt sie. Der Parameter `roi_min_net_disp_frac` (`schema.py:140`) bleibt
als Obergrenze erhalten.
`motion_samples.record_sample` (`motion_samples.py:21`) um die beiden neu
relevanten Größen erweitern (`required_net_px`, `blob_dim_px`), damit
`app/scripts/motion_calibration.py` daraus eine Empfehlung ableiten kann —
das Werkzeug gates bereits auf `MIN_TOTAL = 30` / `MIN_PER_CLASS = 8`
(`motion_calibration.py:33-34`) und ist das Vorbild für THR-2.
Dritter Punkt, gleiche Datei: `motion_samples.jsonl` hat **keine
Rotation** (`motion_samples.py:48`, unbegrenztes Anhängen). Dieselbe
8-MB-Rotation wie im Ledger (`detection_feedback.py:69-72`) nachziehen.

**FILE SCOPE** — `app/app/motion_blob_tracker.py`,
`app/app/motion_samples.py`, `app/scripts/motion_calibration.py`,
`app/tests/test_motion_blob_gate.py` (neu).

**Depends on** — —

**Acceptance** — Test: ein 40 px breiter Blob, der sich um 60 px bewegt
hat, gilt bei 2560 px Bildbreite als kohärent (heute: nicht, 60 < 102) —
schlägt gegen den alten Stand fehl. Gegentest: ein 400 px breiter Blob mit
60 px Verschiebung bleibt inkohärent. Dritter Test: die Rotation greift
bei 8 MB.

**Risk** — niedrig bis mittel. Ein zu weit geöffnetes Bewegungstor
erzeugt mehr Rettungsversuche; SMALL-2s Zähler macht das sofort sichtbar
und die Kosten fallen nur bei tatsächlich fehlender Detektion an.

**Size** — M

---

# Datenhaltbarkeit & Trainings-Korpus · ~45

Hier liegt das Fundament der gesamten unteren Board-Hälfte. CORP-1 ist der
Schlüsselstein des Backlogs.

## CORP-1 · Der Ledger sieht nur die Spitze — und kann deshalb nur nach oben korrigieren

**Warum jetzt** — Das ist der wichtigste Einzelbefund dieser Analyse.
`record_alert` steht in `send_event_alert` bei
`_outbound/__init__.py:622-632`, also **hinter allen neun Push-Toren**:
Mute (`:441-457`), push-Flag (`:460`), push-Schwelle (`:473`), Suppress
(`:483`), Rate-Limit (`:486`), Cooldown (`:497`), Zeitplan (`:522`).
Aufgezeichnet wird also ausschließlich, was ohnehin gesendet wurde — bei
`person` heißt das: nur Scores ≥ 0.85.

Daraus folgt zwingend: **eine Kalibrierung auf diesem Ledger kann eine
Schwelle niemals senken.** Um zu belegen, dass 0.55 sicher wäre, bräuchte
man beurteilte Beispiele zwischen 0.45 und 0.85 — und genau die werden
nicht geschrieben. Die Kategorien *Schwellen-Dynamik* (15), *Rückfragen*
(15) und *Lernen* (14) hängen alle an dieser einen Auslassung.

**Was tun** — Dritte Satzart `candidate` in
`app/app/detection_feedback.py`:

```
record_candidate(storage_root, *, cam_id, event_id, label, score,
                 threshold, ts, blocked_by, detections=None) -> bool
```

`blocked_by` ∈ `{push_disabled, below_threshold, cooldown, rate_limit,
mute, quiet, schedule}`. Geschrieben in `_event_alert.py` (aus HYG-2) an
**jedem** der neun `return`-Punkte, mit demselben `contextlib.suppress`
wie heute bei `:622`. Der `event_id` liegt dort bereits vor.
Zweitens: `judged_alerts()` und `score_summary()` müssen `candidate`-Sätze
mitlesen, damit ein Urteil auf einem *nicht gesendeten* Event zählt (die
Weboberfläche liefert genau solche — siehe FB-1).
Drittens: Helfer `has_verdict(storage_root, event_id) -> bool`, den CORP-3
für den Löschschutz braucht.
Kanten: Volumen. Ein `candidate` pro unterdrücktem Alarm kann bei einer
Kamera mit viel Bewegung deutlich mehr Sätze erzeugen als heute — die
8-MB-Rotation (`:51`, `:69-72`) trägt das, aber der Cooldown-Fall
(`blocked_by="cooldown"`) sollte pro `(cam, label)` höchstens einmal pro
Minute geschrieben werden, sonst dominiert er den Korpus. Diese Drosselung
gehört ins Modul, nicht in den Aufrufer.

**FILE SCOPE** — `app/app/detection_feedback.py`,
`app/app/telegram_bot/_outbound/_event_alert.py`,
`app/tests/test_detection_feedback.py`,
`app/tests/test_feedback_wiring.py`,
`app/tests/test_candidate_records.py` (neu).

**Depends on** — HYG-2 (`send_event_alert` hat 247 Zeilen; erst
extrahieren).

**Acceptance** — Tests, alle gegen den alten Stand rot: (a) ein Alarm mit
`score=0.60` bei `threshold=0.85` erzeugt einen `candidate`-Satz mit
`blocked_by="below_threshold"`; (b) `judged_alerts()` liefert ein Paar,
wenn zu diesem `candidate` ein `verdict` existiert; (c) zwei Cooldown-
Blockaden derselben `(cam, label)` binnen 10 s erzeugen genau einen Satz;
(d) `has_verdict` findet ein Urteil und meldet für ein unbeurteiltes Event
`False`. Die bestehenden 19 Ledger-Tests bleiben grün.

**Risk** — mittel. Neun neue Schreibstellen im Sendepfad. Jede in
`contextlib.suppress` — ein Diagnoseschreibfehler darf niemals einen
Alarm verhindern; das ist im Modul-Docstring bereits als Prinzip
festgehalten (`detection_feedback.py:30-31`).

**Size** — M

## CORP-2 · Es wird kein einziger Crop gespeichert — und das Standbild ist bemalt

**Warum jetzt** — Drei zusammenhängende Befunde:
1. **Nirgends im Projekt wird ein Detektions-Crop persistiert.** Jedes
   `cv2.imwrite` schreibt ein Vollbild oder ein Vollbild-Thumbnail. Crops
   existieren ausschließlich flüchtig im RAM (`_motion.py:185-187`).
   Ohne Crops gibt es keinen Trainingskorpus, Punkt.
2. **Das gespeicherte Standbild ist das annotierte Bild.** `drawn =
   draw_detections(proc_frame, detections)` (`_main_loop.py:407`) malt
   2 px farbige Rahmen plus Beschriftung mit Score
   (`detectors/draw.py:12-32`), und **dieses** Bild wird bei
   `_main_loop.py:702-704` als `<event_id>.jpg` geschrieben, auf 1280 px
   herunterskaliert, q60. Jeder spätere Nutzer dieses Bildes — Korpus,
   Wiedererkennung, Nachbeurteilung — arbeitet auf synthetischen Pixeln.
3. **Das Event-JSON enthält weder `frame_w` noch `frame_h`.** Die Bboxen
   in `detections` sind `proc_frame`-Koordinaten (volle Hauptstrom-
   Auflösung minus `bottom_crop_px`), das JPEG ist ≤ 1280 breit. Ohne die
   Ursprungsbreite ist die Box gegen das gespeicherte Bild **nicht
   rekonstruierbar**. Das ist die Wurzel des Wiedererkennungs-Bugs
   (LEARN-2).

**Was tun** — Neues Modul `app/app/detection_corpus.py`:
`save_crops(storage_root, cam_id, event_id, frame, detections, *,
quota) -> int`. Schreibt je Detektion über einem Score-Boden einen
**ungeschnittenen, unbemalten** Crop mit 20 % Rand nach
`storage/_corpus/<cam_id>/<label>/<event_id>_<n>.jpg` (q90) und eine
Manifestzeile nach `storage/_corpus/manifest.jsonl` (`event_id`, `label`,
`score`, `origin`, `bbox`, `frame_w`, `frame_h`, `path`). Aufruf mit
`proc_frame` **vor** `draw_detections`.
Harte Deckel, testpflichtig: höchstens `quota` Crops pro Label und Tag
(Default 50), höchstens 2 GB Gesamtgröße — bei Überschreitung wird nicht
mehr geschrieben und einmal pro Stunde geloggt. Ein Korpus, der die
Platte füllt, wird abgeschaltet und ist dann wertlos.
Getrennt davon, im selben Paket: `frame_w` und `frame_h` in das
Event-JSON aufnehmen (Snapshot-Pfad in `_stage_record.py`, Video-Pfad in
`_recording/__init__.py:131-155`).
**Ausdrücklich nicht in diesem Paket:** das gespeicherte Standbild auf das
Rohbild umstellen. Die Weboberfläche zeigt heute die eingebrannten Rahmen;
das ist eine UI-Entscheidung mit iOS-Prüfliste und gehört nicht in ein
Korpus-Paket. Der Befund ist hier festgehalten, damit er nicht verloren
geht.

**FILE SCOPE** — `app/app/detection_corpus.py` (neu),
`app/app/camera_runtime/_stage_record.py`,
`app/app/camera_runtime/_recording/**`,
`app/app/camera_runtime/_motion.py`,
`app/tests/test_detection_corpus.py` (neu).

**Depends on** — HYG-1, TRK-2 (beide fassen `_recording/**` an).

**Acceptance** — Tests: (a) ein Frame mit zwei Detektionen erzeugt zwei
Dateien unter `_corpus/<cam>/<label>/` und zwei Manifestzeilen; (b) der
Crop enthält **keine** gemalten Rahmen (Prüfung: das Bild wird aus einem
Frame geschnitten, das vor `draw_detections` übergeben wurde — Test über
einen Farbvergleich der Randpixel); (c) nach `quota` Crops eines Labels
wird nicht mehr geschrieben; (d) das Event-JSON trägt `frame_w`/`frame_h`.
Alle vier neu.
Betrieb: nach einer Woche `du -sh
/mnt/cache-ssd/appdata/squirreling-sightings/storage/_corpus` — die Zahl
gehört in `TASKS.md`.

**Risk** — mittel. Schreibt zusätzlich auf die Platte im Aufnahmepfad.
Die Deckel sind die Gegenmaßnahme und sind testpflichtig, nicht optional.

**Size** — L

## CORP-3 · Was beurteilt wurde, darf nicht verschwinden

**Warum jetzt** — Zwei Löcher im Löschschutz aus `1e5ec8e`:
1. **Telegram-beurteilte Events sind nicht geschützt.** `cleanup_old`
   (`storage.py:664-724`) schützt über `is_judged_event`
   (`storage.py:51-60`), das auf `event["confirmed"]` prüft — gesetzt
   **ausschließlich** von `routes/events.py:94`. Ein Telegram-Urteil
   schreibt nach `settings.json` (`_inbound.py:334`) und in den Ledger,
   **nie** ins Event-JSON. Nach 14 Tagen löscht die Aufräumung Bild und
   Clip, während die Ledger-Zeile bleibt — ein Urteil ohne
   nachvollziehbares Beweisstück.
2. **`_corpus/` und `_diag/` sind nicht ausgenommen.** Beide liegen zwar
   außerhalb von `events_dir` und werden von `cleanup_old` heute nicht
   erfasst (`:692`) — aber das ist Zufall der Verzeichniswahl, nicht
   Absicht im Code, und ihre Größe taucht in keiner Speicherstatistik auf
   (`routes/media.py:27-141`).

Drittens, beim Nachsehen gefunden: `storage.auto_cleanup_enabled` steht in
`schema.py:298` und im Wartungsformular
(`_maintenance_panel.html:8`) — und wird von **keinem** Python-Code
gelesen. `_run_daily_cleanup` (`maintenance.py:22`) läuft bedingungslos.
Und `storage.retention_days` wird an zwei Stellen unterschiedlich
aufgelöst: `maintenance.py:23` liest nur `base_cfg`,
`routes/media.py:277-281` zuerst `settings.json` — Cron und Knopf können
mit verschiedenen Werten arbeiten.

**Was tun** — (1) `is_judged_event` erweitern: zusätzlich zu den
Event-Feldern über `detection_feedback.has_verdict(storage_root,
event_id)` prüfen (Helfer aus CORP-1). Da `judged_event_ids()`
(`storage.py:635-662`) ohnehin einmal alles einliest, den Ledger dort
**einmal** laden statt pro Event zu fragen.
(2) `_corpus` und `_diag` explizit als geschützte Namen in `cleanup_old`
und `trash.cleanup_expired` eintragen — mit Kommentar, warum.
(3) `auto_cleanup_enabled` in `_run_daily_cleanup` tatsächlich abfragen.
(4) `retention_days` einheitlich über einen Helfer auflösen
(`settings.json` vor `base_cfg`, wie in `routes/media.py`).
(5) `api_media_storage_stats` (`routes/media.py:27-141`, 115 Zeilen, über
Budget) um `_corpus`, `_diag` und `.trash` erweitern und dabei in
Teilfunktionen zerlegen. `trash.list_trashed()` liefert heute **keine
Byte-Größen** (`trash.py:170-178`) — die Oberfläche kann nicht zeigen,
wieviel der Papierkorb hält; Größe ergänzen.

**FILE SCOPE** — `app/app/storage.py`, `app/app/trash.py`,
`app/app/routes/media.py`, `app/tests/test_storage_retention_judged.py`,
`app/tests/test_corpus_retention.py` (neu).
`app/app/maintenance.py` gehört DIAG-3 und ist hier **tabu**: die Punkte
(3) und (4) werden deshalb nur für den HTTP-Pfad (`routes/media.py`)
umgesetzt. Der Cron-Pfad (`_run_daily_cleanup`, `maintenance.py:22-23`)
zieht in DIAG-3 nach — der Befund ist dort ausdrücklich vermerkt.

**Depends on** — CORP-1 (`has_verdict`).

**Acceptance** — Tests: (a) ein Event mit Ledger-Urteil, aber **ohne**
`event["confirmed"]`, überlebt `cleanup_old` samt `.jpg` und `.mp4` —
schlägt gegen den alten Stand fehl; (b) `_corpus/` und `_diag/` überstehen
einen Aufräumlauf mit `retention_days=0`; (c) die Speicherstatistik weist
Größen für `_corpus`, `_diag` und `.trash` aus. Die 10 bestehenden
`test_storage_retention_judged.py`-Tests bleiben grün.

**Risk** — mittel. `cleanup_old` löscht endgültig (`p.unlink`, kein
Papierkorb — `storage.py:665-667`). Jede Änderung dort braucht den
bestehenden Testbestand als Netz und darf nur *mehr* schützen, nie
weniger.

**Size** — M

---

# Verarbeitung von User-Einstufungen · ~35

## FB-1 · Web-Urteile landen nirgends

**Warum jetzt** — Der Ledger bekommt Urteile **ausschließlich** von den
zwei Telegram-Knöpfen (`_inbound.py:350`). In der Weboberfläche gibt es
drei Beurteilungsflächen, und keine davon schreibt:
- `routes/events.py:88-97` — `confirm` setzt `event["confirmed"]`, sonst
  nichts. Aufgerufen aus `lightbox.js:642` und
  `mediathek/orchestration.js:881`.
- `routes/events.py:100-118` — `labels` schreibt `event["labels"]` und
  `top_label` neu. **Das ist die faktische Korrekturfläche des Produkts**
  (`lightbox.js:256`) — und `corrected_label` im Ledger
  (`detection_feedback.py:142`) hat bis heute **null Produzenten**.
- `routes/events.py:22-53` — Löschen eines Events als Fehlalarm.

**Was tun** — In `routes/events.py` alle drei verdrahten:
`confirm` ⇒ `record_verdict(correct=True, source="web", cam_id=cam_id)`;
`labels` ⇒ `record_verdict(correct=False, source="web",
corrected_label=<neues top_label>, cam_id=cam_id)`, aber **nur wenn sich
`top_label` tatsächlich ändert** — ein Nutzer, der nur ein Nebenlabel
ergänzt, hat nichts korrigiert; `delete` ⇒ `record_verdict(correct=False,
source="web_delete")`, bevor die Dateien in den Papierkorb wandern.
`cam_id` liegt in allen drei Handlern direkt vor, ein Join über
`alert_index` ist nicht nötig. Alles in `contextlib.suppress`, ein
Ledger-Fehler darf keine 500 erzeugen.

**FILE SCOPE** — `app/app/routes/events.py`,
`app/tests/test_web_verdicts.py` (neu).

**Depends on** — —

**Acceptance** — Drei Tests gegen einen Flask-Testclient mit
Temp-Storage: nach `POST …/confirm` steht ein `verdict`-Satz mit
`source="web"` im Ledger; nach `POST …/labels` mit geändertem `top_label`
steht `corrected_label`; nach `POST …/labels` **ohne** Änderung von
`top_label` steht **kein** Satz. Alle drei neu.

**Risk** — niedrig. Additiv, drei kurze Handler, alles gekapselt.
**Das kleinste Paket mit der größten Hebelwirkung im unteren Board** —
jeder Tag ohne dieses Paket sind verlorene Korrekturen.

**Size** — S

## FB-2 · „Was war es wirklich?" — der Korrektur-Knopf in Telegram

**Warum jetzt** — Auf einem Alarm liegen heute die Knöpfe
`ev:<eid>:ok`, `ev:<eid>:no`, `ev:<eid>:m1h`, optional `siren`, plus
Livebild/Clip/Deeplink (`_outbound/__init__.py:581-603`). Bei ❌ Falsch
ersetzt `_set_badge` (`_inbound.py:309-315`) die **komplette** Tastatur
durch ein graues Abzeichen — eine Rückfrage kann danach nicht mehr an
dieselbe Nachricht. `on_text` (`:243-268`) verwirft freien Text stumm
(`:267-268`), „das war ein Fuchs" landet also im Nichts. Ergebnis: das
System erfährt, *dass* etwas falsch war, nie *was* es war.

**Was tun** — Bei `ev:<eid>:no` statt sofortigem Abzeichen die Tastatur
durch ein Label-Raster ersetzen: `ev:<eid>:lbl:<label>` — passt in die
64-Byte-Grenze für `callback_data`, die bei
`_outbound/__init__.py:111` bereits durchgesetzt wird. Kandidaten: die
Labels aus dem Event plus die vier Hauptklassen, deutsche Beschriftungen
aus `LABEL_DE` (`telegram_helpers.py`). Ein zusätzlicher Knopf „weiß
nicht" ⇒ `record_verdict(correct=False, corrected_label=None)` wie heute.
Erst nach der Auswahl das Abzeichen setzen, mit dem gewählten Label darin.
Kanten: der Nutzer wählt nie ⇒ nach der `no`-Verbuchung ist der Ledger
bereits korrekt (nur ohne `corrected_label`), die Rückfrage ist rein
additiv; ein zweiter Klick auf ein Label darf den Satz nicht verdoppeln
(die `event_feedback`-Idempotenzprüfung bei `_inbound.py:329-332` greift
dafür heute schon).
Den Verdikt-Zweig (`_inbound.py:317-401`) dabei nach
`telegram_bot/_verdict.py` herausziehen — `_inbound.py` hat 828 Zeilen.

**FILE SCOPE** — `app/app/telegram_bot/_verdict.py` (neu, aus
`_inbound.py:309-401`), `app/app/telegram_bot/_inbound.py` (nur die
Router-Zeile und der Import), `app/tests/test_telegram_correction.py` (neu).

**Depends on** — HYG-2.

**Acceptance** — Tests mit einem Bot-Stub: (a) `ev:x:no` ersetzt die
Tastatur durch ein Raster mit `ev:x:lbl:*`-Einträgen, **nicht** durch das
Abzeichen — schlägt gegen den alten Stand fehl; (b) `ev:x:lbl:fox`
schreibt einen `verdict`-Satz mit `corrected_label="fox"`; (c) zweimal
dasselbe Label ⇒ genau ein Satz.

**Risk** — mittel. Der Verdikt-Pfad ist die einzige Beurteilungsfläche,
die heute funktioniert; ein Fehler hier nimmt dem System sein Feedback.
Der Extraktionsschritt vorweg hält den Diff lesbar.

**Size** — M

## FB-3 · `runtime.event_feedback` ablösen

**Warum jetzt** — Jeder Knopfdruck in Telegram schreibt
`settings.json → runtime.event_feedback[<eid>] = {verdict, by, ts}`
(`_inbound.py:334-342`) — **ohne Kamera, ohne Label, ohne Score**. Der
Schlüssel wächst **unbegrenzt**: `runtime_set_subkey`
(`settings/store.py:256-264`) hat keinen Deckel, anders als
`runtime_alert_index_set`, das bei 200 Einträgen LRU-kappt (`:273-285`).
Und jeder Schreibvorgang ruft `self.save()` — ein vollständiges Neuschreiben
von `settings.json` pro Tastendruck, auf der Datei, die CLAUDE.md als
regressionsanfälligste des Projekts führt.
Der Schlüssel hat genau zwei Nutzer: die „bereits bewertet"-Sperre
(`_inbound.py:329-332`) und den „Falsch"-Zähler in `_stats_view`
(`_formatting/_root.py:240-250`).

**Was tun** — Beide Nutzer auf den Ledger umstellen:
`detection_feedback.has_verdict()` (aus CORP-1) für die Sperre, eine
Zählfunktion über `iter_records` für die Statistik. Danach den Schlüssel
in einer Boot-Migration in `app/app/migrations.py` (nicht
`settings/migrations.py` — die gehört THR-1) in den Ledger überführen und
aus `runtime` entfernen. Die Migration muss **additiv** sein: lesen,
fehlende Sätze anhängen, dann `update_section` — niemals `settings.json`
vollständig neu schreiben. Vorher eine Sicherung nach
`settings.json.bak.<ts>`, wie CLAUDE.md verlangt.
`test_feedback_wiring.py:66-73` pinnt heute ausdrücklich, dass
`event_feedback` weiter geschrieben wird — diese Zusicherung wird durch
den Ledger-Test ersetzt.

**FILE SCOPE** — `app/app/telegram_bot/_verdict.py`,
`app/app/telegram_bot/_formatting/_root.py`,
`app/app/settings/store.py`, `app/app/migrations.py`,
`app/tests/test_feedback_wiring.py`,
`app/tests/test_event_feedback_migration.py` (neu).

**Depends on** — FB-2 (`_verdict.py`), CORP-1 (`has_verdict`).

**Acceptance** — Tests: (a) ein bereits im Ledger beurteiltes Event wird
in Telegram als „Bereits bewertet" abgewiesen, **ohne** dass
`settings.json` angefasst wird (Schreibzähler auf dem Store-Stub);
(b) die Migration überführt drei Alt-Einträge und lässt alle übrigen
`settings.json`-Felder bit-identisch (Round-Trip-Diff, wie CLAUDE.md ihn
für Settings-Änderungen vorschreibt); (c) der „Falsch"-Zähler liefert
denselben Wert wie zuvor.

**Risk** — **hoch**, weil `settings.json` betroffen ist. Zwingend: eine
Sicherung vor dem ersten Migrationslauf, und der Round-Trip-Diff-Test ist
nicht verhandelbar.

**Size** — M

---

# Dynamik der Erkennungsschwellen · 15

## THR-1 · Die Schwellen-Landkarte begradigen

**Warum jetzt** — Drei voneinander unabhängige Schwellenebenen, die
nirgends gemeinsam aufgelöst werden:
Detect-Floor 0.20 (`tracker_core/_consts.py:33`), Spawn 0.45-0.55 pro
Label und Kamera (`settings/_consts.py:114-119`), Push 0.80-0.90
(`settings/_consts.py:27-35`). **Eine per-Kamera-Push-Schwelle existiert
nicht** — `telegram.push.labels[*].threshold` ist global
(`_outbound/__init__.py:473`). Die Werkstatt und das Futterhaus müssen
sich also dieselbe Personen-Schwelle teilen, obwohl ihre Entfernungen sich
um eine Größenordnung unterscheiden. Ohne diese Ebene kann keine
Kalibrierung etwas Sinnvolles empfehlen.
Zusätzlich brauchen sechs andere Pakete neue Schlüssel; würde jedes davon
`settings/defaults.py` selbst anfassen, gäbe es sechs Merge-Konflikte.

**Was tun** —
1. `cameras[i].push_thresholds: dict[label, float]`, Default `{}` =
   „globalen Wert nehmen". Schema in `schema.py`, Defaults in
   `settings/defaults.py`, additive Nachrüstung in
   `settings/migrations.py` (Muster: `migrate_telegram_push_defaults`).
2. Neues Modul `app/app/thresholds.py` mit
   `resolve_effective(cam_cfg, push_cfg, label) -> EffectiveThresholds`
   (`detect`, `spawn`, `confirm_n`, `confirm_seconds`, `push`,
   `push_enabled`, `source` je Feld: `"camera" | "global" | "default"`).
   **Ein** Ort, an dem die Auflösungsreihenfolge steht; DIAG-2, THR-2,
   THR-3 und die Oberfläche lesen ihn.
3. Im selben Commit die Schlüssel anlegen, die andere Pakete brauchen:
   `cameras[i].hybrid_mode` (Default `"off"`, HYB-2),
   `cameras[i].label_veto` (Default `{}`, LEARN-1),
   `storage.corpus_quota_per_label_day` (Default 50, CORP-2).
   Nur die Schlüssel und ihre Defaults — keine Logik.
Kanten: `_outbound/__init__.py:473` liest die Push-Schwelle heute selbst;
dieses Paket **ändert dort nichts** (fremder Scope) — der Konsument wird
in THR-3 umgestellt. Bis dahin ist `push_thresholds` gesetzt, aber unwirksam.
Das ist ausdrücklich so gewollt und muss im Commit stehen.

**FILE SCOPE** — `app/app/settings/defaults.py`,
`app/app/settings/_consts.py`, `app/app/settings/migrations.py`,
`app/app/schema.py`, `app/app/thresholds.py` (neu),
`app/tests/test_schema.py`, `app/tests/test_thresholds.py` (neu).

**Depends on** — —

**Acceptance** — Tests: (a) `resolve_effective` liefert für eine Kamera
mit `push_thresholds={"person": 0.5}` genau diesen Wert mit
`source="camera"`, ohne Eintrag den globalen 0.85 mit `source="global"`;
(b) die Migration fügt `push_thresholds` in eine bestehende
`settings.json` ein und **alle anderen Felder bleiben bit-identisch**
(Round-Trip-Diff); (c) die tote Zone ist ableitbar: `push > spawn` für
`person` mit Auslieferungsdefaults. Alle neu.

**Risk** — mittel. `settings.json`-Migration. Round-Trip-Diff und
Sicherung vorher, wie in CLAUDE.md vorgeschrieben.

**Size** — M

## THR-2 · Beratendes Kalibrier-Skript, das auch „zu wenig Daten" sagen kann

**Warum jetzt** — `score_summary()` (`detection_feedback.py:226`) ist
gebaut und hat null Aufrufer. Und die ehrliche Vorbedingung: Statistik auf
drei Beispielen schwingt nur, wie `N2` in `TASKS.md:238-243` richtig
festhält. Es braucht also zuerst ein Werkzeug, das **sagt, ob überhaupt
genug Urteile da sind** — nicht eines, das immer eine Zahl ausspuckt.

**Was tun** — `app/scripts/threshold_calibration.py`, exakt im Muster von
`app/scripts/motion_calibration.py` (das mit `MIN_TOTAL = 30` /
`MIN_PER_CLASS = 8` bei `:33-34` genau diese Zurückhaltung vorlebt).
Pro Kamera und Label ausgeben: `n_true`, `n_false`, Median und Spanne
beider Verteilungen, den trennenden Wert und **ein ausdrückliches Urteil**:
`GENUG` (≥ 30 beurteilt und ≥ 10 Falschbeispiele) oder
`ZU WENIG DATEN (n=…)`, in welchem Fall **keine** Zahl empfohlen wird.
Zusätzlich die Sicherheitsregel aus `TASKS.md:241-243` ins Werkzeug
ziehen: für `person` und `car` darf eine Empfehlung nur nach **unten**
gehen; eine Erhöhung wird mit Begründung unterdrückt („ein verpasster
Einbrecher wiegt schwerer als ein Fehlalarm").
Schreibt nichts außer dem Markdown-Bericht nach `storage/_diag/`.

**FILE SCOPE** — `app/scripts/threshold_calibration.py` (neu),
`app/tests/test_threshold_calibration.py` (neu).

**Depends on** — CORP-1 (ohne `candidate`-Sätze kann das Werkzeug eine
Schwelle grundsätzlich nicht senken — dann ist es nutzlos).

**Acceptance** — Tests gegen einen synthetischen Ledger: (a) 5 Urteile ⇒
`ZU WENIG DATEN`, keine Zahl; (b) 40 Urteile mit sauberer Trennung ⇒ eine
Empfehlung; (c) 40 Urteile für `person`, die eine **Erhöhung** nahelegen ⇒
unterdrückt mit Begründung. Alle neu.
Am Host:
`docker exec squirreling-sightings python3 /app/scripts/threshold_calibration.py`

**Risk** — niedrig. Nur-lesend, empfiehlt, schreibt keine Einstellungen.

**Size** — M

## THR-3 · Anwenden mit Leitplanken

**Warum jetzt** — Eine Empfehlung, die man von Hand abtippen muss, wird
nicht angewendet. Und `push_thresholds` aus THR-1 ist bis hierher gesetzt,
aber unwirksam — der Konsument fehlt.

**Was tun** — Neuer Blueprint `app/app/routes/feedback.py`, registriert in
`routes/__init__.py`:
- `GET /api/feedback/summary` — die Ledger-Bilanz pro Kamera/Label plus
  die aufgelösten Schwellen aus `thresholds.resolve_effective`.
- `POST /api/feedback/apply` — wendet **genau eine** Empfehlung an
  (`cam_id`, `label`, `field`, `value`).
Die Leitplanken in `app/app/thresholds_apply.py`, nicht im Handler:
Sicherung nach `settings.json.bak.<ts>` **vor** jeder Änderung; nur
additive Schreibweise (`settings.data["cameras"][i]["push_thresholds"][label] = v`
gefolgt von `save()`, Muster wie `routes/coral.py:605-621`); für `person`
und `car` sind nur Senkungen erlaubt; Änderungen um mehr als 0.15 in einem
Schritt werden abgewiesen; jede Anwendung schreibt einen `apply`-Satz in
den Ledger (Wer/Wann/Von/Auf), damit ein Rückgang später erklärbar ist;
anschließend `rebuild_runtimes()`.
Und der bis dahin fehlende Konsument: `push_thresholds` wird in
`_outbound/_gates.py` beim Auflösen der Push-Schwelle vor den globalen
Wert gesetzt.

**FILE SCOPE** — `app/app/routes/feedback.py` (neu),
`app/app/routes/__init__.py`, `app/app/thresholds_apply.py` (neu),
`app/app/telegram_bot/_outbound/_gates.py`,
`app/tests/test_threshold_apply.py` (neu).

**Depends on** — THR-1, THR-2, HYG-2.

**Acceptance** — Tests: (a) eine Erhöhung für `person` wird mit 400 und
Begründung abgewiesen; (b) eine Senkung wird angewendet, `settings.json`
unterscheidet sich **ausschließlich** im geänderten Feld
(Round-Trip-Diff), und die Sicherungsdatei existiert; (c) eine Änderung um
0.3 wird abgewiesen; (d) nach der Anwendung liest der Push-Pfad den
kameraspezifischen Wert. Alle neu.

**Risk** — **hoch.** Schreibt in `settings.json` und verändert, wann
Alarme gesendet werden. Deshalb: eine Empfehlung pro Aufruf, Sicherung
zuerst, Sicherheitsregel im Code statt in der Bedienung, Audit-Spur im
Ledger.

**Size** — M

---

# Gezielte Rückfragen (Active Learning) · 15

## ASK-1 · Auswahlpolitik: wann lohnt eine Frage (nur Modul)

**Warum jetzt** — Die Telegram-Knöpfe existieren, die Korrekturfläche
kommt mit FB-2. Was fehlt, ist die Entscheidung, **wen** man fragt. Ohne
Politik fragt man entweder zu selten (kein Nutzen) oder zu oft — und ein
Bot, der zu viel fragt, wird stummgeschaltet, womit die Datenquelle
versiegt. Das ist der Fehlermodus, der diese Kategorie kaputtmacht.

**Was tun** — `app/app/active_learning.py`:
`should_ask(record, *, effective, history) -> tuple[bool, str]`.
Signale, in dieser Reihenfolge:
1. **Uneinigkeit CPU ↔ TPU** (`agreement < 0.5` aus HYB) — das stärkste
   Signal, weil es Modellunsicherheit misst statt Score-Nähe.
2. Score im Band `effective.push ± 0.10` — schwächer, aber immer
   verfügbar.
3. Label auf dieser Kamera noch **nie** beurteilt (`n_total == 0`) —
   der Kaltstart.
4. `origin == "roi"` — die ROI-Rettung ist der unsicherste Pfad.
Harte Budgets, testpflichtig: höchstens `max_per_cam_day` Fragen (Default
3), höchstens eine pro `(cam, label)` und Tag, und **keine** Frage, wenn
das letzte Urteil dieser `(cam, label)` weniger als eine Stunde her ist.
`history` wird hineingereicht (aus `judged_alerts`), das Modul hält keinen
Zustand.
**Kein Einbau** — den macht ASK-2.

**FILE SCOPE** — `app/app/active_learning.py` (neu),
`app/tests/test_active_learning.py` (neu).

**Depends on** — CORP-1 (Satzform), HYB-1 nur als Signalquelle — das
Modul funktioniert auch ohne `agreement`, dann greift Signal 2.

**Acceptance** — Tests: (a) `agreement=0.3` ⇒ `(True, "disagreement")`;
(b) Score genau auf der Schwelle ⇒ `(True, "score_band")`; (c) nach drei
Fragen am selben Tag ⇒ `(False, "budget")`; (d) dasselbe `(cam, label)`
zweimal am Tag ⇒ beim zweiten Mal `False`. Alle neu.

**Risk** — niedrig. Reine Funktion, kein Zustand, kein Aufrufer.

**Size** — M

## ASK-2 · Die Frage stellen und die Antwort gewichten

**Warum jetzt** — Ohne Einbau bleibt ASK-1 wirkungslos — derselbe
Halbfertig-Zustand, in dem C4 wochenlang hing.

**Was tun** — In `_event_alert.py` nach der Sendeentscheidung
`should_ask` befragen; ist die Antwort ja, dem Alarm zusätzlich das
Label-Raster aus FB-2 direkt mitgeben (statt es erst nach ❌ zu zeigen),
mit einer kurzen Zeile „Kurze Rückfrage: war das wirklich ein …?".
Die daraus entstehenden Urteile bekommen `source="telegram_ask"` statt
`"telegram"` — eine bewusst beantwortete Rückfrage ist ein stärkeres
Signal als ein beiläufiger Daumen, und THR-2 kann sie später höher
gewichten.
Kanten: Rückfragen unterliegen den Push-Toren wie jeder Alarm — es wird
**keine** zusätzliche Nachricht erzeugt, das Raster hängt an der ohnehin
gesendeten. Wird der Alarm unterdrückt, entfällt die Frage; das ist
korrekt, und CORP-1s `candidate`-Satz hält den Fall trotzdem fest.

**FILE SCOPE** — `app/app/telegram_bot/_outbound/_event_alert.py`,
`app/app/telegram_bot/_verdict.py`,
`app/tests/test_active_learning_wiring.py` (neu).

**Depends on** — ASK-1, FB-2, FB-3, CORP-1, HYG-2.

**Acceptance** — Tests: (a) `should_ask` liefert True ⇒ die gesendete
Tastatur enthält `ev:<eid>:lbl:*`-Knöpfe; (b) liefert False ⇒ die Tastatur
ist unverändert die alte; (c) eine Antwort darauf schreibt
`source="telegram_ask"`. Alle neu.

**Risk** — mittel. Verändert das Aussehen jeder Alarmnachricht. Der
`should_ask`-Default (Budget 3/Tag) ist die Bremse.

**Size** — M

**Ehrliche Obergrenze dieser Kategorie:** siehe unten.

---

# Dynamisches Lernen im Hintergrund · 14

**Was hier nicht geht, und warum — vorweg.** „Im Hintergrund nachtrainieren"
im Sinne von *das neuronale Netz lernt aus deinen Umklassifizierungen* ist
mit diesem Aufbau **nicht möglich**, und das ist keine Aufwandsfrage:
EdgeTPU-Modelle sind eingefroren und quantisiert; Corals On-Device-Lernen
betrifft nur die letzte Schicht, gilt nur für Klassifikation und braucht
`pycoral`, für das es unter Python 3.11 kein Wheel gibt (der TPU-Zugang
läuft hier über den tflite-Delegate, `detectors/_edgetpu.py`, gerade
deshalb). `TASKS.md:233-237` (N1) hat damit recht.

Was **geht**, ist deterministisches Lernen aus deinen Korrekturen: Regeln,
die aus wenigen Beispielen sofort wirken, und Nächster-Nachbar auf
Merkmalsvektoren. Zwei Pakete, kein drittes — für ein drittes gäbe es
keinen ehrlichen Inhalt.

## LEARN-1 · Label-Veto pro Kamera

**Warum jetzt** — Es gibt Fehlklassifikationen, die ortsgebunden und
absolut sind: „Hund an der Werkstatt ist nie echt". Dafür braucht es kein
Modell und keine Statistik, sondern drei übereinstimmende Korrekturen.
Sobald FB-1 und FB-2 laufen, liegen diese Korrekturen als
`corrected_label` im Ledger — heute ohne jeden Verwerter.

**Was tun** — `app/app/label_veto.py`:
`derive_vetoes(storage_root, *, min_evidence=3, window_days=30) ->
dict[cam_id, set[label]]`. Ein Veto entsteht, wenn für `(cam, label)` im
Fenster **mindestens** `min_evidence` Urteile `correct=False` stehen und
**null** `correct=True`. Eine einzige Bestätigung hebt das Veto sofort auf
— asymmetrisch mit Absicht: ein Veto zu Unrecht ist teurer als eines zu
wenig.
Angewandt in `_stage_alert.py` **ausschließlich auf das Melden**, niemals
auf das Aufnehmen: ein vetoisiertes Label setzt `notify=False`, der Clip
wird trotzdem geschrieben. Ein Veto darf niemals dazu führen, dass
Beweismaterial fehlt.
Zwischenspeicherung: `derive_vetoes` liest den ganzen Ledger; einmal beim
Runtime-Aufbau und danach stündlich, nicht pro Frame.
`cameras[i].label_veto` (Schlüssel aus THR-1) erlaubt zusätzlich ein
manuell gesetztes Veto, das nicht abläuft.
Sicherheitsregel wie bei den Schwellen: **`person` und `car` sind vom
automatischen Veto ausgenommen.** Ein automatisch gelernter Personen-Veto
an einer Sicherheitskamera ist genau der Fehler, den man nicht machen
darf.

**FILE SCOPE** — `app/app/label_veto.py` (neu),
`app/app/camera_runtime/_stage_alert.py`,
`app/tests/test_label_veto.py` (neu).

**Depends on** — CORP-1, DIAG-1 (beide berühren `_stage_alert.py`), FB-1
(liefert die Korrekturen).

**Acceptance** — Tests: (a) drei `correct=False` für `(cam1, dog)` ⇒ Veto;
(b) drei `False` plus ein `True` ⇒ kein Veto; (c) drei `False` für
`(cam1, person)` ⇒ **kein** Veto (Ausnahme); (d) ein vetoisiertes Event
wird trotzdem aufgenommen und nur `notify` ist False. Alle neu.

**Risk** — mittel. Unterdrückt Meldungen. Die Aufnahme bleibt unangetastet
und `person`/`car` sind ausgenommen — beides ist testpflichtig, nicht
Konvention.

**Size** — M

## LEARN-2 · Wiedererkennung: vom 64-Bit-Hash zu Merkmalsvektoren

**Warum jetzt** — Die Katzen-/Personen-Wiedererkennung ist in einem
schlechteren Zustand, als `TASKS.md:190-194` (A4) beschreibt. Vier
unabhängige Defekte:
1. **Maßstab.** `routes/sichtungen.py:64-68` schneidet mit
   `det["bbox"]` (Koordinaten des vollen Hauptstroms) aus dem
   **auf 1280 px herunterskalierten** JPEG (`_main_loop.py:694-704`).
   Bei einem 2560er Reolink-Strom ist das Faktor 2. NumPy klemmt still auf
   die Bildgrenze — der Ausschnitt zeigt also nicht das Tier, sondern eine
   andere Bildregion. Keine Ausnahme, keine Warnung, der Nutzer sieht
   „gespeichert".
2. **Falsches Bild.** Bei Clip-Events ist `snapshot_relpath` das
   mp4-Thumbnail, gezogen bei `total_f // 3` des Clips und auf ≤ 640 px
   skaliert (`_recording/__init__.py:359-370`). Anderer Zeitpunkt,
   vierfach kleinerer Maßstab. `x1` aus einem 2560er Frame ist meist
   > 640, der Ausschnitt also leer und der Endpunkt antwortet
   `400 "Crop leer"` (`:69-70`). **Für Kameras mit Clipaufnahme ist die
   Registrierung faktisch funktionslos.**
3. **Bemalte Pixel.** Das gespeicherte Standbild ist `drawn`
   (`_main_loop.py:407`) — mit 2 px farbigem Rahmen exakt auf der Box und
   Beschriftung darüber (`detectors/draw.py:26-32`). Genau die Pixel, die
   ein 9×8-dHash am stärksten gewichtet.
4. **Asymmetrie.** Der Live-Abgleich macht es richtig: er schneidet aus
   `proc_frame` **vor** `draw_detections` (`_main_loop.py:393-406`,
   `:407`). Registrierung und Abfrage arbeiten also auf systematisch
   verschiedenen Verteilungen — selbst ohne (1)-(3) könnte das nicht
   zuverlässig treffen.
Dazu: die Schwelle ist mit `threshold: int = 10` (von 64 Bit) im
Konstruktor festgenagelt (`cat_identity.py:27`), von keinem Aufrufer
gesetzt, in keinem Schema, in keiner Oberfläche. Und `match_details`
liefert `distance` zurück, das der Aufrufer wegwirft
(`_main_loop.py:397-399`) — die Falschtrefferrate ist deshalb nirgends
messbar. Für `cat_identity.py` existiert **kein einziger Test**.

**Was tun** — In dieser Reihenfolge, in einem Paket:
1. **Registrierung reparieren.** `routes/sichtungen.py` skaliert die Box
   über `event["frame_w"]` (aus CORP-2) auf die tatsächliche Bildgröße;
   ist `frame_w` nicht vorhanden (Alt-Events), wird die Registrierung mit
   einer klaren Meldung abgelehnt statt still falsch durchgeführt.
2. **Merkmalsvektoren statt dHash.** Die vorletzte Schicht des
   MobileNet-CPU-Modells als Embedding ziehen. Das geht **nur auf dem
   CPU-tflite-Modell** — der EdgeTPU-Compiler verschmilzt die Schichten
   und legt nur den Ausgabetensor offen. Seit C2 (`6427515`) laufen die
   Klassifikatoren ohnehin standardmäßig auf der CPU
   (`wildlife.py:94`, `bird_species.py:44`), die Voraussetzung ist also
   erfüllt. Abgleich per Kosinusähnlichkeit, Nächster-Nachbar über die
   Registry.
3. **Zurückweisungsmarge.** Ein Treffer zählt nur, wenn der Beste um
   mindestens `margin` besser ist als der Zweitbeste — heute fehlt das
   völlig und ist der übliche Grund für Fehlzuordnungen.
4. Schwelle und Marge in `settings.json` konfigurierbar,
   `distance`/`similarity` bei **jedem** Treffer auf DEBUG loggen, damit
   die Falschtrefferrate erstmals messbar wird.
5. Die leere Unterklasse `CatRegistry` (`cat_identity.py:112-113`,
   null Referenzen) löschen.

**FILE SCOPE** — `app/app/cat_identity.py`,
`app/app/routes/sichtungen.py`,
`app/web/static/js/sichtungen.js`,
`app/tests/test_cat_identity.py` (neu),
`app/tests/test_identity_registration.py` (neu).

**Depends on** — CORP-2 (`frame_w`/`frame_h` im Event).

**Acceptance** — Tests, alle neu (es gibt heute keinen): (a) ein Event mit
`frame_w=2560` und einem 1280 px breiten Snapshot liefert einen
Ausschnitt, der die Box **korrekt skaliert** trifft — gegen den alten
Stand landet er in der falschen Bildhälfte; (b) ein Alt-Event ohne
`frame_w` wird mit 400 abgelehnt statt falsch registriert; (c) zwei
Ausschnitte desselben Tieres liegen näher beieinander als zwei
verschiedener (auf Fixture-Bildern); (d) fällt die Marge unter den
Schwellwert, wird **kein** Treffer gemeldet.

**Risk** — mittel. Die Registry-Dateien (`cat_registry.json`,
`person_registry.json`) enthalten Nutzerdaten. Das Embedding-Format ist
nicht das Hash-Format — die Migration muss alte Profile **behalten** und
neu eingelernte Vektoren additiv danebenlegen; ein Profil ohne Vektoren
fällt bis zur Neuregistrierung auf den dHash zurück.

**Size** — L

---

# Wo 80 nicht durch Code erreichbar ist

Der Auftrag verlangt ein klares Nein statt einer Scheinfunktion. Vier
Kategorien erreichen 80 **nicht** dadurch, dass die obigen Pakete gemergt
werden.

**Verarbeitung von User-Einstufungen, Schwellen-Dynamik, Rückfragen,
Lernen** hängen alle an derselben Sache: beurteilten Beispielen. Der
Mechanismus lässt sich fertig bauen — Ledger mit `candidate`-Sätzen,
Kalibrierung, Anwendung mit Leitplanken, Rückfrage-Politik, Veto. Die
Zahl im Board steigt trotzdem erst, wenn Urteile vorliegen. Konkret, damit
es überprüfbar ist:

| Kategorie | „80" heißt konkret | Wartezeit |
|---|---|---|
| User-Einstufungen | alle vier Beurteilungsflächen (Telegram ok/no, Web confirm, Web labels, Web delete) schreiben in den Ledger, und `corrected_label` hat einen Produzenten | **sofort nach FB-1 + FB-2** — diese Kategorie ist die einzige der vier, die rein durch Code auf 80 kommt |
| Schwellen-Dynamik | ≥ 30 beurteilte Alarme **und** ≥ 10 Falschbeispiele pro `(Kamera, Label)`, für mindestens `person` und `squirrel` an der Hauptkamera | THR-2 sagt es dir; realistisch mehrere Wochen normaler Nutzung nach CORP-1 |
| Rückfragen | die Politik läuft, das Budget greift, und die Antwortquote auf gestellte Rückfragen liegt über ~50 % | mindestens 2-3 Wochen, und die Quote hängt an dir, nicht am Code |
| Lernen | mindestens ein automatisch abgeleitetes Veto **und** ≥ 10 benannte Beispiele je Identität | Monate, wenn die Tiere selten sind |

Ein zweites, davon unabhängiges Nein: **die Push-Schwellen senkt kein
Paket für dich.** S1 aus `TASKS.md:54-59` bleibt eine Einstellung, die du
setzt. THR-1 macht die tote Zone sichtbar und pro Kamera einstellbar,
THR-3 macht das Anwenden einer belegten Empfehlung sicher — aber die
Auslieferungsdefaults 0.85/0.80 stehen live und blockieren heute jede
Meldung. Das ist eine Minute Arbeit in der Oberfläche und wiegt mehr als
die Hälfte dieses Backlogs.

Drittens: **Hybrid CPU+TPU kann sich als nicht lohnend herausstellen.**
HYB-2s `shadow`-Modus ist genau dafür da. Liegt die Übereinstimmung
zwischen CPU- und TPU-Modell nach einer Woche dauerhaft über 0,95, dann
bringt `merge` nichts und das Uneinigkeits-Signal für ASK-1 ist wertlos.
Das wäre ein gültiges Ergebnis und gehört so ins Board — nicht ein
Feature, das man einschaltet, damit die Kategorie besser aussieht.

---

# Empfohlene Ausführungsreihenfolge

Pakete innerhalb einer Welle haben **disjunkte FILE SCOPES** und können
parallel in eigenen Worktrees laufen. Zwischen den Wellen wird gemergt.

### Welle 1 — Fundament und Entsperrung
`HYG-1` · `HYG-2` · `THR-1` · `FB-1`

`HYG-1` (camera_runtime) und `HYG-2` (telegram_bot/_outbound) entsperren
zusammen zehn spätere Pakete. `THR-1` legt alle neuen Einstellungs-
schlüssel auf einmal an und verhindert damit sechs Merge-Konflikte in
`settings/defaults.py`. `FB-1` ist winzig und startet ab dem Deploy die
Datensammlung, auf die die untere Board-Hälfte wartet.

### Welle 2 — Messen, bevor gebaut wird
`TRK-1` · `TRK-2` · `SMALL-1` · `TPU-1`

### Welle 3 — Der Schlüsselstein
`CORP-1` · `CORP-2` · `CLASS-1` · `CLASS-2`

`CORP-1` ist das wichtigste Paket des Backlogs — ohne die
`candidate`-Sätze bleiben vier Kategorien strukturell blockiert.

### Welle 4
`TRK-3` · `DIAG-1` · `DIAG-2` · `SMALL-2` · `TPU-2`

### Welle 5
`FB-2` · `THR-2` · `CLASS-3` · `DIAG-3` · `CORP-3`

### Welle 6
`HYB-1` · `ASK-1` · `LEARN-2` · `SMALL-3`

### Welle 7
`THR-3` · `FB-3` · `LEARN-1` · `HYB-2`

### Welle 8 — Abschluss
`ASK-2` · `TPU-3` · `HYG-3`

`HYG-3` läuft bewusst zuletzt: die Budget-Basislinie soll den Stand
**nach** allen Splits abbilden, sonst friert sie Zeilenzahlen ein, die
gerade geschrumpft sind.

## Der kritische Pfad

```
HYG-2 ──► CORP-1 ──┬──► THR-2 ──► THR-3
 (W1)      (W3)    │    (W5)      (W7)
                   ├──► ASK-1 ──► ASK-2
                   │    (W6)      (W8)
                   └──► CORP-3
                        (W5)
```

`HYG-2 → CORP-1` ist die einzige Kette, an der die vier schwächsten
Kategorien des Boards gemeinsam hängen. `CORP-1` wartet ausschließlich
deshalb auf `HYG-2`, weil `send_event_alert` heute 247 Zeilen hat und
CLAUDE.md verlangt, vor dem Hinzufügen zu extrahieren. **Verzögert sich
`HYG-2`, verzögert sich das gesamte untere Board.**

Zweite, unabhängige Kette:
`HYG-1 (W1) → SMALL-2 (W4) → HYB-2 (W7)` — sie teilen sich
`_stage_detect.py` und lassen sich nicht parallelisieren.

## Die geteilten Dateien, ausdrücklich

| Datei | Reihenfolge |
|---|---|
| `camera_runtime/_stage_detect.py` | HYG-1 → SMALL-2 → HYB-2 |
| `camera_runtime/_stage_alert.py` | HYG-1 → DIAG-1 → LEARN-1 |
| `camera_runtime/_stage_classify.py` | HYG-1 → CLASS-2 → CLASS-3 |
| `camera_runtime/_stage_record.py` | HYG-1 → CORP-2 |
| `camera_runtime/_recording/**` | TRK-2 → CORP-2 |
| `camera_runtime/_motion.py` | CORP-2 → CLASS-3 |
| `telegram_bot/_outbound/_event_alert.py` | HYG-2 → CORP-1 → ASK-2 |
| `telegram_bot/_verdict.py` | FB-2 → FB-3 → ASK-2 |
| `detectors/coral_object.py`, `_preprocess.py` | TPU-1 → TPU-2 |
| `detection_feedback.py` | CORP-1 (allein) |
| `settings/defaults.py`, `_consts.py`, `migrations.py`, `schema.py` | THR-1 (allein) |
| `routes/__init__.py` | THR-3 → HYG-3 |
| `routes/media.py` | CORP-3 (allein) |
| `maintenance.py`, `logging_setup.py`, `_status.py` | DIAG-3 (allein) |

Jedes andere Paket hat einen Scope, den kein zweites anfasst.
