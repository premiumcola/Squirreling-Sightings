// ─── camedit/erk-sim/index.js ──────────────────────────────────────────────
// Public API for the Erkennung simulation sheet. Wires the
// "Erkennung jetzt simulieren" button → live-detection toggle
// (live.js), the result-panel × button (also stops live), and the
// decision-trace "leeren" button. Single-body sheet — Video sub-tab
// got removed.
//   index.js → live.js → tracker.js + snapshot.js → ../../core/* only
import { byId } from '../../core/dom.js';
import { _onErkSimulateClick, stopLive } from './live.js';


export function bindErkSimulate(){
  const btn = byId('erkSimulateBtn');
  const close = byId('erkSimClose');
  if (btn && !btn.dataset.wired){
    btn.dataset.wired = '1';
    btn.addEventListener('click', _onErkSimulateClick);
  }
  if (close && !close.dataset.wired){
    close.dataset.wired = '1';
    close.addEventListener('click', () => {
      // Synchronous stop so the button label flips back the moment
      // the panel dismisses — the self-policing tick would catch it
      // up to 1 s later, which feels laggy.
      stopLive();
      const wrap = byId('erkSimResult');
      if (wrap){
        wrap.hidden = true;
        delete wrap.dataset.everShown;
      }
    });
  }
  // "leeren" button on the decision-trace log block — clears the
  // text but keeps the block visible so the next simulate writes
  // into an empty pre. Click outside the log doesn't reset it;
  // closing the whole sheet (× button) re-hides everything.
  const logClear = byId('erkSimLogClear');
  if (logClear && !logClear.dataset.wired){
    logClear.dataset.wired = '1';
    logClear.addEventListener('click', () => {
      const body = byId('erkSimLogBody');
      if (body) body.textContent = '';
    });
  }
}
