// ─── mediaview/shell.js ────────────────────────────────────────────────────
// Config-driven composition of the MediaView chrome — now a COMPLETE
// player. mountMediaView builds the shell host node and assembles the
// shared pieces in the unified layout (top → bottom): title bar; video
// stage (media frame + overlay layers, tiling grid, overlay-toggle pills
// top-left, Stream+mode cluster top-right); inline status-legend band;
// playbar + per-class swimlane; colour-coded panel tabs + fine-analysis
// fold — entirely from the openMediaView config (mode + overlays{} +
// panels{}). Weather already rides this shell; recorded (E) + live (F)
// route through it next, so D makes every region present + composable
// with placeholder data.
//
// Each mode flips a small flag set (_MODE_FLAGS) the composition reads;
// every piece is guarded so any mode × overlay × panel flag combination
// composes without error and returns a single teardown handle.

import { byId } from '../core/dom.js';
import { renderTitleBar } from './title-bar.js';
import { renderModeIndicator, renderTilingGrid } from './mode-indicator.js';
import { renderStatusLegend } from './status-legend.js';
import { renderOverlayToggles } from './overlay-toggles.js';
import { renderRetriggerButton } from './retrigger-button.js';
import { renderPanelTabs } from './panel-tabs.js';
import { renderFineAnalysisFold } from './fine-analysis-fold.js';
import { lbRenderTrackTimeline, lbClearTrackTimeline } from '../mediathek/bbox-overlay/index.js';
import { renderLiveSwimlane } from './live-swimlane.js';
import { observeLiveChromeBudget } from './live-chrome-budget.js';

// Per-mode shell behaviour. interactiveMode → live segmented control vs
// read-only badge; contextKey → overlay-toggle persistence
// scope; retrigger / fineFold → whether those pieces mount by default.
const _MODE_FLAGS = {
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
const _TAB_META = {
  detections: { id: 'detections', label: 'Detections' },
  tracksList: { id: 'tracks', label: 'Tracks' },
  settings: { id: 'settings', label: 'Aufnahme-Settings' },
  recordingSettings: { id: 'erkennung', label: 'Erkennung' },
  weather: { id: 'weather', label: 'Wetter' },
};

function _buildTabs(panels, panelRenderers, item) {
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

// Unified player layout, top → bottom (matches the live sim-player):
//   titlebar
//   stage    — frame + media + overlay layers, tiling grid, overlay-
//              toggle pills pinned top-left, read-only readout pinned
//              top-right, Stream+mode cluster (with a reserved
//              Stream-selector slot) pinned top-right for read-only modes.
//   controls — below the stage; empty (and collapsed) unless a mode moves
//              chrome down here. See _relocateControls. Interactive modes
//              also host the legend's "?" chip here (see legendHost).
//   legendband — inline status legend + re-trigger pill, directly below
//                the stage (collapses via :empty).
//   playbar  — recorded/timelapse scrubber + per-class swimlane, or the
//              live swimlane (collapses via :empty for weather).
//   panels   — colour-coded tabs + fine-analysis fold.
const _SHELL_HTML =
  `<div class="mv-shell-titlebar" data-slot="titlebar"></div>` +
  `<div class="mv-shell-stage" data-slot="stage">` +
  `<div class="mv-shell-frame" data-slot="frame"></div>` +
  `<svg class="mv-shell-grid" data-slot="grid" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" hidden></svg>` +
  `<div class="mv-shell-toggles" data-slot="toggles"></div>` +
  `<div class="mv-shell-readout" data-slot="readout"></div>` +
  `<div class="mv-shell-topright" data-slot="topright">` +
  `<div class="mv-shell-streamslot" data-slot="stream"></div>` +
  `<div class="mv-shell-modeind" data-slot="modeind"></div></div></div>` +
  `<div class="mv-shell-controls" data-slot="controls"></div>` +
  `<div class="mv-shell-legendband" data-slot="legendband"></div>` +
  `<div class="mv-shell-playbar" data-slot="playbar"></div>` +
  `<div class="mv-shell-panels" data-slot="panels">` +
  `<div class="mv-shell-tabs" data-slot="tabs"></div>` +
  `<div class="mv-shell-fafold" data-slot="fafold"></div></div>`;

// M · the interactive Stream + detection-mode cluster does NOT stay pinned
// over the picture. Pinned top-left (overlay toggles) and pinned top-right
// (Stream + four mode segments) are two absolutely-positioned boxes in the
// same corner strip with no shared width budget: on a 390 px iPhone stage
// the right cluster is ~360 px wide on its own, so it slid underneath the
// left one and got its leading chips clipped by the stage's overflow.
// They are also different KINDS of control — the toggles change what you
// see on the current frame, Stream/Modus change what the NEXT tick
// computes. Moving the settings cluster into its own row directly below
// the stage makes the collision structurally impossible (siblings in
// normal flow, not two absolute boxes) and gives it real 44 px targets.
// Read-only modes keep their single "angewandt: 2×2" badge over the frame.
function _relocateControls(root, interactive) {
  if (!interactive) return;
  const controls = root.querySelector('[data-slot="controls"]');
  const cluster = root.querySelector('[data-slot="topright"]');
  if (controls && cluster) controls.appendChild(cluster);
}

// I3 · Motion-ROI scan-box caption. The tiling-grid svg is
// preserveAspectRatio="none" (text inside would distort), so the label is a
// plain HTML span pinned over the stage at the box's top-left. Created on
// demand and removed whenever the ROI box isn't drawn.
function _setRoiLabel(stage, on) {
  if (!stage) return;
  const existing = stage.querySelector('.mv-grid-roi-label');
  if (on) {
    if (!existing) {
      const lbl = document.createElement('span');
      lbl.className = 'mv-grid-roi-label';
      lbl.textContent = 'Motion-ROI';
      stage.appendChild(lbl);
    }
  } else if (existing) {
    existing.remove();
  }
}

/**
 * Build the MediaView shell from a config and (optionally) mount it.
 *
 * @param {Object} config  openMediaView config — { mode, overlays{},
 *   panels{}, item, actions{}, appliedTiling?, detMode?, classes?,
 *   mount? }.
 * @returns {{ root: HTMLElement, components: Object, teardown(): void }}
 */
export function mountMediaView(config = {}) {
  const mode = config.mode || 'recorded';
  const flags = _MODE_FLAGS[mode] || _MODE_FLAGS.recorded;
  const overlays = config.overlays || {};
  const panels = config.panels || {};
  const actions = config.actions || {};
  const teardowns = [];
  const components = {};

  const root = document.createElement('div');
  root.className = 'mv-shell';
  root.dataset.mode = mode;
  root.innerHTML = _SHELL_HTML;
  _relocateControls(root, flags.interactiveMode);
  const slot = (name) => root.querySelector(`[data-slot="${name}"]`);

  const tb = renderTitleBar(slot('titlebar'), config);
  if (tb) {
    components.titleBar = tb;
    teardowns.push(tb.teardown);
  }

  const gridSvg = slot('grid');
  // ``hidden`` is an HTMLElement IDL property — it does NOT reflect to
  // the attribute on an SVGElement, so toggle the attribute directly.
  const gridVisible = () => gridSvg && !gridSvg.hasAttribute('hidden');
  const setGridVisible = (show, id) => {
    if (!gridSvg) return;
    // I3 · the ROI scan-box caption rides with the box (HTML span over the
    // stage — the grid svg can't hold undistorted text).
    _setRoiLabel(gridSvg.parentNode, show && id === 'roi');
    if (show) {
      renderTilingGrid(gridSvg, id);
      gridSvg.removeAttribute('hidden');
    } else {
      gridSvg.setAttribute('hidden', '');
    }
  };

  // Mode indicator — interactive for live; read-only "angewandt: X"
  // badge for recorded/weather when an applied tiling is known.
  if (flags.interactiveMode || config.appliedTiling) {
    const mi = renderModeIndicator(slot('modeind'), {
      interactive: flags.interactiveMode,
      value: config.detMode || config.appliedTiling || 'off',
      onChange: (id) => {
        // Interactive (live): selecting a tiling draws the matching split
        // over the frame; "Aus" clears it — so the operator sees how the
        // frame is subdivided for scanning. Read-only badges fire
        // onToggleGrid instead, so this branch only runs for live.
        if (flags.interactiveMode) {
          setGridVisible(id !== 'off', id);
        } else if (gridVisible()) {
          renderTilingGrid(gridSvg, id);
        }
        if (typeof actions.onModeChange === 'function') actions.onModeChange(id);
      },
      onToggleGrid: (show, id) => setGridVisible(show, id),
    });
    if (mi) {
      components.modeIndicator = mi;
      // Programmatic mode change (the backend refusing an unaffordable
      // tiling, say). setValue alone would resync the segments and leave
      // the tiling grid painted for a mode that is no longer selected —
      // one owner for both halves.
      components.setDetMode = (id) => {
        mi.setValue(id);
        setGridVisible(id !== 'off', id);
      };
      teardowns.push(mi.teardown);
    }
  }

  // Overlay-toggle pills pinned top-left INSIDE the stage. The available
  // layers are the keys present in config.overlays (weather passes none,
  // so the pinned slot stays empty + collapses).
  const available = Object.keys(overlays);
  if (available.length) {
    const ot = renderOverlayToggles(slot('toggles'), {
      available,
      contextKey: flags.contextKey,
      onChange: actions.onOverlayChange,
    });
    if (ot) {
      components.overlayToggles = ot;
      teardowns.push(ot.teardown);
    }
  }

  // Inline status legend (float:false — no longer a floating frame
  // overlay). Read-only modes get their own band directly below the
  // stage; the "Neu erkennen" pill shares it (pinned right via 30g) and
  // the band collapses via :empty when a mode mounts neither.
  //
  // M2 · interactive (live) modes put the legend in the CONTROL row
  // instead. On a phone the legend is a single 44 px "?" chip, so its own
  // band was a full-width row carrying one round button and nothing else
  // — about 48 px of a 667 px screen spent on whitespace. The control row
  // below the stage is already ≥ 44 px tall (the mode segments set that
  // floor), so the chip rides at its right end for free. Still below the
  // picture, which is the property test_sim_chrome_layout guards.
  const legendBand = flags.interactiveMode ? slot('controls') : slot('legendband');
  if (overlays.bboxes) {
    // I4 · status legend = the LINE-TYPE legend (Bestätigt / Schwach / Ghost /
    // Maskiert · "Farbe = Person-Nr."). Colour now encodes the track number,
    // so the class-colour legend is gone.
    //
    // EVERY mode mounts it inline in the band below the stage — live no
    // longer floats it over the picture. The float variant auto-positioned
    // itself "opposite the OSD timestamp band", but that band's position is
    // a property of the CAMERA's burnt-in overlay, which no part of this
    // app can see: the mode flag said 'top', the operator's Reolink burns
    // it at the bottom, and the legend landed straight on top of it. There
    // is no placement over the frame that is safe against an overlay we
    // cannot locate — below the frame is.
    const sl = renderStatusLegend(legendBand, { float: false });
    if (sl) {
      components.statusLegend = sl;
      teardowns.push(sl.teardown);
    }
  }
  if (flags.retrigger || typeof actions.onRetrigger === 'function') {
    // Always the band, never the control row: "Neu erkennen" is a wide
    // labelled pill, and the control row it would join is the one row
    // that already has to fit Stream + four mode segments at 375 px.
    const rt = renderRetriggerButton(slot('legendband'), { onClick: actions.onRetrigger });
    if (rt) {
      components.retrigger = rt;
      teardowns.push(rt.teardown);
    }
  }

  // Playbar + per-class swimlane, between the legend band and the panel
  // tabs. recorded/timelapse reuse the recorded scrubber + swimlane
  // (timeline-panel, host-parameterised onto the shell slot); live modes
  // reuse the live swimlane. Weather has no timeline → slot collapses.
  // Placeholder/empty data is fine this batch (no consumer feeds real
  // tracks through the shell yet — E/F wire the data path).
  const playbar = slot('playbar');
  if (playbar) {
    if (mode === 'recorded' || mode === 'timelapse') {
      lbRenderTrackTimeline(config.item || null, { host: playbar });
      teardowns.push(() => {
        try {
          lbClearTrackTimeline(playbar);
        } catch {
          /* ignore */
        }
      });
    } else if (flags.interactiveMode) {
      renderLiveSwimlane(playbar, { detBuffer: [], windowMs: 60_000, objectFilter: null });
      teardowns.push(() => {
        playbar.innerHTML = '';
      });
    }
  }

  const tabs = _buildTabs(panels, config.panelRenderers, config.item);
  if (tabs.length) {
    const pt = renderPanelTabs(slot('tabs'), tabs, {
      mode,
      initialId: config.initialTab || tabs[0].id,
    });
    if (pt) components.panelTabs = pt;
  }

  // config.showFineFold overrides the mode default — recaps pass false
  // (a compilation has no per-event trace), sightings keep the fold.
  const wantFold =
    config.showFineFold !== undefined
      ? !!config.showFineFold
      : flags.fineFold || !!panels.fineAnalysis;
  if (wantFold) {
    // renderFineAnalysisFold(host, lines, opts) — live modes pass the
    // ``live`` flag so the fold reads "Warte auf ersten Tick …" and
    // gets the live accent; recorded/weather start with no lines.
    const ff = renderFineAnalysisFold(slot('fafold'), [], { live: flags.interactiveMode });
    if (ff) components.fineFold = ff;
  }

  if (config.mount) {
    const host = typeof config.mount === 'string' ? byId(config.mount) : config.mount;
    if (host) host.appendChild(root);
  }

  // The live layout sizes its stage against the height the chrome rows
  // leave over, and the playbar in that sum is content-sized (44 px per
  // swimlane lane). Publish the measured total instead of subtracting a
  // constant that goes stale the next time a row gains a line.
  if (flags.interactiveMode) teardowns.push(observeLiveChromeBudget(root));

  return {
    root,
    components,
    teardown: () => {
      for (const fn of teardowns) {
        try {
          fn();
        } catch {
          /* ignore */
        }
      }
      root.remove();
    },
  };
}
