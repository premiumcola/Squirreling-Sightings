// Debounced PATCH helper — shared across clusters. Each unique
// (camId, fieldKey) gets its own 600 ms timer so rapid drags on the
// same slider coalesce into one save, but two different sliders
// don't collide.
export const _saveTimers = new Map();
const _SAVE_DEBOUNCE_MS = 600;
const _saveStatusEls = new Map();

export function _scheduleSave(camId, patchObj, statusEl) {
  const key = `${camId}:${Object.keys(patchObj).sort().join(',')}`;
  if (_saveTimers.has(key)) clearTimeout(_saveTimers.get(key));
  if (statusEl) {
    _saveStatusEls.set(key, statusEl);
    statusEl.dataset.saveState = 'pending';
    statusEl.textContent = 'speichert …';
  }
  const timerId = setTimeout(() => {
    _saveTimers.delete(key);
    _flushSave(camId, patchObj, statusEl, key);
  }, _SAVE_DEBOUNCE_MS);
  _saveTimers.set(key, timerId);
}

export function _flushSave(camId, patchObj, statusEl, key) {
  fetch(`/api/cameras/${encodeURIComponent(camId)}/detection-tuning`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patchObj),
  })
    .then((r) => {
      const el = statusEl || _saveStatusEls.get(key);
      if (!el) return r;
      if (r.ok) {
        el.dataset.saveState = 'ok';
        el.textContent = '✓ gespeichert';
        setTimeout(() => {
          if (el.dataset.saveState === 'ok') {
            el.textContent = '';
            el.dataset.saveState = 'idle';
          }
        }, 1000);
      } else {
        el.dataset.saveState = 'error';
        el.textContent = '⚠ Speichern fehlgeschlagen';
      }
      return r;
    })
    .catch(() => {
      const el = statusEl || _saveStatusEls.get(key);
      if (el) {
        el.dataset.saveState = 'error';
        el.textContent = '⚠ Speichern fehlgeschlagen';
      }
    });
}
