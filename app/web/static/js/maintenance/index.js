// ─── maintenance/index.js ──────────────────────────────────────────────────
// Mediathek-Verwaltung — the one Aufbewahrungs-Formular.
//
// There is no field map in here, and that is the point. Every control in
// `#retentionForm` carries its own settings.json coordinates as
// `data-section` / `data-field`, stamped by the Jinja macro out of
// app/app/retention_catalog.py. Saving walks the form and builds the
// payload from what is actually in the DOM — CLAUDE.md's rule, and the
// reason adding a retention category needs no JS change at all.
//
// Hydration is server-side: the markup Flask sends already carries the
// resolved values. The two panels this replaces hydrated from two
// different endpoints and one of them was broken — `weather/maintenance.js`
// read `/api/bootstrap` → `data.app.weather`, and `bootstrap_state()` has
// never returned an `app` key, so every weather slider showed its Jinja
// literal forever and a saved 30 came back as 90 on the next reload.

import { byId } from '../core/dom.js';
import { apiPost } from '../core/api.js';
import { registerAction } from '../core/action-registry.js';
import { showToast } from '../core/toast.js';

const FORM_ID = 'retentionForm';

function _clamp(input) {
  const min = Number(input.min);
  const max = Number(input.max);
  let v = Math.round(Number(input.value));
  if (!Number.isFinite(v)) v = min;
  return Math.min(max, Math.max(min, v));
}

// "0" on a row that allows it is the OFF position — `nie löschen` —
// not a zero-day window. The backend short-circuits on it before it
// computes a cutoff; the label has to say so or the number reads as
// "delete everything tonight", which is the opposite.
function _paintRow(input) {
  const unit = byId(input.id + '_unit');
  if (!unit) return;
  const off = input.dataset.offAtZero === '1' && Number(input.value) === 0;
  unit.textContent = off ? '= nie löschen' : 'Tage';
  unit.classList.toggle('ret-unit--off', off);
}

function _syncFromRange(range) {
  const input = byId(range.dataset.rangeFor);
  if (!input) return;
  input.value = range.value;
  _paintRow(input);
}

function _syncFromNumber(input) {
  const range = byId(input.id + '_range');
  const value = _clamp(input);
  if (range) range.value = value;
  _paintRow(input);
}

// ── save ──────────────────────────────────────────────────────────────────
// One POST for every section the panel touches. `update_section`
// deep-merges server-side, so sending only these keys leaves every
// sibling setting alone.
function _collect(form) {
  const payload = {};
  form.querySelectorAll('[data-section][data-field]').forEach((el) => {
    const section = (payload[el.dataset.section] ||= {});
    section[el.dataset.field] = el.type === 'checkbox' ? el.checked : _clamp(el);
  });
  return payload;
}

function _initRetentionForm() {
  const form = byId(FORM_ID);
  if (!form) return;
  form.querySelectorAll('.ret-range').forEach((range) => {
    range.addEventListener('input', () => _syncFromRange(range));
  });
  form.querySelectorAll('.ret-num').forEach((input) => {
    input.addEventListener('input', () => _syncFromNumber(input));
    // Only clamp into range on blur — clamping mid-typing turns "30"
    // into "3" the moment the first digit lands below the minimum.
    input.addEventListener('change', () => {
      input.value = _clamp(input);
      _syncFromNumber(input);
    });
    _paintRow(input);
  });
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const status = byId(FORM_ID + '_status');
    try {
      await apiPost('/api/settings/app', _collect(form));
      if (status) status.textContent = 'Gespeichert';
      showToast('Aufbewahrungsfristen gespeichert.', 'success');
    } catch (err) {
      if (status) status.textContent = '';
      showToast('Speichern fehlgeschlagen: ' + (err.message || err), 'error');
    }
  });
}

// Entry point from the Wetter-Sektion, whose own retention sliders moved
// here. Opens the accordion if it is closed, then scrolls it into view.
registerAction('openRetentionPanel', () => {
  const section = byId('set-media-maint');
  if (!section) return false;
  if (!section.classList.contains('open') && typeof window.toggleSetSection === 'function') {
    window.toggleSetSection('set-media-maint');
  }
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return false;
});

document.addEventListener('DOMContentLoaded', _initRetentionForm);
