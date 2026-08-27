# Testplan — Testdaten erzeugen, ohne auf Tiere zu warten

Der Zweck: möglichst schnell an Aufnahmen kommen, an denen sich
Änderungen **belegen** statt behaupten lassen. Jede Aufnahme ist
dauerhaft wiederverwendbar — `app/scripts/replay_tracking.py` spielt
gespeicherte Clips beliebig oft durch denselben Tracker, also wird aus
einem Rundgang ein Testfall, der bei jeder späteren Änderung erneut
läuft.

Reihenfolge unten ist nach **Erkenntnis pro Minute deiner Zeit**
sortiert, nicht nach Vollständigkeit.

---

## Die eine Falle, die du kennen musst

**Halte kein Bild in der Hand.** Der Wildtier-Klassifikator wird
übersprungen, wenn eine Person den zu klassifizierenden Bildausschnitt
überlappt — eine Hand im Ausschnitt reicht. Das ist Absicht (COCO
erkennt Menschen zuverlässig, da lohnt keine zweite Meinung), macht den
Handtest aber wertlos.

Stattdessen: Bild oder Tablet **an einen Stock kleben**, auf einen
Stuhl stellen, an den Futterplatz lehnen — Hauptsache, du selbst bist
außerhalb des Ausschnitts, in dem das Motiv sitzt. Ein Meter Abstand
genügt meist.

Zweite Bedingung: **es muss sich bewegen.** Ein festgeklebtes Foto
löst kein Bewegungstor aus. Also anschieben, im Wind wackeln lassen,
oder auf dem Tablet ein Video abspielen.

---

## Was funktioniert und was nicht

**Ausgedrucktes Foto — funktioniert, mit Abstrichen.** Neuronale Netze
sind auf 2D-Bildern trainiert; ein Foto eines Eichhörnchens ist für sie
inhaltlich ein Eichhörnchen. Was stört: Papierglanz, flaches Licht,
fehlende Tiefenschärfe. Matt drucken, nicht hinter Glas, nicht in die
Sonne halten. Möglichst formatfüllend — ein DIN-A4-Ausdruck am
Futterplatz entspricht ungefähr einem echten Tier auf zwei Metern.

**Tablet oder Handy mit einem Video — deutlich besser.** Bewegung,
realistische Beleuchtung, kein Glanzproblem bei mittlerer Helligkeit.
Ein YouTube-Video mit Eichhörnchen am Futterhaus, Vollbild, Gerät an
den Futterplatz gelehnt. Das ist der schnellste Weg zu brauchbaren
Wildtier-Testdaten.

**Plüschtier an einer Schnur — gut für Tracking, mäßig für
Klassifikation.** Die Form stimmt, die Textur nicht; COCO liest es oft
als `teddy bear`. Für Spur-Kontinuität (bewegt sich das Ding als *eine*
Spur durchs Bild?) ist es ideal, weil du die Bewegung kontrollierst.

**Echte Tiere — unschlagbar, aber nicht planbar.** Nüsse auslegen und
die Kamera laufen lassen. Kostet nur Wartezeit, liefert dafür die
einzigen wirklich echten Daten.

---

## Szenario 1 · Läuft die Kette überhaupt? *(2 Minuten)*

Das Wichtigste zuerst. Ohne das ist jeder weitere Test wertlos.

**Tun:** Vor die **Garten**-Kamera treten, drei bis vier Schritte quer
durchs Bild, kurz stehen bleiben, wieder raus.

Garten deshalb, weil dort `person: alarm` gesetzt ist und **kein**
Aufnahme-Zeitplan greift. Die Werkstatt zeichnet zwischen 08:00 und
21:00 gar nicht auf, Squirrel Town hat `person: off`.

**Erwartet, in dieser Reihenfolge:**

1. Telegram: `🔴 Aufnahme gestartet · Garten` — innerhalb weniger Sekunden
2. Telegram: `⏹ Aufnahme beendet · Garten · Dauer: N s`
3. In der Mediathek eine Kachel, erst „wird aufgenommen", dann „wird verarbeitet", dann das fertige Video
4. Eine echte Alarm-Meldung mit Bild

**Wenn etwas fehlt**, sagt das Log genau wo:

```bash
docker logs squirreling-sightings 2>&1 | grep -E "Recording started|alert routing|tg\] skip|NOT recording"
```

- keine `Recording started` → Bewegungstor oder Aufnahme-Zeitplan
- `NOT recording:` → nennt den Grund direkt
- `alert routing: … notify=False` → Schweregrad-Matrix
- `[tg] skip: … score=… < threshold=` → Push-Schwelle

---

## Szenario 2 · Wie klein darf ein Motiv sein? *(10 Minuten)*

Beantwortet die Kernfrage der schwächsten Kategorie: ab welcher Größe
im Bild kippt die Erkennung.

**Tun:** Vor **Garten** in vier Abständen je zehn Sekunden stehen und
sich leicht bewegen — nah (2 m), mittel (5 m), fern (10 m), sehr fern
(20 m oder am Rand der Wiese). Zwischen den Positionen kurz aus dem
Bild gehen, damit getrennte Ereignisse entstehen.

**Notieren:** ungefähre Uhrzeit je Position. Damit kann ich die
Ereignisse später den Abständen zuordnen und die tatsächlichen
Konfidenzwerte gegen die Bildgröße auftragen.

**Warum das zählt:** Der Mindestgrößen-Filter für Personen (15 %
Bildhöhe) greift im Live-Pfad *nicht* — das ist bekannt. Diese Messung
sagt, ob er greifen *sollte* und bei welchem Wert.

---

## Szenario 3 · Wildtier-Erkennung *(15 Minuten)*

**Tun:** Tablet mit einem Eichhörnchen-Video an den Futterplatz von
**Squirrel Town** lehnen, Vollbild, laufen lassen. Du selbst außerhalb
des Bildes. Zwei bis drei Minuten laufen lassen, dann dasselbe mit
einem Vogel-Video.

**Vorher einschalten**, sonst passiert nichts Sichtbares: `person` auf
Squirrel Town steht auf `off` — für diesen Test irrelevant, aber das
`roi_mode` steht auf `off` und sollte für Kleinmotive auf `roi`.

**Erwartet:** in der Simulationsansicht Boxen mit `squirrel` oder
`bird`. Realistisch ist auch `cat` oder `teddy bear` — COCO kennt kein
Eichhörnchen, dafür ist die Wildtier-Stufe da. Genau dieser Übergang
ist der Test.

---

## Szenario 4 · Tracking-Kontinuität *(5 Minuten)*

**Tun:** Vor **Garten** einmal langsam und einmal zügig komplett durchs
Bild laufen, links nach rechts. Beim zweiten Durchgang in der Mitte
kurz hinter der Leiter oder dem Baum verschwinden und wieder auftauchen.

**Erwartet:** in der Simulationsansicht **eine** Spur `#1`, nicht zehn.
Genau das war der Fehler vom 13. August, und der Fix ist an
synthetischen Daten belegt, an echten noch nicht.

**Prüfen:** danach den Clip durchspielen lassen —

```bash
docker exec squirreling-sightings python3 /app/scripts/replay_tracking.py \
    --cam reolink_cx810_gartendachterrasse_181 --latest 3 --stills 6
```

Die Ausgabe nennt „Spuren" und „Spuren mit Label-Wechsel". Eine Person,
die einmal durchs Bild läuft, sollte **eine** Spur ergeben.

---

## Szenario 5 · Den Korpus füttern *(läuft nebenbei)*

Das ist kein eigener Termin, sondern eine Gewohnheit.

**Tun:** Jede Telegram-Meldung, die ankommt, mit **✅ Gültig** oder
**❌ Falsch** beantworten. Auch die falschen — besonders die falschen.

**Warum:** Erst damit wird Schwellen-Kalibrierung möglich. Der Ledger
speichert seit Kurzem Kamera, Label und den Score, der zur Meldung
geführt hat. Ohne Urteile ist das eine Liste ohne Wahrheit.

**Wieviel:** Sinnvolle Statistik pro Kamera und Klasse beginnt bei
etwa **30 beurteilten Meldungen, davon mindestens 10 falsche**.
Darunter würde jede automatische Anpassung auf Rauschen reagieren.
Bei normalem Betrieb sind das ein bis zwei Wochen.

---

## Was ich mit den Daten mache

| Szenario | Beantwortet |
|---|---|
| 1 | Läuft die Kette von Erkennung bis Meldung? |
| 2 | Ab welcher Motivgröße bricht die Erkennung — und wo gehört der Größenfilter hin? |
| 3 | Greift die Wildtier-Stufe, und bei welcher Konfidenz? |
| 4 | Hält eine Spur, oder zerfällt sie wieder? |
| 5 | Rohdaten für Schwellen-Kalibrierung und späteres Lernen |

Szenario 1 und 4 kann ich sofort auswerten. Szenario 2 und 3 brauchen
die Uhrzeiten von dir, um Ereignisse den Bedingungen zuzuordnen.

---

## Nach jedem Testlauf

```bash
# Was ist entstanden?
docker logs squirreling-sightings 2>&1 | grep -E "Recording started|alert routing" | tail -20

# Und die Clips für die spätere Auswertung
ls -la /mnt/cache-ssd/appdata/squirreling-sightings/storage/motion_detection/*/$(date +%Y-%m-%d)/
```

Schick mir die Ausgabe plus die Uhrzeiten — daraus wird die Auswertung.
