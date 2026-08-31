// ─── mediaview/player/_snapshot.js ─────────────────────────────────────────
// Current-frame → downloadable image. `<canvas>` + drawImage + toBlob is
// the standard approach; no existing project convention was found for
// this specific "export what's on screen" case to reuse instead (the
// other canvas call sites — camedit/coral-test/bbox.js,
// mediaview/canvas/zone-layer.js — draw INTO a canvas for on-screen
// overlay rendering, none of them export/download one).
//
// Deliberately captures the VIDEO FRAME ONLY, not the SVG overlay layers
// (bboxes/trails/zones) composited on top. "What the camera saw", not
// "what our UI drew over it" — the overlay is our own annotation, live-
// recomputed from tracks.json on every open, so compositing it in would
// bake a frame-specific, possibly-stale annotation into a file the
// operator may keep or share long after the sidecar (and the boxes it
// draws) can change. The download-the-clip-file precedent in this
// codebase (recorded-mode.js::_downloadItem) exports the RAW mp4 for the
// same reason — never the annotated view.
//
// The `doc` parameter (default `document`) is dependency injection for
// tests: a real DOM canvas's 2D context and toBlob aren't available
// under plain node:test (no jsdom in this repo — see CLAUDE.md's
// "zero new dependencies" test convention), so tests pass a minimal
// stub implementing only what this file calls.

/**
 * Draw the current video frame onto a fresh canvas. Returns `null`
 * instead of throwing when the video has no usable frame yet (0
 * dimensions — not loaded, or a stream that hasn't started) so a click
 * on an unready player is a no-op, not a crash.
 *
 * @param {HTMLVideoElement} video
 * @param {Document} [doc]
 * @returns {HTMLCanvasElement|null}
 */
export function captureFrameCanvas(video, doc = document) {
  const w = video && video.videoWidth;
  const h = video && video.videoHeight;
  if (!video || !Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return null;
  const canvas = doc.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext && canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(video, 0, 0, w, h);
  return canvas;
}

/** `snapshot_<elapsed-seconds>s.png` — no external state needed. */
export function snapshotFilename(video) {
  const t = video && Number.isFinite(video.currentTime) ? Math.floor(video.currentTime) : 0;
  return `snapshot_${t}s.png`;
}

/**
 * Capture the current frame and trigger a browser download. Returns
 * true when a capture was attempted (the download itself is async via
 * toBlob), false when there was nothing to capture.
 *
 * @param {HTMLVideoElement} video
 * @param {Document} [doc]
 */
export function downloadSnapshot(video, doc = document) {
  const canvas = captureFrameCanvas(video, doc);
  if (!canvas || typeof canvas.toBlob !== 'function') return false;
  const filename = snapshotFilename(video);
  canvas.toBlob((blob) => {
    if (!blob) return;
    // Anchor-click download — same idiom as recorded-mode.js's
    // _downloadItem (the clip-file download), extended with the
    // createObjectURL/revokeObjectURL pair a Blob needs that a plain
    // media URL does not.
    const url = URL.createObjectURL(blob);
    const a = doc.createElement('a');
    a.href = url;
    a.download = filename;
    doc.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }, 'image/png');
  return true;
}
