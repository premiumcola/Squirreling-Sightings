// ─── camedit/erk-sim/snapshot.js ───────────────────────────────────────────
// Render-only helper for the Erkennung simulation sheet. Paints a
// single inference response into the result panel: snapshot image,
// SVG bounding boxes, frame-age caption, detection list, decision-
// trace log. Called per-tick by live.js; the polling lifecycle and
// the IoU tracker live there.
import { byId, esc } from '../../core/dom.js';
import { renderTrace } from './trace.js';

const _ERK_VERDICT_TXT = {
  'pass':         'würde Alarm auslösen',
  'belowthresh':  '',
  'filtered':     '',
};

export function _renderErkSimResult(data){
  const wrap = byId('erkSimResult');
  if (!wrap) return;
  const img  = byId('erkSimImg');
  const ovl  = byId('erkSimOverlay');
  const list = byId('erkSimList');
  const ttl  = byId('erkSimTitle');
  if (img) img.src = data.snapshot || '';
  // Frame-age caption — backend reports the age of the cached frame
  // it ran inference against. Stays muted for fresh frames; flips to
  // a warning class when the captured frame was > 2 s old (the
  // user-visible bug was 2-min-stale snapshots showing yesterday's
  // datetime overlay). The element starts ``hidden`` and is shown
  // only when the backend includes the field, so older responses
  // are forward-compatible.
  const ageEl = byId('erkSimFrameAge');
  if (ageEl){
    const ageMs = parseInt(data.frame_age_ms, 10);
    if (Number.isFinite(ageMs)){
      const ageS = ageMs / 1000;
      const stale = ageMs > 2000;
      ageEl.textContent = stale
        ? `Snapshot · vor ${ageS.toFixed(1)} s aufgenommen — Stream hängt evtl.`
        : `Snapshot · vor ${ageS.toFixed(1)} s aufgenommen`;
      ageEl.classList.toggle('is-stale', stale);
      ageEl.hidden = false;
    } else {
      ageEl.textContent = '';
      ageEl.hidden = true;
    }
  }
  // viewBox in absolute frame pixel coordinates so backend bbox values
  // (which are pixel-space) drop in unchanged. preserveAspectRatio in
  // the inline element default is xMidYMid meet — but since the wrapper
  // .erk-test-result-imgwrap forces a 16:9 aspect ratio and the <img>
  // uses object-fit:contain, the SVG and the image scale identically.
  const fs = data.frame_size || { w: 1920, h: 1080 };
  if (ovl) ovl.setAttribute('viewBox', `0 0 ${Math.max(1, fs.w)} ${Math.max(1, fs.h)}`);

  const dets = data.detections || [];
  const passCount = dets.filter(d => d.verdict === 'pass').length;
  if (ttl){
    ttl.textContent = passCount > 0
      ? `${passCount} Treffer würden Alarm auslösen`
      : (dets.length === 0 ? 'Keine Erkennung' : 'Kein Treffer würde Alarm auslösen');
  }
  // Boxes — paint-order=stroke on the label so the dark halo stays
  // readable above bright snapshot regions. font-size scales with the
  // viewBox; an absolute "10 px" on a 1920-wide viewBox shows up as
  // ~10 px in screen pixels regardless of how the wrapper scales.
  if (ovl){
    ovl.innerHTML = dets.map(d => {
      const cls = `erk-det-box is-${d.verdict}`;
      const labelText = `${d.label} ${Math.round(d.score * 100)}%`;
      const fontSize = Math.max(10, Math.round(fs.w / 100));
      const boxR = Math.max(2, Math.round(fs.w / 480));
      return `
        <rect class="${cls}" x="${d.bbox[0]}" y="${d.bbox[1]}" width="${d.bbox[2]}" height="${d.bbox[3]}" rx="${boxR}" vector-effect="non-scaling-stroke" />
        <text class="erk-det-label" x="${d.bbox[0] + 4}" y="${d.bbox[1] + fontSize + 2}" font-size="${fontSize}">${esc(labelText)}</text>
      `;
    }).join('');
  }
  if (list){
    if (dets.length === 0){
      list.innerHTML = `<div class="erk-det-empty">Coral hat in diesem Frame nichts erkannt.</div>`;
    } else {
      list.innerHTML = dets.map(d => {
        const verdictText = d.reason || _ERK_VERDICT_TXT[d.verdict] || '';
        return `
          <div class="erk-det-row is-${esc(d.verdict)}">
            <span class="det-dot"></span>
            <span class="det-name">${esc(d.label)}</span>
            <span class="det-score">${Math.round(d.score * 100)}%</span>
            <span class="det-verdict">${esc(verdictText)}</span>
          </div>`;
      }).join('');
    }
  }
  // Decision-trace block — collapsible terminal log + active-config
  // chips + size-floor hint. trace.js owns all of that; we just hand
  // it the response payload + the camera id for localStorage scoping.
  const camId = byId('cameraForm')?.elements?.['id']?.value || '';
  renderTrace(data, camId);
  // First-render-only scroll-keep: only the very first tick of a
  // live run runs this. live.js sets wrap.dataset.everShown after
  // the first successful _renderErkSimResult; subsequent ticks see
  // the flag already set and skip the scroll, so the user can scroll
  // through the trace without being yanked back every second.
  const firstShow = wrap.hidden || wrap.dataset.everShown !== '1';
  wrap.hidden = false;
  if (firstShow){
    const btn = byId('erkSimulateBtn');
    if (btn){
      const rect = btn.getBoundingClientRect();
      const vh = window.innerHeight || document.documentElement.clientHeight;
      const inView = rect.top >= 0 && rect.bottom <= vh;
      if (!inView){
        const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        btn.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
      }
    }
  }
}
