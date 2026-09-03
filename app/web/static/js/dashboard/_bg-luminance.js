// ─── dashboard/_bg-luminance.js ─────────────────────────────────────────
// E2 · adaptive overlay palette via per-region luminance sampling.
//
// Every ~2 s each visible tile's snapshot is sub-sampled at three
// distinct regions — identity (top-left), telegram (mid-bottom-left),
// classicons (bottom-strip) — and each region's mean Rec.709 luminance
// is fed through a hysteresis filter (5 % min gap) that flips
// data-bg="light" / "dark" on the corresponding .cv-overlay-region
// element. CSS variables scoped to each region then flip text/icon
// palette + halo direction so overlays stay legible even when the
// snapshot has strong vertical luminance gradients (bright sky over
// dark interior, etc.). Buttons stay dark in both modes — they live
// outside the regions and read a static drop-shadow filter.
//
// Split out of dashboard.js (1082 lines against a 400-line ceiling).
// This is the one self-contained timer in that file: it owns its canvas,
// its interval and its thresholds, and nothing else in the dashboard
// reads them.
import { byId } from '../core/dom.js';

const _BG_LUM_LIGHT_ENTER = 0.55; // dark → light if Y above
const _BG_LUM_DARK_ENTER = 0.5; // light → dark if Y below
const _OVERLAY_REGIONS = [
  // top-left identity (icon · name · live-pill)
  { region: 'identity', x: 0.0, y: 0.0, w: 0.4, h: 0.22 },
  // mid-bottom-left telegram/MQTT cluster row
  { region: 'telegram', x: 0.0, y: 0.62, w: 0.38, h: 0.26 },
  // bottom-strip class-icon row
  { region: 'classicons', x: 0.0, y: 0.86, w: 0.38, h: 0.14 },
];
let _bgLumCanvas = null;
let _bgLumCtx = null;
let _bgLumInterval = null;

function _ensureBgLumCanvas() {
  if (_bgLumCanvas) return;
  // 8×8 destination is plenty for an averaging sampler — each region
  // gets the same small target so the four bytes per pixel stay
  // dominated by the source-region's content, not by canvas resize
  // artefacts.
  _bgLumCanvas = document.createElement('canvas');
  _bgLumCanvas.width = 8;
  _bgLumCanvas.height = 8;
  _bgLumCtx = _bgLumCanvas.getContext('2d', { willReadFrequently: true });
}

function _sampleTileOverlayLuminance(card) {
  const img = card.querySelector('.cv-img');
  if (!img || !img.classList.contains('loaded')) return;
  const W = img.naturalWidth,
    H = img.naturalHeight;
  if (!W || !H) return;
  _ensureBgLumCanvas();
  for (const spec of _OVERLAY_REGIONS) {
    const target = card.querySelector(`.cv-overlay-region[data-region="${spec.region}"]`);
    if (!target) continue;
    const sx = Math.floor(W * spec.x);
    const sy = Math.floor(H * spec.y);
    const sw = Math.max(1, Math.floor(W * spec.w));
    const sh = Math.max(1, Math.floor(H * spec.h));
    try {
      _bgLumCtx.clearRect(0, 0, 8, 8);
      _bgLumCtx.drawImage(img, sx, sy, sw, sh, 0, 0, 8, 8);
      const data = _bgLumCtx.getImageData(0, 0, 8, 8).data;
      let sum = 0,
        n = 0;
      for (let i = 0; i < data.length; i += 4) {
        const r = data[i],
          g = data[i + 1],
          b = data[i + 2];
        sum += 0.2126 * r + 0.7152 * g + 0.0722 * b;
        n++;
      }
      if (!n) continue;
      const Y = sum / (n * 255);
      const current = target.dataset.bg || 'dark';
      let next = current;
      if (current === 'dark' && Y > _BG_LUM_LIGHT_ENTER) next = 'light';
      else if (current === 'light' && Y < _BG_LUM_DARK_ENTER) next = 'dark';
      if (next !== current) target.dataset.bg = next;
    } catch {
      // Canvas can taint on cross-origin pixels — same-origin
      // snapshots shouldn't trigger this in practice. Swallow so a
      // single bad frame on one region doesn't kill the loop for
      // the rest of the tile.
    }
  }
}

export function startBgLuminanceMonitor() {
  if (_bgLumInterval) clearInterval(_bgLumInterval);
  _bgLumInterval = setInterval(() => {
    if (document.hidden) return;
    const grid = byId('cameraCards');
    if (!grid) return;
    grid.querySelectorAll('.cv-card[data-camid]').forEach((card) => {
      _sampleTileOverlayLuminance(card);
    });
  }, 2000);
}
