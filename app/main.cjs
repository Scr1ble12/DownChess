// The Electron main process: opens the window, runs Stockfish processes for
// the page, and makes the web requests to Chess.com and Lichess.

const { app, BrowserWindow, ipcMain, net, protocol, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const RENDERER = path.join(__dirname, 'renderer');
const USER_AGENT = `DownChess/${app.getVersion()} (personal game analysis app; https://github.com/Scr1ble12/DownChess)`;

// Serve the page from app://downchess/ so it gets a stable origin (IndexedDB
// keeps its data) and ES modules load normally.
protocol.registerSchemesAsPrivileged([{ scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);

function stockfishPath() {
  const exe = process.platform === 'win32' ? 'stockfish.exe' : 'stockfish';
  const candidates = [
    app.isPackaged ? path.join(process.resourcesPath, 'stockfish', exe) : path.join(__dirname, 'stockfish', exe),
    process.env.STOCKFISH_PATH,
    '/opt/homebrew/bin/stockfish', '/usr/local/bin/stockfish', '/usr/games/stockfish', '/usr/bin/stockfish',
  ];
  return candidates.find(p => p && fs.existsSync(p)) || null;
}

const engines = new Map();
let nextId = 1;

ipcMain.on('engine:start', event => {
  const bin = stockfishPath();
  if (!bin) {
    event.returnValue = { error: 'Stockfish not found. Run "npm run stockfish" in the app folder.' };
    return;
  }
  const id = nextId++;
  const proc = spawn(bin, [], { stdio: ['pipe', 'pipe', 'ignore'] });
  let buf = '';
  proc.stdout.setEncoding('utf8');
  proc.stdout.on('data', chunk => {
    buf += chunk;
    const lines = buf.split(/\r?\n/);
    buf = lines.pop();
    if (!event.sender.isDestroyed()) event.sender.send('engine:lines', id, lines);
  });
  proc.on('exit', () => engines.delete(id));
  proc.on('error', err => { if (!event.sender.isDestroyed()) event.sender.send('engine:lines', id, [`error ${err.message}`]); });
  engines.set(id, proc);
  event.returnValue = { id };
});

ipcMain.on('engine:send', (_e, id, cmd) => engines.get(id)?.stdin.write(`${cmd}\n`));
ipcMain.on('engine:stop', (_e, id) => {
  const proc = engines.get(id);
  if (!proc) return;
  proc.stdin.end('quit\n');
  setTimeout(() => proc.kill(), 1000);
});

// Only the two chess sites, GET only.
const ALLOWED_HOSTS = new Set(['api.chess.com', 'lichess.org']);
ipcMain.handle('net:fetch', async (_e, url, opts = {}) => {
  const host = new URL(url).hostname;
  if (!ALLOWED_HOSTS.has(host)) throw new Error(`Not allowed: ${host}`);
  const resp = await net.fetch(url, { headers: { ...(opts.headers || {}), 'User-Agent': USER_AGENT } });
  return { status: resp.status, body: await resp.text() };
});

function createWindow() {
  const win = new BrowserWindow({
    width: 1100, height: 900, backgroundColor: '#000000', title: 'DownChess',
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: true },
  });
  win.setMenuBarVisibility(false);
  // Links (game pages) open in the normal browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  win.loadURL('app://downchess/index.html');
}

app.whenReady().then(() => {
  protocol.handle('app', req => {
    const rel = decodeURIComponent(new URL(req.url).pathname);
    const file = path.normalize(path.join(RENDERER, rel));
    if (!file.startsWith(RENDERER)) return new Response('Not found', { status: 404 });
    return net.fetch(pathToFileURL(file).toString());
  });
  createWindow();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => app.quit());
app.on('quit', () => { for (const p of engines.values()) p.kill(); });
