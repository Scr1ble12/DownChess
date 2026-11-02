// Per-move labels, game phase and accuracy. A port of engine/classify.py.
//
// All evals are from White's point of view. The eval at ply p is the position
// after move p; ply 0 is the starting position. The cp loss of move p is how
// much the mover's eval dropped across the move.

import { Chess } from '../vendor/chess.js';

export const INACCURACY = 50, MISTAKE = 100, BLUNDER = 300;
export const OPENING_MAX_PLY = 20;
export const ENDGAME_MATERIAL = 13; // non-pawn material per side, in pawns
export const CP_CAP = 1000;
export const BOOK_PLIES = 8; // first 8 plies count as opening theory and aren't evaluated

const PIECE_VALUES = { n: 3, b: 3, r: 5, q: 9 };

export function label(cpLoss) {
  if (cpLoss >= BLUNDER) return 'blunder';
  if (cpLoss >= MISTAKE) return 'mistake';
  if (cpLoss >= INACCURACY) return 'inaccuracy';
  return 'ok';
}

export function phase(ply, fenBefore) {
  if (ply <= OPENING_MAX_PLY) return 'opening';
  const material = { w: 0, b: 0 };
  for (const row of new Chess(fenBefore).board()) {
    for (const sq of row) if (sq) material[sq.color] += PIECE_VALUES[sq.type] || 0;
  }
  return material.w > ENDGAME_MATERIAL || material.b > ENDGAME_MATERIAL ? 'middlegame' : 'endgame';
}

export function winPercent(cp) {
  cp = Math.max(-CP_CAP, Math.min(CP_CAP, cp));
  return 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
}

export function moveAccuracy(winBefore, winAfter) {
  const drop = Math.max(0, winBefore - winAfter);
  return Math.max(0, Math.min(100, 103.1668 * Math.exp(-0.04354 * drop) - 3.1669));
}

// moves: [{ply, fenBefore}], evals: {ply: cp}. Returns one row per move whose
// before and after evals are both known.
export function classifyGame(moves, evals) {
  const out = [];
  for (const { ply, fenBefore } of moves) {
    if (evals[ply - 1] == null || evals[ply] == null) continue;
    const sign = ply % 2 === 1 ? 1 : -1; // odd plies are White's moves
    const before = sign * evals[ply - 1], after = sign * evals[ply];
    const cpLoss = Math.max(0, before - after);
    const accuracy = Math.round(moveAccuracy(winPercent(before), winPercent(after)) * 10) / 10;
    out.push({ ply, cpLoss, label: label(cpLoss), phase: phase(ply, fenBefore), accuracy });
  }
  return out;
}
