# Die Zeichnungen der README

Alles unter `docs/assets/` ist von Hand gezeichnetes SVG. Keine echten
Kamerabilder, keine Stockfotos, keine fremden Lizenzen.

| Datei | Zeigt |
|---|---|
| `hero.svg` | Kopfbild; enthält das Markenlogo der App |
| `legende-klassen.svg` | die elf erkannten Klassen mit ihren Farben |
| `ansicht-player.svg` | der Clip-Player |
| `ansicht-mediathek.svg` | das Ereignis-Raster |
| `ansicht-sichtungen.svg` | Quests und Medaillenbrett |
| `ansicht-gewitter.svg` | das Gewitter-Archiv |
| `ansicht-wetter.svg` | Wetterseite mit Tagesverlauf |
| `ansicht-telegram.svg` | die Chat-Meldung |
| `ablauf.svg` | der Weg einer Sichtung in fünf Schritten |

## Woher die Symbole kommen

Nichts darin ist für die README neu erfunden. Jeder Glyph ist ein
Auszug aus dem Quelltext der Oberfläche, damit README und App dieselbe
Sprache sprechen:

| Quelle in der App | Was daraus stammt |
|---|---|
| `app/web/static/js/core/icons.js` (`OBJ_SVG`) | Person, Katze, Hund, Vogel, Auto, Bewegung, Pfote |
| `app/web/static/js/core/animal-icons.js` (`BIRD_SVGS`, `MAMMAL_SVGS`) | Blaumeise, Kohlmeise, Amsel, Rotkehlchen, Elster, Eichelhäher, Buntspecht, Eichhörnchen, Igel, Fuchs, Reh |
| `app/web/static/js/core/class-colors.js` (`CLASS_COLORS`) | die Farbe jeder Klasse |
| `app/web/static/js/core/weather-types.js` (`WEATHER_TYPES`) | Gewitter, Starkregen, Schnee, Nebel, Sturmfront, Sonnenauf-/-untergang |
| `app/web/static/js/sichtungen/_achievements.js` (`_medalSVG`) | Aufbau der Medaillen (Rand r=47, Fläche r=36, Glanzbogen) |
| `app/web/static/js/mediaview/player/_transport-controls.js` | die Transportknöpfe unter dem Video |
| `app/web/static/img/logos/logo-tree-lens-dark.svg` | das Baum-Linsen-Logo im Kopfbild |
| `app/web/static/css/01-base.css` | Grundfarben: `#111` Grund, `#1a1a1a` Fläche, `#edf4fb` Text |

Ändert sich eine dieser Quellen sichtbar, gehört die passende Zeichnung
nachgezogen — sonst zeigt die README eine App, die es so nicht mehr gibt.

## Warum gezeichnet und nicht abfotografiert

- Echte Aufnahmen zeigen den Garten, die Straße und die Kameranamen des
  Betreibers. Das Repo ist öffentlich.
- Zeichnungen lassen sich aus dem Quelltext nachziehen. Ein Screenshot
  muss nach jeder Oberflächenänderung neu geschossen werden.
- SVG rendert GitHub direkt, skaliert auf jedem Bildschirm und bringt
  keine Lizenzfragen mit.

## Regeln beim Ändern

- **Eigener, undurchsichtiger Hintergrund** in jeder Datei. GitHub zeigt
  Bilder im hellen *und* im dunklen Theme; eine Zeichnung ohne eigenen
  Grund wird in einem der beiden unlesbar.
- **Kein Skript, kein externer Verweis.** GitHub führt in SVG nichts aus
  und lädt nichts nach. `<use href="#…">` innerhalb derselben Datei ist
  in Ordnung — mit `xlink:href` daneben für ältere Renderer.
- **Keine Emoji und keine Dingbats im Text.** Sie fallen je nach Schrift
  auf ein leeres Kästchen zurück. Ein Symbol wird gezeichnet.
- **Schriften nur als System-Stack** (`-apple-system, … system-ui,
  sans-serif`). Eingebettete Schriften wären eine externe Abhängigkeit.
- **Nie eine echte Adresse, ein echtes Token oder eine echte Chat-ID.**
  In den Zeichnungen stehen erfundene Kameranamen und keine Adressen;
  wo eine gebraucht wird, gilt RFC 5737 — `192.0.2.x`, `cam.lan`,
  `<BOT_TOKEN>`.

Wer diese Zeichnungen später doch durch echte Aufnahmen ersetzt, trägt
hier Quelle, Lizenz und Urheber jedes sichtbaren Bildes ein.
