// ─── library/_tests/dispatch.test.js ────────────────────────────────────
// Dispatch correctness: one fixture per `/api/library` kind, shaped like
// the REAL item + `extra` each reader in `library/_motion_reader.py` /
// `library/_weather_readers.py` actually produces (not an invented
// shape) — asserts `libraryCardHTML` calls through to the right existing
// builder by checking for markup only THAT builder emits, and that an
// unrecognised kind renders a safe fallback instead of throwing.
import './_setup.js';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { libraryCardHTML } from '../index.js';
// Only for the byte-identical "footage-less fallback renders exactly
// like before this feature existed" test below — these are the exact
// same pure helpers episodeCardHTML's own fallback body calls, so the
// expected string is built from the real source of truth, not a
// hand-guessed shape.
import { esc } from '../../core/dom.js';
import { episodeSparklineSvg } from '../../weather/_episode-sparkline.js';
import {
  episodeTitle,
  fmtDayMonth,
  fmtTime,
  fmtDuration,
  classMeta,
  characterMeta,
  effectiveClass,
} from '../../storms/_helpers.js';

const MOTION_ITEM = {
  kind: 'motion',
  id: 'motion:e1',
  cam_id: 'cam1',
  cam_name: 'Cam 1',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:01:00',
  video_url: '/media/motion_detection/cam1/2026-08-30/e1.mp4',
  thumb_url: '/media/motion_detection/cam1/2026-08-30/e1.jpg',
  missing_media: false,
  // The whole raw event JSON — see motion_reader.py::motion_candidate.
  extra: {
    event_id: 'e1',
    camera_id: 'cam1',
    time: '2026-08-30T12:00:00',
    labels: ['fox'],
    snapshot_relpath: 'motion_detection/cam1/2026-08-30/e1.jpg',
    video_relpath: 'motion_detection/cam1/2026-08-30/e1.mp4',
    duration_s: 12,
  },
};

const SIGHTING_ITEM = {
  kind: 'sighting',
  id: 'sighting:sight_1',
  cam_id: 'cam1',
  cam_name: 'Cam 1',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:00:30',
  video_url: '/api/weather/sightings/sight_1/clip',
  thumb_url: '/api/weather/sightings/sight_1/thumb',
  missing_media: false,
  // Real weather_candidates() shape (weather_episodes/_footage_sources.py).
  extra: { sighting_id: 'sight_1', event_type: 'thunder', api_snapshot: null, sun_snapshot: null },
};

const RECAP_ITEM = {
  kind: 'recap',
  id: 'recap:recap_1',
  cam_id: '',
  cam_name: '',
  start: '2026-06-01T00:00:00',
  end: '2026-06-30T23:59:59',
  video_url: '/api/weather/recaps/recap_1/clip',
  thumb_url: '',
  missing_media: false,
  extra: { recap_id: 'recap_1', period_label: 'Q2 2026', n_clips: 5, duration_s: 90 },
};

const MANUAL_ITEM = {
  kind: 'manual',
  id: 'manual:m1',
  cam_id: '',
  cam_name: '',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:30:00',
  video_url: '',
  thumb_url: '',
  missing_media: true,
  extra: {
    manual_event_id: 'm1',
    name: 'Regenguss',
    categories: ['heavy_rain'],
    characteristic: null,
  },
};

const EPISODE_ITEM = {
  kind: 'episode',
  id: 'episode:ep_1',
  cam_id: '',
  cam_name: '',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:30:00',
  video_url: '',
  thumb_url: '',
  missing_media: true,
  // The whole stripped-samples episode record (_store.py::_strip_samples).
  extra: {
    id: 'ep_1',
    started_at: '2026-08-30T12:00:00',
    ended_at: '2026-08-30T12:30:00',
    duration_min: 30,
    user_class: 'thunder',
    character: 'single_spike',
    curve_preview: { field: 'cape', values: [1, 2, 3, 4] },
  },
};

// Same shape as EPISODE_ITEM's `extra` (the whole stripped-samples
// record, _store.py::_strip_samples), plus `footage_count` +
// `footage_hero` — exactly what `_store._fold` stamps onto the record
// once `append_footage_count` has been called with a hero (see
// weather_episodes/_footage.py::_hero_item for the hero's own shape:
// kind/kind_label/cam_name/time_label/thumb_url/video_url, nothing
// more).
const EPISODE_ITEM_WITH_FOOTAGE = {
  kind: 'episode',
  id: 'episode:ep_2',
  cam_id: '',
  cam_name: '',
  start: '2026-08-30T12:00:00',
  end: '2026-08-30T12:30:00',
  video_url: '',
  thumb_url: '',
  missing_media: true,
  extra: {
    id: 'ep_2',
    started_at: '2026-08-30T12:00:00',
    ended_at: '2026-08-30T12:30:00',
    duration_min: 30,
    user_class: 'thunder',
    character: 'single_spike',
    curve_preview: { field: 'cape', values: [1, 2, 3, 4] },
    footage_count: 3,
    footage_hero: {
      kind: 'thunder',
      kind_label: 'Gewitter',
      cam_name: 'Hof',
      time_label: '14:12',
      thumb_url: '/api/weather/sightings/x/thumb',
      video_url: '/api/weather/sightings/x/clip',
    },
  },
};

const TIMELAPSE_ITEM = {
  kind: 'timelapse',
  id: 'timelapse:cam1:2026-08-30',
  cam_id: 'cam1',
  cam_name: 'Cam 1',
  start: '2026-08-29T00:00:00',
  end: '2026-08-30T00:00:00',
  video_url: '/media/timelapse/cam1/2026-08-30.mp4',
  thumb_url: '/media/timelapse/cam1/2026-08-30.jpg',
  missing_media: false,
  extra: { profile: 'daily' },
};

test('motion kind dispatches to mediaCardHTML', () => {
  const html = libraryCardHTML(MOTION_ITEM, {});
  assert.match(html, /class="media-card /);
  assert.match(html, /data-event-id="e1"/);
});

test('sighting kind dispatches to sightingCardHTML', () => {
  const html = libraryCardHTML(SIGHTING_ITEM, {});
  assert.match(html, /class="ws-card/);
  assert.match(html, /data-id="sight_1"/);
});

test('recap kind dispatches to recapCardHTML', () => {
  const html = libraryCardHTML(RECAP_ITEM, {});
  assert.match(html, /data-recap-idx="0"/);
  assert.match(html, /data-id="recap_1"/);
});

test('manual kind dispatches to manualEventCardHTML', () => {
  const html = libraryCardHTML(MANUAL_ITEM, {});
  assert.match(html, /class="ws-recap-card ws-manual-card"/);
  assert.match(html, /data-manual-id="m1"/);
});

test('episode kind dispatches to episodeCardHTML', () => {
  const html = libraryCardHTML(EPISODE_ITEM, {});
  assert.match(html, /data-ep-id="ep_1"/);
  // The character badge is episodeCardHTML's own distinguishing feature
  // (Stage 5) — proves the full extra record, not a trimmed copy, made
  // it through the adapter.
  assert.match(html, /ws-ep-character/);
});

test('an episode with NO footage_hero renders BYTE-IDENTICAL to the pre-footage-card fallback', () => {
  // The real regression this guards: episodeCardHTML's curve-only body
  // must not drift one character just because a sibling branch (the
  // footage-primary shell) was added above it. Built from the SAME
  // exported helpers episodeCardHTML itself calls — not a hand-guessed
  // shape — so a real template change fails this test too, not just a
  // "does it crash" smoke check.
  const ep = { ...EPISODE_ITEM.extra };
  const meta = classMeta(effectiveClass(ep));
  const charMeta = ep.character ? characterMeta(ep.character) : null;
  const characterHTML = charMeta
    ? `<div class="ws-ep-character" title="${esc(charMeta.de)}">` +
      `<span class="ws-ep-character-icon" aria-hidden="true">${charMeta.icon}</span>` +
      `<span class="ws-ep-character-label">${esc(charMeta.de)}</span></div>`
    : '';
  const fc = ep.footage_count;
  const metaLine = [
    fmtDayMonth(ep.started_at),
    fmtTime(ep.started_at),
    fmtDuration(ep.duration_min),
    Number.isFinite(Number(fc)) && Number(fc) > 0 ? `${fc} Aufnahmen` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  const spark = episodeSparklineSvg(ep.curve_preview, meta.color);
  const sparkHTML = spark ? `<div class="ws-ep-spark-wrap">${spark}</div>` : '';
  const expected = `
      <div class="ws-recap-card" data-ep-id="${esc(ep.id)}">
        <div class="ws-recap-card-period">${esc(episodeTitle(ep))}</div>
        <div class="ws-recap-card-meta">${esc(metaLine)}</div>
        ${characterHTML}
        ${sparkHTML}
        <span class="ws-recap-card-play" aria-hidden="true">${meta.icon}</span>
      </div>`;
  assert.equal(libraryCardHTML(EPISODE_ITEM, {}), expected);
});

test('an episode WITH a stamped footage_hero renders the thumbnail-primary shell instead', () => {
  const html = libraryCardHTML(EPISODE_ITEM_WITH_FOOTAGE, {});
  assert.match(html, /class="ws-card ws-card--episode"/);
  assert.match(html, /data-ep-id="ep_2"/);
  assert.match(html, /src="\/api\/weather\/sightings\/x\/thumb"/);
  // A real clip (both thumb_url and video_url present) gets the play
  // affordance.
  assert.match(html, /ws-card-play/);
  // Character badge + curve move OUT of corner overlays and into the
  // footer strip below the thumbnail.
  assert.match(html, /ws-ep-foot/);
  assert.match(html, /ws-ep-character/);
  assert.match(html, /ws-ep-spark-wrap/);
  // NOT the old curve-only shell — the two are mutually exclusive.
  assert.doesNotMatch(html, /ws-recap-card-period/);
  assert.doesNotMatch(html, /ws-recap-card-play/);
});

test('rendering a whole PAGE of footage-primary episode cards fires zero network requests', () => {
  // The design decision this pins: the merged grid reads `footage_hero`
  // straight off data `/api/library` already returned (stamped into the
  // ledger at sweep/footage-route time, see
  // weather_episodes/_footage.py::episode_hero + _store.append_footage_count)
  // rather than each card fetching GET /api/weather/episodes/<id>/footage
  // on paint. A 30-item page (the grid's real default page size,
  // library/page.js::_PAGE_LIMIT) must not turn into 30 requests. Proven
  // behaviourally, not just by code inspection: any fetch call during
  // rendering throws, and libraryCardHTML is synchronous (returns a
  // plain string, never a Promise) — an async fetch-then-render could
  // not produce that even if it never actually resolved in time.
  const realFetch = globalThis.fetch;
  globalThis.fetch = () => {
    throw new Error('unexpected network call from a card render');
  };
  try {
    for (let i = 0; i < 30; i++) {
      const item = {
        ...EPISODE_ITEM_WITH_FOOTAGE,
        id: `episode:ep_${i}`,
        extra: { ...EPISODE_ITEM_WITH_FOOTAGE.extra, id: `ep_${i}` },
      };
      const html = libraryCardHTML(item, { idx: i });
      assert.equal(typeof html, 'string');
      assert.match(html, /ws-card--episode/);
    }
  } finally {
    globalThis.fetch = realFetch;
  }
});

test('timelapse kind dispatches to the new timelapseCardHTML', () => {
  const html = libraryCardHTML(TIMELAPSE_ITEM, {});
  assert.match(html, /class="media-card mmc-tl"/);
  assert.match(html, /data-lib-id="timelapse:cam1:2026-08-30"/);
});

test('an unrecognised kind renders a safe fallback instead of throwing', () => {
  const html = libraryCardHTML({ kind: 'weird_future_kind', id: 'x:1', cam_name: 'Whatever' }, {});
  assert.match(html, /lib-card--unknown/);
  assert.match(html, /data-lib-kind="weird_future_kind"/);
});

test('a malformed item (no kind at all) does not throw', () => {
  assert.doesNotThrow(() => libraryCardHTML({}, {}));
  assert.doesNotThrow(() => libraryCardHTML(null, {}));
  assert.match(libraryCardHTML(null, {}), /lib-card--unknown/);
});
