# Documentation audit — 2026-05-06

Read-only inventory of every documentation file and graphic asset
checked into the repo, with a per-item verdict against the **current**
codebase. No rewrites land in this commit; this file is the source of
truth that drives the README rewrite + subpage refresh in the
follow-up commits.

## Method

- Listed every `*.md` and image asset reachable via `git ls-files`.
- Compared mentioned features / config keys / paths against the live
  modules (Python in `app/app/`, JS in `app/web/static/js/`).
- Noted the file's last-touched commit (date / sha) where it surfaces
  decay risk.
- Cross-checked feature claims against the patterns table in
  `.claude/chat-restart.md` (which lists everything that landed in the
  recent F-task batches).

## Markdown files

### `README.md` — root landing page

- **Last touched:** `5a6d115`, 2026-04-27.
- **Length:** 248 lines.
- **Tone / structure:** mixed German + English. Hero banner, badges,
  `<table>`-based feature grid, screenshot block, architecture
  diagram, quickstart, configuration, tech-stack, roadmap, credits.
- **Verdict:** **STALE / under-claims**. Predates the recent F-task
  batches. Concrete gaps:
  - No mention of **F09 Quest system** (saisonale Quests +
    Telegram-Glückwunsch on completion) — `app/app/quests.py`.
  - No mention of **F08 Bird Dossiers** (auto Wikipedia + Xeno-canto
    fetch on first sighting) — `app/app/bird_dossiers.py`.
  - No mention of **F06 First-Since Detector** (anomaly tagging per
    class + Telegram caption variant) — `app/app/first_since.py`.
  - "Sun-Timelapses" is mentioned but the feature has been hardened
    (window locked at 75 min, day/night mode override, recording
    pipeline anchored to window-start) — README still suggests
    user-tunable durations.
  - "Sunset" is listed under Wetter as a 10 s-clip event — that raw
    pipeline was just removed; sunrise / sunset live exclusively in
    the timelapse path now.
  - Telegram caption variant for first-since events not mentioned.
  - Patterned-magenta corruption filter (just-added strengthening of
    the timelapse frame-validity detector) not documented.
  - Mediathek "Sonderaktionen" accordion (recent move of admin
    actions out of the top bar) not reflected in the screenshot text.
- **Hard-rule violation per current spec:** README contains an HTML
  table for the Features grid + a markdown table for "Pfad / Zweck"
  in Configuration. The README rewrite must drop both.
- **Action:** **rewrite from scratch** (Task 21).

### `app/README.md` — backend architecture deep-dive

- **Last touched:** `0de7790`, 2026-05-04.
- **Length:** 174 lines.
- **Verdict:** **mostly current** — was refreshed in the same commit
  that trimmed `server.py`. Lists the package split (routes/,
  detectors/, camera_runtime/, weather_service/, telegram_bot/) and
  mentions sun-timelapse + per-cam profiles.
- **Gaps to close:**
  - Doesn't mention `quests.py`, `bird_dossiers.py`, `first_since.py`.
  - Doesn't mention `_event_tl.py` (event-timelapse triggers
    thunder_rising / front_passing / storm_front).
  - Doesn't mention the `is_timelapse` per-event-type marker that
    just landed in `web/static/js/core/weather-types.js`.
- **Action:** add a short "Newer modules" section to flag the F-task
  additions (Task 22).

### `CLAUDE.md` — operating manual for the agent

- **Last touched:** `0de7790`, 2026-05-04.
- **Verdict:** **current**. Refreshed in the server-trim commit;
  documents lint stack, hard rules, design principles, iOS rules,
  Docker workflow (`restart` not `compose up --build`), and the
  full `app/app/` module map including the new packages.
- **Action:** none in this audit. Refresh later only if a hard rule
  changes.

### `app/INSTALL_UNRAID.md` — Unraid deployment guide

- **Last touched:** `6164e93`, 2026-04-27.
- **Length:** 105 lines.
- **Verdict:** **current** for bind-mount layout + Telegram deeplink
  setup. Predates the F-task batches but those don't change install.
- **Action:** spot-check links + paths during Task 22; likely no
  change beyond a "what's new" pointer.

### `app/docs/INSTALL_CORAL.md` — Coral USB install

- **Last touched:** `02ec3be`, 2026-04-27.
- **Length:** 122 lines.
- **Verdict:** **current**. Walks through device passthrough,
  pycoral install, fallback to CPU tflite. References
  `coral-pipeline.svg` illustration which is also current.
- **Action:** none.

### `app/docs/camera_notes.md` — vendor-specific notes

- **Last touched:** `6631c24`, 2026-04-27.
- **Length:** 108 lines.
- **Verdict:** **current**. Documents Reolink / Hikvision / Dahua
  RTSP paths, ID schema, discovery quirks. RFC-5737 placeholder IPs
  used per CLAUDE.md hard rule.
- **Action:** none.

### `app/web/static/css/README.md` — CSS partials build

- **Length:** 86 lines.
- **Verdict:** **likely stale numbering**. Recent partials that
  landed across the F-task work (`28-quests.css`, `29-birds.css`)
  exist in `css_builder.py` LOAD_ORDER but the README's enumeration
  of partials may not reflect them.
- **Action:** verify in Task 22; one-line update if the list is off.

### `app/web/templates/partials/README.md` — partial mounting rules

- **Length:** 75 lines.
- **Verdict:** **needs verification** — partials may have been
  added since (Quest pinboard, Bird-Dossiers section) without a
  corresponding README mention.
- **Action:** verify in Task 22.

### `docs/screenshots/CREDITS.md` — screenshot recipe

- **Last touched:** `423035f`, 2026-04-27.
- **Length:** 39 lines.
- **Verdict:** **current** mechanically (the placeholder-IP rule
  hasn't changed) but the three screenshot SVG mockups it credits
  are outdated — they do not show the Quest pinboard, the bird-
  dossier modal, or the new mobile dock pill, and the Mediathek SVG
  shows the now-removed admin buttons in the top bar.
- **Action:** the SVGs need refreshing OR replacing with real
  captures (Task 22 graphics pass).

### `storage/test_images/README.md`

- **Length:** 37 lines.
- **Verdict:** scoped doc for the test-image fixtures.
  Self-contained, no live-feature claims to drift.
- **Action:** none.

## Image / graphic assets

### Hero / banner

- `docs/banner.svg` — referenced from README hero.
  - **Verdict:** present, renders via the README. Visual style
    pre-dates the new camera-themed brand glyph that just landed in
    the app's hero panel — reuse-or-refresh decision in Task 22.

### Architecture

- `docs/architecture.svg` — referenced from README's Architecture
  section.
  - **Verdict:** **stale**. Pre-dates the F-task additions (Quests,
    Bird Dossiers, First-Since detector, Event-Timelapse triggers).
    Should either be redrawn or replaced with a Mermaid flowchart in
    the README rewrite.

### Illustrations

- `docs/illustrations/app-modules.svg` — module-graph illustration
  for the README architecture section.
  - **Verdict:** **stale** — predates `quests.py`, `bird_dossiers.py`,
    `first_since.py`, and `_event_tl.py`. Refresh in Task 22.
- `app/docs/illustrations/camera-id-schema.svg` — referenced from
  `camera_notes.md`.
  - **Verdict:** **current**.
- `app/docs/illustrations/coral-pipeline.svg` — referenced from
  `INSTALL_CORAL.md`.
  - **Verdict:** **current**.

### Screenshots

- `docs/screenshots/01-mediathek.svg` — Mediathek mockup.
  - **Verdict:** **stale** on the top-bar admin-action cluster
    (Thumbnails / Neu scannen / Tracking neu generieren) — those
    moved into the "Mediathek-Einstellungen → Sonderaktionen"
    accordion. Replace.
- `docs/screenshots/02-cam-edit.svg` — Cam-edit mockup.
  - **Verdict:** **stale** on the Geräte-row action cluster (toggle
    + Verbinden + trash) — those were stripped from the collapsed
    row when cameras became always-active. Replace.
- `docs/screenshots/03-telegram.svg` — Telegram-push mockup.
  - **Verdict:** still illustrative but doesn't show first-since
    captions or quest-completion notifications.

### App icons / favicons / splash screens

- `app/web/static/icons/icon-{120..1024}.png`,
  `favicon-{16,32}.png`, splash-screen variants under
  `app/web/static/icons/splash/` — **160+ binary assets**.
  - **Verdict:** **all current**. These are the PWA icon set, not
    documentation graphics. Generated by `_build_icons.py` and
    referenced from `manifest.json` / index template.
- `app/web/static/squirrel-mini.svg` — legacy hero glyph (replaced
  in the title by the new camera-themed inline SVG, but the file is
  kept on disk per CLAUDE.md hard rule "additive only").
  - **Verdict:** unused by the current hero, retained for back-compat.

## Spot-checks against `.claude/chat-restart.md` patterns table

- **Bird Dossiers Service** (`app/app/bird_dossiers.py` +
  `routes/sichtungen.py`):
  - Mentioned in any doc? → **No**. README "Sichtungen" tile only
    talks about achievement medals.
- **Quest System** (`app/app/quests.py` + Pinboard in
  `sichtungen.html`):
  - Mentioned in any doc? → **No**. README has no quest section.
- **First-Since Detector** (`app/app/first_since.py` + Hook in
  `_recording.py::_finalize_motion_clip`):
  - Mentioned in any doc? → **No**. Telegram-caption section in
    README ends at "Anchor-Bubble".

## Summary headlines for the rewrite

1. README under-sells by ~3 major features. Rewrite is justified.
2. Three screenshot SVGs all show outdated UI states; need new
   captures from the running app or fresh SVG mockups.
3. `app/README.md` is mostly current — needs only a small "newer
   modules" amendment.
4. `architecture.svg` and `app-modules.svg` need redrawing OR
   replacement with a Mermaid flowchart inline in the README.
5. Hard rule for Task 21: drop the existing `<table>` Features grid +
   the markdown table in Configuration. README must contain zero
   tables.
