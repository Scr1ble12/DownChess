"""Review one game move by move, like Chess.com's Game Review, with local Stockfish.

A game comes from the database, a pasted PGN, or a game link. Stored games
are analysed and saved exactly as the batch pass would (so they also count
towards the stats); pasted games are analysed in memory.

Move labels: book (inside the book window), best (the engine's move),
good, inaccuracy, mistake, blunder. Thresholds are the ones in classify.py.
"""

from __future__ import annotations

import io
import os
import re
import sqlite3
from dataclasses import dataclass, field

import chess
import chess.engine
import chess.pgn

from engine import runner
from engine.classify import classify_game
from fetch import http
from fetch.normalize import Move, parse_pgn_moves

LABELS = ["best", "good", "inaccuracy", "mistake", "blunder", "book"]
NAG = {"inaccuracy": "?!", "mistake": "?", "blunder": "??"}

LICHESS_LINK = re.compile(r"lichess\.org/(?:game/export/)?([A-Za-z0-9]{8})(?:[A-Za-z0-9]{4})?(?:/(?:white|black))?/?(?:[?#].*)?$")
CHESSCOM_LINK = re.compile(r"chess\.com/(?:game/)?(?:live|daily|game)(?:/game)?/(\d+)")


@dataclass
class ReviewGame:
    white: str
    black: str
    result: str
    moves: list[Move]
    url: str | None = None
    played_at: str | None = None
    game_id: int | None = None  # set when the game is in the database
    headers: dict = field(default_factory=dict)

    @property
    def ucis(self) -> list[str]:
        return [m.uci for m in self.moves]


@dataclass
class MoveReview:
    ply: int
    san: str
    uci: str
    fen_before: str
    label: str  # one of LABELS, or "" when the move has no evals
    cp_loss: int | None
    accuracy: float | None
    eval_cp: int | None  # position after the move, White POV
    mate_in: int | None
    best_uci: str | None  # engine's move in the position before
    best_san: str | None

    @property
    def mover(self) -> str:
        return "white" if self.ply % 2 == 1 else "black"


# --------------------------------------------------------------------------- #
# Loading a game
# --------------------------------------------------------------------------- #


def parse_pgn(text: str) -> ReviewGame:
    game = chess.pgn.read_game(io.StringIO(text.strip()))
    if game is None or game.errors or not list(game.mainline_moves()):
        raise ValueError("Couldn't read that as a PGN. On Chess.com: Share > PGN > copy. On Lichess: Share & export > PGN.")
    if game.board().fen() != chess.STARTING_FEN:
        raise ValueError("Only games from the standard starting position can be reviewed.")
    moves, _ = parse_pgn_moves(game)
    h = game.headers
    date = h.get("UTCDate") or h.get("Date")
    def name(color: str) -> str:
        value = h.get(color, "")
        return color if value in ("", "?") else value

    return ReviewGame(
        white=name("White"), black=name("Black"), result=h.get("Result", "*"),
        moves=moves, url=h.get("Link") or (h.get("Site") if h.get("Site", "").startswith("http") else None),
        played_at=date.replace(".", "-") if date and "?" not in date else None, headers=dict(h),
    )


def stored_game(conn: sqlite3.Connection, game_id: int) -> ReviewGame:
    g = conn.execute("SELECT white, black, result, url, played_at FROM games WHERE id = ?", (game_id,)).fetchone()
    moves = [
        Move(r["ply"], r["san"], r["uci"], r["fen_before"], r["clock_remaining_s"])
        for r in conn.execute("SELECT * FROM moves WHERE game_id = ? ORDER BY ply", (game_id,))
    ]
    return ReviewGame(g["white"], g["black"], g["result"], moves, g["url"], g["played_at"], game_id)


def parse_link(text: str) -> tuple[str, str] | None:
    """A Chess.com or Lichess game link -> (platform, game id)."""
    text = text.strip()
    if m := CHESSCOM_LINK.search(text):
        return "chesscom", m.group(1)
    if m := LICHESS_LINK.search(text):
        return "lichess", m.group(1)
    return None


def find_stored(conn: sqlite3.Connection, platform: str, platform_game_id: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM games WHERE platform = ? AND platform_game_id = ?", (platform, platform_game_id)
    ).fetchone()
    return row[0] if row else None


def fetch_lichess_pgn(session, game_id: str) -> str:
    resp = http.get(session, f"https://lichess.org/game/export/{game_id}",
                    params={"clocks": "true", "evals": "false"}, headers={"Accept": "application/x-chess-pgn"})
    return resp.text


def load(conn: sqlite3.Connection, text: str, session=None) -> ReviewGame:
    """Whatever was pasted: a game link or a PGN."""
    link = parse_link(text) if "\n" not in text.strip() else None
    if link is None:
        return parse_pgn(text)
    platform, gid = link
    if (stored := find_stored(conn, platform, gid)) is not None:
        return stored_game(conn, stored)
    if platform == "chesscom":
        raise ValueError(
            "That Chess.com game isn't downloaded yet. Run  python cli.py fetch chesscom:<user>  "
            "for one of the players, or paste the PGN instead (on Chess.com: Share > PGN)."
        )
    try:
        return parse_pgn(fetch_lichess_pgn(session or http.make_session(), gid))
    except http.NotFound:
        raise ValueError(f"Lichess has no game {gid}.") from None


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #

Evals = dict[int, tuple[int, int | None, str | None]]  # ply -> (eval_cp, mate_in, best_move_uci)


def open_engine() -> chess.engine.SimpleEngine:
    """One engine using every core: a single game is faster this way."""
    engine = chess.engine.SimpleEngine.popen_uci(runner.find_stockfish())
    engine.configure({"Threads": os.cpu_count() or 1, "Hash": 256})
    return engine


def analyse_moves(ucis: list[str], depth: int, progress=None) -> Evals:
    engine = open_engine()
    try:
        results = runner.analyse_positions(engine, ucis, depth, progress)
    finally:
        engine.quit()
    return {ply: (cp, mate, best) for ply, cp, mate, best in results}


def stored_evals(conn: sqlite3.Connection, game_id: int) -> tuple[Evals, int | None] | None:
    """(evals, depth) for a game the engine pass has finished, else None. depth is None for Lichess's own analysis."""
    row = conn.execute("SELECT source, depth FROM analysed_games WHERE game_id = ?", (game_id,)).fetchone()
    if row is None:
        return None
    evals = {
        r[0]: (r[1], r[2], r[3])
        for r in conn.execute(
            "SELECT ply, eval_cp, mate_in, best_move_uci FROM evals WHERE game_id = ? AND source = ?", (game_id, row[0])
        )
    }
    return evals, row[1]


def analyse_stored(conn: sqlite3.Connection, game_id: int, depth: int, progress=None) -> Evals:
    """Run Stockfish on one stored game and save it like the batch pass does."""
    ucis = [r[0] for r in conn.execute("SELECT uci FROM moves WHERE game_id = ? ORDER BY ply", (game_id,))]
    engine = open_engine()
    try:
        results = runner.analyse_positions(engine, ucis, depth, progress)
    finally:
        engine.quit()
    runner.save_evals(conn, game_id, depth, results)
    runner.save_labels(conn, game_id, "stockfish")
    runner.mark_analysed(conn, game_id, "stockfish", depth)
    conn.commit()
    return stored_evals(conn, game_id)[0]


def review_moves(moves: list[Move], evals: Evals) -> list[MoveReview]:
    plain = {ply: e[0] for ply, e in evals.items() if e[0] is not None}
    classified = {row[0]: row for row in classify_game([(m.ply, m.fen_before) for m in moves], plain)}
    out = []
    for m in moves:
        after = evals.get(m.ply, (None, None, None))
        best_uci = evals.get(m.ply - 1, (None, None, None))[2]
        best_san = None
        if best_uci:
            board = chess.Board(m.fen_before)
            best = chess.Move.from_uci(best_uci)
            best_san = board.san(best) if best in board.legal_moves else None
        row = classified.get(m.ply)
        if row is None:
            label, cp_loss, acc = ("book" if m.ply <= runner.BOOK_PLIES else ""), None, None
        else:
            _, cp_loss, base, _, acc = row
            label = "best" if best_uci == m.uci else ("good" if base == "ok" else base)
        out.append(MoveReview(m.ply, m.san, m.uci, m.fen_before, label, cp_loss, acc,
                              after[0], after[1], best_uci, best_san))
    return out


def side_summary(reviews: list[MoveReview]) -> dict[str, dict]:
    """Per color: accuracy (mean per-move accuracy) and a count of each label."""
    out = {}
    for color in ("white", "black"):
        mine = [r for r in reviews if r.mover == color]
        accs = [r.accuracy for r in mine if r.accuracy is not None]
        out[color] = {"accuracy": sum(accs) / len(accs) if accs else None,
                      **{label: sum(r.label == label for r in mine) for label in LABELS}}
    return out


def fmt_eval(cp: int | None, mate: int | None) -> str:
    if mate is not None:
        return "checkmate" if mate == 0 else f"{'+' if mate > 0 else '-'}M{abs(mate)}"
    return "?" if cp is None else f"{cp / 100:+.1f}"
