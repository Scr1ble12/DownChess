// Stockfish over UCI. The desktop app runs the official Stockfish binary in the
// main process (main.cjs) and passes UCI lines through the preload bridge;
// tests plug in a native Stockfish through the same `transport` interface.
//
// Like the Python version: for the batch pass, one single-threaded engine per
// CPU core, each on a different game, which beats one engine on many threads
// at shallow depth. A single-game review uses one engine on every core.

import { Chess } from '../vendor/chess.js';
import { BOOK_PLIES, CP_CAP } from './classify.js';

export const DEFAULT_DEPTH = 12;

// The score in the last full "info" line, turned to White's point of view.
// -> {cp, mate, best}
export function parseSearch(lines, whiteToMove) {
  let score = null, pv = null;
  for (const line of lines) {
    if (!line.startsWith('info') || !line.includes(' score ') || / (lower|upper)bound/.test(line)) continue;
    if (/ multipv (?!1 )\d+/.test(line)) continue;
    const m = / score (cp|mate) (-?\d+)/.exec(line);
    if (m) score = [m[1], parseInt(m[2], 10)];
    const p = / pv (\S+)/.exec(line);
    if (p) pv = p[1];
  }
  const bestLine = lines.find(l => l.startsWith('bestmove'));
  const best = bestLine?.split(' ')[1];
  const sign = whiteToMove ? 1 : -1;
  let cp = 0, mate = null;
  if (score?.[0] === 'cp') cp = Math.max(-CP_CAP, Math.min(CP_CAP, sign * score[1]));
  else if (score?.[0] === 'mate') { mate = sign * score[1]; cp = mate > 0 ? CP_CAP : -CP_CAP; }
  return { cp, mate, best: best && best !== '(none)' ? best : pv };
}

// A Stockfish process in the main process, through the preload bridge.
export function appTransport() {
  const bridge = globalThis.downchess.engine;
  const id = bridge.start();
  return { send: cmd => bridge.send(id, cmd), onLine: cb => bridge.onLine(id, cb), close: () => bridge.stop(id) };
}

export class Engine {
  constructor(transport) {
    this.t = transport;
    this.buffer = [];
    this.waiter = null;
    transport.onLine(text => {
      for (const line of text.split('\n')) {
        if (!line) continue;
        this.buffer.push(line);
        if (this.waiter && this.waiter.test(line)) {
          const { resolve } = this.waiter;
          const lines = this.buffer;
          this.waiter = null;
          this.buffer = [];
          resolve(lines);
        }
      }
    });
  }

  until(test) {
    return new Promise(resolve => { this.waiter = { test, resolve }; });
  }

  async init({ threads = 1, hash = 64 } = {}) {
    const ok = this.until(l => l === 'uciok');
    this.t.send('uci');
    await ok;
    this.t.send(`setoption name Threads value ${threads}`);
    this.t.send(`setoption name Hash value ${hash}`);
    const ready = this.until(l => l === 'readyok');
    this.t.send('isready');
    await ready;
    return this;
  }

  async newGame() {
    this.t.send('ucinewgame');
    const ready = this.until(l => l === 'readyok');
    this.t.send('isready');
    await ready;
  }

  async evaluate(fen, depth) {
    this.buffer = [];
    const done = this.until(l => l.startsWith('bestmove'));
    this.t.send(`position fen ${fen}`);
    this.t.send(`go depth ${depth}`);
    return parseSearch(await done, fen.split(' ')[1] === 'w');
  }

  close() {
    this.t.send('quit');
    this.t.close?.();
  }
}

// Eval of the position after each ply from BOOK_PLIES to the end.
// moves: [{uci}] -> {ply: [cp, mate, best]}, White POV.
export async function analysePositions(engine, moves, depth, progress) {
  const board = new Chess();
  const evals = {};
  await engine.newGame();
  for (let ply = 0; ply <= moves.length; ply++) {
    if (ply > 0) {
      const u = moves[ply - 1].uci;
      board.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] });
      progress?.(ply, moves.length + 1);
    }
    if (ply < BOOK_PLIES) continue;
    if (board.isGameOver()) {
      // Score a finished position without the engine.
      evals[ply] = board.isCheckmate() ? [board.turn() === 'w' ? -CP_CAP : CP_CAP, 0, null] : [0, null, null];
      continue;
    }
    const { cp, mate, best } = await engine.evaluate(board.fen(), depth);
    evals[ply] = [cp, mate, best];
  }
  return evals;
}

// True when Lichess's own analysis covers every move after the book plies.
export function lichessEvalsComplete(game) {
  const n = game.moves.length;
  const have = Object.keys(game.lichessEvals || {}).filter(p => +p >= BOOK_PLIES).length;
  return n > BOOK_PLIES && have >= n - BOOK_PLIES; // Lichess often leaves the final position unscored
}

// Analyse many games with `workers` engines in parallel. onDone(game, analysis)
// is called as each finishes; stop by aborting `signal`.
export async function analyseMany(games, { depth = DEFAULT_DEPTH, workers = defaultWorkers(), makeTransport = appTransport,
  onDone, onProgress, signal } = {}) {
  const queue = [...games];
  let finished = 0;
  const run = async () => {
    const engine = await new Engine(makeTransport()).init();
    try {
      while (queue.length && !signal?.aborted) {
        const game = queue.shift();
        const evals = await analysePositions(engine, game.moves, depth);
        if (signal?.aborted) break;
        await onDone(game, { source: 'stockfish', depth, evals });
        onProgress?.(++finished, games.length);
      }
    } finally {
      engine.close();
    }
  };
  await Promise.all(Array.from({ length: Math.max(1, Math.min(workers, games.length)) }, run));
  return finished;
}

export const cores = () => globalThis.navigator?.hardwareConcurrency || 2;
export const defaultWorkers = () => cores();

// One game with one engine on every core, for the review page.
export async function analyseOne(moves, depth, progress, makeTransport = appTransport) {
  const engine = await new Engine(makeTransport()).init({ threads: cores(), hash: 256 });
  try {
    return await analysePositions(engine, moves, depth, progress);
  } finally {
    engine.close();
  }
}
