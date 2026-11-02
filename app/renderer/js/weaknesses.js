// The weakness report. A port of stats/weaknesses.py: each check compares you
// with a baseline from your own games, and the biggest relative shortfalls
// become the top 3.
//
// Severity is a relative shortfall, so checks on different scales can be ranked together:
//   "bad when higher" (a rate):  (value - baseline) / baseline
//   "bad when lower"  (a score): (baseline - value) / baseline

import { BLUNDER } from './classify.js';
import { gameEvals, mean } from './analysis.js';

export const MIN_SEVERITY = 0.10;
const TIME_TROUBLE_FRACTION = 0.10, TIME_TROUBLE_SECONDS = 120; // rapid: under 10% or under 2 minutes
const WINNING = 300; // "+3" in centipawns
const TILT_GAP_HOURS = 2;
const EXAMPLES = 3;

const rel = (value, baseline, higherIsWorse) => (baseline <= 0 ? 0 : (higherIsWorse ? value - baseline : baseline - value) / baseline);

function finding(f) {
  return { minOk: true, examples: [], ...f, get flagged() { return this.minOk && this.severity >= MIN_SEVERITY; } };
}

// The single worst move from each of the n games where it was worst. -> [{game, ply}]
function worstMoves(moves, n = EXAMPLES) {
  const seen = new Set(), out = [];
  for (const m of [...moves].sort((a, b) => b.cpLoss - a.cpLoss)) {
    if (seen.has(m.game.key)) continue;
    seen.add(m.game.key);
    out.push({ game: m.game, ply: m.ply });
    if (out.length === n) break;
  }
  return out;
}

const worstInGames = (moves, keys) => worstMoves(moves.filter(m => keys.has(m.game.key)));
const unique = xs => new Set(xs).size;

// One row per analysed game, oldest first.
function analysedGames(moves) {
  const byKey = new Map();
  for (const m of moves) {
    if (byKey.has(m.game.key)) continue;
    const g = m.game, white = m.color === 'white';
    const score = g.result === '1/2-1/2' ? 0.5 : (g.result === '1-0') === white ? 1 : 0;
    byKey.set(g.key, { key: g.key, game: g, color: m.color, score, playedAt: new Date(g.playedAt), opening: g.opening || g.eco || 'Unknown' });
  }
  return [...byKey.values()].sort((a, b) => a.playedAt - b.playedAt);
}

export function phaseWeakness(moves, minMoves = 100) {
  const phases = ['opening', 'middlegame', 'endgame']
    .map(p => ({ p, ms: moves.filter(m => m.phase === p) }))
    .filter(x => x.ms.length >= minMoves);
  if (phases.length < 2) return null;
  const worst = phases.reduce((a, b) => (mean(b.ms.map(m => m.cpLoss)) > mean(a.ms.map(m => m.cpLoss)) ? b : a));
  const others = phases.filter(x => x !== worst).flatMap(x => x.ms);
  const value = mean(worst.ms.map(m => m.cpLoss)), baseline = mean(others.map(m => m.cpLoss));
  return finding({
    key: 'phase', title: `${worst.p[0].toUpperCase()}${worst.p.slice(1)} play`, value, baseline, unit: 'cp',
    detail: `You lose ${value.toFixed(0)} centipawns per move in the ${worst.p}, vs ${baseline.toFixed(0)} in the rest of the game.`,
    sample: `${worst.ms.length} ${worst.p} moves in ${unique(worst.ms.map(m => m.game.key))} games`,
    severity: rel(value, baseline, true), examples: worstMoves(worst.ms),
  });
}

export function weakOpenings(moves, minGames = 10) {
  const games = analysedGames(moves);
  const overall = mean(games.map(g => g.score));
  const groups = new Map();
  for (const g of games) {
    const k = `${g.opening}\u0000${g.color}`;
    (groups.get(k) ?? groups.set(k, []).get(k)).push(g);
  }
  const big = [...groups.entries()].filter(([, gs]) => gs.length >= minGames);
  if (!big.length || !overall) return null;
  const [k, these] = big.reduce((a, b) => (mean(b[1].map(g => g.score)) < mean(a[1].map(g => g.score)) ? b : a));
  const [opening, color] = k.split('\u0000');
  const score = mean(these.map(g => g.score));
  return finding({
    key: 'opening', title: `${opening} as ${color}`, value: score * 100, baseline: overall * 100, unit: 'pct',
    detail: `You score ${(score * 100).toFixed(0)}% in the ${opening} as ${color}, vs ${(overall * 100).toFixed(0)}% overall.`,
    sample: `${these.length} games`, severity: rel(score, overall, false),
    examples: worstInGames(moves, new Set(these.filter(g => g.score < 1).map(g => g.key))),
  });
}

export function timeTrouble(moves, minMoves = 30) {
  const clocked = moves.filter(m => m.clock != null && m.game.baseSeconds != null);
  if (!clocked.length) return null;
  // "under 10% OR under 2 minutes" means under whichever threshold is larger
  const isLow = m => m.clock < Math.max(m.game.baseSeconds * TIME_TROUBLE_FRACTION, TIME_TROUBLE_SECONDS);
  const low = clocked.filter(isLow), normal = clocked.filter(m => !isLow(m));
  if (!normal.length) return null;
  const rate = ms => (ms.length ? (ms.filter(m => m.cpLoss >= BLUNDER).length / ms.length) * 100 : 0);
  const value = rate(low), baseline = rate(normal);
  return finding({
    key: 'time', title: 'Time trouble', value, baseline, unit: 'pct',
    detail: `With under 2 minutes (or 10% of your time) left, ${value.toFixed(1)}% of your moves are blunders, vs ${baseline.toFixed(1)}% with more time.`,
    sample: `${low.length} low-clock moves in ${unique(low.map(m => m.game.key))} games`,
    severity: rel(value, baseline, true), examples: worstMoves(low.filter(m => m.cpLoss >= BLUNDER)),
    minOk: low.length >= minMoves,
  });
}

// How often you fail to win from +3, vs how often opponents fail to win from +3 against you.
export function thrownWins(moves, minGames = 10) {
  const games = analysedGames(moves);
  const myEvals = new Map();
  for (const g of games) {
    const sign = g.color === 'white' ? 1 : -1;
    const evals = Object.entries(gameEvals(g.game) || {}).filter(([, e]) => e[0] != null).map(([p, e]) => [+p, sign * e[0]]);
    if (evals.length) myEvals.set(g.key, evals);
  }
  const hadWin = games.filter(g => myEvals.has(g.key) && Math.max(...myEvals.get(g.key).map(e => e[1])) >= WINNING);
  const oppHadWin = games.filter(g => myEvals.has(g.key) && Math.min(...myEvals.get(g.key).map(e => e[1])) <= -WINNING);
  if (hadWin.length < minGames || oppHadWin.length < minGames) return null;
  const thrown = hadWin.filter(g => g.score < 1), saved = oppHadWin.filter(g => g.score > 0);
  const value = (thrown.length / hadWin.length) * 100, baseline = (saved.length / oppHadWin.length) * 100;

  // Key moment: your worst move after the peak eval.
  const examples = [];
  for (const g of thrown.slice(0, EXAMPLES)) {
    const mine = moves.filter(m => m.game.key === g.key);
    const peak = myEvals.get(g.key).reduce((a, b) => (b[1] > a[1] ? b : a))[0];
    const after = mine.filter(m => m.ply > peak);
    const pick = (after.length ? after : mine).sort((a, b) => b.cpLoss - a.cpLoss)[0];
    if (pick) examples.push({ game: g.game, ply: pick.ply });
  }
  return finding({
    key: 'thrown', title: 'Converting winning positions', value, baseline, unit: 'pct',
    detail: `You don't win ${value.toFixed(0)}% of games where you reach +3, while your opponents don't win ${baseline.toFixed(0)}% of games where they reach +3 against you.`,
    sample: `${hadWin.length} games where you reached +3`, severity: rel(value, baseline, true), examples,
  });
}

export function tilt(moves, minGames = 15) {
  const games = analysedGames(moves);
  const afterLoss = [], afterWin = [];
  for (let i = 1; i < games.length; i++) {
    if (games[i].playedAt - games[i - 1].playedAt > TILT_GAP_HOURS * 3600e3) continue;
    if (games[i - 1].score === 0) afterLoss.push(games[i]);
    if (games[i - 1].score === 1) afterWin.push(games[i]);
  }
  if (afterLoss.length < minGames || afterWin.length < minGames) return null;
  const value = mean(afterLoss.map(g => g.score)) * 100, baseline = mean(afterWin.map(g => g.score)) * 100;
  return finding({
    key: 'tilt', title: 'Playing on after a loss', value, baseline, unit: 'pct',
    detail: `In the next game after a loss (within ${TILT_GAP_HOURS} hours) you score ${value.toFixed(0)}%, vs ${baseline.toFixed(0)}% after a win.`,
    sample: `${afterLoss.length} games right after a loss`, severity: rel(value, baseline, false),
    examples: worstInGames(moves, new Set(afterLoss.filter(g => g.score === 0).map(g => g.key))),
  });
}

// Score vs the Elo-expected score, against higher- and lower-rated opponents. `view` is stats.playerView().
export function ratingGap(view, moves, minGames = 20) {
  const rated = view.filter(r => r.myElo != null && r.oppElo != null)
    .map(r => ({ ...r, expected: 1 / (1 + 10 ** ((r.oppElo - r.myElo) / 400)) }));
  const candidates = [['higher', rated.filter(r => r.oppElo > r.myElo + 50)], ['lower', rated.filter(r => r.oppElo < r.myElo - 50)]]
    .filter(([, part]) => part.length >= minGames)
    .map(([name, part]) => ({ name, part, actual: mean(part.map(r => r.score)), expected: mean(part.map(r => r.expected)) }));
  if (!candidates.length) return null;
  const c = candidates.reduce((a, b) => (rel(b.actual, b.expected, false) > rel(a.actual, a.expected, false) ? b : a));
  return finding({
    key: 'rating', title: `Against ${c.name}-rated opponents`, value: c.actual * 100, baseline: c.expected * 100, unit: 'pct',
    detail: `Against opponents rated more than 50 points ${c.name} than you, you score ${(c.actual * 100).toFixed(0)}%; the rating difference predicts ${(c.expected * 100).toFixed(0)}%.`,
    sample: `${c.part.length} games`, severity: rel(c.actual, c.expected, false),
    examples: worstInGames(moves, new Set(c.part.filter(r => r.score < 1).map(r => r.game.key))),
  });
}

export function allFindings(view, moves) {
  if (!moves.length) return [];
  return [phaseWeakness(moves), weakOpenings(moves), timeTrouble(moves), thrownWins(moves), tilt(moves), ratingGap(view, moves)]
    .filter(Boolean)
    .sort((a, b) => b.severity - a.severity);
}

export const top = (findings, n = 3) => findings.filter(f => f.flagged).slice(0, n);
