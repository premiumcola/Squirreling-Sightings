# Screenshot credits

The three files `01-mediathek.svg`, `02-cam-edit.svg`, `03-telegram.svg` are
**hand-drawn SVG mockups**, not real screenshots. They sketch the structure and
layout of the corresponding views without showing any user data, real camera
imagery, or third-party licensed photos.

> **2026-05-06 — known stale state.** The mockups predate several UI
> moves and now show controls that are no longer present:
> `01-mediathek.svg` still depicts the three admin buttons in the top
> bar (they moved into the "Mediathek-Einstellungen → Sonderaktionen"
> accordion); `02-cam-edit.svg` still depicts the active/inactive
> toggle + "Verbinden" button + trash icon on the collapsed Geräte
> row (those were stripped — cameras are always active and
> auto-connect); `03-telegram.svg` doesn't reflect the new
> first-since captions ("Erstes Eichhörnchen seit 14 h ✨ neuer
> Rekord") or the quest-completion bubble. A follow-up pass will
> redraw or replace these — see `docs/_audit.md` for the full list
> of stale visuals.

Why mockups instead of real screenshots:

- The README is meant for visitors who arrive at the public repo. Real
  screenshots from a running deployment would either include the maintainer's
  garden / property (privacy) or require a one-shot demo deployment seeded
  with stock images.
- Mockups stay reproducible — anyone can regenerate them from the SVG source.
  Real screenshots drift the moment the UI changes and need re-shooting.
- SVG renders natively on GitHub, scales cleanly on retina and mobile, and
  has no third-party licensing concerns.

All shaped values inside the mockups (IP addresses, host names, RTSP
URLs) are RFC 5737/3849 documentation placeholders — `192.0.2.x` and
`<user>:•••@` patterns. Never copy a real LAN address into these files.

If you replace these with real screenshots later, please ensure:

- No user data (camera names that map to your address, IPs, Telegram tokens
  or chat IDs, MAC addresses) is visible.
- Any image content captured by the cameras either belongs to you or is
  licensed for redistribution. Stock images used to seed the gallery should
  be listed here with source / licence / author.

## Stock-image attribution template

When real screenshots replace the mockups, list each visible thumbnail here:

| File                  | Source     | Licence        | Author       |
|-----------------------|------------|----------------|--------------|
| 01-mediathek.png      | TBD        | TBD            | TBD          |
| 02-cam-edit.png       | TBD        | TBD            | TBD          |
| 03-telegram.png       | TBD        | TBD            | TBD          |
