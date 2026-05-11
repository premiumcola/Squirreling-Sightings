// ─── mediaview/index.js ────────────────────────────────────────────────────
// Public facade for the unified MediaView shell. The shell will
// eventually host four legacy viewers — Mediathek-Lightbox, Cam-Edit
// "Erkennung jetzt simulieren", Dashboard "Live öffnen", and the
// Timelapse-Lightbox — behind one composable config object.
//
// This file is the SKELETON landing of the migration plan: the tree
// is in place, the public surface is defined, but `openMediaView`
// still routes recorded events through the existing Mediathek
// lightbox flow until the migration tasks (#3-#6 in the queue) move
// the implementation in piece by piece. That way the legacy lightbox
// keeps working for daily use during the migration and the new code
// paths come online incrementally.
//
// Layout under mediaview/:
//   shell.js                 — composes the six structural pieces
//   title-bar.js             — header, prev/next/close
//   canvas/
//     index.js               — image | video | mjpeg source switch
//     bbox-layer.js          — derived from bbox-overlay/renderer.js + raf.js
//     trail-layer.js         — placeholder for path trails (future)
//     zone-layer.js          — read-only camera-zone polygon overlay
//   playbar/
//     index.js               — composes scrubber + axis + lanes + cursor
//     scrubber.js
//     time-axis.js
//     swimlane.js            — per-class row builder
//     confirmer-row.js
//     playhead-line.js       — the ONE vertical line cutting every row
//   panel-tabs.js
//   panels/
//     detections.js
//     tracks-list.js
//     recording-settings.js  — moved from bbox-overlay/settings-panel.js
//     weather.js
//   fine-analysis-fold.js
//   detail-pill.js
//   keyboard.js
//
// Re-exports from bbox-overlay/ keep `lightbox.js` working without an
// import-path change during the migration. As tasks #3-#6 move the
// implementation here, this file replaces those re-exports with the
// real owners.

import {
  _lbDrawDetections,
  lbClearTrackTimeline,
  lbInvalidateTracks,
  lbLoadTracksForItem,
  lbRenderSettingsPanel,
  lbRenderTrackTimeline,
  lbStopTrackingPlayback,
} from '../mediathek/bbox-overlay/index.js';

// ── Public surface ─────────────────────────────────────────────────────────
// Verbatim back-compat exports — every name the old bbox-overlay
// index exposed is forwarded here, so a caller can flip its import
// path from mediathek/bbox-overlay/index.js to mediaview/index.js at
// any point without touching the rest of the code.
export {
  _lbDrawDetections,
  lbClearTrackTimeline,
  lbInvalidateTracks,
  lbLoadTracksForItem,
  lbRenderSettingsPanel,
  lbRenderTrackTimeline,
  lbStopTrackingPlayback,
};

// ── openMediaView ──────────────────────────────────────────────────────────
// Public entry for the new shell. Config shape:
//   { mode:    'recorded' | 'live' | 'live-detect' | 'timelapse',
//     source:  { type: 'mp4'|'image'|'mjpeg', url, frameSize? },
//     item:    <existing mediathek item passthrough — unchanged shape>,
//     overlays:{ bboxes, trails, zones, masks, confirmer },
//     panels:  { detections, tracksList, settings, weather },
//     actions: { onConfirm, onDelete, onDownload, onPrev, onNext, onClose } }
//
// Skeleton behaviour: for `mode='recorded'` we delegate to the legacy
// Mediathek openLightbox flow so nothing visibly changes during the
// migration. Other modes throw — they'll be wired up in later tasks
// once cam-edit, dashboard, and timelapse callsites get migrated.
export function openMediaView(config){
  if (!config || typeof config !== 'object'){
    throw new Error('openMediaView: config object required');
  }
  const mode = config.mode;
  if (mode === 'recorded'){
    // Delegate to the legacy lightbox until task #3 wires the shell
    // composition in. The item field carries the same shape today.
    const open = typeof window !== 'undefined' && window.openLightbox;
    if (typeof open !== 'function'){
      throw new Error('openMediaView(recorded): legacy openLightbox not available yet');
    }
    return open(config.item);
  }
  throw new Error(`openMediaView: mode '${mode}' not yet migrated`);
}
