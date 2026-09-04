// ─── scripts/uishot/_surfaces.mjs ──────────────────────────────────────────
// What to photograph, and how to put it on screen.
//
// Every mount here drives the REAL module's public entry against a
// fixture — openVideoPlayer(), renderDashboard(), renderMediaGrid(),
// renderPanel(), and for the weather panel the button click that is its
// only mount path. Nothing writes markup of its own. If a surface
// changes shape, these shots change with it; that is the entire point.
//
// The page under them is the real index.html with every real Jinja
// partial (render_shell.py) and the real /static/app.css built from the
// real LOAD_ORDER, so containers, cascade order and media queries are
// the ones that ship.

import {
  CAMERA,
  NETZ_STATE,
  MEDIA,
  CLIP_ITEM,
  CLIP_ONLY_ITEM,
  WEATHER_SAMPLES,
  WEATHER_RANGE,
  WEATHER_HISTORY,
  WEATHER_HISTORY_SPARSE,
} from './_fixtures.mjs';

/** Put a fixture on window so the in-page mounts can read it. */
export async function seedFixtures(page) {
  await page.evaluate(
    (fx) => {
      window.__fx = fx;
    },
    {
      CAMERA,
      NETZ_STATE,
      MEDIA,
      CLIP_ITEM,
      CLIP_ONLY_ITEM,
      WEATHER_SAMPLES,
      WEATHER_RANGE,
      WEATHER_HISTORY,
    },
  );
}

/**
 * The unified video player on a recorded clip.
 *
 * `fxKey` picks WHICH clip, and with it which population the timeline
 * draws from — the two are photographed separately because they are
 * never mixed into one rail (vplayer/timeline/_basis.js).
 *
 * No DEFAULT for it, deliberately: run.mjs calls `mount(page, width)`,
 * so a second positional parameter here is handed the viewport width and
 * a default would be silently shadowed by it. Both surfaces name their
 * fixture through a wrapper that drops the width.
 */
async function mountVPlayer(page, fxKey) {
  await page.evaluate(async (key) => {
    const vp = await import('/static/js/vplayer/index.js');
    vp.openVideoPlayer({
      mode: 'recorded',
      source: { url: '/static/uishot-clip.webm' },
      item: window.__fx[key],
      actions: {
        onPrev() {},
        onNext() {},
        onConfirm() {},
        onDelete() {},
        onDownload() {},
        onClose() {},
      },
    });
  }, fxKey);
  // The timeline lays out against video.duration; without metadata every
  // lane collapses to zero width and the shot would flatter the layout.
  await page
    .waitForFunction(() => {
      const v = document.querySelector('.vp-root video');
      return v && v.readyState >= 1 && v.duration > 0;
    }, { timeout: 8000 })
    .catch(() => {});
  // Park the playhead where BOTH fixture tracks have samples. At t=0 no
  // track has started, so every box and trail is correctly empty — and a
  // shot of correctly-empty overlay layers cannot tell an overlay that
  // works from one that never paints, which is exactly the confusion
  // this surface was photographed in the first time.
  //
  // PLAYED there, not seeked. ffmpeg's screencast build writes no cues,
  // so a `currentTime =` assignment on the stand-in clip silently does
  // nothing — the first attempt at this shot photographed frame 0 with a
  // clock reading 0:00 and no boxes, which looks exactly like the defect
  // it was meant to prove fixed. Fast-forwarding is a real playback the
  // container can do.
  await page.evaluate(async () => {
    const v = document.querySelector('.vp-root video');
    if (!v || !(v.duration > 6)) return;
    v.playbackRate = 8;
    await v.play().catch(() => {});
    await new Promise((done) => {
      const tick = () => {
        if (v.currentTime >= 5.4 || v.ended) {
          v.pause();
          v.playbackRate = 1;
          done();
        } else setTimeout(tick, 50);
      };
      tick();
    });
    // The idle auto-hide arms itself the moment playback starts, and a
    // paused clip that has run is allowed to hide. One mouse move puts
    // the transport back, which is the state the operator looks at.
    document.querySelector('.vp-stage')?.dispatchEvent(new MouseEvent('mousemove'));
  });
  await page.waitForTimeout(600);
}

/**
 * The detection simulation, opened the way the dashboard button opens it.
 *
 * Through `_cvOpenSim` deliberately, not by calling openVideoPlayer
 * directly. The defect this surface exists to catch was ENTIRELY in that
 * function: it opens the new player and returns, so the legacy path that
 * seeds the poll session and starts it never runs, and the panel sits on
 * "Warte auf ersten Tick" for ever while the picture — an independent
 * MJPEG stream — plays on. A surface that mounted the player itself
 * would have photographed a perfectly healthy panel and proved nothing.
 *
 * There was no simulation surface here at all before, which is how the
 * whole thing shipped.
 */
async function mountVPlayerSim(page) {
  await page.evaluate(async () => {
    const dash = await import('/static/js/dashboard.js');
    const { state } = await import('/static/js/core/state.js');
    dash._cvOpenSim(state.cameras[0].id);
  });
  // Long enough for the first tick to land AND for the cadence to
  // schedule a second — one arriving frame could be a fluke of mount
  // order, two is a running loop.
  await page.waitForTimeout(2500);
}

/**
 * The species dossier — reference photos plus the clip gallery.
 *
 * The one surface in this app whose two reported defects could never be
 * checked: the reference photos standing at different widths, and the
 * clip preview showing the wrong shape until play is pressed. Both are
 * layout, both need a render, and neither could be looked at because
 * this panel was not in the harness.
 *
 * The fixture deliberately mixes a LANDSCAPE and a PORTRAIT reference
 * photo. Two landscape sources would sit at the same width whatever the
 * CSS did, and would prove nothing about the case the operator sent a
 * screenshot of.
 */
async function mountDossier(page) {
  await page.evaluate(async () => {
    const mod = await import('/static/js/sichtungen/_dossier-panel.js');
    await mod.loadBirdDossiers();
    mod.selectSpeciesDossierByName('Hausrotschwanz');
  });
  await page.waitForSelector('#speciesDossierPanel:not([hidden])', { timeout: 8000 });
  await page.waitForTimeout(700);
}

/** The weather manual-event save panel. */
async function mountWeatherSave(page) {
  await page.evaluate(async () => {
    const base = '/static/js';
    const zoom = await import(`${base}/weather/_zoom.js`);
    const stats = await import(`${base}/weather/stats.js`);
    stats._wsStatsState.data = { units: {}, samples: window.__fx.WEATHER_SAMPLES };
    zoom.setZoomRange(window.__fx.WEATHER_RANGE.start, window.__fx.WEATHER_RANGE.end);
    const actions = document.getElementById('weatherZoomActions');
    if (actions) actions.hidden = false;
    document.getElementById('weatherZoomSaveBtn')?.click();
  });
  await page.waitForSelector('#weatherZoomSavePanel:not([hidden])', { timeout: 8000 });
  await page.waitForTimeout(500);
}

/**
 * The Wetterdaten panel — range pills, the multi-line chart, the legend.
 *
 * Mounted through renderWeatherStats() rather than the chart renderer
 * alone, because the panel the operator photographed is all three: the
 * pills decide the window, and the auto-hide of flat fields inside
 * renderWeatherStats decides how many curves the chart even has.
 *
 * The block ships inside the Mediathek's Wetter tab, so its ancestors
 * carry display:none until that tab is opened. renderStatsChartInto
 * measures the wrapper and bails on a zero box, so the shot would be an
 * empty rectangle without this — same reason mountMediathek unhides
 * #mediaDrilldown.
 */
async function mountWeatherChart(page) {
  await page.evaluate(async () => {
    const base = '/static/js';
    for (let el = document.getElementById('weatherStatsBlock'); el; el = el.parentElement) {
      if (getComputedStyle(el).display === 'none') el.style.display = 'block';
      el.hidden = false;
    }
    const stats = await import(`${base}/weather/stats.js`);
    await stats.loadWeatherStats();
  });
  await page.waitForSelector('#weatherStatsChartWrap svg', { timeout: 8000 });
  await page.waitForTimeout(400);
}

/** The dashboard camera tile plus its Erkennungsnetz panel row. */
async function mountDashboard(page) {
  await page.evaluate(async () => {
    const base = '/static/js';
    const { state } = await import(`${base}/core/state.js`);
    state.cameras = [window.__fx.CAMERA];
    // Seed the netz store BEFORE the dashboard renders: renderPanel is a
    // no-op for a camera the store does not know, and renderDashboard
    // kicks initNetPanels() as its last statement.
    const nz = await import(`${base}/netz/_state.js`);
    nz.netzState.cameras = [{ id: window.__fx.CAMERA.id, name: window.__fx.CAMERA.name }];
    nz.netzState.states = { [window.__fx.CAMERA.id]: window.__fx.NETZ_STATE };
    const dash = await import(`${base}/dashboard.js`);
    dash.renderDashboard();
    const panel = await import(`${base}/netz/_panel.js`);
    panel.ensurePanelsMounted();
    panel.renderPanel(window.__fx.CAMERA.id);
  });
  await page.waitForSelector('#cameraCards .cv-card', { timeout: 8000 });
  await page.waitForTimeout(700);
}

/** The Mediathek grid. */
async function mountMediathek(page) {
  await page.evaluate(async () => {
    const base = '/static/js';
    const { state } = await import(`${base}/core/state.js`);
    state.media = window.__fx.MEDIA;
    state._allMedia = window.__fx.MEDIA;
    state.mediaPage = 1;
    state.mediaTotalPages = 1;
    state.mediaSelectMode = false;
    state.mediaSelected = new Set();
    // Ships display:none; without a layout box calcItemsPerPage() returns
    // a degenerate page size and the grid renders one column.
    const dd = document.getElementById('mediaDrilldown');
    if (dd) dd.style.display = '';
    const paging = await import(`${base}/mediathek/_paging.js`);
    paging.renderMediaGrid();
    paging.renderMediaPagination();
  });
  await page.waitForSelector('#mediaGrid .media-card', { timeout: 8000 });
  await page.waitForTimeout(500);
}

/**
 * The whole Statistik section: period pills, donut, top detections,
 * timeline, Erkennungswolke and the 24 h heatmap.
 *
 * Mounted through the panel's real entries — the Aktualisieren button
 * (its only non-observer path, `statistics.js`) plus the two renderers
 * the observer would otherwise call. `state.cameras` is seeded FIRST on
 * purpose: the panel hydrates on an IntersectionObserver that can beat
 * `/api/cameras` home, and letting that race decide would make the shot
 * non-deterministic. Seeded, the fixture still poses the interesting
 * half of it — one configured camera, one the timeline names and the
 * camera list does not.
 */
async function mountStatistik(page) {
  await page.evaluate(async () => {
    const base = '/static/js';
    const { state } = await import(`${base}/core/state.js`);
    state.cameras = [window.__fx.CAMERA];
    await import(`${base}/statistics.js`);
    const tl = await import(`${base}/timeline.js`);
    const dc = await import(`${base}/detection-cloud.js`);
    document.getElementById('statRefreshBtn')?.click();
    tl.renderTimeline();
    dc.initDetectionCloud();
  });
  await page.waitForSelector('#statContent .stat-period-pill', { timeout: 8000 });
  await page.waitForSelector('#statHeatmapBlock .stat-hm-row', { timeout: 8000 });
  await page.waitForTimeout(700);
}

/**
 * The surfaces, in the order the brief ranks them.
 *
 * `clip` is the element the PNG is cropped to; null means full page.
 * `scope` is what the DOM audits walk — narrower than the whole
 * document, so a defect in an unrelated section is not blamed here.
 */
export const SURFACES = [
  {
    id: 'vplayer-recorded',
    title: 'Unified video player · recorded clip (sidecar basis)',
    mount: (page) => mountVPlayer(page, 'CLIP_ITEM'),
    clip: '.vp-root',
    scope: '.vp-root',
  },
  {
    id: 'vplayer-clip-basis',
    title: 'Unified video player · lanes from the whole-clip aggregate',
    mount: (page) => mountVPlayer(page, 'CLIP_ONLY_ITEM'),
    clip: '.vp-root',
    scope: '.vp-root',
  },
  {
    id: 'vplayer-sim',
    title: 'Unified video player · detection simulation',
    mount: mountVPlayerSim,
    clip: '.vp-root',
    scope: '.vp-root',
  },
  {
    id: 'sichtungen-dossier',
    title: 'Sichtungen · Artendossier mit Referenzfotos und Clip-Galerie',
    mount: mountDossier,
    clip: '#speciesDossierPanel',
    scope: '#speciesDossierPanel',
  },
  {
    id: 'weather-save-panel',
    title: 'Weather manual-event save panel',
    mount: mountWeatherSave,
    clip: '#weatherZoomSavePanel',
    scope: '#weatherZoomSavePanel',
  },
  {
    id: 'weather-chart',
    title: 'Wetterdaten panel · range pills + verlauf chart',
    mount: mountWeatherChart,
    clip: '#weatherStatsBlock',
    scope: '#weatherStatsBlock',
  },
  {
    id: 'weather-chart-sparse',
    title: 'Wetterdaten panel · three hours of archive, wider steps dark',
    mount: mountWeatherChart,
    stubs: { '/api/weather/history': WEATHER_HISTORY_SPARSE },
    clip: '#weatherStatsBlock',
    scope: '#weatherStatsBlock',
  },
  {
    id: 'dashboard-tile',
    title: 'Dashboard camera tile + Erkennungsnetz row',
    mount: mountDashboard,
    clip: '#cameraCards',
    scope: '#cameraCards',
  },
  {
    id: 'mediathek-grid',
    title: 'Mediathek grid',
    mount: mountMediathek,
    clip: '#mediaDrilldown',
    scope: '#mediaGrid',
  },
  {
    id: 'statistik-page',
    title: 'Statistik · pills, donut, top detections, Erkennungswolke, heatmap',
    mount: mountStatistik,
    clip: '#statistik',
    scope: '#statistik',
  },
];
