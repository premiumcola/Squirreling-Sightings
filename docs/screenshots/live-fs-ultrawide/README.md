# Live FS letterbox · ultrawide screenshots

Drop two screenshots in here after the next 21:9 / 32:9 verification pass:

- `before.png` — pre-fix snapshot: dashboard tile in fullscreen on an
  ultrawide monitor showing the cropped / "zoomed in" output.
- `after.png` — post-fix snapshot: same monitor, same tile, now
  letterboxed with black gutters on the wide edges (or top/bottom
  if the source is taller than 21:9).

The fix lives in `app/web/static/css/03-dashboard.css` —
`.cv-img-wrap:fullscreen .cv-img` (and the `:-webkit-full-screen` /
`.fake-fullscreen` sibling selectors) now use `width:100%` and
`height:100%` with `!important` so `object-fit:contain` controls
the visible rect regardless of the MJPEG stream's reported
intrinsic dimensions.

The lightbox FS path (`#lightboxModal.lb-fs-video`) is intentionally
untouched.
