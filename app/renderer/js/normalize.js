// Turn raw Chess.com / Lichess payloads (or a pasted PGN) into one game record.
// A port of fetch/normalize.py: both sites give a PGN, so moves, clocks and
// Lichess's evals are all read from the PGN.

import { Chess } from '../vendor/chess.js';
import { CP_CAP } from './classify.js';

export class SkipGame extends Error {}

const VALID_RESULTS = new Set(['1-0', '0-1', '1/2-1/2']);

// '600+5' -> [600, 5]. '600' -> [600, 0]. Daily ('1/259200') or '-' -> [null, null].
export function parseTimeControl(tc) {
  if (!tc || tc.includes('/') || tc === '-') return [null, null];
  const [base, inc = '0'] = tc.split('+');
  const b = parseInt(base, 10), i = parseInt(inc, 10);
  return Number.isNaN(b) || Number.isNaN(i) ? [null, null] : [b, i];
}

// Lichess's rule: estimated duration = base + 40 * increment.
export function timeClassFromSeconds(base, inc) {
  if (base == null) return null;
  const total = base + 40 * (inc || 0);
  if (total < 180) return 'bullet';
  if (total < 480) return 'blitz';
  if (total < 1500) return 'rapid';
  return 'classical';
}

function parseClock(comment) {
  const m = /\[%clk (\d+):(\d+):(\d+(?:\.\d+)?)\]/.exec(comment || '');
  return m ? +m[1] * 3600 + +m[2] * 60 + parseFloat(m[3]) : null;
}

// -> [eval_cp, mate_in] from White's point of view, or null.
function parseEval(comment) {
  const m = /\[%eval (#?)(-?[\d.]+)/.exec(comment || '');
  if (!m) return null;
  if (m[1]) {
    const mate = parseInt(m[2], 10);
    return [mate >= 0 ? CP_CAP : -CP_CAP, mate];
  }
  const cp = Math.round(parseFloat(m[2]) * 100);
  return [Math.max(-CP_CAP, Math.min(CP_CAP, cp)), null];
}

// Reads a PGN's main line: headers, moves (with clocks) and any [%eval] comments.
export function readPgn(text) {
  const chess = new Chess();
  try {
    chess.loadPgn(text.trim());
  } catch (e) {
    throw new SkipGame(`unreadable PGN: ${e.message}`);
  }
  const headers = chess.getHeaders();
  if (headers.SetUp === '1' || (headers.FEN && !headers.FEN.startsWith('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w'))) {
    throw new SkipGame('not from the standard starting position');
  }
  const comments = new Map(chess.getComments().map(c => [c.fen, c.comment]));
  const moves = [], evals = {};
  chess.history({ verbose: true }).forEach((m, i) => {
    const ply = i + 1, comment = comments.get(m.after);
    moves.push({ ply, san: m.san, uci: m.lan, fenBefore: m.before, clock: parseClock(comment) });
    const ev = parseEval(comment);
    if (ev) evals[ply] = ev;
  });
  return { headers, moves, evals };
}

function playedAt(headers, fallbackEpochS) {
  const date = headers.UTCDate, time = headers.UTCTime;
  if (date && time && !date.includes('?')) return `${date.replaceAll('.', '-')}T${time}Z`;
  if (fallbackEpochS != null) return new Date(fallbackEpochS * 1000).toISOString().replace('.000Z', 'Z');
  throw new SkipGame('no game date');
}

const intOrNull = v => (v == null || v === '' || Number.isNaN(parseInt(v, 10)) ? null : parseInt(v, 10));

// 'https://www.chess.com/openings/Sicilian-Defense-Open-2...Nc6' -> 'Sicilian Defense Open'
export function chesscomOpeningName(ecoUrl) {
  if (!ecoUrl) return null;
  const slug = ecoUrl.replace(/\/+$/, '').split('/').pop();
  const words = [];
  for (const w of slug.split('-')) {
    if (/^\d/.test(w)) break;
    words.push(w);
  }
  return words.join(' ') || null;
}

function record(fields, moves, evals) {
  return { key: `${fields.platform}:${fields.gameId}`, ...fields, moves, lichessEvals: evals };
}

export function normalizeChesscom(raw) {
  if ((raw.rules || 'chess') !== 'chess') throw new SkipGame(`variant ${raw.rules}`);
  if (!raw.pgn) throw new SkipGame('no PGN');
  const { headers, moves } = readPgn(raw.pgn);
  const result = headers.Result || '*';
  if (!VALID_RESULTS.has(result)) throw new SkipGame(`result ${result}`);
  const url = raw.url || null;
  const gameId = (url ? url.replace(/\/+$/, '').split('/').pop() : null) || raw.uuid;
  if (!gameId) throw new SkipGame('no game id');
  const tc = raw.time_control || headers.TimeControl || null;
  const [base, inc] = parseTimeControl(tc);
  const white = raw.white || {}, black = raw.black || {};
  return record({
    platform: 'chesscom', gameId: String(gameId), url,
    white: white.username || headers.White, black: black.username || headers.Black,
    whiteElo: intOrNull(white.rating ?? headers.WhiteElo), blackElo: intOrNull(black.rating ?? headers.BlackElo),
    result, termination: headers.Termination || null, rated: raw.rated ?? null,
    timeControl: tc, timeClass: raw.time_class || timeClassFromSeconds(base, inc),
    baseSeconds: base, incrementSeconds: inc, eco: headers.ECO || null,
    opening: chesscomOpeningName(raw.eco || headers.ECOUrl),
    playedAt: playedAt(headers, raw.end_time),
  }, moves, {}); // Chess.com PGNs carry no evals
}

export function normalizeLichess(raw) {
  if ((raw.variant || 'standard') !== 'standard') throw new SkipGame(`variant ${raw.variant}`);
  if (!raw.pgn) throw new SkipGame('no PGN');
  const { headers, moves, evals } = readPgn(raw.pgn);
  const result = headers.Result || '*';
  if (!VALID_RESULTS.has(result)) throw new SkipGame(`result ${result}`);
  const clock = raw.clock || {};
  let base = clock.initial ?? null, inc = clock.increment ?? null;
  if (base == null) [base, inc] = parseTimeControl(headers.TimeControl);
  const players = raw.players || {};
  const name = color => players[color]?.user?.name || headers[color[0].toUpperCase() + color.slice(1)] || '?';
  return record({
    platform: 'lichess', gameId: raw.id, url: `https://lichess.org/${raw.id}`,
    white: name('white'), black: name('black'),
    whiteElo: intOrNull(players.white?.rating ?? headers.WhiteElo), blackElo: intOrNull(players.black?.rating ?? headers.BlackElo),
    result, termination: raw.status || headers.Termination || null, rated: raw.rated ?? null,
    timeControl: base != null ? `${base}+${inc}` : headers.TimeControl || null,
    timeClass: raw.speed || timeClassFromSeconds(base, inc),
    baseSeconds: base, incrementSeconds: inc,
    eco: raw.opening?.eco || headers.ECO || null, opening: raw.opening?.name || headers.Opening || null,
    playedAt: playedAt(headers, raw.createdAt ? raw.createdAt / 1000 : null),
  }, moves, evals);
}

// A pasted PGN, for the review page. Not stored.
export function pastedGame(text) {
  const { headers, moves } = readPgn(text);
  if (!moves.length) throw new SkipGame('no moves');
  const name = c => (headers[c] && headers[c] !== '?' ? headers[c] : c);
  const date = headers.UTCDate || headers.Date;
  return {
    key: null, platform: null, white: name('White'), black: name('Black'), result: headers.Result || '*',
    url: headers.Link || (headers.Site?.startsWith('http') ? headers.Site : null),
    playedAt: date && !date.includes('?') ? date.replaceAll('.', '-') : null, moves, lichessEvals: {},
  };
}
