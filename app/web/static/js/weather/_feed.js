// ─── weather/_feed.js ───────────────────────────────────────────────────
// Card builders for the two compilation record types that render inline
// in the unified Wetter-Ereignisse grid alongside sightings: recaps
// (multi-clip period summaries) and Gewitter-episodes (the storm
// archive's own records). Neither is a single event_type, so both
// ignore the sighting filter chips and always show — matching the old
// recap strip's always-visible behaviour. Split out of sightings.js to
// keep that file's per-function line budget; this is a self-contained
// "how does a compilation record become a grid cell" concern.
import { esc, byId } from '../core/dom.js';
import {
  episodeTitle,
  fmtDayMonth,
  fmtTime,
  fmtDuration,
  classMeta,
  effectiveClass,
} from '../storms/_helpers.js';

export function recapCardHTML(m, idx) {
  const dur = parseInt(m.duration_s || 0, 10);
  const mm = Math.floor(dur / 60),
    ss = dur % 60;
  const durLbl = `${mm}:${ss.toString().padStart(2, '0')} min`;
  return `
      <div class="ws-recap-card" data-recap-idx="${idx}" data-id="${esc(m.id)}">
        <div class="ws-recap-card-period">${esc(m.period_label || m.id)}</div>
        <div class="ws-recap-card-meta">${m.n_clips || 0} Clips · ${esc(durLbl)}</div>
        <span class="ws-recap-card-play" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>
        </span>
      </div>`;
}

// A card into the Gewitter-Archiv's own detail view (storms/index.js's
// hash router), not the MediaView lightbox — an episode is a whole
// window with compare/footage/notes, not a single playable clip.
export function episodeCardHTML(ep) {
  const meta = classMeta(effectiveClass(ep));
  const fc = ep.footage_count;
  const metaLine = [
    fmtDayMonth(ep.started_at),
    fmtTime(ep.started_at),
    fmtDuration(ep.duration_min),
    Number.isFinite(Number(fc)) && Number(fc) > 0 ? `${fc} Aufnahmen` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  return `
      <div class="ws-recap-card" data-ep-id="${esc(ep.id)}">
        <div class="ws-recap-card-period">${esc(episodeTitle(ep))}</div>
        <div class="ws-recap-card-meta">${esc(metaLine)}</div>
        <span class="ws-recap-card-play" aria-hidden="true">${meta.icon}</span>
      </div>`;
}

// Jump into the Gewitter-Archiv's own detail state for this episode.
// The hash isn't an element id, so a plain <a href> would silently
// leave the viewport where it was — storms/index.js's hashchange
// listener still renders the detail, just off-screen, without this.
export function openStormEpisode(id) {
  if (!id) return;
  location.hash = `#/gewitter/${encodeURIComponent(id)}`;
  byId('storms')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Merge sightings (already filtered + carrying their absolute lightbox
// idx), recaps and episodes into one feed sorted newest-first. Each
// entry keeps its own kind so the grid renderer can pick the right card
// template and click handler.
export function unifiedFeedItems(filteredSightings, recaps, episodes) {
  const sightings = filteredSightings.map((s, i) => ({
    kind: 'sighting',
    ts: s.sun_event_at || s.started_at || '',
    idx: i,
    data: s,
  }));
  const recapEntries = (recaps || []).map((m, i) => ({
    kind: 'recap',
    ts: m.built_at || '',
    idx: i,
    data: m,
  }));
  const episodeEntries = (episodes || []).map((ep) => ({
    kind: 'episode',
    ts: ep.started_at || '',
    data: ep,
  }));
  return [...sightings, ...recapEntries, ...episodeEntries].sort((a, b) =>
    String(b.ts).localeCompare(String(a.ts)),
  );
}
