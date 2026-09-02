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

import { CAMERA, NETZ_STATE, MEDIA, CLIP_ITEM, WEATHER_SAMPLES, WEATHER_RANGE } from './_fixtures.mjs';

/** Put a fixture on window so the in-page mounts can read it. */
export async function seedFixtures(page) {
  await page.evaluate(
    (fx) => {
      window.__fx = fx;
    },
    { CAMERA, NETZ_STATE, MEDIA, CLIP_ITEM, WEATHER_SAMPLES, WEATHER_RANGE },
  );
}

/** The unified video player on a recorded clip. */
async function mountVPlayer(page) {
  await page.evaluate(async () => {
    const vp = await import('/static/js/vplayer/index.js');
    vp.openVideoPlayer({
      mode: 'recorded',
      source: { url: '/static/uishot-clip.webm' },
      item: window.__fx.CLIP_ITEM,
      actions: {
        onPrev() {},
        onNext() {},
        onConfirm() {},
        onDelete() {},
        onDownload() {},
        onClose() {},
      },
    });
  });
  // The timeline lays out against video.duration; without metadata every
  // lane collapses to zero width and the shot would flatter the layout.
  await page
    .waitForFunction(() => {
      const v = document.querySelector('.vp-root video');
      return v && v.readyState >= 1 && v.duration > 0;
    }, { timeout: 8000 })
    .catch(() => {});
  await page.waitForTimeout(600);
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
 * The surfaces, in the order the brief ranks them.
 *
 * `clip` is the element the PNG is cropped to; null means full page.
 * `scope` is what the DOM audits walk — narrower than the whole
 * document, so a defect in an unrelated section is not blamed here.
 */
export const SURFACES = [
  {
    id: 'vplayer-recorded',
    title: 'Unified video player · recorded clip',
    mount: mountVPlayer,
    clip: '.vp-root',
    scope: '.vp-root',
  },
  {
    id: 'weather-save-panel',
    title: 'Weather manual-event save panel',
    mount: mountWeatherSave,
    clip: '#weatherZoomSavePanel',
    scope: '#weatherZoomSavePanel',
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
];
