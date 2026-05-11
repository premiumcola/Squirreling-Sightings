// ─── mediaview/playbar/time-axis.js ────────────────────────────────────────
// Tick row below the scrubber: 0 / ¼ / ½ / ¾ / full duration labels.
// Lives in its own row so the playhead line cuts through cleanly.
//
// SKELETON — re-exports the existing time-axis helpers; task #4
// migrates them into this file and adapts them to the new shell.

export {
  _refreshPlayButtonGlyph,
  _updatePlayPct,
  _wirePlayButton,
  _wirePlayCursorDrag,
  _wireScrubBar,
} from '../../mediathek/bbox-overlay/time-axis.js';
