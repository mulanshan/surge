// Local-only capture sink. Listens on 127.0.0.1:18819 (Surge can reach
// macOS loopback because Surge runs on the same Mac).
//
// Surge response-script POSTs:
//   POST /capture?endpoint=get_watch&len=12345
//   body: raw redacted bytes
//
// Server writes them to ~/surge/captures-redacted/<timestamp>_<endpoint>_<len>.bin
//
// No upload anywhere. Loopback only.
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';

const OUT = path.join(os.homedir(), 'surge', 'captures-redacted');
await fs.mkdir(OUT, { recursive: true });

const server = http.createServer(async (req, res) => {
  if (req.method !== 'POST' || !req.url.startsWith('/capture')) {
    res.writeHead(404).end();
    return;
  }
  const u = new URL(req.url, 'http://localhost');
  const ep = u.searchParams.get('endpoint') || 'unknown';
  const declared = u.searchParams.get('len') || '0';
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = Buffer.concat(chunks);
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const file = path.join(OUT, `${stamp}_${ep}_${body.length}.bin`);
  await fs.writeFile(file, body);
  console.log(`saved ${file}  (declared=${declared} got=${body.length})`);
  res.writeHead(200, { 'content-type': 'text/plain' }).end('ok\n');
});

server.listen(18819, '127.0.0.1', () => {
  console.log(`Listening on http://127.0.0.1:18819 — output dir: ${OUT}`);
  console.log('Leave this running, then trigger iPhone YouTube playback.');
  console.log('Stop with Ctrl+C when you have enough samples.');
});
