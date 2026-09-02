// ─── weather/save-panel-fx/_particles.js ───────────────────────────────
// Rain and snow, on ONE canvas behind the save panel. Per-particle DOM
// nodes were never an option here (this panel opens on a box that is
// also decoding camera streams), and the loop is written to the same
// budget: at most FX_MAX_PARTICLES points, one clearRect and at most
// three batched path draws per frame — near-rain, far-rain, snow — no
// shadows, no blur, no per-particle draw call.
//
// The loop owns nothing but its own rAF handle and stops dead on stop():
// index.js calls it when the panel closes, when the tab goes hidden and
// when prefers-reduced-motion turns on.
import { FX_RAIN_SLANT, particleCountFor, seedParticle, stepParticle } from './_helpers.js';

const RAIN_NEAR = 'rgba(186, 214, 238, 0.42)';
const RAIN_FAR = 'rgba(186, 214, 238, 0.2)';
const SNOW_FILL = 'rgba(228, 240, 252, 0.6)';
// The backing store is capped well below a phone's real DPR — this is
// out-of-focus atmosphere, not artwork, and 3× would triple the fill
// cost for nothing anyone can see.
const MAX_DPR = 1.5;
// After a tab switch or a long paint stall the delta can be seconds;
// clamping it stops every particle teleporting off-panel at once.
const MAX_STEP_MS = 64;
const TAU = Math.PI * 2;

export function createParticleLayer(canvas) {
  const ctx = canvas.getContext?.('2d') || null;
  let raf = 0;
  let last = 0;
  let particles = [];
  let kinds = { rain: false, snow: false };
  let w = 0;
  let h = 0;

  function _reseed() {
    const active = (kinds.rain ? 1 : 0) + (kinds.snow ? 1 : 0);
    particles = [];
    if (!active || w < 1 || h < 1) return;
    for (const kind of ['rain', 'snow']) {
      if (!kinds[kind]) continue;
      const n = particleCountFor(kind, w, h, active);
      for (let i = 0; i < n; i += 1) particles.push(seedParticle(kind, w, h, Math.random));
    }
  }

  function _strokeRain(near, style) {
    ctx.strokeStyle = style;
    ctx.lineWidth = near ? 1.4 : 1;
    ctx.beginPath();
    for (const p of particles) {
      if (p.kind !== 'rain' || p.near !== near) continue;
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(p.x + p.len * FX_RAIN_SLANT, p.y - p.len);
    }
    ctx.stroke();
  }

  function _fillSnow() {
    ctx.fillStyle = SNOW_FILL;
    ctx.beginPath();
    for (const p of particles) {
      if (p.kind !== 'snow') continue;
      ctx.moveTo(p.x + p.r, p.y);
      ctx.arc(p.x, p.y, p.r, 0, TAU);
    }
    ctx.fill();
  }

  function _draw() {
    ctx.clearRect(0, 0, w, h);
    if (kinds.rain) {
      _strokeRain(false, RAIN_FAR);
      _strokeRain(true, RAIN_NEAR);
    }
    if (kinds.snow) _fillSnow();
  }

  function _frame(ts) {
    raf = requestAnimationFrame(_frame);
    const dt = last ? Math.min(MAX_STEP_MS, ts - last) : 16.6667;
    last = ts;
    for (const p of particles) stepParticle(p, dt, w, h);
    _draw();
  }

  return {
    // Called from index.js's ResizeObserver. Re-seeding on every resize
    // is fine: it happens on open and on an orientation change, not per
    // frame, and a stretched particle field would look worse.
    resize(nextW, nextH) {
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      w = Math.max(0, Math.round(nextW));
      h = Math.max(0, Math.round(nextH));
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      _reseed();
    },
    setKinds(next) {
      const changed = next.rain !== kinds.rain || next.snow !== kinds.snow;
      kinds = { rain: !!next.rain, snow: !!next.snow };
      if (changed) _reseed();
      return kinds.rain || kinds.snow;
    },
    start() {
      if (raf || !ctx) return;
      last = 0;
      raf = requestAnimationFrame(_frame);
    },
    stop() {
      if (!raf) return;
      cancelAnimationFrame(raf);
      raf = 0;
      last = 0;
      if (ctx) ctx.clearRect(0, 0, w, h);
    },
  };
}
