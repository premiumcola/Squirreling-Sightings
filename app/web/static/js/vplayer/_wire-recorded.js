// ─── vplayer/_wire-recorded.js ─────────────────────────────────────────────
// The recorded-clip half of the player's wiring: fetch the clip's data,
// hand it to the panel, and paint the rail + the boxes from it.
//
// Split out of index.js, which had grown past CLAUDE.md's 400-line
// ceiling. The seam is the natural one — index.js mounts and composes,
// while this owns one source of data end to end — and it is where the
// repaint hook belongs anyway, since everything a repaint needs (the
// widened item, the sidecar, the pre-roll numbers) is already local here.

import { timelineBasis } from './timeline/_basis.js';
import { loadRecorded } from './_data/recorded.js';

export /**
 * Load a recorded clip's data and paint the panel and the timeline
 * with it. Fire-and-forget: the shell is already up, so the picture
 * plays while the sidecar is still in flight.
 */
function wireRecorded(cfg, stage, panel, timeline, overlays, relanes) {
  if (cfg.flags.live) return;
  loadRecorded(cfg.item)
    .then((data) => {
      panel?.update(data);
      _paintRecordedTimeline(cfg, stage, timeline, overlays, data, relanes);
    })
    .catch(() => {
      /* the clip still plays; the panel simply stays empty */
    });
}

/**
 * Paint the rail (and the boxes) for a recorded clip — and leave a way
 * to paint them AGAIN.
 *
 * The repaint is the point. The lanes are built from the event's own
 * detection rows (`timeline/_basis.js`), and a label correction rewrites
 * exactly those rows — `event_relabel.py` neutralizes any detection that
 * carried a disproven class, the reply carries the rewritten lists back,
 * and `core/label-patch.js` lands them on the very item object this
 * function closed over. Everything was therefore already correct EXCEPT
 * that nothing ever drew it again: the basis was resolved once, at load.
 * So „wenn ich das Hund runter nehme dann ist die Spur immernoch so
 * beschriftet" — the rail kept the retracted class until the clip was
 * reopened. `relanes.run` is what the panel's save hook calls.
 */
function _paintRecordedTimeline(cfg, stage, timeline, overlays, data, relanes) {
  const p = data.provenance || {};
  const rs = cfg.item.recording_settings || {};
  const timing = p.timing || {};
  // The WIDENED item, not cfg.item: loadRecorded folds a `whole_clip`
  // recovered from /api/event/<id> into its copy, and a clip opened
  // from a narrow route would otherwise be told it has no aggregate
  // by the very object that just fetched one. It is also the object a
  // correction patches IN PLACE (panels/_recorded.js), which is what
  // makes the repaint below see the new rows without re-fetching.
  const item = data.item || cfg.item;
  // THE MEASUREMENT WINS OVER THE INTENTION, and the order used to be
  // the other way round — which is the whole of „wieso kein Vor- und
  // Nachlauf!???".
  //
  // `provenance.timing.pre_roll_s` is what the pre-roll was CONFIGURED
  // as (3 s on every camera here). `recording_settings.pre_motion_seconds`
  // is what the splice actually ACHIEVED — _finalize.py writes
  // `round(achieved_pre_s, 2)` into it after the ring has been spliced
  // onto the clip. Reading the configured number first meant the rail
  // drew a 3 s band onto clips that contain no pre-roll at all.
  //
  // The details fold keeps showing the configured value, correctly —
  // there it is labelled as the setting. Here the rail is a picture of
  // the clip, so it may only draw what the clip has.
  const preRoll = rs.pre_motion_seconds ?? timing.pre_roll_s;
  // ONE basis per render — the sidecar's tracks when it has any, else
  // lanes synthesised from the clip aggregate. Never both: see
  // timeline/_basis.js for why merging them would lie. The trigger frame
  // sits at the END of the pre-roll (that is what a pre-roll IS) and only
  // the third basis uses it, when sidecar and aggregate are both empty.
  let picked = timelineBasis(item, data.tracks, { triggerT: preRoll });
  const render = () => {
    // The boxes come from the same sidecar the lanes do, so a lane and
    // the box it explains are one subject in one colour. The sidecar's
    // own gate wins over the caller's threshold inside setTracks.
    overlays?.setTracks(data.tracks, { threshold: p.effective?.spawn_default, item });
    timeline?.render(picked.tracks, {
      duration: stage.video.duration,
      preRoll,
      // Same rule, same reason: the clip's own number first.
      postRoll: rs.post_motion_seconds ?? timing.post_roll_s,
      threshold: p.effective?.spawn_default ?? rs.conf_thresh_general,
      basis: picked.basis,
      item,
      tracks: data.tracks,
    });
  };
  render();
  // Duration arrives with the metadata, which on first open lands
  // after this render — without the second pass every lane would be
  // laid out against a duration of 0.
  stage.video.addEventListener('loadedmetadata', render);
  // Re-resolve the basis, not just re-draw it: a correction that empties
  // the label set neutralizes the rows the current basis was built from,
  // and the row count itself can change with it.
  if (relanes) {
    relanes.run = () => {
      picked = timelineBasis(item, data.tracks, { triggerT: preRoll });
      render();
    };
  }
}
