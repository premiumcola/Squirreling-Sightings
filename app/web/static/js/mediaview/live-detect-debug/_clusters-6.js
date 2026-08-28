// ─── mediaview/live-detect-debug/_clusters-6.js ────────────────────────────
// Cluster 6 · "Auslastung & Modelle".
//
// Not a fourth tab: the strip is deliberately three entries wide on a
// 375 px phone. And not merged into Cluster 4 either — Cluster 4 is the
// health of the SIM TICK (cadence, drops, frame age), Cluster 6 is the
// ACCELERATOR and the models on it. A slow tick and a saturated device
// look identical on screen and want opposite fixes, which is exactly why
// they get separate clusters instead of one "Performance" heap.
import { _renderClusterHeader } from './_clusters-1.js';
import { renderTelemetryBody, telemetryHeaderHint } from '../telemetry/index.js';

export function _renderCluster6() {
  return `
    <div class="mv-ld-cluster" data-cluster-id="6">
      ${_renderClusterHeader(
        6,
        'Cluster 6 · Auslastung & Modelle',
        'Analysezeit, Kopffreiheit, Gerät und Modell je Stufe · was 2×2 / 3×3 kosten würden',
        telemetryHeaderHint(),
      )}
      <div class="mv-ld-cluster-body">${renderTelemetryBody()}</div>
    </div>`;
}
