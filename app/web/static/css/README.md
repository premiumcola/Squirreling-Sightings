# CSS partials

This directory is the **source of truth** for the app's stylesheet. The file
`app/web/static/app.css` next to it is a build artifact: generated at server
boot by `app/app/css_builder.py` (or manually via `python scripts/build_css.py`)
and gitignored.

## Load order

The build script concatenates partials in this exact order (defined in
`app/app/css_builder.py::LOAD_ORDER`). The order matters where later rules
override earlier ones — design tokens must come first; mobile media queries
must come last so their @media rules win against any default-state rule the
domain partials introduce.

1. `tokens.css` — `:root` variables (color/spacing/radius), font setup
2. `base.css` — element resets, body, scrollbar, focus, the `.panel` /
   `.section` frame
3. `utilities.css` — `.btn-*`, badges, chips, the `.row` / `.row3` / `.split`
   helpers, anything genuinely utility-class shaped
4. `chrome.css` — sidebar accordion, mobile bottom dock, section-head icons,
   toast, tooltips, password-toggle
5. `hero.css` — hero panel + build-info column
6. `dashboard.css` — camera grid, `.cv-card`, surveillance overlay,
   offline/connecting placeholders, live pill, HD badge, settings cog
7. `mediathek.css` — `.media-*` + `.moc-*` + `.ws-card-*` + lightbox + bbox
   overlay + multi-select + pagination + pills + filters
8. `timeline.css` — `.tl-*` timeline lanes, range slider
9. `cam-edit.css` — every `.cam-*` + `.erk-*` + `.alert-*` + `.field-*` +
   zone/mask editor + RTSP builder + recovery
10. `timelapse.css` — Timelapse mode grid + period selectors + speed-up
    labels + active tags
11. `weather.css` — Wetter-Sichtungen + `.ws-*` + map markers + day/night
    override row + length-preview + sun-event sliders
12. `statistics.css` — Statistik dashboard + heatmap + chart
13. `sichtungen.css` — Achievements + Sichtungen accordion +
    animal-silhouette tiles
14. `coral.css` — Coral pipeline tree + 3-tab layout + per-model breakdown +
    grouped model browser
15. `telegram.css` — Telegram page + push settings + chat-thread
16. `mobile.css` — every `@media (max-width: 768px)` block from across the
    app, gathered into one place. Easier to review the mobile story end to
    end. **MUST stay last.**

## Editing partials

- Edit a partial → restart the server (or run `python scripts/build_css.py`)
  → hard-reload the browser. The `static_v()` cache-bust hash picks up the
  new content.
- Run `python scripts/watch_css.py` for a polling watch loop that rebuilds
  `app.css` whenever a partial's mtime changes.
- The build is a pure concatenation. No transforms, no minification, no
  preprocessor. What you write in a partial is what ships.

## Cross-domain rules

Some classes are consumed across domains (e.g. `.media-pill` styles used both
inside the Mediathek and inside the Wetter-Card view). Rule of thumb: the
class lives with its **primary domain** and other consumers just inherit. If
two domains genuinely co-own a class, leave it where its strongest visual
identity sits and add a one-line comment in the consuming partial pointing to
the owner.

## Adding a partial

1. Create the file under `css/`.
2. Add it to `LOAD_ORDER` in `app/app/css_builder.py` at the right position.
3. Update this README's load-order list.
4. Restart server / re-run build.
