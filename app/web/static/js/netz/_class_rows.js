// ─── netz/_class_rows.js ───────────────────────────────────────────────────
// The per-class Meldeschwelle rows — one editable row per detection class.
//
// These used to be the SECOND radar on this page. That radar was removed
// (one page, one net — two charts with different geometries read as a
// bug), and the values were demoted to a plain text line. That went one
// step too far: it deleted the only control in the whole GUI that can
// move a class's alert threshold. `patchAxes` in _api.js was left without
// a single caller while `PATCH /api/netz/<cam>/axes` stayed live — the
// exact "setting the UI shows but nobody can reach" shape this project
// keeps finding elsewhere.
//
// So the values stay TEXT-shaped, as chosen, but each row carries a
// slider. The E scale is INVERTED on purpose (see _mapping.js): pulling
// right = higher E = LOWER threshold = more alerts. The row prints the
// resulting percentage live so the operator never has to think in E.
import { esc } from '../core/dom.js';
import { showToast } from '../core/toast.js';
import { patchAxes } from './_api.js';
import { E_MAX, E_MIN, clampE, pushFor } from './_mapping.js';

const _DE = {
  person: 'Person',
  cat: 'Katze',
  dog: 'Hund',
  bird: 'Vogel',
  squirrel: 'Eichhörnchen',
  fox: 'Fuchs',
  hedgehog: 'Igel',
  marten: 'Marder',
  deer: 'Reh',
  car: 'Auto',
};

function _pct(v) {
  return Number.isFinite(Number(v)) ? `${Math.round(Number(v) * 100)} %` : '—';
}

function _rowHtml(a) {
  const label = String(a.label || '');
  const de = _DE[label] || label;
  const e = clampE(Number(a.E));
  // push_enabled=false means the class never alerts at all — the slider
  // would be a lie there, so the row says so instead of showing a number.
  const off = a.push_enabled === false;
  const val = off ? 'aus' : _pct(a.push);
  const slider = off
    ? ''
    : `<input type="range" class="netz-cls-slider" min="${E_MIN}" max="${E_MAX}" step="1"
         value="${e}" data-cls="${esc(label)}"
         aria-label="Meldeschwelle ${esc(de)}" />`;
  return (
    `<div class="netz-cls-row${off ? ' is-off' : ''}" data-cls-row="${esc(label)}">` +
    `<span class="netz-cls-name">${esc(de)}</span>` +
    `<span class="netz-cls-val" data-cls-val="${esc(label)}">${esc(val)}</span>` +
    slider +
    `</div>`
  );
}

/** The whole block: heading + one row per class. */
export function classRowsHtml(st) {
  const axes = st.axes || [];
  if (!axes.length) return '';
  return (
    `<div class="netz-card-conf">` +
    `<b>Meldeschwelle je Klasse</b>` +
    `<span class="netz-cls-hint">Regler nach rechts = empfindlicher, meldet früher.</span>` +
    axes.map(_rowHtml).join('') +
    `</div>`
  );
}

// Live percentage while dragging — no network, no save. The value the
// row prints must be the value the server will compute, so it goes
// through the same pushFor() mirror the radar uses.
function _bindLivePreview(card) {
  card.querySelectorAll('.netz-cls-slider').forEach((sl) => {
    sl.addEventListener('input', () => {
      const label = sl.dataset.cls;
      const out = card.querySelector(`[data-cls-val="${CSS.escape(label)}"]`);
      if (out) out.textContent = _pct(pushFor(label, clampE(Number(sl.value))));
    });
  });
}

/**
 * Save on release. `change` (not `input`) so a drag is ONE request, and
 * the camera comes from the card's own dataset — with every camera's net
 * on screen at once, a module-level "current camera" is how a drag on one
 * camera writes to another.
 */
export function bindClassRows(card, onSaved) {
  _bindLivePreview(card);
  card.querySelectorAll('.netz-cls-slider').forEach((sl) => {
    sl.addEventListener('change', async () => {
      const camId = card.dataset.cam;
      const label = sl.dataset.cls;
      if (!camId || !label) return;
      const e = clampE(Number(sl.value));
      sl.disabled = true;
      const res = await patchAxes(camId, { [label]: e });
      sl.disabled = false;
      if (!res || res.error) {
        showToast('Konnte nicht gespeichert werden: ' + ((res && res.error) || '—'), 'error');
        return;
      }
      // The server clamps `person` on a security camera up to the safety
      // floor unless the blocking dialog was shown. Report the value that
      // ACTUALLY landed, never the one that was dragged.
      const written = (res.written || {})[label] || {};
      const landedE = Number.isFinite(Number(written.E)) ? Number(written.E) : e;
      const landedPush = Number.isFinite(Number(written.push))
        ? Number(written.push)
        : pushFor(label, landedE);
      sl.value = String(landedE);
      const out = card.querySelector(`[data-cls-val="${CSS.escape(label)}"]`);
      if (out) out.textContent = _pct(landedPush);
      const de = _DE[label] || label;
      if (written.clamped) {
        showToast(
          `${de}: auf ${_pct(landedPush)} begrenzt — unter dieser Schwelle ` +
            `würde die Kamera Personen übersehen.`,
          'warn',
          { lifetime: 7000 },
        );
      } else {
        showToast(`${de} meldet jetzt ab ${_pct(landedPush)}.`, 'success');
      }
      if (typeof onSaved === 'function') onSaved(camId);
    });
  });
}
