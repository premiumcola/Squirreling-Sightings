// ─── weather/settings-suntltest.js ─────────────────────────────────────────
// Sun-Timelapse TEST subtab. Fires an ad-hoc capture against the
// user-selected weather camera using the same backend code path the real
// sunrise/sunset schedule runs through, and surfaces every signal needed
// to diagnose why twilight captures come out monochrome with duplicate-
// frame stretches:
//
//   • daynight-override result (Color set / failed / skipped)
//   • elapsed / target seconds with a progress bar
//   • frame counters (captured / expected / retries / invalid)
//   • per-reason rejection breakdown — the smoking-gun for the
//     duplicate-frame bug (long blocks of frames rejected by
//     grey_uniform / too_dark / no_detail get padded by ffmpeg)
//   • scrolling tail of [sun-tl-test] / [weather] / [capture-stats]
//     log lines straight from the in-memory ring buffer the backend
//     keeps alongside the session
//
// Polls /api/weather/sun-tl/test/status every 1.5 s while a session is
// active; auto-stops on completion. Switching to another tab also stops
// the poller (settings.js calls stopSunTlTestPolling).
//
// This file was 842 lines against a 400-line ceiling. It is now the
// composition root over ./suntltest/:
//
//   _consts.js  window/target allowlists + the capture-budget math
//   _state.js   the mutable selection + poll state, one object
//   _form.js    configurator, math readout, running-vs-idle buttons
//   _run.js     start / cancel / poll and the slot-event delta merge
//   _live.js    heatmap, counters, action row, pills, log tail
//   _result.js  cancelled / error / planned-vs-delivered diff card
//
// The module path is unchanged so settings.js and the backend's G5
// invariant comments still point at a file that exists.

import { byId } from '../core/dom.js';
import { apiGet } from '../core/api.js';
import {
  bindForm,
  refreshConfigurator,
  renderHeader,
  setRunningUi,
  weatherCams,
} from './suntltest/_form.js';
import { cancelTest, startPolling, startTest, stopSunTlTestPolling } from './suntltest/_run.js';
import { renderLive } from './suntltest/_live.js';
import { renderResult } from './suntltest/_result.js';
import { S } from './suntltest/_state.js';

export { stopSunTlTestPolling };

// Surface any prior session immediately on tab open so the user doesn't
// lose state when they switch tabs mid-run.
function _resumeAnyRunningSession() {
  apiGet('/api/weather/sun-tl/test/status')
    .then((d) => {
      if (!d || !d.cam_id) return;
      renderLive(d);
      // Tab-open re-render: if a test is still in flight when the user
      // navigates back, surface the abort button immediately so they
      // can stop it without waiting for the next poll tick.
      setRunningUi(d.running && !d.finished);
      if (d.running && !d.finished) startPolling();
      else renderResult(d);
    })
    .catch(() => {});
}

export function renderSunTlTestPanel() {
  const root = byId('sunTlTestPanel');
  if (!root) return;
  const cams = weatherCams();
  if (!cams.length) {
    root.innerHTML = `<div class="field-help">Keine Wetter-Kamera aktiv. Aktiviere eine Kamera unter "📷 Kameras".</div>`;
    return;
  }
  if (!cams.find((c) => c.id === S.cam)) S.cam = cams[0].id;
  root.innerHTML = renderHeader(cams);
  bindForm(root, { onStart: startTest, onCancel: cancelTest });
  // G1 · initial start-button enabled-state + math readout sync.
  refreshConfigurator();
  _resumeAnyRunningSession();
}
