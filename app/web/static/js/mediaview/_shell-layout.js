// ─── mediaview/_shell-layout.js ─────────────────────────────────────────────
// The static per-mode/per-panel layout DATA shell.js's mountMediaView
// composes against: behaviour flags, the panel-tab metadata table, and
// the tab-list builder. Split out of shell.js (which crossed the
// 400-line file ceiling once the tier flag and Transport v2's
// controls-slot threading landed) — this is pure data/composition with
// no DOM side effects, the natural seam CLAUDE.md's package-layout
// convention calls for.
//
// `_SHELL_HTML` and `_relocateControls` stay in shell.js on purpose,
// even though `_SHELL_HTML` is equally pure data: four test files
// (`test_sim_chrome_layout.py`, `test_sim_stage_readouts.py`,
// `test_app_branding_surface.py`, `test_debug_tab_phone_layout.py`) pin
// the shell's `data-slot="…"` markup by reading shell.js's own source
// text at that file path — moving the template string would silently
// fail every one of them despite changing no real behaviour. Grepped
// for `_MODE_FLAGS`/`_TAB_META`/`_buildTabs` across every test file
// first; none of those three are referenced by source-text scan, so
// they are the safe part of this file to extract.

// Per-mode shell behaviour. interactiveMode → live segmented control vs
// read-only badge; contextKey → overlay-toggle persistence
// scope; retrigger / fineFold → whether those pieces mount by default.
export const _MODE_FLAGS = {
  recorded: {
    interactiveMode: false,
    contextKey: 'mediathek',
    retrigger: true,
    fineFold: true,
  },
  timelapse: {
    interactiveMode: false,
    contextKey: 'timelapse',
    retrigger: false,
    fineFold: false,
  },
  weather: {
    interactiveMode: false,
    contextKey: 'weather',
    retrigger: false,
    fineFold: true,
  },
  live: {
    interactiveMode: true,
    contextKey: 'live',
    retrigger: false,
    fineFold: true,
  },
  'live-detect': {
    interactiveMode: true,
    contextKey: 'live',
    retrigger: false,
    fineFold: true,
  },
};

// Panel-flag key → tab descriptor. F mounts placeholder bodies; G/H/I
// swap in the real panel renderers (weather.js / recording-settings.js
// / detections.js) without changing the tab wiring here.
export const _TAB_META = {
  detections: { id: 'detections', label: 'Detections' },
  tracksList: { id: 'tracks', label: 'Tracks' },
  settings: { id: 'settings', label: 'Aufnahme-Settings' },
  // Label-correction bubbles — same tap-to-toggle gesture the photo
  // lightbox has always had (panels/labels.js::_renderLbLabels), now
  // also reachable for a recorded VIDEO clip via this tab. Not offered
  // for timelapses (buildRecordedShellConfig gates it off): a
  // timelapse carries the synthetic "timelapse" pseudo-label, never a
  // real classifier verdict there is anything to correct.
  labels: { id: 'labels', label: 'Labels' },
  recordingSettings: { id: 'erkennung', label: 'Erkennung' },
  weather: { id: 'weather', label: 'Wetter' },
};

export function _buildTabs(panels, panelRenderers, item) {
  const out = [];
  for (const key of Object.keys(_TAB_META)) {
    if (!panels[key]) continue;
    const meta = _TAB_META[key];
    // A real renderer wired by the consumer (G: weather; H/I: recorded
    // / live panels) takes over; otherwise a placeholder marks the tab
    // as not-yet-migrated so the strip still composes.
    const custom = panelRenderers && typeof panelRenderers[key] === 'function';
    out.push({
      id: meta.id,
      label: meta.label,
      render: custom
        ? (host) => panelRenderers[key](host, item)
        : (host) => {
            host.innerHTML = `<div class="mv-tab-placeholder">${meta.label} · wird migriert</div>`;
          },
    });
  }
  return out;
}
