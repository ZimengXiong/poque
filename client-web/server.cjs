const fs = require('fs');
const http = require('http');
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT || 3000);
const POQUE_API = process.env.POQUE_API || 'https://poque.v3c.dev';
const DATA_FILE = process.env.DATA_FILE || path.join(__dirname, 'data', 'sessions.json');
const DIST_DIR = path.join(__dirname, 'dist');

fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });

function readSessions() {
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  } catch {
    return { sessions: {} };
  }
}

function writeSessions(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

function parseJson(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 16384) {
        req.destroy();
        reject(new Error('request body too large'));
      }
    });
    req.on('end', () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
  });
}

function browserFingerprint(req) {
  const clientFingerprint = req.headers['x-browser-fingerprint'];
  if (clientFingerprint && String(clientFingerprint).length <= 128) return String(clientFingerprint);

  const raw = [
    req.headers['user-agent'] || '',
    req.headers['accept-language'] || '',
    req.headers['sec-ch-ua'] || '',
    req.headers['sec-ch-ua-platform'] || '',
    req.socket.remoteAddress || '',
  ].join('|');
  return `server-${crypto.createHash('sha256').update(raw).digest('hex').slice(0, 24)}`;
}

function sendJson(res, status, payload) {
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
  });
  res.end(JSON.stringify(payload));
}

async function poque(pathname, method = 'GET', body) {
  const response = await fetch(`${POQUE_API}${pathname}`, {
    method,
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await response.text();
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = { ok: response.ok, text };
  }
  return { status: response.status, payload };
}

async function handleSession(req, res, url) {
  const fingerprint = browserFingerprint(req);
  const store = readSessions();
  const session = store.sessions[fingerprint] || null;

  if (url.pathname === '/session/status' && req.method === 'GET') {
    return sendJson(res, 200, { ok: true, fingerprint, ...session });
  }

  if (url.pathname === '/session/join' && req.method === 'POST') {
    const body = await parseJson(req);
    const name = String(body.name || '').trim().slice(0, 32);
    if (!name) return sendJson(res, 400, { ok: false, error: 'name is required' });

    const joined = await poque('/api/join', 'POST', { name });
    if (!joined.payload.ok) return sendJson(res, joined.status, joined.payload);

    const playerId = joined.payload.player_id;
    store.sessions[fingerprint] = {
      player_id: playerId,
      name,
      joined_at: new Date().toISOString(),
      last_seen_at: new Date().toISOString(),
    };
    writeSessions(store);
    return sendJson(res, joined.status, { ...joined.payload, fingerprint });
  }

  if (url.pathname === '/session/keepalive' && req.method === 'POST') {
    if (!session?.player_id) return sendJson(res, 404, { ok: false, error: 'no session for this browser' });
    const kept = await poque('/api/keepalive', 'POST', { player_id: session.player_id });
    store.sessions[fingerprint] = { ...session, last_seen_at: new Date().toISOString() };
    writeSessions(store);
    return sendJson(res, kept.status, kept.payload);
  }

  if (url.pathname === '/session/leave' && req.method === 'POST') {
    if (!session?.player_id) return sendJson(res, 200, { ok: true });
    const left = await poque('/api/leave', 'POST', { player_id: session.player_id });
    delete store.sessions[fingerprint];
    writeSessions(store);
    return sendJson(res, left.status, left.payload);
  }

  return sendJson(res, 404, { ok: false, error: 'unknown session endpoint' });
}

async function proxyApi(req, res, url) {
  const upstreamPath = `${url.pathname}${url.search}`;
  const body = req.method === 'GET' || req.method === 'HEAD' ? undefined : await parseJson(req);
  const proxied = await poque(upstreamPath, req.method, body);
  return sendJson(res, proxied.status, proxied.payload);
}

function serveStatic(req, res, url) {
  const requested = url.pathname === '/' ? '/index.html' : url.pathname;
  const filePath = path.normalize(path.join(DIST_DIR, requested));
  if (!filePath.startsWith(DIST_DIR)) return sendJson(res, 403, { ok: false });

  const finalPath = fs.existsSync(filePath) && fs.statSync(filePath).isFile()
    ? filePath
    : path.join(DIST_DIR, 'index.html');
  const ext = path.extname(finalPath);
  const type = {
    '.html': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
  }[ext] || 'application/octet-stream';
  res.writeHead(200, { 'content-type': type });
  fs.createReadStream(finalPath).pipe(res);
}

http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host}`);
    if (url.pathname.startsWith('/session/')) return await handleSession(req, res, url);
    if (url.pathname.startsWith('/api/')) return await proxyApi(req, res, url);
    return serveStatic(req, res, url);
  } catch (error) {
    console.error(error);
    return sendJson(res, 500, { ok: false, error: 'internal server error' });
  }
}).listen(PORT, '0.0.0.0', () => {
  console.log(`poque client listening on ${PORT}`);
});
