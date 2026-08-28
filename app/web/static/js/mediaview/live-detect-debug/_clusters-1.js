import { esc } from '../../core/dom.js';
export const _CLUSTER_CHEVRON =
  '<svg class="mv-ld-cluster-chevron" viewBox="0 0 24 24" width="14" height="14" ' +
  'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" ' +
  'stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

// Module defaults, shown when a camera carries no override. These
// mirror tracker_core/_consts.py — MISS_GRACE_DEFAULT_SECONDS is 8.0,
// which the Erkennung tab's placeholder claimed was 6.0 until D7.
const _CLUSTER1_DEFAULTS = {
  track_iou_match_threshold: 0.2,
  track_miss_grace_seconds: 8.0,
  track_continue_min_score: 0.2,
};

// Cluster 1 render — three READ-ONLY read-outs (IoU / grace / floor)
// plus the evidence box. Editing lives on the Erkennung tab behind the
// Experte fold; see the note on _renderSlider.
export function _renderCluster1(ctx, cam) {
  const iou = _readField(cam, 'track_iou_match_threshold', _CLUSTER1_DEFAULTS.track_iou_match_threshold);
  const grace = _readField(cam, 'track_miss_grace_seconds', _CLUSTER1_DEFAULTS.track_miss_grace_seconds);
  const floor = _readField(cam, 'track_continue_min_score', _CLUSTER1_DEFAULTS.track_continue_min_score);
  return `
    <div class="mv-ld-cluster mv-ld-cluster-warn" data-cluster-id="1">
      ${_renderClusterHeader(1, 'Cluster 1 · Person/Objekt reißt ab beim Bewegen',
        'Track stirbt obwohl Subjekt noch im Bild ist · neue Person-ID nach Drehung',
        _cluster1HeaderHint(ctx))}
      <div class="mv-ld-cluster-body">
        ${_renderSlider({
          field: 'track_iou_match_threshold',
          label: 'IoU-Match-Schwelle',
          value: iou,
          min: 0.0,
          max: 0.95,
          step: 0.01,
          desc: 'Wie groß muss die Überlappung zur Vorgängerbox sein, damit es derselbe Track bleibt',
          hint: '↓ Senken (0.10) = toleranter bei Drehungen / Sprüngen',
        })}
        ${_renderSlider({
          field: 'track_miss_grace_seconds',
          label: 'Miss-Grace (Sek.)',
          value: grace,
          min: 1.0,
          max: 30.0,
          step: 0.5,
          desc: 'Wie lange ein Track ohne neue Detection überleben darf (z.B. Verdeckung)',
          hint: '↑ Erhöhen (15 s) = überlebt längere Verdeckung / Drehung',
        })}
        ${_renderSlider({
          field: 'track_continue_min_score',
          label: 'Floor-Score (Weiterführung)',
          value: floor,
          min: 0.0,
          max: 0.95,
          step: 0.01,
          desc: 'Minimale Confidence, damit existierender Track weiterläuft (≠ Spawn-Score!)',
          hint: '↓ Senken (0.10) = Track überlebt schwache Frames (Drehung, dunkle Pose)',
        })}
        ${_renderCluster1Evidence(ctx, cam)}
        <div class="mv-ld-cluster-note">Anzeige · geändert wird auf dem Erkennung-Tab
          unter „Experte · Track-Kontinuität".</div>
      </div>
    </div>`;
}

export function _renderClusterHeader(num, title, sub, hint) {
  // Q2-2 · the head is the collapse toggle (tap to expand the body).
  // role=button + aria-expanded for a11y; the leading chevron rotates
  // via the root's data-collapsed attribute.
  return `
    <div class="mv-ld-cluster-head" role="button" tabindex="0" aria-expanded="false">
      ${_CLUSTER_CHEVRON}
      <div class="mv-ld-cluster-head-text">
        <div class="mv-ld-cluster-head-title">${esc(title)}</div>
        <div class="mv-ld-cluster-head-sub">${esc(sub)}</div>
      </div>
      ${hint ? `<div class="mv-ld-cluster-head-hint" data-hint-tone="${hint.tone}">${esc(hint.text)}</div>` : ''}
    </div>`;
}

export function _cluster1HeaderHint(ctx) {
  // For SIMU-05b the evidence ring-buffer (SIMU-05h) isn't wired yet;
  // surface a calm placeholder so the cluster reads stable instead
  // of empty. SIMU-05h replaces this with a real count.
  const evidence = ctx.fullData?.cluster_evidence?.cluster1;
  if (!evidence) return { tone: 'mute', text: '· Live-Daten in Vorbereitung' };
  const n = Number(evidence.deaths_60s || 0);
  return n > 0
    ? { tone: 'warn', text: `⚠ Letzte 60 s: ${n} DEATH` }
    : { tone: 'ok', text: '· Letzte 60 s: 0 DEATH' };
}

export function _renderCluster1Evidence(ctx, cam) {
  const ev = ctx.fullData?.cluster_evidence?.cluster1;
  const clean = !ev || Number(ev.deaths_60s || 0) === 0;
  if (clean) {
    return `<div class="mv-ld-evidence mv-ld-evidence-ok" data-cluster-evidence="1">
      <div class="mv-ld-evidence-line">📊 Letzte 60 s an dieser Kamera:</div>
      <div class="mv-ld-evidence-mono">Aktuell stabil · keine Track-Abbrüche</div>
    </div>`;
  }
  const deaths = Number(ev.deaths_60s || 0);
  const spawns = Number(ev.spawns_60s || 0);
  const reids = Number(ev.reid_successes_60s || 0);
  const attempts = Array.isArray(ev.reid_attempts_60s) ? ev.reid_attempts_60s : [];
  // Diagnose: pick the worst failing IoU attempt and surface it.
  let diagnose = '';
  if (attempts.length) {
    const worst = attempts.reduce((a, b) => (Number(a.iou) < Number(b.iou) ? a : b));
    const iouCur = Number(cam.track_iou_match_threshold || 0.2).toFixed(2);
    diagnose = `Wahrscheinliche Ursache: IoU ${Number(worst.iou).toFixed(2)} unterschreitet Schwelle ${iouCur} beim Drehen`;
  }
  return `<div class="mv-ld-evidence mv-ld-evidence-warn" data-cluster-evidence="1">
    <div class="mv-ld-evidence-line">📊 Letzte 60 s an dieser Kamera:</div>
    <div class="mv-ld-evidence-mono">${deaths}× DEATH · ${spawns}× SPAWN · ${reids} erfolgreiche RE-ID</div>
    ${diagnose ? `<div class="mv-ld-evidence-diagnose">${esc(diagnose)}</div>` : ''}
  </div>`;
}

export function _readField(cam, key, defaultVal) {
  const v = Number(cam[key]);
  return Number.isFinite(v) && v > 0 ? v : defaultVal;
}

// D11 · READ-ONLY. Diagnosis needs to SEE these numbers; it does not
// need the right to write them. The Erkennung tab's Experte fold owns
// the edit (grace + IoU), the Netz owns everything confidence-shaped,
// and a third writing surface in a debug panel is how the same value
// ends up with three owners and no source of truth. The bar still shows
// where the value sits between its bounds — that is the diagnostic part.
export function _renderSlider(cfg) {
  const valDisplay = _formatValue(cfg.value, cfg.step);
  const pct = _valToPct(cfg.value, cfg.min, cfg.max);
  return `
    <div class="mv-ld-slider is-readonly" data-field="${esc(cfg.field)}" data-min="${cfg.min}" data-max="${cfg.max}" data-step="${cfg.step}" data-value="${cfg.value}">
      <div class="mv-ld-slider-top">
        <span class="mv-ld-slider-label">${esc(cfg.label)}</span>
        <span class="mv-ld-slider-value" data-slider-value>${esc(valDisplay)}</span>
      </div>
      <div class="mv-ld-slider-track">
        <div class="mv-ld-slider-fill" data-slider-fill style="width:${pct.toFixed(2)}%"></div>
        <div class="mv-ld-slider-knob" data-slider-knob style="left:${pct.toFixed(2)}%"></div>
      </div>
      <div class="mv-ld-slider-bounds">
        <span>${esc(_formatValue(cfg.min, cfg.step))}</span>
        <span>${esc(_formatValue(cfg.max, cfg.step))}</span>
      </div>
      <div class="mv-ld-slider-desc">${esc(cfg.desc)}</div>
      <div class="mv-ld-slider-hint">${esc(cfg.hint)}</div>
    </div>`;
}

export function _formatValue(v, step) {
  return step >= 0.5 ? `${Number(v).toFixed(1)}` : `${Number(v).toFixed(2)}`;
}

export function _valToPct(v, min, max) {
  const range = Math.max(0.0001, max - min);
  return Math.min(100, Math.max(0, ((Number(v) - min) / range) * 100));
}

// D11 · Cluster 1 is a READ-OUT now. The sliders render their value and
// its position between the bounds; nothing here binds a pointer to them
// and nothing writes. The Save / Defaults / Empfohlene buttons went with
// the write path — a "Defaults" button that silently disagrees with the
// module defaults is how track_continue_min_score ended up with three
// different notions of its own default.
export function _wireCluster1() {}
