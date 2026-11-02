// Games and analysis live in the browser's IndexedDB, so each device keeps its
// own copy and nothing leaves the computer.
//
//   players: {key: 'chesscom:scr1ble', platform, username, fetchedAt, from, to}
//   games:   the records from normalize.js, plus `analysis` once Stockfish has
//            run: {source: 'stockfish' | 'lichess', depth, evals: {ply: [cp, mate, best]}}

const NAME = 'downchess', VERSION = 1;
let dbPromise = null;

function open() {
  dbPromise ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('games')) db.createObjectStore('games', { keyPath: 'key' });
      if (!db.objectStoreNames.contains('players')) db.createObjectStore('players', { keyPath: 'key' });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbPromise;
}

const done = req => new Promise((resolve, reject) => { req.onsuccess = () => resolve(req.result); req.onerror = () => reject(req.error); });

async function store(name, mode = 'readonly') {
  return (await open()).transaction(name, mode).objectStore(name);
}

export const playerKey = (platform, username) => `${platform}:${username.toLowerCase()}`;

// Adds a game unless it is already stored. Returns true when it was new.
export async function addGame(game) {
  const s = await store('games', 'readwrite');
  if (await done(s.getKey(game.key))) return false;
  await done(s.put(game));
  return true;
}

export async function saveAnalysis(key, analysis) {
  const s = await store('games', 'readwrite');
  const game = await done(s.get(key));
  game.analysis = analysis;
  await done(s.put(game));
}

export async function getGame(key) {
  return done((await store('games')).get(key));
}

// Every stored game where `username` played, oldest first.
export async function playerGames(platform, username) {
  const all = await done((await store('games')).getAll());
  const u = username.toLowerCase();
  return all
    .filter(g => g.platform === platform && (g.white.toLowerCase() === u || g.black.toLowerCase() === u))
    .sort((a, b) => a.playedAt.localeCompare(b.playedAt));
}

export async function players() {
  const all = await done((await store('players')).getAll());
  return all.sort((a, b) => (b.fetchedAt || '').localeCompare(a.fetchedAt || ''));
}

export async function touchPlayer(platform, username, extra = {}) {
  const s = await store('players', 'readwrite');
  const key = playerKey(platform, username);
  const old = (await done(s.get(key))) || {};
  await done(s.put({ ...old, key, platform, username, fetchedAt: new Date().toISOString(), ...extra }));
}

export async function deletePlayer(platform, username) {
  const games = await playerGames(platform, username);
  const db = await open();
  const tx = db.transaction(['games', 'players'], 'readwrite');
  for (const g of games) tx.objectStore('games').delete(g.key);
  tx.objectStore('players').delete(playerKey(platform, username));
  await new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = () => reject(tx.error); });
}
