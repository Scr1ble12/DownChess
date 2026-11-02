// The DownChess window: four pages, all buttons and plain text.

import { Chess } from '../vendor/chess.js';
import * as db from './db.js';
import { gameEvals, playerMoves, summary } from './analysis.js';
import { boardSvg } from './board.js';
import { analyseMany, analyseOne, DEFAULT_DEPTH, lichessEvalsComplete } from './engine.js';
import { fetchChesscom, fetchLichess, fetchLichessPgn, NotFound, parseLink } from './fetchers.js';
import { pastedGame, SkipGame } from './normalize.js';
import { fmtEval, ISSUES, moveNo, NAG, reviewMoves, sideSummary } from './review.js';
import { byColor, byOpening, byRatingBand, overall, playerView, ratingByMonth } from './stats.js';
import { allFindings, top } from './weaknesses.js';
import { winPercent } from './classify.js';
import { fmt, table } from './text.js';

const $ = id => document.getElementById(id);
const el = (tag, props = {}, ...children) => {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
};
const pre = text => el('pre', { textContent: text });
const h2 = text => el('h2', { textContent: text });
const svg = markup => el('div', { className: 'board', innerHTML: markup });

const state = { page: 'games', player: null, timeClass: 'rapid', games: [], review: null };

// --------------------------------------------------------------------------- //
// Player and time control
// --------------------------------------------------------------------------- //

async function refreshPlayers(select) {
  const players = await db.players();
  const sel = $('player');
  sel.replaceChildren(...players.map(p => el('option', { value: p.key, textContent: `${p.platform}:${p.username}` })));
  const key = select ?? state.player?.key ?? players[0]?.key;
  state.player = players.find(p => p.key === key) || players[0] || null;
  if (state.player) sel.value = state.player.key;
  await refreshGames();
}

async function refreshGames() {
  state.games = state.player ? await db.playerGames(state.player.platform, state.player.username) : [];
  const counts = {};
  for (const g of state.games) counts[g.timeClass || '?'] = (counts[g.timeClass || '?'] || 0) + 1;
  const classes = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
  const sel = $('time-class');
  sel.replaceChildren(...[...classes, 'all'].map(c => el('option', { value: c, textContent: c === 'all' ? `all (${state.games.length})` : `${c} (${counts[c]})` })));
  if (![...classes, 'all'].includes(state.timeClass)) state.timeClass = classes.includes('rapid') ? 'rapid' : classes[0] || 'all';
  sel.value = state.timeClass;
}

const filtered = () => state.games.filter(g => state.timeClass === 'all' || g.timeClass === state.timeClass);
const user = () => state.player?.username;

function showPage(page) {
  state.page = page;
  for (const b of document.querySelectorAll('nav button')) b.classList.toggle('active', b.dataset.page === page);
  for (const s of document.querySelectorAll('.page')) s.hidden = s.id !== `page-${page}`;
  $('filters').hidden = page === 'games' && !state.player;
  render();
}

function render() {
  if (state.page === 'games') renderStored();
  if (state.page === 'stats') renderStats();
  if (state.page === 'weaknesses') renderWeaknesses();
  if (state.page === 'review') renderReviewPicker();
}

const needPlayer = page => {
  if (state.player) return false;
  $(`page-${page}`).replaceChildren(pre('No games yet. Go to Games and download some first.'));
  return true;
};

// --------------------------------------------------------------------------- //
// Games page: download and analyse
// --------------------------------------------------------------------------- //

function setRange(months) {
  if (months === 'all') {
    $('dl-from').value = '';
    $('dl-to').value = '';
    return;
  }
  const to = new Date(), from = new Date();
  from.setMonth(from.getMonth() - Number(months));
  $('dl-from').value = from.toISOString().slice(0, 10);
  $('dl-to').value = to.toISOString().slice(0, 10);
}

function logger(id) {
  const box = $(id);
  return {
    clear() { box.textContent = ''; },
    line(text) { box.textContent += `${text}\n`; box.scrollTop = box.scrollHeight; },
    replaceLast(text) {
      const lines = box.textContent.split('\n');
      lines[lines.length - 2] = text;
      box.textContent = lines.join('\n');
    },
  };
}

let downloadAbort = null;

async function download() {
  const site = $('dl-site').value, username = $('dl-user').value.trim();
  const from = $('dl-from').value || null, to = $('dl-to').value || null;
  const speed = $('dl-speed').value || null;
  const log = logger('dl-log');
  log.clear();
  if (!username) return log.line('Type a username first.');
  if (from && to && from > to) return log.line('"From" is after "To".');
  downloadAbort = new AbortController();
  $('dl-go').disabled = true;
  $('dl-stop').disabled = false;
  let added = 0;
  log.line(`Downloading ${speed || 'all'} games for ${site}:${username}, ${from || 'the start'} to ${to || 'today'}...`);
  try {
    const fetcher = site === 'chesscom' ? fetchChesscom : fetchLichess;
    const counts = await fetcher(username, {
      from, to, speed, signal: downloadAbort.signal, log: log.line,
      onGame: async g => { if (await db.addGame(g)) added++; },
    });
    await db.touchPlayer(site, username, { from, to });
    log.line(`Done. ${counts.kept} games in range, ${added} new, ${counts.kept - added} already stored.`);
    await refreshPlayers(db.playerKey(site, username));
    $('filters').hidden = false;
  } catch (e) {
    log.line(e instanceof NotFound ? `${site === 'chesscom' ? 'Chess.com' : 'Lichess'} has no user named "${username}".` : `Stopped: ${e.message}`);
    if (added) await db.touchPlayer(site, username, { from, to }).then(() => refreshPlayers(db.playerKey(site, username)));
  } finally {
    $('dl-go').disabled = false;
    $('dl-stop').disabled = true;
    renderStored();
  }
}

let analyseAbort = null;

async function analyse() {
  const log = logger('an-log');
  log.clear();
  if (!state.player) return log.line('Download some games first.');
  const limit = Number($('an-games').value) || 200, depth = Number($('an-depth').value) || DEFAULT_DEPTH;
  const recent = [...filtered()].reverse().slice(0, limit);
  const pending = recent.filter(g => !(g.analysis && (g.analysis.source === 'lichess' || g.analysis.depth >= depth)));

  let reused = 0;
  for (const g of pending.filter(lichessEvalsComplete)) {
    await db.saveAnalysis(g.key, { source: 'lichess', depth: null });
    reused++;
  }
  if (reused) log.line(`Reused Lichess's own analysis for ${reused} games.`);
  const todo = pending.filter(g => !lichessEvalsComplete(g));
  if (!todo.length) {
    log.line(`Nothing left to analyse in the latest ${recent.length} ${state.timeClass} games.`);
    return refreshGames();
  }

  analyseAbort = new AbortController();
  $('an-go').disabled = true;
  $('an-stop').disabled = false;
  const start = performance.now();
  log.line(`Analysing ${todo.length} games at depth ${depth}...`);
  log.line('');
  try {
    await analyseMany(todo, {
      depth, signal: analyseAbort.signal,
      onDone: (g, analysis) => db.saveAnalysis(g.key, analysis),
      onProgress: (done, total) => {
        const elapsed = (performance.now() - start) / 1000, left = (elapsed / done) * (total - done);
        const bar = '#'.repeat(Math.round((done / total) * 30)).padEnd(30, '.');
        log.replaceLast(`[${bar}] ${done}/${total} games  (${elapsed.toFixed(0)}s elapsed, ~${left.toFixed(0)}s left)`);
      },
    });
    log.line(analyseAbort.signal.aborted ? 'Stopped. Finished games are saved; press Analyse to continue.' : 'Done.');
  } catch (e) {
    log.line(`Stopped: ${e.message}`);
  } finally {
    $('an-go').disabled = false;
    $('an-stop').disabled = true;
    await refreshGames();
    renderStored();
  }
}

async function renderStored() {
  const players = await db.players();
  if (!players.length) {
    $('stored').textContent = 'Nothing yet.';
    $('stored-actions').replaceChildren();
    return;
  }
  const rows = [];
  for (const p of players) {
    const games = await db.playerGames(p.platform, p.username);
    rows.push({
      name: `${p.platform}:${p.username}`, games: games.length, analysed: games.filter(g => g.analysis).length,
      first: games[0]?.playedAt.slice(0, 10) ?? '-', last: games.at(-1)?.playedAt.slice(0, 10) ?? '-',
    });
  }
  $('stored').textContent = table(rows, [['name', 'player']], [['games', 'games'], ['analysed', 'analysed'], ['first', 'first game'], ['last', 'last game']]);
  $('stored-actions').replaceChildren(...players.map(p => el('button', {
    textContent: `Delete ${p.platform}:${p.username}`,
    onclick: async () => {
      if (!confirm(`Delete every stored game for ${p.platform}:${p.username}?`)) return;
      await db.deletePlayer(p.platform, p.username);
      await refreshPlayers();
      renderStored();
    },
  })));
}

// --------------------------------------------------------------------------- //
// Stats page
// --------------------------------------------------------------------------- //

const WDL = [['games', 'games'], ['wins', 'W'], ['draws', 'D'], ['losses', 'L'], ['scorePct', 'score', 'pct']];

function renderStats() {
  const page = $('page-stats');
  if (needPlayer('stats')) return;
  const view = playerView(filtered(), user());
  if (!view.length) return page.replaceChildren(pre('No games for this time control.'));
  const o = overall(view);
  const lines = [
    `Record   ${o.wins}W ${o.draws}D ${o.losses}L   score ${fmt(o.scorePct, 'pct')}`,
    `Period   ${view[0].game.playedAt.slice(0, 10)} to ${view.at(-1).game.playedAt.slice(0, 10)}`,
  ];
  const a = summary(playerMoves(filtered(), user()));
  lines.push(a.games
    ? `Engine   ${a.games} of ${view.length} games analysed   accuracy ${a.accuracy.toFixed(1)}%\n` +
      `Per game ${a.blundersPerGame.toFixed(1)} blunders  ${a.mistakesPerGame.toFixed(1)} mistakes  ` +
      `${a.inaccuraciesPerGame.toFixed(1)} inaccuracies   (avg cp loss ${a.avgCpLoss.toFixed(0)})`
    : 'Engine   not run yet. Go to Games > Analyse with Stockfish.');

  const minGames = el('input', { type: 'number', min: 1, value: 3 });
  const openings = pre('');
  const drawOpenings = () => {
    const rows = byOpening(view, Number(minGames.value) || 1);
    openings.textContent = rows.length ? table(rows, [['opening', 'opening'], ['color', 'color']], WDL) : `No opening with ${minGames.value}+ games.`;
  };
  minGames.oninput = drawOpenings;
  drawOpenings();

  page.replaceChildren(
    pre(lines.join('\n')),
    h2('By color'), pre(table(byColor(view), [['name', 'color']], WDL)),
    h2('By opponent rating'), pre("Opponent's rating compared with yours at the time."),
    pre(table(byRatingBand(view), [['name', 'opponent']], WDL)),
    h2('By opening'), el('label', {}, 'Minimum games per opening ', minGames), openings,
    h2('Rating by month'),
    pre(table(ratingByMonth(view), [['name', 'month']], [['rating', 'rating'], ['change', 'change', 'signed'], ['games', 'games'], ['scorePct', 'score', 'pct']])),
  );
}

// --------------------------------------------------------------------------- //
// Weaknesses page
// --------------------------------------------------------------------------- //

const showValue = f => (f.unit === 'cp' ? `${f.value.toFixed(0)} cp` : f.value < 10 ? `${f.value.toFixed(1)}%` : fmt(f.value, 'pct'));
const showBaseline = f => (f.unit === 'cp' ? `${f.baseline.toFixed(0)} cp` : f.baseline < 10 ? `${f.baseline.toFixed(1)}%` : fmt(f.baseline, 'pct'));

function moment(game, ply) {
  const m = game.moves[ply - 1];
  const evals = gameEvals(game) || {};
  const mover = ply % 2 === 1 ? 'white' : 'black';
  const sign = mover === 'white' ? 1 : -1;
  const best = evals[ply - 1]?.[2] || null;
  const [r] = reviewMoves([m], { [ply - 1]: evals[ply - 1] || [null, null, best], [ply]: evals[ply] || [null, null, null] });
  const before = evals[ply - 1]?.[0], after = evals[ply]?.[0];
  const ev = v => (v == null ? '?' : fmtEval(sign * v, null));
  const lines = [
    `${game.playedAt.slice(0, 10)}  ${game.white} vs ${game.black}  ${game.result}`,
    `You played ${moveNo(ply)} ${m.san} (${r.label || 'unlabelled'}, -${r.cpLoss ?? 0} cp): eval ${ev(before)} -> ${ev(after)}`,
  ];
  if (r.bestSan && best !== m.uci) lines.push(`Best was ${r.bestSan} (white arrow). Your move is the dark arrow.`);
  return el('div', { className: 'example' },
    svg(boardSvg(m.fenBefore, { played: m.uci, best, orientation: mover, size: 320 })),
    pre(lines.join('\n')),
    el('div', { className: 'buttons' },
      el('button', { textContent: 'Review this game', onclick: () => openReview(game, ply) }),
      game.url ? el('a', { href: game.url, target: '_blank', textContent: 'Open on the site' }) : ''),
  );
}

function renderWeaknesses() {
  const page = $('page-weaknesses');
  if (needPlayer('weaknesses')) return;
  const moves = playerMoves(filtered(), user());
  const findings = allFindings(playerView(filtered(), user()), moves);
  if (!findings.length) return page.replaceChildren(pre('No engine analysis yet. Go to Games > Analyse with Stockfish.'));
  const out = [];
  const best = top(findings);
  if (!best.length) out.push(pre('Nothing stands out: no metric is 10% or more worse than its baseline.'));
  best.forEach((f, i) => {
    out.push(h2(`${i + 1}. ${f.title}`), pre(`${f.detail}\nBased on ${f.sample}.  ${(f.severity * 100).toFixed(0)}% worse than the baseline.`));
    for (const ex of f.examples) out.push(moment(ex.game, ex.ply));
    out.push(el('hr'));
  });
  out.push(h2('All checks'), pre('Every metric, ranked. Ones marked * have too few games to trust.'));
  out.push(pre(table(findings.map(f => ({
    metric: f.title + (f.minOk ? '' : ' *'), you: showValue(f), baseline: showBaseline(f),
    gap: `${f.severity >= 0 ? '+' : ''}${(f.severity * 100).toFixed(0)}%`, sample: f.sample,
  })), [['metric', 'metric']], [['you', 'you'], ['baseline', 'baseline'], ['gap', 'worse by'], ['sample', 'based on']])));
  page.replaceChildren(...out);
}

// --------------------------------------------------------------------------- //
// Game review page
// --------------------------------------------------------------------------- //

function renderReviewPicker() {
  const sel = $('rv-game');
  const games = [...filtered()].reverse();
  const current = sel.value;
  sel.replaceChildren(el('option', { value: '', textContent: games.length ? '-- pick one of your games --' : '-- no stored games --' }),
    ...games.map(g => {
      const v = playerView([g], user())[0];
      const elo = v.oppElo ? ` (${v.oppElo})` : '';
      return el('option', { value: g.key, textContent: `${g.playedAt.slice(0, 10)}  ${v.color.padEnd(5)}  vs ${v.opponent}${elo}  ${v.outcome}${g.analysis ? '' : '  (not analysed)'}` });
    }));
  if (games.some(g => g.key === current)) sel.value = current;
  if (!state.review) $('rv-body').replaceChildren(pre('Pick a game above, or paste one.'));
}

async function openReview(game, ply = 0) {
  showPage('review');
  if (game.key) $('rv-game').value = game.key;
  state.review = { game, ply, reviews: null, flip: false };
  await loadReview();
}

async function loadPasted() {
  const text = $('rv-paste').value.trim();
  const body = $('rv-body');
  if (!text) return;
  try {
    let game;
    const link = !text.includes('\n') && parseLink(text);
    if (link) {
      const stored = await db.getGame(`${link[0]}:${link[1]}`);
      if (stored) game = stored;
      else if (link[0] === 'chesscom') {
        return body.replaceChildren(pre("That Chess.com game isn't downloaded yet. Download that player's games on the Games page,\nor paste the PGN instead (on Chess.com: Share > PGN)."));
      } else game = pastedGame(await fetchLichessPgn(link[1]));
    } else game = pastedGame(text);
    state.review = { game, ply: 0, reviews: null, flip: false };
    await loadReview(true);
  } catch (e) {
    body.replaceChildren(pre(e instanceof SkipGame || e instanceof NotFound
      ? "Couldn't read that as a game. On Chess.com: Share > PGN > copy. On Lichess: paste the game link."
      : `Couldn't load that game: ${e.message}`));
  }
}

// Saved analysis when there is some (with a button to go deeper); otherwise an
// Analyse button for stored games and an immediate run for pasted ones.
async function loadReview(autorun = false) {
  const { game } = state.review;
  const body = $('rv-body');
  const depth = Number($('rv-depth').value) || 14;
  if (game.key && game.analysis && !state.review.deeper) return showReview(gameEvals(game));
  if (game.key && lichessEvalsComplete(game)) {
    await db.saveAnalysis(game.key, { source: 'lichess', depth: null });
    game.analysis = { source: 'lichess', depth: null };
    return showReview(gameEvals(game));
  }
  const status = pre(`${game.analysis ? `Analysed at depth ${game.analysis.depth}.` : 'Not analysed yet.'} ${game.moves.length} moves; this takes a few seconds.`);
  const go = el('button', { className: 'primary', textContent: `Analyse at depth ${depth}` });
  const progress = pre('');
  go.onclick = async () => {
    go.disabled = true;
    try {
      const evals = await analyseOne(game.moves, depth, (done, total) => {
        progress.textContent = `[${'#'.repeat(Math.round((done / total) * 30)).padEnd(30, '.')}] Stockfish: position ${done} of ${total}`;
      });
      state.review.deeper = false;
      if (game.key) {
        game.analysis = { source: 'stockfish', depth, evals };
        await db.saveAnalysis(game.key, game.analysis);
        await refreshGames();
      }
      showReview(evals);
    } catch (e) {
      progress.textContent = `Stockfish failed: ${e.message}`;
      go.disabled = false;
    }
  };
  body.replaceChildren(status, go, progress);
  if (autorun || !game.key) go.click();
}

function showReview(evals) {
  const r = state.review;
  r.reviews = reviewMoves(r.game.moves, evals);
  const me = (user() || '').toLowerCase();
  r.myColor = r.game.black.toLowerCase() === me ? 'black' : 'white';
  drawReview();
}

function drawReview() {
  const { game, reviews, myColor } = state.review;
  const n = reviews.length;
  const ply = state.review.ply = Math.max(0, Math.min(n, state.review.ply));
  const s = sideSummary(reviews);
  const acc = c => (s[c].accuracy == null ? '-' : s[c].accuracy.toFixed(1));
  const summaryRows = ['white', 'black'].map(c => ({ name: c === 'white' ? game.white : game.black, accuracy: acc(c), ...s[c] }));

  const go = p => { state.review.ply = p; drawReview(); };
  const nextError = () => {
    const nxt = reviews.find(x => x.ply > ply && ISSUES.includes(x.label) && x.mover === myColor);
    if (nxt) go(nxt.ply);
  };
  const slider = el('input', { type: 'range', min: 0, max: n, value: ply, oninput: e => go(Number(e.target.value)) });
  const orientation = (myColor === 'black') !== state.review.flip ? 'black' : 'white';

  let boardMarkup, caption;
  if (ply === 0) {
    boardMarkup = boardSvg('rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1', { orientation });
    caption = 'Starting position. Press Next or the right arrow key.';
  } else {
    const m = reviews[ply - 1];
    const after = ply < n ? reviews[ply].fenBefore : afterFen(m);
    boardMarkup = boardSvg(after, { played: m.uci, best: m.bestSan ? m.bestUci : null, orientation });
    let verdict = m.label || 'not analysed';
    if (m.cpLoss && m.label !== 'best') verdict += `, -${m.cpLoss} cp`;
    const white = m.evalCp == null ? 0 : Math.round((winPercent(m.evalCp) / 100) * 30);
    const lines = [`${moveNo(ply)} ${m.san}  ${verdict}`,
      `Eval ${fmtEval(m.evalCp, m.mateIn)}   ${m.evalCp == null ? '' : `White ${'█'.repeat(white)}${'░'.repeat(30 - white)} Black`}`];
    if (m.bestSan && m.bestUci !== m.uci) lines.push(`Best was ${m.bestSan} (white arrow). The move played is the dark arrow.`);
    else if (m.label === 'best') lines.push("That was the engine's move.");
    caption = lines.join('\n');
  }

  const issues = reviews.filter(x => ISSUES.includes(x.label));
  const moveList = [];
  for (let i = 0; i < n; i += 2) {
    const cell = x => (x ? `${(x.san + (NAG[x.label] || '')).padEnd(9)}${x.label.padEnd(10)} ${fmtEval(x.evalCp, x.mateIn).padStart(6)}` : '');
    moveList.push(`${String(i / 2 + 1).padStart(3)}. ${cell(reviews[i])}   ${cell(reviews[i + 1])}`.trimEnd());
  }

  $('rv-body').replaceChildren(
    pre(`${game.white} vs ${game.black}  ${game.result}${game.playedAt ? `  ${game.playedAt.slice(0, 10)}` : ''}`),
    game.url ? el('a', { href: game.url, target: '_blank', textContent: 'Open on the site' }) : '',
    deeperButton(game),
    pre(table(summaryRows, [['name', 'player']], [['accuracy', 'accuracy'], ['best', 'best'], ['good', 'good'], ['book', 'book'], ['inaccuracy', 'inaccuracy'], ['mistake', 'mistake'], ['blunder', 'blunder']])),
    el('div', { className: 'nav-row' },
      el('button', { textContent: 'Start', onclick: () => go(0) }),
      el('button', { textContent: 'Back', onclick: () => go(ply - 1) }),
      el('button', { textContent: 'Next', onclick: () => go(ply + 1) }),
      el('button', { textContent: 'End', onclick: () => go(n) }),
      el('button', { textContent: 'Next error', title: 'Jump to your next inaccuracy, mistake or blunder', onclick: nextError })),
    el('label', {}, `Move ${ply} of ${n}`, slider),
    el('label', {}, el('input', { type: 'checkbox', checked: state.review.flip, onchange: e => { state.review.flip = e.target.checked; drawReview(); } }), ' Flip board'),
    svg(boardMarkup),
    pre(caption),
    h2('Key moments'),
    pre(issues.length
      ? table(issues.map(x => ({ move: `${moveNo(x.ply)} ${x.san}${NAG[x.label]}`, who: x.mover === 'white' ? game.white : game.black, label: x.label, loss: `-${x.cpLoss} cp`, best: x.bestSan || '-' })),
        [['move', 'move']], [['who', 'player'], ['label', 'label'], ['loss', 'loss'], ['best', 'best']])
      : 'No inaccuracies, mistakes or blunders.'),
    el('div', { className: 'buttons' }, ...issues.map(x => el('button', { textContent: `${moveNo(x.ply)} ${x.san}`, onclick: () => go(x.ply) }))),
    h2('All moves'),
    pre(moveList.join('\n')),
  );
}

function deeperButton(game) {
  const depth = Number($('rv-depth').value) || 14;
  if (!game.key || !game.analysis || game.analysis.source !== 'stockfish' || game.analysis.depth >= depth) return '';
  return el('button', {
    textContent: `Analysed at depth ${game.analysis.depth}. Re-analyse at depth ${depth}`,
    onclick: () => { state.review.deeper = true; loadReview(true); },
  });
}

function afterFen(m) {
  // the final position: replay the last move on its "before" position
  const c = new Chess(m.fenBefore);
  c.move({ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), promotion: m.uci[4] });
  return c.fen();
}

// --------------------------------------------------------------------------- //
// Wiring
// --------------------------------------------------------------------------- //

async function main() {
  for (const b of document.querySelectorAll('nav button')) b.onclick = () => showPage(b.dataset.page);
  for (const b of document.querySelectorAll('[data-range]')) b.onclick = () => setRange(b.dataset.range);
  $('player').onchange = async e => { await refreshPlayers(e.target.value); state.review = null; render(); };
  $('time-class').onchange = e => { state.timeClass = e.target.value; render(); };
  $('dl-go').onclick = download;
  $('dl-stop').onclick = () => downloadAbort?.abort();
  $('an-go').onclick = analyse;
  $('an-stop').onclick = () => analyseAbort?.abort();
  $('rv-game').onchange = async e => {
    const game = state.games.find(g => g.key === e.target.value);
    if (game) await openReview(game);
  };
  $('rv-load').onclick = loadPasted;
  document.addEventListener('keydown', e => {
    if (state.page !== 'review' || !state.review?.reviews || /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) return;
    if (e.key === 'ArrowRight') { state.review.ply++; drawReview(); }
    if (e.key === 'ArrowLeft') { state.review.ply--; drawReview(); }
  });
  setRange(12);
  await refreshPlayers();
  if (state.player) $('dl-user').value = state.player.username;
  if (state.player) $('dl-site').value = state.player.platform;
  showPage('games');
}

main();
