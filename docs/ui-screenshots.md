# UI-Screenshots — actually looking at the app

Until now every UI change in this repo was verified by reading CSS and
reasoning about it. There was no browser anywhere in the toolchain, so
defects that are obvious in one glance shipped repeatedly: elements
overlapping on a phone, a control row the approved design had struck,
buttons invisibly dark-on-dark.

`scripts/uishot/` renders the real UI at real phone widths, writes PNGs,
and reports what the DOM can answer objectively about them.

## One command

```bash
node scripts/uishot/run.mjs
```

PNGs land in `.uishots/` (gitignored), one per surface × width:

```
.uishots/vplayer-recorded-375.png      .uishots/vplayer-recorded-393.png
.uishots/weather-save-panel-375.png    .uishots/dashboard-tile-375.png
.uishots/mediathek-grid-375.png        …and each at 1440 px
```

Limit it to one surface while iterating:

```bash
node scripts/uishot/run.mjs vplayer-recorded
node scripts/uishot/run.mjs dashboard-tile mediathek-grid
```

Surface ids: `vplayer-recorded`, `weather-save-panel`, `dashboard-tile`,
`mediathek-grid`. Widths: 375 (iPhone SE), 393 (iPhone 14), 1440.
Dark theme, `deviceScaleFactor: 2`, touch + mobile emulation below 500 px.

## This is a tool, not a gate

It is wired into no CI workflow, no pre-commit hook and no npm script.
It answers "what does this look like", which is a question for a person.
Nothing here may become blocking — a flaky screenshot gate teaches people
to skip it.

## Installing the browser

The browser is deliberately **not** a dependency of this repo.
`package.json` stays the lint-only manifest it has always been, and
nothing lands inside the git tree.

```bash
bash scripts/uishot/install-browser.sh
```

Default prefix `~/.cache/sq-uibrowser`, override with `SQ_UIBROWSER_HOME`.
Roughly 1.1 GB, in three parts, because the devbox container is minimal:

| part | size | why |
|---|---|---|
| playwright + Chromium | ~870 MB | the browser |
| Debian runtime libs → `sysroot/` | ~150 MB | libX11, libnss3, libgbm … 21 of them are simply absent here |
| fonts + `fonts.conf` | (in sysroot) | the host has **no fonts at all** |

No root and no `apt-get install`: the `.deb`s are downloaded as a normal
user and unpacked into a private sysroot that only this tool's
`LD_LIBRARY_PATH` points at. Nothing outside the prefix is touched.

Without the fontconfig step Chromium starts, lays text out, and paints
**no glyphs at all** — you get a screenshot with correctly-sized empty
boxes. If shots ever come back wordless, that is the thing that broke.

Run it without a browser installed and you get the install command and
exit 3, not a stack trace.

## What is actually rendered

Not a mock-up:

- **CSS** — `scripts/build_css.py` builds `app.css` from the real
  `LOAD_ORDER` in `app/app/css_builder.py` (57 partials). The page links
  that one file, exactly as `index.html` does.
- **Markup** — `scripts/uishot/render_shell.py` renders the real
  `app/web/templates/index.html` with the real Jinja2 and every real
  `{% include %}`. Every surface here is JS-generated into a container
  that ships in a partial, so the containers must come from the templates.
- **Behaviour** — each surface drives the module's public entry against a
  fixture: `openVideoPlayer()`, `renderDashboard()` + `renderPanel()`,
  `renderMediaGrid()`, and for the weather panel the button click that is
  its only mount path.

No Flask. `/api/*` is answered at the browser (`_stubs.mjs`); the two CDN
`<script>` tags are stubbed so the harness never needs the network.

The `<video>` gets a real 12-second WebM, generated once
(`_clip.mjs`). That is not decoration: the recorded timeline lays every
lane out against `video.duration`, and with no decodable source the strip
collapses to zero width and the screenshot flatters the layout.

## The automatic checks

Per surface, printed with selectors. Each maps to a defect class this
project has actually shipped:

| rule | what it means |
|---|---|
| `occluded` | `elementFromPoint` says something else answers where this text is — the honest "is it buried" test, and the only rule that sees chrome from outside the surface (the mobile dock) |
| `overflow` | box extends past the viewport's right edge |
| `textcollide` | text partially covered by other text or by a painted box. Partial only: full containment is layering, not a bug |
| `overlap` | in-flow siblings sharing pixels |
| `contrast` | computed colour on computed background below 4.5:1 |
| `touch` | interactive element under 44 × 44 px (CLAUDE.md, iOS) |

## What it still cannot see

Be honest about the limits before trusting a green run:

- **Not a real iPhone.** Chromium on Linux with mobile emulation. No
  Safari, so no iOS-specific `dvh` / `position: fixed` / address-bar
  collapse behaviour — the exact family CLAUDE.md calls the most
  recurring regression class. The 375/393 shots are a layout check, not
  an iOS check.
- **Fonts differ.** The app asks for `Inter, system-ui, …` and ships no
  `@font-face`; here that resolves to DejaVu Sans. Glyph widths are
  close but not identical, so a text box within a few px of overflowing
  may fall on either side.
- **Fixture data, not your data.** A camera name twice as long, or a
  species list of six, will break rows these shots show as fine.
- **One moment in time.** No hover, no focus, no open menus, no
  animation mid-flight, no scrolled state.
- **Colour only where CSS declares it.** The contrast rule skips any
  element whose backdrop is an image or gradient rather than inventing a
  number for it.
- **Static picture.** Nothing here checks that a button *does* anything.
