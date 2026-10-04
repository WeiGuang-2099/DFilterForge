/**
 * @fileoverview Serves the static export in out/ under the base path.
 *
 * Used by the Playwright tests and, later, the Docker site image; node:http
 * only, no dependency. It behaves like a static host: index.html for a
 * directory, a redirect from a directory path without its slash, and 404.html
 * with status 404 for anything else. A path segment that is empty mid-path,
 * is "." or "..", or decodes to text holding a slash, backslash, colon or NUL
 * is refused with status 400, so no request reads outside out/.
 *
 * Usage, from apps/web after `pnpm build`: `node scripts/serve.mjs`.
 * HOST (default 127.0.0.1) and PORT (default 3000) set the address.
 */

import {createReadStream, statSync} from 'node:fs';
import {stat} from 'node:fs/promises';
import {createServer} from 'node:http';
import path from 'node:path';

import {basePath} from './base_path.mjs';

const ROOT = path.resolve('out');
const NOT_FOUND = path.join(ROOT, '404.html');
const HOST = process.env['HOST'] ?? '127.0.0.1';
const PORT = Number(process.env['PORT'] ?? '3000');

const CONTENT_TYPES = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.gif', 'image/gif'],
  ['.html', 'text/html; charset=utf-8'],
  ['.ico', 'image/x-icon'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.txt', 'text/plain; charset=utf-8'],
  ['.woff2', 'font/woff2'],
]);

/**
 * Returns the size of a regular file, or null when there is none.
 *
 * @param {string} filePath
 * @return {Promise<number | null>}
 */
async function fileSize(filePath) {
  try {
    const info = await stat(filePath);
    return info.isFile() ? info.size : null;
  } catch {
    return null;
  }
}

/**
 * Maps a raw request path to a path under ROOT.
 *
 * @param {string} pathname
 * @return {string | null | undefined} null when the path is outside the base
 *     path; undefined when it is refused.
 */
function filePathFor(pathname) {
  if (pathname !== basePath && !pathname.startsWith(`${basePath}/`)) {
    return pathname.startsWith('/') ? null : undefined;
  }
  const parts = pathname.slice(basePath.length).split('/');
  const segments = [];
  for (const [index, raw] of parts.entries()) {
    // Empty only before the first slash or after the last, so a redirect can
    // never send "//host".
    if (raw === '' && index !== 0 && index !== parts.length - 1) {
      return undefined;
    }
    let segment;
    try {
      segment = decodeURIComponent(raw);
    } catch {
      return undefined;
    }
    if (segment === '.' || segment === '..' || /[/\\:\0]/.test(segment)) {
      return undefined;
    }
    segments.push(segment);
  }
  const filePath = path.join(ROOT, ...segments);
  return filePath === ROOT || filePath.startsWith(ROOT + path.sep) ? filePath : undefined;
}

/**
 * Sends a file, or only its headers for HEAD.
 *
 * @param {import('node:http').IncomingMessage} request
 * @param {import('node:http').ServerResponse} response
 * @param {number} status
 * @param {string} filePath
 * @param {number} size
 */
function sendFile(request, response, status, filePath, size) {
  response.writeHead(status, {
    'Cache-Control': 'no-cache',
    'Content-Length': size,
    'Content-Type': CONTENT_TYPES.get(path.extname(filePath)) ?? 'application/octet-stream',
    'X-Content-Type-Options': 'nosniff',
  });
  if (request.method === 'HEAD') {
    response.end();
    return;
  }
  createReadStream(filePath)
    .on('error', () => response.destroy())
    .pipe(response);
}

/**
 * @param {import('node:http').IncomingMessage} request
 * @param {import('node:http').ServerResponse} response
 */
async function handle(request, response) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    response.writeHead(405, {Allow: 'GET, HEAD'}).end();
    return;
  }
  const target = request.url ?? '';
  const queryStart = target.indexOf('?');
  const pathname = queryStart === -1 ? target : target.slice(0, queryStart);
  const query = queryStart === -1 ? '' : target.slice(queryStart);
  const filePath = filePathFor(pathname);
  if (filePath === undefined) {
    response.writeHead(400).end();
    return;
  }
  if (filePath !== null) {
    const isDirectory = pathname.endsWith('/');
    const file = isDirectory ? path.join(filePath, 'index.html') : filePath;
    const size = await fileSize(file);
    if (size !== null) {
      sendFile(request, response, 200, file, size);
      return;
    }
    if (!isDirectory && (await fileSize(path.join(filePath, 'index.html'))) !== null) {
      response.writeHead(301, {Location: `${pathname}/${query}`}).end();
      return;
    }
  }
  sendFile(request, response, 404, NOT_FOUND, (await fileSize(NOT_FOUND)) ?? 0);
}

if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) {
  throw new Error(`PORT must be an integer from 1 to 65535; got ${process.env['PORT']}`);
}
for (const required of [path.join(ROOT, 'index.html'), NOT_FOUND]) {
  if (!statSync(required, {throwIfNoEntry: false})?.isFile()) {
    console.error(`${required} is missing; build the static export first.`);
    process.exit(1);
  }
}

createServer((request, response) => {
  handle(request, response).catch(() => {
    if (response.headersSent) {
      response.destroy();
    } else {
      response.writeHead(500).end();
    }
  });
}).listen(PORT, HOST, () => {
  console.log(`Serving ${ROOT} at http://${HOST}:${PORT}${basePath}/`);
});
