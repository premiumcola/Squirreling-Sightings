// ─── scripts/uishot/_clip.mjs ──────────────────────────────────────────────
// Build the stand-in clip the recorded player plays.
//
// THIS IS NOT DECORATION. vplayer/_wireRecorded lays every timeline lane
// out against `stage.video.duration`. With no decodable source the
// duration is NaN, every lane collapses to zero width, and the shot
// shows a tidy empty strip instead of the real one — the harness would
// be flattering exactly the surface it exists to check.
//
// Built from what is already on hand. playwright's ffmpeg is a stripped
// screencast build: no lavfi, no x264, no PNG decoder and no `pipe:`
// protocol — it can demux image2pipe, decode MJPEG and encode VP8, and
// that is all. So Chromium draws the frames and exports them as JPEG,
// they go to a real file, and ffmpeg turns that into a WebM with a
// proper duration in the container header.

import { spawnSync } from 'node:child_process';
import { existsSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const W = 640;
const H = 360;
const FPS = 12;
const SECONDS = 12;

/** Draw the frames in the browser and hand back base64 JPEGs. */
function paintFrames([w, h, count]) {
  const cv = document.createElement('canvas');
  cv.width = w;
  cv.height = h;
  const g = cv.getContext('2d');
  const out = [];
  for (let i = 0; i < count; i++) {
    const t = i / count;
    const sky = g.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, '#2b3a4a');
    sky.addColorStop(1, '#16202b');
    g.fillStyle = sky;
    g.fillRect(0, 0, w, h);
    g.fillStyle = '#1b2a1f';
    g.fillRect(0, h * 0.62, w, h * 0.38);
    // Something that moves, so scrubbing and seeking read as real.
    g.fillStyle = '#dcbe5a';
    g.beginPath();
    g.arc(40 + t * (w - 80), h * 0.45 + Math.sin(t * 6.28) * 40, 26, 0, 6.2832);
    g.fill();
    g.fillStyle = '#7d93a8';
    g.font = '20px sans-serif';
    g.fillText(`uishot fixture · ${(i / 12).toFixed(1)}s`, 20, h - 24);
    out.push(cv.toDataURL('image/jpeg', 0.7).split(',')[1]);
  }
  return out;
}

/**
 * Write the clip if it is not already there.
 *
 * @param {object} browser  a launched playwright browser
 * @param {string} ffmpeg   path to playwright's ffmpeg binary
 * @param {string} dest     where the .webm should land
 * @returns {Promise<boolean>} true when a playable file exists afterwards
 */
export async function ensureClip(browser, ffmpeg, dest) {
  if (existsSync(dest)) return true;
  if (!ffmpeg || !existsSync(ffmpeg)) return false;

  const page = await browser.newPage();
  const b64 = await page.evaluate(paintFrames, [W, H, FPS * SECONDS]).catch(() => null);
  await page.close();
  if (!b64 || !b64.length) return false;

  const scratch = join(tmpdir(), `uishot-frames-${process.pid}.mjpeg`);
  writeFileSync(scratch, Buffer.concat(b64.map((s) => Buffer.from(s, 'base64'))));
  // `-c:v mjpeg` BEFORE -i is load-bearing: the image2 probe is stripped
  // out of this build, so without an explicit input codec ffmpeg reports
  // "Video: none, none: unknown codec" and refuses the stream.
  const r = spawnSync(ffmpeg, [
    '-y', '-f', 'image2pipe', '-c:v', 'mjpeg', '-framerate', String(FPS), '-i', scratch,
    '-c:v', 'libvpx', '-b:v', '600k', '-pix_fmt', 'yuv420p', dest,
  ]);
  rmSync(scratch, { force: true });
  return r.status === 0 && existsSync(dest);
}
