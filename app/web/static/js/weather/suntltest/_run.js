// ─── weather/suntltest/_run.js ─────────────────────────────────────────────
// Start / cancel / poll. Owns the poll timer and the delta merge into
// the per-slot event cache.
//
// Imports go one way — _run uses _form / _live / _result, none of them
// import back. That is why bindForm takes its start+cancel handlers as
// arguments instead of reaching for them.

import { byId } from '../../core/dom.js';
import { apiGet, apiPost } from '../../core/api.js';
import { showToast } from '../../core/toast.js';
import { setRunningUi } from './_form.js';
import { renderLive } from './_live.js';
import { renderResult } from './_result.js';
import { S, resetEventCache } from './_state.js';

export function stopSunTlTestPolling() {
  if (S.pollTimer) {
    clearInterval(S.pollTimer);
    S.pollTimer = null;
  }
}

export function startPolling() {
  stopSunTlTestPolling();
  pollOnce();
  // G3 · bumped 2 s → 1.5 s once the heatmap is live. With ?since=
  // delta polling the response stays small even on long sessions.
  S.pollTimer = setInterval(pollOnce, 1500);
}

// Merge new slot_events into the per-slot cache. The status payload's
// slot_events is ALWAYS the post-since delta, never the whole list, so
// we accumulate forward.
function _mergeSlotEvents(d) {
  if (!d || !Array.isArray(d.slot_events)) return;
  for (const e of d.slot_events) {
    if (!e || typeof e.slot !== 'number') continue;
    S.eventBySlot.set(e.slot, e);
    if (e.ts > S.lastEventTs) S.lastEventTs = e.ts;
  }
}

export async function pollOnce() {
  let d = null;
  try {
    // G3 · ship the timestamp of the last event we've seen so the
    // backend's ?since=<float> filter returns only NEW slot_events.
    // The whole-history fallback is the unset default while
    // S.lastEventTs is still 0 (fresh session).
    const url =
      S.lastEventTs > 0
        ? `/api/weather/sun-tl/test/status?since=${encodeURIComponent(S.lastEventTs)}`
        : `/api/weather/sun-tl/test/status`;
    d = await apiGet(url);
  } catch (_err) {
    return;
  }
  _mergeSlotEvents(d);
  renderLive(d);
  if (d && (d.finished || !d.running)) {
    stopSunTlTestPolling();
    setRunningUi(false);
    renderResult(d);
  }
}

export async function startTest() {
  // Synchronous reset BEFORE the network round-trip so the user never
  // sees the previous run's MP4 card or live tile while the new run is
  // starting. Polling repaints these from the live status response
  // within ~1.5 s.
  const wrap = byId('suntltestResult');
  if (wrap) {
    wrap.hidden = true;
    wrap.innerHTML = '';
  }
  const live = byId('suntltestLive');
  if (live) {
    live.hidden = true;
    live.innerHTML = '';
  }
  // G3 · clear the per-slot cache so the previous session's cells don't
  // bleed into this run; lastEventTs back to 0 so the first poll
  // re-fetches the whole event list.
  resetEventCache();

  const btn = byId('suntltestStart');
  if (!S.cam) {
    showToast('Keine Wetter-Kamera ausgewählt.', 'error');
    return;
  }
  if (btn) btn.disabled = true;
  try {
    const j = await apiPost('/api/weather/sun-tl/test', {
      cam_id: S.cam,
      phase: S.phase,
      duration_s: S.duration,
      target_duration_s: S.targetLength,
    });
    if (!j?.ok) {
      showToast('Start fehlgeschlagen: ' + (j?.error || 'Fehler'), 'error');
      if (btn) btn.disabled = false;
      return;
    }
    showToast('Test läuft …', 'success');
    setRunningUi(true);
    startPolling();
  } catch (e) {
    showToast('Netzwerkfehler beim Start: ' + (e?.message || e), 'error');
    if (btn) btn.disabled = false;
  }
}

export async function cancelTest() {
  const btn = byId('suntltestCancel');
  if (btn) btn.disabled = true;
  try {
    const j = await apiPost('/api/weather/sun-tl/test/cancel');
    if (!j?.ok) {
      showToast('Abbruch fehlgeschlagen: ' + (j?.error || 'Fehler'), 'error');
      if (btn) btn.disabled = false;
      return;
    }
    showToast('Abbruch wird gesendet …', 'info');
    // Don't stop polling — let the status endpoint confirm the run
    // actually stopped, then pollOnce swaps the UI back to the start
    // state and renders the cancelled card.
  } catch (e) {
    showToast('Netzwerkfehler beim Abbruch: ' + e, 'error');
    if (btn) btn.disabled = false;
  }
}
