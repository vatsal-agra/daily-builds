// Tiny static dev server: node serve.js [port]
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('.', import.meta.url)));
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json' };
const port = Number(process.argv[2] || process.env.PORT || 8080);

export function createServer() {
  return http.createServer(async (req, res) => {
    try {
      let p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
      if (p === '/') { res.writeHead(302, { location: '/web/index.html' }).end(); return; }
      const file = normalize(join(root, p));
      if (!file.startsWith(root) || !/^\/(web|src|dist)\//.test(file.slice(root.length - 0).replace(/\\/g, '/'))) { res.writeHead(404).end('not found'); return; }
      const body = await readFile(file);
      res.writeHead(200, { 'content-type': types[extname(file)] || 'application/octet-stream' }).end(body);
    } catch { res.writeHead(404).end('not found'); }
  });
}
if (import.meta.url === `file://${process.argv[1]}`) {
  createServer().listen(port, () => console.log(`Fathom on http://localhost:${port}`));
}
