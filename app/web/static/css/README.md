# CSS partials

This directory is the **source of truth** for the app's stylesheet. The file
`app/web/static/app.css` next to it is a build artifact: generated at server
boot by `app/app/css_builder.py` (or manually via `python scripts/build_css.py`)
and gitignored.

## Why numbered prefixes?

Partials are concatenated in the exact order shown by the file names'
numeric prefix (`01-…` → `25-…`). That order **matches the original
source-position** of every rule in the pre-split monolith. Preserving source
order is what guarantees the cascade — same selector + same specificity →
last write wins. Reordering rules across partials would silently change
which rule survives, especially inside `@media` blocks.

This is why mobile rules are NOT all gathered into `25-mobile.css`. Most
`@media (max-width:768px)` blocks live with their owning domain (so they
appear at the same source position as in the original file). Only the large
"iOS / mobile foundation" tail block (formerly the bottom ~600 lines of
`app.css`) lives in `25-mobile.css`. A future "gather mobile" pass can
revisit this once we have a dedicated visual-regression harness — for this
round, byte-identity wins.

## Load order (= file-name order)

| # | File | Lines | What's primarily inside |
|---|---|---:|---|
| 01 | `01-base.css` | 49 | `:root` tokens, element resets, `.shell`, `.panel`, sidebar/nav |
| 02 | `02-hero.css` | 95 | Hero panel + build-info column |
| 03 | `03-dashboard.css` | 314 | Camera grid, `.cv-card`, monitoring placeholders, pills, surveillance overlay, settings cog, unified category filter button |
| 04 | `04-coral-1.css` | 56 | Coral pipeline tree (compact) |
| 05 | `05-chrome-dock.css` | 116 | Mobile bottom dock |
| 06 | `06-cam-edit-1.css` | 949 | Zone/mask editor + Erkennung 5-step + Alerting + per-cam pill bar + Erkennung+Aufnahme block |
| 07 | `07-timelapse-1.css` | 54 | Timelapse Settings section |
| 08 | `08-settings.css` | 141 | Sidebar settings accordion + storage bar + password-toggle |
| 09 | `09-telegram-1.css` | 77 | Telegram page |
| 10 | `10-timeline.css` | 13 | Timeline tooltip / hover popup |
| 11 | `11-chrome-overlays.css` | 21 | Toast + section-head icon |
| 12 | `12-sichtungen.css` | 100 | Achievements + Sichtungen drilldown accordion |
| 13 | `13-statistics.css` | 62 | Statistics dashboard |
| 14 | `14-mediathek-1.css` | 14 | Mediathek multi-select mode |
| 15 | `15-coral-2.css` | 165 | Coral 3-tab layout + accent overrides + per-model breakdown + grouped model browser |
| 16 | `16-cam-edit-2.css` | 18 | Reconnect button |
| 17 | `17-timelapse-2.css` | 20 | Timelapse mode grid |
| 18 | `18-telegram-2.css` | 107 | Group/Telegram panels content inset + fullscreen + push-settings |
| 19 | `19-weather-1.css` | 60 | Wetter-Ereignisse |
| 20 | `20-mediathek-2.css` | 34 | Lightbox |
| 21 | `21-weather-2.css` | 152 | Wetter settings + recaps strip + per-cam sun-timelapse + event-timelapse |
| 22 | `22-cam-edit-3.css` | 82 | Camera connection-recovery indicator + modal |
| 23 | `23-weather-3.css` | 136 | Wetterdaten & Prognose chart block |
| 24 | `24-cam-edit-4.css` | 67 | Camera-edit live id preview |
| 25 | `25-mobile.css` | 584 | iOS / mobile foundation through end of file |
| 26 | `26-erk-sim-sheet.css` | — | Camera-edit Erkennung-tab simulation sheet (single-body) |
| 27 | `27-coral-test-modes.css` | — | Coral test panel mode selector + per-detection model badges |
| 28 | `28-quests.css` | — | Quest pinboard (F09) — saisonale Quests in Sichtungen |
| 29 | `29-birds.css` | — | Vogel-Dossier-Galerie + Modal mit Audio-Player (F08) |

Total: 3486 lines from the pre-split `app.css`, plus per-file additions.

## Editing partials

- Edit a partial → restart the server (or run `python scripts/build_css.py`)
  → hard-reload the browser. The `static_v()` cache-bust hash picks up the
  new content.
- Run `python scripts/watch_css.py` for a polling watch loop that rebuilds
  `app.css` whenever a partial's mtime changes.
- The build is a pure concatenation. No transforms, no minification, no
  preprocessor. What you write in a partial is what ships.

## Why some domains span multiple files

`cam-edit-1.css`, `cam-edit-2.css`, `cam-edit-3.css`, `cam-edit-4.css` —
camera-edit rules appear in four non-adjacent slabs of the original file.
Same for `coral-1` / `coral-2`, `weather-1` / `-2` / `-3`, `telegram-1` /
`-2`, `mediathek-1` / `-2`, `timelapse-1` / `-2`. The numbered suffix tells
you which slab; together they're the full domain. A "decompose by domain"
follow-up pass can merge these once a visual-regression harness is in
place. For now: contiguous slabs only, source order preserved.

## Adding a partial

1. Create the file under `css/`. Use the next free numeric prefix for the
   slot you want it loaded in.
2. Add it to `LOAD_ORDER` in `app/app/css_builder.py` at the right
   position.
3. Update this README's load-order table.
4. Restart server / re-run build.
