# Frontend module-refactor verification — stages 1–4

Captured 2026-05-02 after stages 1, 2, 3a, 3b, 4 of the
`app.js → ES modules` migration shipped.

---

## a) Module inventory

| File | Lines | Purpose |
|---|---:|---|
| `js/main.js` | 13 | Module entry — imported via `<script type="module">`. |
| `js/legacy.js` | 9314 | Monolith bridge — shrinks one stage at a time. |
| `js/core/state.js` | 51 | `state` singleton, `shapeState`, `IS_IOS`, `STAT_MEDIA_DRILLDOWN`. |
| `js/core/dom.js` | 19 | `byId`, `esc`, `qs`, `qsa`. |
| `js/core/api.js` | 55 | `apiGet/apiPost/apiPut/apiDelete` + legacy `j`. |
| `js/core/toast.js` | 83 | `showToast`, `showConfirm`, `bindConfirmModal`. |
| `js/core/icons.js` | 108 | `colors`, `OBJ_LABEL`, `OBJ_SVG`, `objBubble`, `objIconSvg`, `getCameraIcon`, `getCameraColor`, `TL_LABELS`. |
| `js/dashboard.js` | 460 | All dashboard rendering + helpers + 5 fps preview + reload animation. |
| `js/lightbox.js` | 98 | Lightbox pure DOM helpers (orchestration still in legacy). |

Module loader confirmed: `index.html:1644` →
`<script type="module" src="/static/js/main.js?v={{ static_v('js/main.js') }}"></script>`

`core/*` import-graph health: every core module is imported by ≥ 1 consumer.

| Module | Consumers |
|---|---:|
| `core/state.js` | 3 |
| `core/dom.js` | 3 |
| `core/api.js` | 2 |
| `core/toast.js` | 1 |
| `core/icons.js` | 2 |

Single-source-of-truth check passed for representative symbols
(`renderDashboard`, `_camImgRetry`, `_lbShowError`,
`_makeConnectingPlaceholder`, `_updateLbConfirmBtn`) — each
appears in exactly one module.

**Discrepancy with task spec:** the brief expected `mediathek.js`
to exist post-stage-4. It does NOT exist yet — stage 4 only
extracted lightbox helpers (the bigger lightbox/mediathek surface
was deferred because it's entangled with timelapse + live-view).
Stage 4's actual scope was reflected in commit `446198e`
("extract lightbox pure DOM helpers"). Mediathek extraction is
queued for a future stage.

---

## b) Quality sweep — fixed inline this commit

### `console.*` (was 3, now 0)
- `legacy.js:96` — `console.error('label update failed', e)` inside
  `_renderLbLabels`'s label-toggle catch → replaced with
  `showToast('Label-Änderung fehlgeschlagen', 'error')`.
- `legacy.js:1930` — `console.error('editCamera: not found', camId)`
  → silenced; the `_currentEditCamId = null` reset that follows is
  the real recovery, the log line was diagnostic-only.
- `legacy.js:4761` — `console.warn('[toggleSetSection] not found:', id)`
  → silenced; the `return` that follows is the real handler, the
  warn was diagnostic-only.

### Native `confirm/prompt/alert` (was 3, now 0)
- `legacy.js:3091` — push-presets overwrite confirm → `await showConfirm(...)`.
- `legacy.js:3940` — Reolink rescan overwrite confirm → `await showConfirm(...)`.
- `legacy.js:8225` — weather-event delete confirm → `showConfirm(...).then(...)`.

All three sites now route through the styled confirm modal in
`core/toast.js`.

---

## c) Legacy `window.*` bridge inventory

68 explicit `window.X = X` assignments in `legacy.js` (down from
~70 pre-stage-1). Plus 5 in `dashboard.js`, 2 in `core/toast.js`.

| Module | window bridges |
|---|---:|
| `legacy.js` | 68 |
| `dashboard.js` | 5 (`_camImgRetry`, `_cvCardClick`, `toggleCardHd`, `_refreshLivePillForCard`, `reloadCamera`) |
| `core/toast.js` | 2 (`showToast`, `showConfirm`) |

These are necessary as long as inline `onclick="X(...)"` survives in
HTML templates and JS-rendered template strings. Stage 16's planned
"drop legacy.js bridge" pass should also retire these in favour of
addEventListener — but that's a separate sweep.

---

## d) Section-header inventory of `legacy.js`

The work-list for stages 6+. Every `// ── …` block in `legacy.js`,
in source order:

| Line | Section | Target domain (proposed) |
|---:|---|---|
| 104 | Squirrel character library | `core/icons.js` (or delete — currently dead) |
| 123 | Camera edit slide panel | `camedit/panel.js` |
| 154 | Live update | `live-update.js` |
| 464 | Timeline | `timeline.js` |
| 632 | RTSP path options | `camedit/rtsp.js` |
| 650 | URL password masking | `camedit/rtsp.js` |
| 857 | Camera merge modal | `camera-merge.js` |
| 974 | Whitelist chips | `camedit/whitelist.js` |
| 994 | Camera form one-time listeners | `camedit/detection.js` |
| 1260 | Alerting tab — class-severity matrix | `camedit/detection.js` |
| 1806 | camera_id JS port | `camedit/camera_id.js` (lockstep with python) |
| 2238 | Connection-recovery modal | `camedit/recovery.js` |
| 2543 | Live View Modal | `chrome/live-view.js` |
| 2608 | Fullscreen helpers | `chrome/fullscreen.js` |
| 2799 | Telegram page hydrate & logic | `telegram.js` |
| 2874 | Push-Settings UI (Phase 2) | `push.js` |
| 3439 | Shape-editor UI updaters | `camedit/shape-editor.js` |
| 3948 | Section-level save functions | `camedit/saves.js` |
| 4422 | Camera card placeholders | already in `dashboard.js` (legacy stub remains) |
| 4442 | Timelapse Settings | `camedit/timelapse.js` |
| 4720 | Timelapse Status Bar | `dashboard.js` extension |
| 4759 | Settings collapsible sections | `chrome/settings-collapse.js` |
| 4783 | Sidebar settings scroll-link | `chrome/sidebar.js` |
| 4836 | Sidebar active-nav state | `chrome/sidebar.js` |
| 4880 | Password field visibility toggle | `chrome/password-toggle.js` |
| 4904 | Media storage stats | `chrome/storage-stats.js` |
| 4967 | Shape editor wiring | `camedit/shape-editor.js` |
| 5185 | Sidebar | `chrome/sidebar.js` |
| 5224 | Mobile bottom dock | `chrome/mobile-dock.js` |
| 5326 | Logs | `chrome/logs.js` |
| 5361 | Telegram test button | `telegram.js` |
| 5380 | Media rescan button | `mediathek/rescan.js` |
| 5486 | Lightbox / Media viewer | `lightbox.js` (orchestration) |
| 5502 | Detection-bbox overlay | `lightbox/bbox-overlay.js` |
| 5814 | iOS native video player handoff | `lightbox/ios-video.js` |
| 5987 | Media overview + drill-down | `mediathek/drilldown.js` |
| 6463 | Multi-select / bulk delete | `mediathek/bulk-delete.js` |
| 6527 | Media grid resize observer | `mediathek/grid.js` |
| 6636 | Bird SVG icons | `core/icons.js` or `core/animal-icons.js` |
| 6683 | Mammal SVG icons | same |
| 6694 | Sichtungen drilldown | `sichtungen.js` |
| 6821 | Achievements / Sichtungen | `sichtungen.js` |
| 7046 | Statistics dashboard | `statistics.js` |
| 7305 | Wetter-Ereignisse Phase 2 | `weather/sightings.js` |
| 7339 | Wetterdaten & Prognose chart | `weather/chart.js` |
| 8286 | Settings: Wetter-Ereignisse | `weather/settings.js` |
| 8303 | Weather "zuletzt gespeichert" hint | `weather/settings.js` |
| 8680 | Event-Timelapse: per-camera Settings rows | `camedit/timelapse.js` |
| 8788 | Weather location map (Leaflet) | `weather/map.js` |
| 8998 | Wetter-Ereignisse Phase 3: Recaps + push UI + hash anchor | `weather/sightings.js` |
| 9092 | Push Weather settings | `push.js` extension |
| 9143 | Hash anchor handler | `weather/sightings.js` or `main.js` |
| 9190 | Telegram deep-link router | `main.js` boot |

**~9000 lines of legacy code to migrate across ~13 sections / ~15
files.** Stages 6–16 in the queue cover this work.

---

## e) Mobile bottom-nav regression check — PASS

`app.css:539` reads:

```css
bottom: max(var(--m-dock-gap), env(safe-area-inset-bottom, 0px));
```

No regression to the additive `calc(env(...) - 8px)` formula. The
fix from commit `6840cce` is intact.

---

## f) Build + log check

Cannot run docker from this WSL shell; instead the static checks
ran:

- `node --check` on every file under `js/` — all parse clean.
- Module-import-graph manually walked — every `import` from
  `core/`, `dashboard.js`, `lightbox.js` resolves to an actually-
  exported symbol.
- Symbol single-source check (above) — no duplicate definitions.

These are the same kinds of breakage the previous regression
caused (duplicate `_tlPeriodLabel`, missing `window._openMediaItem`).
The same audit pattern would have caught those, so the discipline
is in place.

User must run the following before signing off:

```
docker restart tam-spy
```

Hard reload (Ctrl+Shift+R), walk each nav item: Dashboard, Cams,
Statistik, Mediathek, Wetter, Sichtungen, Settings, Logs. DevTools
console must be clean (the harmless `apple-mobile-web-app-capable`
deprecation warning is fine).

---

## TODO (deferred, do NOT touch in this commit)

- **`mediathek.js` does not exist yet.** Task brief expected it
  post-stage-4 but stage 4 only carried lightbox pure helpers.
  Mediathek extraction is queued.
- **68 `window.X = X` bridges in legacy.js.** Required while inline
  `onclick="..."` handlers survive in templates. A future
  "addEventListener migration" sweep can retire them in lockstep
  with template edits — that's a discrete refactor, not part of
  the module split.
- **The `SQUIRREL_CHARS` library at line 104** is currently dead
  code (its renderer was retired in the hero-panel refactor).
  Either delete entirely or fold into `core/icons.js` if a future
  feature wants the squirrel-art assets back. Logged here so it
  doesn't get accidentally moved during the next stage.
