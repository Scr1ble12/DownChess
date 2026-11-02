// Engine results per move, counted from the player's side. A port of stats/analysis.py.

import { classifyGame } from './classify.js';

// {ply: [cp, mate, best]} from whichever source analysed the game, or null.
export function gameEvals(game) {
  const a = game.analysis;
  if (!a) return null;
  if (a.source === 'lichess') {
    return Object.fromEntries(Object.entries(game.lichessEvals || {}).map(([p, [cp, mate]]) => [p, [cp, mate, null]]));
  }
  return a.evals;
}

export function labels(game) {
  const evals = gameEvals(game);
  if (!evals) return [];
  const plain = Object.fromEntries(Object.entries(evals).filter(([, e]) => e[0] != null).map(([p, e]) => [p, e[0]]));
  return classifyGame(game.moves, plain);
}

export const myColor = (game, user) => (game.white.toLowerCase() === user.toLowerCase() ? 'white' : 'black');

// One row per analysed move the player made.
export function playerMoves(games, user) {
  const rows = [];
  for (const game of games) {
    const color = myColor(game, user);
    for (const l of labels(game)) {
      if ((l.ply % 2 === 1) !== (color === 'white')) continue;
      const m = game.moves[l.ply - 1];
      rows.push({ ...l, game, color, san: m.san, uci: m.uci, fenBefore: m.fenBefore, clock: m.clock });
    }
  }
  return rows;
}

const mean = xs => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN);

export function summary(moves) {
  if (!moves.length) return { games: 0 };
  const byGame = new Map();
  for (const m of moves) (byGame.get(m.game.key) ?? byGame.set(m.game.key, []).get(m.game.key)).push(m);
  const n = byGame.size;
  const count = label => moves.filter(m => m.label === label).length;
  return {
    games: n,
    accuracy: mean([...byGame.values()].map(ms => mean(ms.map(m => m.accuracy)))),
    avgCpLoss: mean(moves.map(m => m.cpLoss)),
    blundersPerGame: count('blunder') / n,
    mistakesPerGame: count('mistake') / n,
    inaccuraciesPerGame: count('inaccuracy') / n,
  };
}

export { mean };
