// ─── mediaview/player/_frame-step.js ───────────────────────────────────────
// Frame-by-frame stepping. There is no reliable cross-browser API to
// read a <video>'s actual per-clip frame rate (requestVideoFrameCallback
// exists but doesn't expose the source fps either), so a fixed step is
// used instead of guessing per-clip.
//
// FRAME_STEP_SECONDS = 0.1 (1/10 s) matches this project's OWN encoding
// default: camera_runtime/_recording/__init__.py's
// _finalize_motion_clip(..., fps=10.0) — every motion clip ffmpeg writes
// defaults to 10 fps unless the caller overrides it (clamped 5-30 fps
// elsewhere in that module). A clip actually recorded faster steps more
// than one encoded frame per press and one recorded slower steps less
// than one — an unavoidable approximation without a real per-clip fps
// read, but 1/10 s is the one fixed value that is exactly right for the
// common case instead of an arbitrary round number.

export const FRAME_STEP_SECONDS = 0.1;

/**
 * Pure — next currentTime for a frame-step, clamped to [0, duration].
 * `duration` <= 0 (metadata not loaded yet) clamps only at 0.
 *
 * @param {number} current   video.currentTime
 * @param {number} duration  video.duration
 * @param {number} [dir]     +1 (default, forward) or -1 (back)
 */
export function stepFrameTime(current, duration, dir = 1) {
  const cur = Number.isFinite(current) && current > 0 ? current : 0;
  const dur = Number.isFinite(duration) && duration > 0 ? duration : 0;
  const next = cur + FRAME_STEP_SECONDS * (dir < 0 ? -1 : 1);
  const clampedLow = Math.max(0, next);
  return dur > 0 ? Math.min(dur, clampedLow) : clampedLow;
}

/** Impure — steps video.currentTime and returns the new value. */
export function applyFrameStep(video, dir = 1) {
  if (!video) return null;
  const t = stepFrameTime(video.currentTime, video.duration, dir);
  video.currentTime = t;
  return t;
}
