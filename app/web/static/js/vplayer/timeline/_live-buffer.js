// ─── vplayer/timeline/_live-buffer.js ──────────────────────────────────────
// PURE. Ticks in, tracks out — the rolling strip's missing input.
//
// „wo ist der Durchlauf der Spur-/Objekt-KI-Informationen??"
//
// WHY THE STRIP WAS EMPTY. index.js handed the timeline `frame.tracks`,
// and `_data/_map.js::mapFrame` produces no `tracks` key at all — it
// returns detections, kept/tentative/discarded, diag, models and trace.
// So the argument was `undefined` on every tick, the rolling strip was
// rendered with an empty lane list, and both the live view and the
// simulation showed a blank band where the objects' history belongs.
// Nothing threw; the component simply had no input and drew what no
// input looks like.
//
// A LIVE TICK IS ONE INSTANT. The backend has no notion of the last
// sixty seconds — it answers "what is in THIS frame". The history is the
// client's to keep, and keeping it is all this file does.
//
// KEYED ON `track_num`, which only `verdict: 'pass'` detections carry
// (measured against the running instance: of 26 detections in one tick,
// exactly the one passing person had a number; every filtered, no_track
// and outside_zone row had none). That is the right population and not a
// convenience: a lane is an object with an identity over time, and a
// detection the tracker refused to adopt has none. The raw-detections
// fold below the strip is where those belong, and it already lists them.

/** The rolling window, in seconds. Matches `cfg.windowMs`'s default. */
const DEFAULT_WINDOW_S = 60;

/**
 * A track's colour is its NUMBER's colour, applied downstream.
 *
 * Deliberately left null here so `_lanes.js` falls back to
 * `liveTrackColor(trackNum)` — the same function the boxes on the
 * picture use for the same number. Stamping a colour here would be a
 * second source for one decision, and the two would drift.
 */
const _LANE_COLOUR = null;

/**
 * PURE: one mapped detection → one sample, or null.
 *
 * `source: 'detect'` because every row that reaches here was detected
 * this frame — the tracker's own carried-forward boxes are not sent to
 * the client as detections. `classifySample` then decides `weak` from
 * the score against the spawn threshold, which is the honest reading:
 * a low-scoring pass is a weak sample, not a predicted one.
 */
function _sampleOf(det, t) {
  const raw = det?.raw || det;
  if (!raw) return null;
  const num = raw.track_num;
  if (!Number.isFinite(num)) return null;
  return {
    num,
    label: raw.label || '',
    sample: { t, bbox: raw.bbox, score: raw.score, source: 'detect' },
  };
}

/**
 * A rolling buffer of live ticks, shaped like `tracks.json` on the way
 * out so `buildTimelineModel` needs no live-specific branch.
 *
 * @param {object} [opts]
 * @param {number} [opts.windowS]  how much history to keep
 * @returns {{push, tracks, clear, size}}
 */
export function makeLiveTrackBuffer(opts = {}) {
  const windowS = opts.windowS > 0 ? opts.windowS : DEFAULT_WINDOW_S;
  /** @type {Map<number, {label: string, samples: Array}>} */
  const byNum = new Map();

  /** Drop everything that fell out of the window, then empty tracks. */
  const trim = (nowS) => {
    const cutoff = nowS - windowS;
    for (const [num, tr] of byNum) {
      // The samples are appended in time order, so the survivors are a
      // suffix — find the first one still inside and slice once.
      let i = 0;
      while (i < tr.samples.length && tr.samples[i].t < cutoff) i += 1;
      if (i > 0) tr.samples = tr.samples.slice(i);
      if (!tr.samples.length) byNum.delete(num);
    }
  };

  return {
    /**
     * Fold one tick in.
     *
     * @param {object} frame  a mapped frame from _data/_map.js
     * @param {number} nowS   the tick's timestamp, seconds
     */
    push(frame, nowS) {
      const t = Number.isFinite(nowS) ? nowS : 0;
      for (const det of (frame && frame.detections) || []) {
        const s = _sampleOf(det, t);
        if (!s) continue;
        let tr = byNum.get(s.num);
        if (!tr) {
          tr = { label: s.label, samples: [] };
          byNum.set(s.num, tr);
        }
        // The label can sharpen mid-track — the wildlife stage names a
        // species several frames in. The latest naming wins, which is
        // the same rule the object list follows.
        if (s.label) tr.label = s.label;
        tr.samples.push(s.sample);
      }
      trim(t);
    },

    /** The buffer as tracks.json-shaped tracks, lowest number first. */
    tracks() {
      return [...byNum.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([num, tr]) => ({
          _num: num,
          label: tr.label,
          species: null,
          color: _LANE_COLOUR,
          samples: tr.samples,
        }));
    },

    /** Forget everything — a new session is not a continuation. */
    clear() {
      byNum.clear();
    },

    /** How many tracks are currently held. For tests and diagnostics. */
    size() {
      return byNum.size;
    },
  };
}
