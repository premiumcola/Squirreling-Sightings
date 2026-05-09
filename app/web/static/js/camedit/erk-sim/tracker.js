// ─── camedit/erk-sim/tracker.js ────────────────────────────────────────────
// Pure client-side IoU tracker used by live-detection mode (live.js).
// Each tick takes the latest detections and returns the confirmed
// tracks (hit_count ≥ 2), letting the renderer paint stable bboxes
// + path trails across frames without flicker.
//
// No network calls, no DOM access. Pure data structure + math so the
// behaviour is unit-testable in isolation if/when we add tests for it.

const _MIN_IOU       = 0.3;     // greedy-match threshold per same-label pair
const _PROMOTE_HITS  = 2;       // confirmed once we've seen the same subject twice
const _MAX_MISSES    = 5;       // ≈ 5 s at 1 Hz before we drop a stale track
const _MAX_AGE_MS    = 15_000;  // hard ceiling — even a flickering match dies after 15 s
const _PATH_CAP      = 60;      // bound per-track memory; renderer slices the tail

export class IoUTracker {
  constructor(){
    this._tracks = new Map();   // id -> track entry
    this._nextId = 1;
    this._lastDropped = [];     // tracks dropped on the most recent tick(); read once via lastDropped()
  }

  // dets : Array<{ label:string, bbox:[x,y,w,h], score:number, verdict:string }>
  // returns confirmed tracks (hit_count ≥ _PROMOTE_HITS), in insertion order
  tick(dets, now_ms){
    this._lastDropped = [];
    // 1. Build per-label candidate pairs (same label only — a "person"
    //    detection should never inherit a "bird" track even if their
    //    bboxes happen to overlap).
    const pairs = [];
    for (const det of dets){
      for (const track of this._tracks.values()){
        if (track.label !== det.label) continue;
        const iou = _iou(track.bbox, det.bbox);
        if (iou < _MIN_IOU) continue;
        pairs.push({ det, track, iou });
      }
    }
    pairs.sort((a, b) => b.iou - a.iou);

    // 2. Greedy descending-IoU matching. A pair where either side
    //    is already taken gets skipped — the higher-IoU pair wins.
    const matchedDets = new Set();
    const matchedTracks = new Set();
    for (const pair of pairs){
      if (matchedDets.has(pair.det) || matchedTracks.has(pair.track)) continue;
      matchedDets.add(pair.det);
      matchedTracks.add(pair.track);
      _updateTrack(pair.track, pair.det, now_ms);
    }

    // 3. Open provisional tracks for unmatched detections. They start
    //    at hit_count=1 — one more matched tick promotes them.
    for (const det of dets){
      if (matchedDets.has(det)) continue;
      const id = this._nextId++;
      const cx = det.bbox[0] + det.bbox[2] / 2;
      const cy = det.bbox[1] + det.bbox[3] / 2;
      this._tracks.set(id, {
        id,
        label: det.label,
        bbox: det.bbox.slice(),
        last_verdict: det.verdict,
        last_score: det.score,
        last_seen_ms: now_ms,
        hit_count: 1,
        miss_count: 0,
        path: [{ t: now_ms, cx, cy }],
      });
    }

    // 4. Increment miss_count for unmatched tracks; drop the stale
    //    ones. Iterate over a frozen snapshot so the .delete() calls
    //    don't disturb a live iterator.
    for (const [id, track] of Array.from(this._tracks.entries())){
      if (!matchedTracks.has(track)){
        track.miss_count += 1;
      }
      const stale = track.miss_count >= _MAX_MISSES
        || (now_ms - track.last_seen_ms) > _MAX_AGE_MS;
      if (stale){
        this._tracks.delete(id);
        // Capture the dropped track for the next caller of
        // lastDropped() — the timeline uses this to render a "× lost"
        // marker at the row's trailing edge.
        if (track.hit_count >= _PROMOTE_HITS){
          this._lastDropped.push(track);
        }
      }
    }

    // 5. Confirmed tracks only (hit_count ≥ promote threshold).
    return Array.from(this._tracks.values()).filter(t => t.hit_count >= _PROMOTE_HITS);
  }

  // Tracks dropped on the most recent tick(). Returns confirmed
  // tracks only — a provisional one-hit-then-gone subject doesn't
  // emit a lost marker because it was never visualised in the first
  // place. Snapshot-style copy: the renderer can mutate the array.
  lastDropped(){
    return this._lastDropped.slice();
  }
}

function _updateTrack(track, det, now_ms){
  track.bbox = det.bbox.slice();
  track.last_seen_ms = now_ms;
  track.last_verdict = det.verdict;
  track.last_score = det.score;
  track.hit_count += 1;
  track.miss_count = 0;
  const cx = det.bbox[0] + det.bbox[2] / 2;
  const cy = det.bbox[1] + det.bbox[3] / 2;
  track.path.push({ t: now_ms, cx, cy });
  if (track.path.length > _PATH_CAP){
    track.path.splice(0, track.path.length - _PATH_CAP);
  }
}

// IoU of two [x,y,w,h] bboxes. Returns 0 for non-overlapping or
// degenerate (zero-area) inputs — IoUTracker.tick filters those
// out via the _MIN_IOU threshold.
function _iou(a, b){
  const ax2 = a[0] + a[2], ay2 = a[1] + a[3];
  const bx2 = b[0] + b[2], by2 = b[1] + b[3];
  const ix1 = Math.max(a[0], b[0]);
  const iy1 = Math.max(a[1], b[1]);
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  const iw = Math.max(0, ix2 - ix1);
  const ih = Math.max(0, iy2 - iy1);
  const inter = iw * ih;
  const aArea = a[2] * a[3];
  const bArea = b[2] * b[3];
  const union = aArea + bArea - inter;
  return union > 0 ? inter / union : 0;
}
