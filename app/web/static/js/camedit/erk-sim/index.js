// ─── camedit/erk-sim/index.js ──────────────────────────────────────────────
// Public API for the Erkennung simulation sheet. Wires the
// "Erkennung jetzt simulieren" button + the result-panel close
// + the decision-trace "leeren" button. Single-body sheet: the
// Video sub-tab and its tab strip got removed (commit fix).
//   index.js → snapshot.js → ../../core/* only
import { byId } from '../../core/dom.js';
import { _onErkSimulateClick } from './snapshot.js';


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
      const wrap = byId('erkSimResult');
      if (wrap) wrap.hidden = true;
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
