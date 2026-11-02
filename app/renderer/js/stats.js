// Win/draw/loss breakdowns from the player's side. A port of stats/games.py and
// stats/results.py. Every table carries its game count.

import { myColor } from './analysis.js';

export function playerView(games, user, timeClass) {
  return games
    .filter(g => !timeClass || g.timeClass === timeClass)
    .map(g => {
      const color = myColor(g, user);
      const white = color === 'white';
      const score = g.result === '1/2-1/2' ? 0.5 : (g.result === '1-0') === white ? 1 : 0;
      return {
        game: g, color, opponent: white ? g.black : g.white,
        myElo: white ? g.whiteElo : g.blackElo, oppElo: white ? g.blackElo : g.whiteElo,
        score, outcome: score === 1 ? 'win' : score === 0.5 ? 'draw' : 'loss',
        playedAt: new Date(g.playedAt), opening: g.opening || g.eco || 'Unknown',
      };
    });
}

function wdl(rows) {
  const n = rows.length;
  return {
    games: n,
    wins: rows.filter(r => r.score === 1).length,
    draws: rows.filter(r => r.score === 0.5).length,
    losses: rows.filter(r => r.score === 0).length,
    scorePct: n ? (rows.reduce((a, r) => a + r.score, 0) / n) * 100 : null,
  };
}

function groupBy(rows, keyFn) {
  const out = new Map();
  for (const r of rows) {
    const k = keyFn(r);
    if (k == null) continue;
    (out.get(k) ?? out.set(k, []).get(k)).push(r);
  }
  return out;
}

export const overall = wdl;

export function byColor(rows) {
  const g = groupBy(rows, r => r.color);
  return ['white', 'black'].filter(c => g.has(c)).map(c => ({ name: c, ...wdl(g.get(c)) }));
}

export const RATING_BANDS = [
  [-Infinity, -200, '200+ lower'],
  [-200, -100, '100-199 lower'],
  [-100, 100, 'within 100'],
  [100, 200, '100-199 higher'],
  [200, Infinity, '200+ higher'],
];

export function byRatingBand(rows) {
  const g = groupBy(rows.filter(r => r.myElo != null && r.oppElo != null), r => {
    const d = r.oppElo - r.myElo;
    return RATING_BANDS.find(([lo, hi]) => d >= lo && d < hi)[2];
  });
  return RATING_BANDS.map(b => b[2]).filter(l => g.has(l)).map(l => ({ name: l, ...wdl(g.get(l)) }));
}

// Grouped by opening and color: playing an opening as White and facing it as Black are different problems.
export function byOpening(rows, minGames = 1) {
  const g = groupBy(rows, r => `${r.opening}\u0000${r.color}`);
  return [...g.entries()]
    .map(([k, rs]) => { const [opening, color] = k.split('\u0000'); return { opening, color, ...wdl(rs) }; })
    .filter(r => r.games >= minGames)
    .sort((a, b) => b.games - a.games || a.scorePct - b.scorePct);
}

// Rating at the end of each month, with that month's game count and score.
export function ratingByMonth(rows) {
  const g = groupBy(rows.filter(r => r.myElo != null), r => r.playedAt.toISOString().slice(0, 7));
  const months = [...g.keys()].sort();
  let prev = null;
  return months.map(month => {
    const rs = g.get(month).sort((a, b) => a.playedAt - b.playedAt);
    const rating = rs[rs.length - 1].myElo;
    const row = { name: month, rating, change: prev == null ? null : rating - prev, games: rs.length, scorePct: wdl(rs).scorePct };
    prev = rating;
    return row;
  });
}
