// Download a player's games from Chess.com or Lichess for a date range.
// Both sites' public APIs need no key. In the app, requests go through the
// main process (see appFetch), which also sets a descriptive User-Agent.
//
// Chess.com serves monthly archives, so we fetch the months that overlap the
// range and keep the games inside it. Lichess takes since/until directly.
// Requests go one at a time, and an HTTP 429 means wait a minute, as both ask.

import { SkipGame, normalizeChesscom, normalizeLichess } from './normalize.js';

const RETRY_WAIT_MS = 60_000;

export class NotFound extends Error {}

// fetch() for the app: the request runs in the main process.
export async function appFetch(url, opts = {}) {
  const r = await globalThis.downchess.fetch(url, opts);
  return { status: r.status, ok: r.status >= 200 && r.status < 300, text: async () => r.body, json: async () => JSON.parse(r.body) };
}

async function get(url, opts = {}, { fetchImpl = globalThis.downchess ? appFetch : fetch, sleep = ms => new Promise(r => setTimeout(r, ms)), log = () => {} } = {}) {
  for (let attempt = 0; attempt < 5; attempt++) {
    const resp = await fetchImpl(url, opts);
    if (resp.status === 404) throw new NotFound(url);
    if (resp.status === 429 || resp.status >= 500) {
      log(`Server said ${resp.status}; waiting a minute before retrying.`);
      await sleep(RETRY_WAIT_MS);
      continue;
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status} from ${url}`);
    return resp;
  }
  throw new Error(`Gave up on ${url} after 5 attempts`);
}

// 'YYYY-MM-DD' (inclusive) -> epoch ms. A missing end means now.
export function rangeMs(from, to) {
  const start = from ? Date.parse(`${from}T00:00:00Z`) : 0;
  const end = to ? Date.parse(`${to}T23:59:59.999Z`) : Date.now();
  return [start, end];
}

// '.../games/2026/09' -> '2026/09'
export const archiveKey = url => url.replace(/\/+$/, '').split('/').slice(-2).join('/');

export function archivesInRange(urls, from, to) {
  const lo = from ? from.slice(0, 7).replace('-', '/') : '0000/00';
  const hi = to ? to.slice(0, 7).replace('-', '/') : '9999/99';
  return urls.filter(u => archiveKey(u) >= lo && archiveKey(u) <= hi);
}

function keep(game, speed, start, end) {
  const t = Date.parse(game.playedAt);
  return (!speed || game.timeClass === speed) && t >= start && t <= end;
}

// Calls onGame(game) for each game in range. Returns {seen, kept, skipped}.
export async function fetchChesscom(username, { from, to, speed = 'rapid', onGame, log = () => {}, fetchImpl, sleep, signal } = {}) {
  const env = { fetchImpl, sleep, log };
  const user = username.trim().toLowerCase();
  const list = await (await get(`https://api.chess.com/pub/player/${encodeURIComponent(user)}/games/archives`, {}, env)).json();
  const urls = archivesInRange(list.archives || [], from, to);
  const [start, end] = rangeMs(from, to);
  const counts = { seen: 0, kept: 0, skipped: 0 };
  log(`Chess.com: ${urls.length} month(s) to download.`);
  for (const url of urls) {
    if (signal?.aborted) break;
    const data = await (await get(url, {}, env)).json();
    let kept = 0;
    for (const raw of data.games || []) {
      counts.seen++;
      let game;
      try {
        game = normalizeChesscom(raw);
      } catch (e) {
        if (!(e instanceof SkipGame)) throw e;
        counts.skipped++;
        continue;
      }
      if (!keep(game, speed, start, end)) { counts.skipped++; continue; }
      await onGame(game);
      counts.kept++; kept++;
    }
    log(`  ${archiveKey(url)}: ${kept} game(s)`);
  }
  return counts;
}

export function lichessParams(from, to, speed) {
  const [start, end] = rangeMs(from, to);
  const p = new URLSearchParams({ pgnInJson: 'true', clocks: 'true', evals: 'true', opening: 'true', sort: 'dateAsc' });
  if (from) p.set('since', String(start));
  if (to) p.set('until', String(end));
  if (speed) p.set('perfType', speed);
  return p;
}

async function* ndjsonLines(resp) {
  if (!resp.body) { // the app's fetch returns the whole response at once
    for (const line of (await resp.text()).split('\n')) if (line.trim()) yield JSON.parse(line);
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (line) yield JSON.parse(line);
    }
  }
  if (buf.trim()) yield JSON.parse(buf);
}

export async function fetchLichess(username, { from, to, speed = 'rapid', onGame, log = () => {}, fetchImpl, sleep, signal } = {}) {
  const env = { fetchImpl, sleep, log };
  const url = `https://lichess.org/api/games/user/${encodeURIComponent(username.trim())}?${lichessParams(from, to, speed)}`;
  const resp = await get(url, { headers: { Accept: 'application/x-ndjson' } }, env);
  const [start, end] = rangeMs(from, to);
  const counts = { seen: 0, kept: 0, skipped: 0 };
  log('Lichess: streaming games (about 20 per second)...');
  for await (const raw of ndjsonLines(resp)) {
    if (signal?.aborted) break;
    counts.seen++;
    let game;
    try {
      game = normalizeLichess(raw);
    } catch (e) {
      if (!(e instanceof SkipGame)) throw e;
      counts.skipped++;
      continue;
    }
    if (!keep(game, speed, start, end)) { counts.skipped++; continue; }
    await onGame(game);
    counts.kept++;
    if (counts.kept % 100 === 0) log(`  ${counts.kept} games so far`);
  }
  return counts;
}

// One Lichess game by id, as PGN, for the review page.
export async function fetchLichessPgn(id, { fetchImpl } = {}) {
  const resp = await get(`https://lichess.org/game/export/${id}?clocks=true&evals=false`, { headers: { Accept: 'application/x-chess-pgn' } }, { fetchImpl });
  return resp.text();
}

// A Chess.com or Lichess game link -> [platform, gameId], or null.
export function parseLink(text) {
  text = text.trim();
  let m = /chess\.com\/(?:game\/)?(?:live|daily|game)(?:\/game)?\/(\d+)/.exec(text);
  if (m) return ['chesscom', m[1]];
  m = /lichess\.org\/(?:game\/export\/)?([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?(?:\/(?:white|black))?\/?(?:[?#].*)?$/.exec(text);
  return m ? ['lichess', m[1]] : null;
}
