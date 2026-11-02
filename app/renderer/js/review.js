// Review one game move by move, like Chess.com's Game Review. A port of engine/review.py.
//
// Labels: book (inside the book window), best (the engine's move), good,
// inaccuracy, mistake, blunder. Thresholds are the ones in classify.js.

import { Chess } from '../vendor/chess.js';
import { BOOK_PLIES, classifyGame } from './classify.js';

export const LABELS = ['best', 'good', 'book', 'inaccuracy', 'mistake', 'blunder'];
export const ISSUES = ['inaccuracy', 'mistake', 'blunder'];
export const NAG = { inaccuracy: '?!', mistake: '?', blunder: '??' };

function sanOf(fen, uci) {
  try {
    return new Chess(fen).move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san;
  } catch {
    return null;
  }
}

// moves: [{ply, san, uci, fenBefore}], evals: {ply: [cp, mate, best]}
export function reviewMoves(moves, evals) {
  const plain = Object.fromEntries(Object.entries(evals).filter(([, e]) => e[0] != null).map(([p, e]) => [p, e[0]]));
  const classified = new Map(classifyGame(moves, plain).map(r => [r.ply, r]));
  return moves.map(m => {
    const after = evals[m.ply] || [null, null, null];
    const bestUci = evals[m.ply - 1]?.[2] || null;
    const row = classified.get(m.ply);
    let label = m.ply <= BOOK_PLIES ? 'book' : '', cpLoss = null, accuracy = null;
    if (row) {
      ({ cpLoss, accuracy } = row);
      label = bestUci === m.uci ? 'best' : row.label === 'ok' ? 'good' : row.label;
    }
    return {
      ply: m.ply, san: m.san, uci: m.uci, fenBefore: m.fenBefore, label, cpLoss, accuracy,
      evalCp: after[0], mateIn: after[1], bestUci, bestSan: bestUci ? sanOf(m.fenBefore, bestUci) : null,
      mover: m.ply % 2 === 1 ? 'white' : 'black',
    };
  });
}

// Per color: accuracy (mean per-move accuracy) and a count of each label.
export function sideSummary(reviews) {
  const out = {};
  for (const color of ['white', 'black']) {
    const mine = reviews.filter(r => r.mover === color);
    const accs = mine.map(r => r.accuracy).filter(a => a != null);
    out[color] = { accuracy: accs.length ? accs.reduce((a, b) => a + b, 0) / accs.length : null };
    for (const l of LABELS) out[color][l] = mine.filter(r => r.label === l).length;
  }
  return out;
}

export function fmtEval(cp, mate) {
  if (mate != null) return mate === 0 ? 'checkmate' : `${mate > 0 ? '+' : '-'}M${Math.abs(mate)}`;
  return cp == null ? '?' : `${cp >= 0 ? '+' : ''}${(cp / 100).toFixed(1)}`;
}

export const moveNo = ply => `${Math.floor((ply + 1) / 2)}${ply % 2 ? '.' : '...'}`;
