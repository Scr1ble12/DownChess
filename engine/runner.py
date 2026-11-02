# engine/runner.py
"""Batch Stockfish analysis.

- One Stockfish process per worker, 1 thread each, one worker per CPU core.
  Many single-threaded engines on separate games beat one multi-threaded
  engine at shallow depth, because there is no thread coordination cost.
- Workers only compute. The main process does every SQLite write, since
  SQLite allows one writer at a time.
- Results are committed after each game, so stopping (Ctrl+C) loses at most
  the games in flight. Rerunning skips games already analysed at this depth.
- Games that Lichess already analysed reuse those evals instead.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass

import chess
import chess.engine

from db import store
from engine.classify import CP_CAP, classify_game

BOOK_PLIES = 8  # first 8 plies are treated as opening theory and not evaluated
DEFAULT_DEPTH = 12


def find_stockfish() -> str:
    path = os.environ.get("STOCKFISH_PATH") or shutil.which("stockfish")
    for candidate in (path, "/opt/homebrew/bin/stockfish", "/usr/local/bin/stockfish", "/usr/games/stockfish"):
        if candidate and os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        "Stockfish not found. Install it (macOS: brew install stockfish) "
        "or set STOCKFISH_PATH to the binary."
    )


@dataclass
class Task:
    game_id: int
    ucis: list[str]
    depth: int


# --------------------------------------------------------------------------- #
# Worker side
# --------------------------------------------------------------------------- #

_engine: chess.engine.SimpleEngine | None = None


def _init_worker(stockfish_path: str) -> None:
    global _engine
    _engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    _engine.configure({"Threads": 1, "Hash": 64})


def _terminal_eval(board: chess.Board) -> tuple[int, int | None]:
    """Score a finished position without the engine. White POV."""
    if board.is_checkmate():
        return (-CP_CAP if board.turn == chess.WHITE else CP_CAP), 0
    return 0, None  # stalemate, insufficient material


def analyse_positions(engine, ucis: list[str], depth: int, progress=None) -> list[tuple[int, int, int | None, str | None]]:
    """Eval of the position after each ply from BOOK_PLIES to the end.
    Returns [(ply, eval_cp, mate_in, best_move_uci)], White POV.
    `progress(done, total)` is called after each position, if given."""
    board = chess.Board()
    results = []
    for ply in range(len(ucis) + 1):
        if progress and ply:
            progress(ply, len(ucis) + 1)
        if ply > 0:
            board.push_uci(ucis[ply - 1])
        if ply < BOOK_PLIES:
            continue
        if board.is_game_over():
            cp, mate = _terminal_eval(board)
            results.append((ply, cp, mate, None))
            continue
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        score = info["score"].white()
        cp = max(-CP_CAP, min(CP_CAP, score.score(mate_score=100_000)))
        best = info["pv"][0].uci() if info.get("pv") else None
        results.append((ply, cp, score.mate(), best))
    return results


def _work(task: Task):
    return task.game_id, task.depth, analyse_positions(_engine, task.ucis, task.depth)


# --------------------------------------------------------------------------- #
# Main process
# --------------------------------------------------------------------------- #


def pending_games(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None, limit: int, depth: int) -> list[int]:
    """The player's most recent `limit` games, minus those already analysed at >= depth."""
    rows = conn.execute(
        """
        SELECT g.id FROM games g
        WHERE g.platform = :platform AND (g.white = :user OR g.black = :user)
          AND (:tc IS NULL OR g.time_class = :tc)
        ORDER BY g.played_at DESC LIMIT :limit
        """,
        {"platform": platform, "user": username, "tc": time_class, "limit": limit},
    ).fetchall()
    done = {
        r[0] for r in conn.execute(
            "SELECT game_id FROM analysed_games WHERE source = 'lichess' OR depth >= ?", (depth,)
        )
    }
    return [r[0] for r in rows if r[0] not in done]


def lichess_evals_complete(conn: sqlite3.Connection, game_id: int) -> bool:
    """True when Lichess's own analysis covers every move after the book plies."""
    n_moves = conn.execute("SELECT COUNT(*) FROM moves WHERE game_id = ?", (game_id,)).fetchone()[0]
    have = conn.execute(
        "SELECT COUNT(*) FROM evals WHERE game_id = ? AND source = 'lichess' AND ply >= ?",
        (game_id, BOOK_PLIES),
    ).fetchone()[0]
    # Positions BOOK_PLIES..n_moves; Lichess often leaves the final one unscored.
    return n_moves > BOOK_PLIES and have >= n_moves - BOOK_PLIES


def mark_analysed(conn: sqlite3.Connection, game_id: int, source: str, depth: int | None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO analysed_games (game_id, source, depth, analysed_at) VALUES (?, ?, ?, ?)",
        (game_id, source, depth, store.now_iso()),
    )


def save_labels(conn: sqlite3.Connection, game_id: int, source: str) -> None:
    moves = conn.execute("SELECT ply, fen_before FROM moves WHERE game_id = ? ORDER BY ply", (game_id,)).fetchall()
    evals = dict(conn.execute("SELECT ply, eval_cp FROM evals WHERE game_id = ? AND source = ?", (game_id, source)))
    conn.execute("DELETE FROM move_labels WHERE game_id = ?", (game_id,))
    conn.executemany(
        "INSERT INTO move_labels (game_id, ply, cp_loss, label, phase, accuracy) VALUES (?, ?, ?, ?, ?, ?)",
        [(game_id, *row) for row in classify_game([(m[0], m[1]) for m in moves], evals)],
    )


def save_evals(conn: sqlite3.Connection, game_id: int, depth: int, results) -> None:
    conn.execute("DELETE FROM evals WHERE game_id = ? AND source = 'stockfish'", (game_id,))
    conn.executemany(
        "INSERT INTO evals (game_id, ply, eval_cp, mate_in, best_move_uci, depth, source) VALUES (?, ?, ?, ?, ?, ?, 'stockfish')",
        [(game_id, ply, cp, mate, best, depth) for ply, cp, mate, best in results],
    )


def analyze(conn: sqlite3.Connection, platform: str, username: str, *, time_class: str | None = "rapid",
            limit: int = 200, depth: int = DEFAULT_DEPTH, workers: int | None = None, log=print) -> dict:
    game_ids = pending_games(conn, platform, username, time_class, limit, depth)
    stats = {"lichess_reused": 0, "engine": 0}

    tasks = []
    for gid in game_ids:
        if platform == "lichess" and lichess_evals_complete(conn, gid):
            save_labels(conn, gid, "lichess")
            mark_analysed(conn, gid, "lichess", None)
            stats["lichess_reused"] += 1
        else:
            ucis = [r[0] for r in conn.execute("SELECT uci FROM moves WHERE game_id = ? ORDER BY ply", (gid,))]
            tasks.append(Task(gid, ucis, depth))
    conn.commit()
    if stats["lichess_reused"]:
        log(f"Reused Lichess's own analysis for {stats['lichess_reused']} games.")
    if not tasks:
        log("Nothing left to analyse.")
        return stats

    workers = workers or os.cpu_count() or 1
    path = find_stockfish()
    log(f"Analysing {len(tasks)} games at depth {depth} with {workers} Stockfish process(es)...")
    start = time.monotonic()
    with mp.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(path,)) as pool:
        for i, (gid, d, results) in enumerate(pool.imap_unordered(_work, tasks), start=1):
            save_evals(conn, gid, d, results)
            save_labels(conn, gid, "stockfish")
            mark_analysed(conn, gid, "stockfish", d)
            conn.commit()
            stats["engine"] += 1
            elapsed = time.monotonic() - start
            eta = elapsed / i * (len(tasks) - i)
            log(f"  {i}/{len(tasks)} games  ({elapsed:.0f}s elapsed, ~{eta:.0f}s left)")
    return stats
