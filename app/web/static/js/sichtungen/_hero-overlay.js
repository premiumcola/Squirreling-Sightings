// ─── sichtungen/_hero-overlay.js ─────────────────────────────────────────
// Hero-photo overlays (species name scrim + play button) and the
// compact audio-recordings list for the species dossier panel. Split
// out of _dossier-panel.js by CLAUDE.md's 400-line file ceiling once
// the 2026-09 redesign (name burned into the photo, a tappable
// play/chirp icon on the photo itself, a much shorter panel) pushed
// the hero-related markup past what belongs inline in the main module.
//
// The play button and every compact row below share ONE playback
// state: tapping the hero button toggles the currently "active"
// recording; tapping a row switches which recording is active and
// starts it. Only one <audio> element plays at a time.
import { cssUrl, esc } from '../core/dom.js';

function _recordingsOf(d) {
  if (Array.isArray(d.recordings) && d.recordings.length) return d.recordings.slice(0, 3);
  if (d.audio_url) {
    return [
      {
        file_url: d.audio_url,
        type_de: 'Aufnahme',
        recordist: d.audio_attribution,
        license_url: d.audio_license,
      },
    ];
  }
  return [];
}

/** Every REAL reference photo this dossier has, in display order.
 *
 * A photo box exists only for a URL that actually resolves to a
 * photograph — there is deliberately no placeholder any more. The old
 * "🐦" fallback rendered the app's generic bird glyph inside the frame,
 * and next to a real photograph it read as a picture OF the species
 * rather than as an empty slot ("irgend 'n random roter Vogel, macht
 * keinen Sinn"). A species Wikipedia only has one usable image for now
 * shows exactly one box and picks the second up on a later fetch. */
export function photoUrlsOf(d) {
  // `photo_urls` is the real store (bird_dossiers.py); the two scalar
  // fields are its backward-compat mirror and are all a dossier cached
  // before the list existed has — until the photo backfill sweep grows
  // it. Reading both keeps an un-refetched dossier rendering.
  const list =
    Array.isArray(d.photo_urls) && d.photo_urls.length
      ? d.photo_urls
      : [d.wikipedia_thumb_url, d.wikipedia_thumb_url_2];
  return list.map((u) => (typeof u === 'string' ? u.trim() : '')).filter(Boolean);
}

// Hero: every available reference photo side by side (so the operator
// can compare their own recording against more than one view), each
// contained — never cropped — inside its own box. The box COUNT drives
// the frame's shape via a --n modifier (see 29-birds.css): one photo
// gets a single wide frame, two split it into 1:1 squares, three put
// the primary photo across the top with the two comparison views
// beneath. Only the first photo carries the bottom gradient scrim with
// the species name burned in (replaces the old plain-text .sd-name line
// — CLAUDE.md forbids showing the same info twice) and, only when a
// recording actually exists, a prominent centred play/pause button. No
// audio → no button at all (never a tappable-looking dead end).
//
// With no photos at all there is no hero: the name falls back to a
// plain heading line, so it is still shown exactly once.
export function heroHtml(d) {
  const photos = photoUrlsOf(d);
  const name = esc(d.common_name_de || d.latin);
  // The latin name rides along under the German one INSIDE the scrim
  // rather than as its own line below the photo — same reason the
  // German name moved in: one identity block, not two stacked ones.
  // Suppressed when it would just repeat the line above (a species with
  // no German name falls back to the latin one for `name`).
  const latin = esc(d.latin || '');
  const latinLine = latin && latin !== name ? `<div class="sd-hero-latin">${latin}</div>` : '';
  if (!photos.length) {
    return `<div class="sd-name-line">${name}${latinLine ? `<span class="sd-name-latin">${latin}</span>` : ''}</div>`;
  }
  const hasAudio = _recordingsOf(d).length > 0;
  const playBtn = hasAudio
    ? `<button type="button" class="sd-hero-play" id="sdHeroPlay" aria-pressed="false" aria-label="Vogelstimme abspielen">
        <svg class="sd-hero-play-icon sd-hero-play-icon--play" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>
        <svg class="sd-hero-play-icon sd-hero-play-icon--pause" viewBox="0 0 24 24" width="26" height="26" aria-hidden="true"><path fill="currentColor" d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>
      </button>`
    : '';
  const boxes = photos
    .map((src, i) => {
      const overlay =
        i === 0
          ? `<div class="sd-hero-scrim"></div><div class="sd-hero-caption"><div class="sd-hero-name">${name}</div>${latinLine}</div>${playBtn}`
          : '';
      // The bird is shown whole (`contain`), and the frame around it is
      // filled by the same photograph, blown up and blurred — see the
      // .sd-hero-photo block in 29-birds.css for why this box was
      // rebuilt rather than patched a fourth time.
      //
      // The blurred ground is a ::before fed by this custom property,
      // not a second <img>. One image element means assistive tech is
      // not told about the same photo twice, and a pseudo-element has no
      // layout box of its own to escape the frame — an over-scaled <img>
      // does, and its rect reached down over the summary text even
      // though `overflow: hidden` clipped the paint.
      return (
        `<div class="sd-hero-photo" style="--sd-hero-src: url(&quot;${cssUrl(src)}&quot;)">` +
        `<img class="sd-hero-subject" src="${esc(src)}" alt="" loading="lazy"/>` +
        `${overlay}</div>`
      );
    })
    .join('');
  return `<div class="sd-hero sd-hero--${photos.length}">${boxes}</div>`;
}

function _audioItemHtml(r, idx) {
  const recordist = esc(r.recordist || 'unbekannt');
  const license = r.license_url
    ? ` · <a href="${esc(r.license_url)}" target="_blank" rel="noopener noreferrer">Lizenz</a>`
    : '';
  return `<div class="sd-audio-item">
    <button type="button" class="sd-audio-row${idx === 0 ? ' sd-audio-row--active' : ''}" data-audio-idx="${idx}">
      <span class="sd-audio-row-icon" aria-hidden="true">♪</span>
      <span class="sd-audio-type">${esc(r.type_de || 'Aufnahme')}</span>
    </button>
    <div class="sd-audio-attribution">${recordist}${license}</div>
    <audio class="sd-audio-el" data-audio-idx="${idx}" preload="none" src="${esc(r.file_url)}"></audio>
  </div>`;
}

// Compact recording list (up to three) — CC-BY attribution stays next
// to each recording (bird_dossiers.py's module docstring), but the
// native <audio controls> widget is gone: playback now runs entirely
// through the hero button + this list's own small row buttons, wired
// by wireHeroAudio() below.
//
// With no recording the block does NOT vanish: an empty slot read as
// "this app has no bird-song feature" rather than "this species has no
// clip yet" — the same honesty _dossier-panel.js already applies to a
// missing Wikipedia extract. Still no play button on the hero (that
// would be a tappable dead end); just a line saying which of the two
// states this is. `audio_checked_at` is stamped on every xeno-canto
// attempt, hit or miss (bird_dossiers.py::_apply_xeno_canto), so a
// dossier that was asked and came back empty is distinguishable from
// one that has not been asked yet.
export function audioListHtml(d) {
  const list = _recordingsOf(d);
  if (!list.length) {
    const msg = d.audio_checked_at
      ? 'Keine Vogelstimme verfügbar — der nächste Abgleich versucht es erneut.'
      : 'Vogelstimme noch nicht geladen — der nächste Abgleich holt sie nach.';
    return `<div class="sd-audio"><div class="sd-audio-source">${esc(msg)}</div></div>`;
  }
  return `<div class="sd-audio">
    ${list.map(_audioItemHtml).join('')}
    <div class="sd-audio-source">Quelle: <a href="https://xeno-canto.org/" target="_blank" rel="noopener noreferrer">xeno-canto.org</a></div>
  </div>`;
}

// Binds the hero play button + every compact row to the <audio>
// elements audioListHtml() rendered. Call once per panel render, after
// both heroHtml() and audioListHtml() are in the DOM under `root`.
export function wireHeroAudio(root) {
  const heroBtn = root.querySelector('#sdHeroPlay');
  const rows = Array.from(root.querySelectorAll('.sd-audio-row'));
  const audios = Array.from(root.querySelectorAll('.sd-audio-el'));
  if (!audios.length) return;
  let activeIdx = 0;

  const audioAt = (idx) => audios.find((a) => Number(a.dataset.audioIdx) === idx);
  const setActiveRow = (idx) => {
    activeIdx = idx;
    rows.forEach((r) =>
      r.classList.toggle('sd-audio-row--active', Number(r.dataset.audioIdx) === idx),
    );
  };
  const setPlayingUI = (isPlaying) => {
    if (!heroBtn) return;
    heroBtn.classList.toggle('sd-hero-play--playing', isPlaying);
    heroBtn.setAttribute('aria-pressed', String(isPlaying));
    heroBtn.setAttribute(
      'aria-label',
      isPlaying ? 'Vogelstimme pausieren' : 'Vogelstimme abspielen',
    );
  };
  const toggle = (idx) => {
    const audio = audioAt(idx);
    if (!audio) return;
    if (idx !== activeIdx) setActiveRow(idx);
    if (audio.paused) {
      audios.forEach((a) => {
        if (a !== audio) a.pause();
      });
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  };

  audios.forEach((a) => {
    a.addEventListener('play', () => {
      setActiveRow(Number(a.dataset.audioIdx));
      setPlayingUI(true);
    });
    a.addEventListener('pause', () => setPlayingUI(false));
    a.addEventListener('ended', () => setPlayingUI(false));
  });
  heroBtn?.addEventListener('click', () => toggle(activeIdx));
  rows.forEach((r) => r.addEventListener('click', () => toggle(Number(r.dataset.audioIdx))));
}
