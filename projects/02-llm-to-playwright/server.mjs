import http from 'http';
import fs from 'fs';
import path from 'path';
import url from 'url';

const port = Number(process.env.PORT || 4173);
const rootDir = path.resolve(process.cwd(), 'projects/02-llm-to-playwright/demo');

const mimeTypes = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.jpg', 'image/jpeg'],
  ['.jpeg', 'image/jpeg'],
]);

const server = http.createServer((req, res) => {
  if (!req.url) {
    res.writeHead(400);
    res.end('Bad Request');
    return;
  }

  const parsed = url.parse(req.url);
  const pathname = parsed.pathname && parsed.pathname !== '/' ? parsed.pathname : '/index.html';
  const filePath = path.join(rootDir, pathname);

  if (!filePath.startsWith(rootDir)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('Not Found');
      return;
    }
    const ext = path.extname(filePath);
    const contentType = mimeTypes.get(ext) || 'application/octet-stream';
    res.writeHead(200, { 'content-type': contentType });
    res.end(data);
  });
});

server.listen(port, () => {
  console.log(`Demo server listening on http://127.0.0.1:${port}`);
});

const shutdown = () => {
  server.close(() => process.exit(0));
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
