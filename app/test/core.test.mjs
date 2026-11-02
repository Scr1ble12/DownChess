// Core logic tests: node --test web/test/
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import test from 'node:test';

import { classifyGame, label, phase } from '../renderer/js/classify.js';
import { analysePositions, Engine, lichessEvalsComplete, parseSearch } from '../renderer/js/engine.js';
import { archivesInRange, fetchChesscom, fetchLichess, lichessParams, parseLink } from '../renderer/js/fetchers.js';
import { normalizeChesscom, normalizeLichess, pastedGame, SkipGame } from '../renderer/js/normalize.js';
import { fmtEval, reviewMoves, sideSummary } from '../renderer/js/review.js';
import { byColor, byRatingBand, overall, playerView, ratingByMonth } from '../renderer/js/stats.js';
import { labels, playerMoves, summary } from '../renderer/js/analysis.js';
import { table } from '../renderer/js/text.js';

const FIX = new URL('../../tests/fixtures/', import.meta.url);
const fixture = name => fs.readFileSync(new URL(name, FIX), 'utf8');
const lichessRaw = i => JSON.parse(fixture('lichess_games.ndjson').split('\n')[i]);
const chesscomRaw = () => JSON.parse(fixture('chesscom_2026_09.json')).games;

const BUNDLED = new URL(`../stockfish/stockfish${process.platform === 'win32' ? '.exe' : ''}`, import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const STOCKFISH = [BUNDLED, '/usr/games/stockfish', '/opt/homebrew/bin/stockfish', '/usr/local/bin/stockfish', '/usr/bin/stockfish'].find(p => fs.existsSync(p));

function nativeTransport() {
  const proc = spawn(STOCKFISH);
  let listener = () => {};
  proc.stdout.setEncoding('utf8');
  let buf = '';
  proc.stdout.on('data', d => {
    buf += d;
    const lines = buf.split('\n');
    buf = lines.pop();
    for (const l of lines) listener(l.trim());
  });
  return { send: c => proc.stdin.write(`${c}\n`), onLine: cb => { listener = cb; }, close: () => proc.kill() };
}

test('labels and phases match the Python thresholds', () => {
  assert.deepEqual([0, 49, 50, 100, 299, 300].map(label), ['ok', 'ok', 'inaccuracy', 'mistake', 'mistake', 'blunder']);
  assert.equal(phase(60, 'r3k3/pp3ppp/2b5/8/8/8/PP3PPP/R3KB2 w - - 0 30'), 'endgame');
  assert.equal(phase(60, 'r3k3/pp3ppp/8/8/8/8/PP3PPP/RR2K1Q1 w - - 0 30'), 'middlegame');
});

test('normalizes a Chess.com game', () => {
  const g = normalizeChesscom(chesscomRaw()[0]);
  assert.equal(g.platform, 'chesscom');
  assert.equal(g.moves.length, 7);
  assert.equal(g.moves.at(-1).san, 'Qxf7#');
  assert.equal(g.moves[0].clock, 598.1);
  assert.equal(g.timeClass, 'rapid');
  assert.equal(g.opening, 'Bishops Opening');
  assert.match(g.playedAt, /^2026-09-03T18:20:05/);
});

test('normalizes a Lichess game with its evals', () => {
  const g = normalizeLichess(lichessRaw(0));
  assert.equal(g.key, 'lichess:AbCdEfGh');
  assert.deepEqual(g.lichessEvals[9], [-350, null]);
  assert.deepEqual(g.lichessEvals[10], [-1000, -6]);
  assert.equal(g.moves[0].clock, 600);
  assert.throws(() => normalizeLichess(lichessRaw(2)), SkipGame); // chess960
});

test('stats from the player side', () => {
  const games = [normalizeLichess(lichessRaw(0)), normalizeLichess(lichessRaw(1))];
  const view = playerView(games, 'ajtest', 'rapid');
  assert.deepEqual(view.map(r => r.color), ['white', 'black']);
  assert.equal(overall(view).losses, 2);
  assert.equal(byColor(view)[0].name, 'white');
  assert.equal(byRatingBand(view)[0].name, 'within 100');
  assert.equal(ratingByMonth(view)[0].name, '2026-10');
  assert.equal(table(byColor(view), [['name', 'color']], [['games', 'games'], ['scorePct', 'score', 'pct']]),
    'color  games  score\n-----  -----  -----\nwhite      1     0%\nblack      1     0%');
});

test('Lichess analysis is reused and labelled', () => {
  const g = normalizeLichess(lichessRaw(0));
  assert.ok(lichessEvalsComplete(g));
  g.analysis = { source: 'lichess', depth: null };
  const byPly = Object.fromEntries(labels(g).map(l => [l.ply, l.label]));
  assert.equal(byPly[9], 'blunder');
  const s = summary(playerMoves([g], 'AjTest'));
  assert.equal(s.games, 1);
  assert.equal(s.blundersPerGame, 1);
});

test('review labels best moves and counts per side', () => {
  const g = pastedGame('1. e4 e5 2. Nf3 *');
  const evals = { 0: [30, null, 'e2e4'], 1: [30, null, 'e7e5'], 2: [30, null, 'b1c3'], 3: [-200, null, null] };
  const r = reviewMoves(g.moves, evals);
  assert.deepEqual(r.map(x => x.label), ['best', 'best', 'mistake']);
  assert.equal(r[2].bestSan, 'Nc3');
  assert.equal(sideSummary(r).white.mistake, 1);
  assert.equal(fmtEval(-1000, -6), '-M6');
  assert.equal(pastedGame('1. e4 e5 *').white, 'White');
});

test('parses game links', () => {
  assert.deepEqual(parseLink('https://www.chess.com/game/live/123456789'), ['chesscom', '123456789']);
  assert.deepEqual(parseLink('https://lichess.org/AbCdEfGhIjKl'), ['lichess', 'AbCdEfGh']);
  assert.equal(parseLink('1. e4 e5'), null);
});

test('UCI search output is turned to White POV', () => {
  const lines = ['info depth 10 score cp 35 nodes 1 pv e7e5 g1f3', 'info depth 11 score cp 20 lowerbound', 'bestmove e7e5 ponder g1f3'];
  assert.deepEqual(parseSearch(lines, false), { cp: -35, mate: null, best: 'e7e5' });
  assert.deepEqual(parseSearch(['info depth 5 score mate 2 pv d8h4', 'bestmove d8h4'], false), { cp: -1000, mate: -2, best: 'd8h4' });
});

const json = body => ({ status: 200, ok: true, json: async () => body, text: async () => JSON.stringify(body) });

test('Chess.com download keeps only months and games inside the date range', async () => {
  assert.deepEqual(archivesInRange(['x/games/2026/08', 'x/games/2026/09', 'x/games/2026/10'], '2026-09-01', '2026-09-30'), ['x/games/2026/09']);
  const calls = [];
  const fetchImpl = async url => {
    calls.push(url);
    if (url.endsWith('/archives')) return json({ archives: ['https://api.chess.com/pub/player/ajtest/games/2026/08', 'https://api.chess.com/pub/player/ajtest/games/2026/09'] });
    return json(JSON.parse(fixture('chesscom_2026_09.json')));
  };
  const got = [];
  const counts = await fetchChesscom('AjTest', { from: '2026-09-01', to: '2026-09-04', fetchImpl, onGame: g => got.push(g) });
  assert.equal(calls.length, 2); // archive list + September only
  assert.ok(got.length >= 1 && got.every(g => g.playedAt < '2026-09-05'));
  assert.equal(counts.seen, counts.kept + counts.skipped);
});

test('Lichess download sends the date range', async () => {
  const p = lichessParams('2026-10-01', '2026-10-31', 'rapid');
  assert.equal(p.get('since'), String(Date.parse('2026-10-01T00:00:00Z')));
  assert.equal(p.get('until'), String(Date.parse('2026-10-31T23:59:59.999Z')));
  const body = fixture('lichess_games.ndjson');
  const fetchImpl = async () => ({ status: 200, ok: true, body: new Blob([body]).stream() });
  const got = [];
  const counts = await fetchLichess('AjTest', { from: '2026-10-01', to: '2026-10-31', fetchImpl, onGame: g => got.push(g) });
  assert.equal(counts.skipped, 1); // the chess960 game
  assert.equal(got.length, 2);
});

test('engine pass with a real Stockfish', { skip: !STOCKFISH && 'Stockfish not installed' }, async () => {
  const engine = await new Engine(nativeTransport()).init();
  try {
    const g = normalizeLichess(lichessRaw(0));
    const evals = await analysePositions(engine, g.moves, 8);
    assert.deepEqual(Object.keys(evals).map(Number), [8, 9, 10]);
    const r = reviewMoves(g.moves, evals);
    assert.equal(r[8].label, 'blunder'); // 5. Nxe5??
    // Fool's-mate pattern past the book: the final position is scored without the engine.
    const mate = pastedGame('1. f3 e5 2. a3 a6 3. b3 b6 4. c3 c6 5. g4 Qh4# 0-1');
    const ev = await analysePositions(engine, mate.moves, 8);
    assert.deepEqual(ev[10], [-1000, 0, null]);
  } finally {
    engine.close();
  }
});
