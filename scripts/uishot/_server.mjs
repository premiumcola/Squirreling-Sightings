// ─── scripts/uishot/_server.mjs ────────────────────────────────────────────
// A read-only static file server for the screenshot harness.
//
// WHY NOT FLASK. Every surface the harness shoots is JS-generated into a
// container that ships in a Jinja partial. Rendering those partials needs
// Jinja (render_shell.py does that), but SERVING them needs nothing more
// than correct MIME types — the app talks only to /api/*, which the
// harness stubs at the browser instead. Booting Flask would drag in
// config, storage, camera runtimes and Open-Meteo for zero extra fidelity.
//
// http:// rather than file:// is not optional: ES modules are blocked by
// CORS on file://, and the whole point is to import the real modules.

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { join, normalize, extname } from 'node:path';

import { REF_PHOTOS } from './_fixtures.mjs';

const MIME = {
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.mp4': 'video/mp4',
};

/** Resolve a URL path under `root`, refusing anything that escapes it. */
function _safeJoin(root, urlPath) {
  const clean = normalize(decodeURIComponent(urlPath.split('?')[0])).replace(/^(\.\.[/\\])+/, '');
  const full = join(root, clean);
  return full.startsWith(root) ? full : null;
}

/**
 * Serve `app/web/static` at /static and the pre-rendered shell at /.
 *
 * @param {string} staticRoot  absolute path to app/web/static
 * @param {string} shellPath   absolute path to the rendered index.html
 * @returns {Promise<{url: string, close: () => Promise<void>}>}
 */
export function startServer(staticRoot, shellPath) {
  const server = createServer(async (req, res) => {
    const path = req.url === '/' ? '/__shell__' : req.url;

    // Fixture images, served rather than inlined. A data: URI would not
    // survive the hero ground's `cssUrl` allowlist, and a fixture the
    // code silently rejects photographs a state production never gets
    // into. See REF_PHOTOS in _fixtures.mjs.
    const fixture = REF_PHOTOS.get(path);
    if (fixture) {
      res
        .writeHead(200, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'no-store' })
        .end(fixture);
      return;
    }

    let file = null;
    if (path.startsWith('/__shell__')) file = shellPath;
    else if (path.startsWith('/static/'))
      file = _safeJoin(staticRoot, path.slice('/static'.length));

    if (!file) {
      res.writeHead(404).end('not found');
      return;
    }
    try {
      const body = await readFile(file);
      res.writeHead(200, {
        'Content-Type': MIME[extname(file).toLowerCase()] || 'application/octet-stream',
        'Cache-Control': 'no-store',
      });
      res.end(body);
    } catch {
      res.writeHead(404).end('not found');
    }
  });

  return new Promise((resolve) => {
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}`,
        close: () => new Promise((done) => server.close(done)),
      });
    });
  });
}
