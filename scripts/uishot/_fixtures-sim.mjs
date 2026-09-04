// ─── scripts/uishot/_fixtures-sim.mjs ──────────────────────────────────────
// The simulation's whole world: one healthy tick, the ten ways the
// endpoint can refuse one, and the utilisation block the TPU chip reads.
//
// Its own file because the simulation is the only surface with a FAILURE
// half — every other fixture poses one state, this one poses twelve — and
// because _fixtures.mjs was already 757 lines before those failure bodies
// existed. CLAUDE.md's ceiling is 400.
//
// It imports NOTHING from _fixtures.mjs, deliberately. TPU_STATUS keys its
// per-camera block by the camera's id at module-eval time, so importing
// CAMERA back would evaluate this module while that binding is still in
// its temporal dead zone — a ReferenceError at import, not at use. The id
// is declared HERE and _fixtures.mjs reads it from here instead, so the
// dependency runs one way.

/** The camera every simulation fixture is about. CAMERA.id reads this. */
export const SIM_CAM_ID = 'reolink_rlc810a_garten_51';

/**
 * One tick of POST /api/cameras/<id>/test-detection — the simulation's
 * whole world.
 *
 * Shaped from routes/coral_test_detection.py's own response body, not
 * invented: `modes` is _sim_debug.modes_block (the ROI and device chips
 * read `roi_mode_active` and `inference.device` off it), `detections`
 * are the pre-gate rows with their verdicts, `decision_trace` feeds the
 * track-events list and `debug.tracks` the track rows.
 *
 * It exists because the harness could not exercise the simulation at
 * all: with no answer for this endpoint the poll loop only ever saw a
 * network error, so no shot and no probe could tell a loop that was
 * running from one that had never been started — which is exactly the
 * defect that shipped.
 */
// FIELD NAMES ARE THE BACKEND'S OWN, checked against the real builders,
// not against what the panel happens to read. The first pass of this
// fixture invented three of them and photographed a working panel as
// broken — the same trap `busy_ratio` sprang on TPU_STATUS below:
//
//   · a track row is keyed `id`, not `num` (routes/_sim_debug.py's tracks
//     block). panels/_helpers.js::trackRow reads `track.id`, so every row
//     rendered "—" for its number and the shot showed a panel that could
//     not identify a single subject.
//   · a detection's `model` is a cascade STAGE token — "detector" — and
//     the `models` table is keyed by the same tokens, so `coco` joined
//     against nothing and every row said "—" for the model too.
//   · `modes.inference` is describe_backend()'s four keys
//     (device/api/mode/reason), not {device, model}. `reason` is the ONLY
//     place a CPU fallback is visible, and a fixture without it cannot
//     pose the TPU-taken state at all.
//
// `diag` carries the real gate/threshold/parity blocks for the same
// reason: the Debug tab and the trace read them, and a two-key stand-in
// photographs an empty tab as if it were unimplemented.
export const SIM_TICK = {
  ok: true,
  snapshot: null,
  frame_size: { w: 640, h: 360 },
  frame_age_ms: 120,
  frame_interval_avg_ms: 350,
  decoder_backlog_suspected: false,
  revision: null,
  detections: [
    {
      label: 'person',
      score: 0.81,
      bbox: [210, 90, 120, 210],
      verdict: 'pass',
      reason: '',
      track_num: 1,
      model: 'detector',
    },
    {
      label: 'cat',
      score: 0.34,
      bbox: [420, 200, 90, 70],
      verdict: 'tentative',
      reason: '',
      track_num: 2,
      model: 'detector',
    },
    {
      label: 'bird',
      score: 0.29,
      bbox: [60, 250, 40, 35],
      verdict: 'masked',
      reason: '',
      track_num: null,
      model: 'detector',
    },
    // Two more, because a live tick with three well-spaced detections is
    // not what a garden camera reports. The squirrel is deliberately at
    // the TOP of the frame and small: its plate would be drawn above the
    // box, which is where the layer switches are — the case the plate's
    // flip rule exists for. „Eichhörnchen“ is also the longest German
    // class name there is, on the smallest box in the tick.
    {
      label: 'squirrel',
      score: 0.63,
      bbox: [484, 34, 76, 60],
      verdict: 'pass',
      reason: '',
      track_num: 3,
      model: 'detector',
    },
    {
      label: 'marten',
      score: 0.41,
      bbox: [150, 246, 112, 82],
      verdict: 'tentative',
      reason: '',
      track_num: 4,
      model: 'detector',
    },
  ],
  decision_trace: [
    { t: 'SPAWN', track: 1, label: 'person', score: 0.81 },
    { t: 'HOLD', track: 2, label: 'cat', score: 0.34 },
    { t: 'SPAWN', track: 3, label: 'squirrel', score: 0.63 },
    { t: 'HOLD', track: 4, label: 'marten', score: 0.41 },
  ],
  diag: {
    frame_src: 'main',
    stream_pref: 'main',
    det_mode: '2x2',
    sub_stream_available: true,
    frame_size: { w: 2560, h: 1440 },
    frame_age_ms: 120,
    capture_lag_ms: 180,
    coral_available: true,
    inference_ms: 11,
    mode_invokes: 5,
    gates: {
      raw: 5,
      pass: 2,
      tentative: 2,
      belowthresh: 1,
      no_track: 0,
      filtered: 0,
      masked: 1,
      outside_zone: 0,
    },
    top_raw: [
      { label: 'person', score: 0.81 },
      { label: 'squirrel', score: 0.63 },
      { label: 'marten', score: 0.41 },
    ],
    thresholds: { floor: 0.25, spawn: 0.5, global: 0.4, per_class: { bird: 0.45 } },
    object_filter: ['person', 'cat', 'bird', 'squirrel', 'marten'],
    excluded_classes: [],
    validator_profile: null,
    validator_reason: null,
    source_frame_size: { w: 2560, h: 1440 },
    snapshot_frame_size: { w: 640, h: 360 },
    bbox_space: 'snapshot',
  },
  cluster_evidence: null,
  modes: {
    inference: { device: 'tpu', api: 'pycoral', mode: 'coral', reason: 'ok' },
    role: 'garten',
    alarm_profile: 'standard',
    detection_trigger: 'motion',
    roi_mode: '2x2',
    roi_mode_active: '2x2',
  },
  models: {
    detector: {
      device: 'tpu',
      api: 'pycoral',
      mode: 'coral',
      reason: 'ok',
      file: 'coco_ssd_mobilenet_v2_edgetpu.tflite',
      sha256: 'ab12cd34',
    },
    tpu_active: true,
  },
  debug: {
    raw_floor: 0.05,
    track_floor: 0.25,
    spawn_floor: 0.5,
    raw_detections: [],
    raw_below_floor: 4,
    tracks: [
      {
        id: 1,
        track_id: 't_17',
        state: 'active',
        label: 'person',
        model: 'detector',
        age_s: 4.2,
        idle_s: 0,
        misses: 0,
        last_iou: 0.62,
        score: 0.81,
        best_score: 0.83,
        samples: 14,
        end_reason: null,
      },
      {
        id: 2,
        track_id: 't_18',
        state: 'coasting',
        label: 'cat',
        model: 'detector',
        age_s: 1.1,
        idle_s: 0.9,
        misses: 2,
        last_iou: null,
        score: 0.34,
        best_score: 0.41,
        samples: 3,
        end_reason: null,
      },
      {
        id: 3,
        track_id: 't_19',
        state: 'active',
        label: 'squirrel',
        model: 'detector',
        age_s: 2.6,
        idle_s: 0,
        misses: 0,
        last_iou: 0.55,
        score: 0.63,
        best_score: 0.66,
        samples: 9,
        end_reason: null,
      },
      {
        id: 4,
        track_id: 't_20',
        state: 'coasting',
        label: 'marten',
        model: 'detector',
        age_s: 0.8,
        idle_s: 0.4,
        misses: 1,
        last_iou: 0.31,
        score: 0.41,
        best_score: 0.44,
        samples: 2,
        end_reason: null,
      },
    ],
  },
};

/**
 * The endpoint's failure bodies, one per mode, verbatim from the code
 * that writes them.
 *
 * They exist so the harness can PHOTOGRAPH an outage. Until it could,
 * every message the poll loop produced went into the legacy modal's media
 * wrap — a node the unified player does not render — and no shot and no
 * test could tell "the panel explains the failure" from "the panel says
 * nothing at all", which is what shipped.
 *
 * Each carries `status` alongside the body, because the status is half
 * the classification: the two bare 503s and the 400 have no `code` field
 * of their own on an older container.
 *
 *   busy               routes/_sim_guard.py::busy_payload
 *   modeRefused        routes/_sim_guard.py::refusal_payload (2×2 on CPU)
 *   coralUnavailable   coral_test_detection.py — every detector tier failed
 *   noFrame/stale      _sim_frame.py::FramePick.failure
 *   runtimeInactive    coral_test_detection.py — no runtime thread
 *   inferenceFailed    coral_test_detection.py — _run_pass threw
 */
export const SIM_FAILURES = {
  busy: {
    status: 429,
    body: {
      ok: false,
      code: 'busy',
      error: 'Simulation läuft noch — die vorherige Analyse ist nicht abgeschlossen.',
    },
  },
  modeRefused: {
    status: 429,
    body: {
      ok: false,
      code: 'mode_too_expensive',
      error:
        '2×2 kostet auf dieser Hardware 5 Inferenzen pro Bild — geschätzt 2.7 s je Tick ' +
        '(~540 ms je Inferenz). Der Deckel liegt bei 2.0 s, weil ein Bild danach älter ist, ' +
        'als der Frische-Vertrag dieser Ansicht erlaubt. Die Kamera ist in Ordnung; der ' +
        'Modus ist zu teuer. Mit Coral-TPU oder auf dem Sub-Stream wird er tragbar.',
      mode: '2x2',
      estimated_ms: 2700,
      per_invoke_ms: 540,
      invokes: 5,
      ceiling_ms: 2000,
    },
  },
  coralUnavailable: {
    status: 503,
    body: { ok: false, code: 'coral_unavailable', error: 'Coral nicht verfügbar (motion-only?)' },
  },
  runtimeInactive: {
    status: 503,
    body: {
      ok: false,
      code: 'runtime_inactive',
      error: 'Kamera-Runtime nicht aktiv (deaktiviert?)',
    },
  },
  noFrame: {
    status: 503,
    body: {
      ok: false,
      code: 'no_frame',
      error: 'Kamera liefert noch keine Frames',
      frame_age_ms: 0,
      validator_reason: null,
      validator_profile: null,
    },
  },
  stale: {
    status: 503,
    body: {
      ok: false,
      code: 'stale',
      error: 'Stream-Puffer hinkt zurück — kein frischer Frame innerhalb 2.5 s',
      frame_age_ms: 9040,
      validator_reason: 'capture_lag=9.0s',
      validator_profile: 'twilight',
    },
  },
  inferenceFailed: {
    status: 500,
    body: {
      ok: false,
      code: 'inference_failed',
      error:
        'Inference fehlgeschlagen: Node number 4 (EdgeTpuDelegateForCustomOp) failed to invoke',
    },
  },
};

/**
 * A tick that SUCCEEDED on the wrong processor.
 *
 * The failure mode with no failure response: when another process owns
 * the Edge TPU the detector walks down to its CPU tier and the endpoint
 * answers an ordinary 200. Its only trace is `modes.inference.reason`,
 * and on screen that used to be a chip reading "CPU" with nothing to say
 * that the numbers beside it describe hardware the camera is not using.
 */
export const SIM_TICK_CPU_FALLBACK = {
  ...SIM_TICK,
  modes: {
    ...SIM_TICK.modes,
    inference: {
      device: 'cpu',
      api: 'tflite-cpu',
      mode: 'cpu',
      reason: 'cpu_fallback (coral: Failed to load delegate from libedgetpu.so.1)',
    },
  },
  models: {
    detector: {
      device: 'cpu',
      api: 'tflite-cpu',
      mode: 'cpu',
      reason: 'cpu_fallback',
      file: 'coco_ssd_mobilenet_v2_quant_postprocess.tflite',
      sha256: 'ab12cd34',
    },
    tpu_active: false,
  },
};

/**
 * The `tpu` block of GET /api/status, as detectors/_utilisation.py's
 * fleet_tpu_utilisation writes it. The simulation panel's TPU chip
 * reads it through tpuFor(status, camId) — from the STATUS payload, not
 * from the frame, which is why a panel handed a null status can never
 * fill that chip however well the poll loop is running.
 */
// Field names are detectors/_utilisation.py::_readouts's own — `busy`
// is the 0..1 fraction the chip prints, and it is NOT called
// `busy_ratio`, which is what this fixture said on the first pass. A
// stub that invents a field name renders a placeholder and proves the
// chip broken when it is fine.
export const TPU_STATUS = {
  window_s: 60,
  total: { count: 118, busy_s: 1.74, span_s: 4.1, mean_ms: 14.7, per_s: 28.8, busy: 0.424 },
  cameras: {
    [SIM_CAM_ID]: {
      count: 118,
      busy_s: 1.74,
      span_s: 4.1,
      mean_ms: 14.7,
      per_s: 28.8,
      busy: 0.424,
    },
  },
};
