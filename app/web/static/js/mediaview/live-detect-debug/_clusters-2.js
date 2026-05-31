import { esc } from '../../core/dom.js';
import { _scheduleSave } from './_save.js';
import { _renderSlider, _renderClusterHeader, _wireSlider, _forceSave, _valToPct, _formatValue } from './_clusters-1.js';
// Per-class default thresholds — keep aligned with the project's
// shipped tuning. Used by Cluster 2's "Defaults" button.
const _CLASS_DEFAULT_THRESH = {
  person: 0.5,
  cat: 0.5,
  bird: 0.5,
  car: 0.5,
  dog: 0.5,
  squirrel: 0.5,
};
const _ALL_FILTER_CANDIDATES = ['person', 'cat', 'bird', 'car', 'dog', 'squirrel', 'motion'];

// SIMU-05c · Cluster 2 · Recognition.
export function _renderCluster2(ctx, cam) {
  const filterArr = Array.isArray(cam.object_filter) ? cam.object_filter : [];
  const thresholds = cam.label_thresholds || {};
  const globalThresh = Number(cam.detection_min_score) || 0.55;
  const sortedClasses = filterArr
    .slice()
    .sort((a, b) => Object.keys(_CLASS_DEFAULT_THRESH).indexOf(a) - Object.keys(_CLASS_DEFAULT_THRESH).indexOf(b));
  const classSlidersHtml = sortedClasses
    .map((lbl) => {
      const v = Number(thresholds[lbl]);
      const val = Number.isFinite(v) && v > 0 ? v : globalThresh;
      return _renderSlider({
        field: `label_thresholds:${lbl}`,
        label: lbl,
        value: val,
        min: 0.0,
        max: 0.95,
        step: 0.01,
        desc: `Min. Confidence damit "${lbl}" als gültige Detection passt`,
        hint: '↓ Senken = mehr Detections (aber mehr False Positives)',
      });
    })
    .join('');
  const filterPillsHtml = _ALL_FILTER_CANDIDATES.map((lbl) => {
    const on = filterArr.includes(lbl);
    return `<button type="button" class="mv-ld-filter-pill" data-filter-pill="${esc(lbl)}" data-on="${on ? '1' : '0'}">${esc(lbl)}${on ? ' ✓' : ''}</button>`;
  }).join('');
  const profil = ctx.fullData?.diag?.validator_profile || '—';
  return `
    <div class="mv-ld-cluster mv-ld-cluster-warn" data-cluster-id="2">
      ${_renderClusterHeader(2, 'Cluster 2 · Objekt wird gar nicht erkannt',
        'Coral findet die Klasse nicht · oder Score landet unter der Schwelle',
        _cluster2HeaderHint(ctx, sortedClasses))}
      <div class="mv-ld-cluster-body">
        ${sortedClasses.length
          ? `<div class="mv-ld-subsection-head">PER-KLASSE SCHWELLEN</div>${classSlidersHtml}`
          : '<div class="mv-ld-empty-row">Kein object_filter aktiv — alle Klassen werden akzeptiert</div>'}
        <div class="mv-ld-subsection-head">PROFIL-OVERRIDE</div>
        <div class="mv-ld-profil-line">
          <span>Profil <span class="mv-ld-profil-val">${esc(profil)}</span> (aktiv)</span>
          <button type="button" class="mv-ld-link-btn" data-action="open-profil-editor">Profil-Editor öffnen</button>
        </div>
        <div class="mv-ld-subsection-desc">Tag/Twilight/Nacht haben separate Schwellen-Sets · aktuell aktiv: ${esc(profil)}.</div>
        <div class="mv-ld-subsection-head">OBJEKT-FILTER</div>
        <div class="mv-ld-subsection-desc">Welche Klassen ÜBERHAUPT durchgelassen werden — alles andere wird sofort verworfen</div>
        <div class="mv-ld-filter-pills">${filterPillsHtml}</div>
        ${_renderCluster2Evidence(ctx, cam)}
        <div class="mv-ld-cluster-actions">
          <button type="button" class="mv-ld-action-btn mv-ld-action-save" data-action="save-cluster2">Speichern (Cam)</button>
          <button type="button" class="mv-ld-action-btn" data-action="defaults-cluster2">Defaults</button>
          <span class="mv-ld-save-status" data-save-status data-save-state="idle"></span>
        </div>
      </div>
    </div>`;
}

export function _cluster2HeaderHint(ctx, filterClasses) {
  const ev = ctx.fullData?.cluster_evidence?.cluster2;
  if (!ev) return { tone: 'mute', text: '· Live-Daten in Vorbereitung' };
  const missing = Array.isArray(ev.missing_classes_60s) ? ev.missing_classes_60s : [];
  if (!missing.length && filterClasses.length) {
    return { tone: 'ok', text: '✓ Letzte 60 s: alle Klassen OK' };
  }
  if (missing.length) {
    return { tone: 'warn', text: `⚠ ${missing[0]} seit 60 s ohne Detection` };
  }
  return { tone: 'mute', text: '· kein Filter aktiv' };
}

export function _renderCluster2Evidence(ctx, cam) {
  const ev = ctx.fullData?.cluster_evidence?.cluster2;
  const filterArr = Array.isArray(cam.object_filter) ? cam.object_filter : [];
  if (!ev) {
    return `<div class="mv-ld-evidence mv-ld-evidence-ok" data-cluster-evidence="2">
      <div class="mv-ld-evidence-line">📊 Letzte 60 s an dieser Kamera:</div>
      <div class="mv-ld-evidence-mono">Auf erstes Tick warten …</div>
    </div>`;
  }
  const perClass = ev.per_class_60s_counts || {};
  const missing = Array.isArray(ev.missing_classes_60s) ? ev.missing_classes_60s : [];
  const allHave = filterArr.length > 0 && missing.length === 0;
  const parts = filterArr.map((lbl) => {
    const c = perClass[lbl] || { raw: 0, pass: 0, below: 0 };
    return `${lbl}: ${c.raw || 0} raw · ${c.pass || 0} pass · ${c.below || 0} u.S.`;
  });
  const diagnose = allHave
    ? 'Alle aktivierten Klassen liefern Detections — keine fehlt komplett'
    : missing.length
      ? `${missing.join(', ')} seit 60 s ohne Detection — Schwelle prüfen oder Klasse aus Filter entfernen`
      : '';
  return `<div class="mv-ld-evidence ${allHave ? 'mv-ld-evidence-ok' : 'mv-ld-evidence-warn'}" data-cluster-evidence="2">
    <div class="mv-ld-evidence-line">📊 Letzte 60 s an dieser Kamera:</div>
    <div class="mv-ld-evidence-mono">${esc(parts.join(' · '))}</div>
    ${diagnose ? `<div class="mv-ld-evidence-diagnose">${esc(diagnose)}</div>` : ''}
  </div>`;
}

export function _wireCluster2(host, cam, ctx) {
  const camId = (ctx.session || {}).camId || cam.id;
  host.querySelectorAll('.mv-ld-slider[data-field^="label_thresholds:"]').forEach((root) => {
    _wireSlider(root, camId);
  });
  host.querySelectorAll('[data-filter-pill]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const lbl = btn.dataset.filterPill;
      const isOn = btn.dataset.on === '1';
      const nextOn = !isOn;
      btn.dataset.on = nextOn ? '1' : '0';
      btn.textContent = nextOn ? `${lbl} ✓` : lbl;
      const allPills = Array.from(host.querySelectorAll('[data-filter-pill]'));
      const filter = allPills
        .filter((p) => p.dataset.on === '1')
        .map((p) => p.dataset.filterPill);
      const statusEl = btn.closest('.mv-ld-cluster')?.querySelector('[data-save-status]');
      _scheduleSave(camId, { object_filter: filter }, statusEl);
    });
  });
  host
    .querySelector('[data-action="save-cluster2"]')
    ?.addEventListener('click', () => _forceSave(camId, host));
  host
    .querySelector('[data-action="defaults-cluster2"]')
    ?.addEventListener('click', () => {
      const filterArr = Array.isArray(cam.object_filter) ? cam.object_filter : [];
      const lt = {};
      for (const lbl of filterArr) {
        lt[lbl] = _CLASS_DEFAULT_THRESH[lbl] || 0.5;
        const sliderRoot = host.querySelector(`.mv-ld-slider[data-field="label_thresholds:${lbl}"]`);
        if (sliderRoot) _setSliderValue(sliderRoot, lt[lbl]);
      }
      const statusEl = host.querySelector('[data-action="defaults-cluster2"]').closest('.mv-ld-cluster').querySelector('[data-save-status]');
      _scheduleSave(camId, { label_thresholds: lt }, statusEl);
    });
  host
    .querySelector('[data-action="open-profil-editor"]')
    ?.addEventListener('click', () => {
      const url = `/#cam-edit?cam=${encodeURIComponent(camId)}&tab=erkennung`;
      window.location.href = url;
    });
}

export function _setSliderValue(root, val) {
  const min = Number(root.dataset.min);
  const max = Number(root.dataset.max);
  const step = Number(root.dataset.step);
  const pct = _valToPct(val, min, max);
  root.dataset.value = String(val);
  const knob = root.querySelector('[data-slider-knob]');
  const fill = root.querySelector('[data-slider-fill]');
  const valEl = root.querySelector('[data-slider-value]');
  if (knob) knob.style.left = `${pct.toFixed(2)}%`;
  if (fill) fill.style.width = `${pct.toFixed(2)}%`;
  if (valEl) valEl.textContent = _formatValue(val, step);
}

