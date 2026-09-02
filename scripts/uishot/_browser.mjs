// ─── scripts/uishot/_browser.mjs ───────────────────────────────────────────
// Locate the out-of-tree browser install and launch it.
//
// The browser is DELIBERATELY not a dependency of this repo. package.json
// stays a lint-only manifest; playwright, Chromium and the Debian runtime
// libs all live under one prefix outside the git tree, created by
// scripts/uishot/install-browser.sh. Nothing here is ever installed on
// demand — a missing browser prints the install command and exits 3.

import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';

/** Where the browser prefix lives. Env override wins. */
export function browserHome() {
  return process.env.SQ_UIBROWSER_HOME || join(homedir(), '.cache', 'sq-uibrowser');
}

/**
 * Point the loader at the vendored Debian libs and fonts.
 *
 * The container this runs in has no libX11, no libnss3 and no fonts at
 * all, so Chromium neither starts nor draws a single glyph without
 * these. They are set on process.env so the Chromium child inherits
 * them; nothing outside this process is touched.
 */
function _applyEnv(prefix) {
  const sysroot = join(prefix, 'sysroot');
  if (existsSync(sysroot)) {
    const libs = [
      join(sysroot, 'usr/lib/x86_64-linux-gnu'),
      join(sysroot, 'lib/x86_64-linux-gnu'),
      join(sysroot, 'usr/lib'),
    ];
    process.env.LD_LIBRARY_PATH = [...libs, process.env.LD_LIBRARY_PATH || ''].join(':');
  }
  const fonts = join(prefix, 'fonts.conf');
  if (existsSync(fonts)) process.env.FONTCONFIG_FILE = fonts;
  process.env.PLAYWRIGHT_BROWSERS_PATH = join(prefix, 'browsers');
}

/** The message a reader gets instead of a stack trace. */
export function missingBrowserMessage(prefix) {
  return [
    '',
    '  The screenshot harness needs a browser, and none is installed.',
    '',
    `  Expected prefix : ${prefix}`,
    '  Install it with : bash scripts/uishot/install-browser.sh',
    '',
    '  The install goes OUTSIDE the repo (~1.1 GB: Chromium, playwright,',
    '  and the Debian runtime libs + fonts this container lacks).',
    '  package.json is deliberately left alone.',
    '  Override the location with SQ_UIBROWSER_HOME=/some/prefix.',
    '',
  ].join('\n');
}

/**
 * Launch Chromium from the external prefix.
 *
 * @returns {Promise<{browser: object, prefix: string}>}
 * @throws {Error} tagged `ENOBROWSER` when the prefix is not installed
 */
export async function launchBrowser() {
  const prefix = browserHome();
  const entry = join(prefix, 'node_modules', 'playwright', 'index.mjs');
  if (!existsSync(entry)) {
    const err = new Error(missingBrowserMessage(prefix));
    err.code = 'ENOBROWSER';
    throw err;
  }
  _applyEnv(prefix);
  const { chromium } = await import(pathToFileURL(entry).href);
  const browser = await chromium.launch({
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-color-profile=srgb'],
  });
  return { browser, prefix };
}
