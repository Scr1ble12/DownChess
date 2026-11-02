# ui/board.py
"""Grayscale board images for the white-on-black page."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import chess
import chess.svg

COLORS = {
    "square light": "#d0d0d0",
    "square dark": "#7a7a7a",
    "square light lastmove": "#d0d0d0",
    "square dark lastmove": "#7a7a7a",
    "margin": "#000000",
    "coord": "#ffffff",
}
PLAYED_ARROW = "#000000cc"  # dark: the move you played
BEST_ARROW = "#ffffffcc"  # white: the engine's best move


@dataclass
class MomentView:
    svg: str
    caption: str
    url: str | None


def _fmt_eval(cp: int | None) -> str:
    return "?" if cp is None else f"{cp / 100:+.1f}"


def render_moment(conn: sqlite3.Connection, game_id: int, ply: int, size: int = 320) -> MomentView:
    """The position before move `ply`, from the mover's side, with the played
    move (dark arrow) and the engine's best move (white arrow)."""
    m = conn.execute(
        """SELECT m.san, m.uci, m.fen_before, l.cp_loss, l.label,
                  g.url, g.played_at, g.white, g.black, g.result
           FROM moves m
           JOIN games g ON g.id = m.game_id
           LEFT JOIN move_labels l ON l.game_id = m.game_id AND l.ply = m.ply
           WHERE m.game_id = ? AND m.ply = ?""",
        (game_id, ply),
    ).fetchone()
    source = conn.execute("SELECT source FROM analysed_games WHERE game_id = ?", (game_id,)).fetchone()
    source = source[0] if source else "stockfish"
    ev = dict(
        (r[0], (r[1], r[2]))
        for r in conn.execute(
            "SELECT ply, eval_cp, best_move_uci FROM evals WHERE game_id = ? AND source = ? AND ply IN (?, ?)",
            (game_id, source, ply - 1, ply),
        )
    )

    board = chess.Board(m["fen_before"])
    mover = board.turn
    played = chess.Move.from_uci(m["uci"])
    arrows = [chess.svg.Arrow(played.from_square, played.to_square, color=PLAYED_ARROW)]
    best_uci = ev.get(ply - 1, (None, None))[1]
    best_san = None
    if best_uci and best_uci != m["uci"]:
        best = chess.Move.from_uci(best_uci)
        if best in board.legal_moves:
            best_san = board.san(best)
            arrows.append(chess.svg.Arrow(best.from_square, best.to_square, color=BEST_ARROW))

    svg = chess.svg.board(board, orientation=mover, arrows=arrows, size=size, colors=COLORS, coordinates=True)

    sign = 1 if mover == chess.WHITE else -1
    before = ev.get(ply - 1, (None,))[0]
    after = ev.get(ply, (None,))[0]
    move_no = f"{(ply + 1) // 2}{'.' if mover == chess.WHITE else '...'}"
    lines = [
        f"{m['played_at'][:10]}  {m['white']} vs {m['black']}  {m['result']}",
        f"You played {move_no} {m['san']} ({m['label'] or 'unlabelled'}, -{m['cp_loss'] or 0} cp): "
        f"eval {_fmt_eval(None if before is None else sign * before)} -> {_fmt_eval(None if after is None else sign * after)}",
    ]
    if best_san:
        lines.append(f"Best was {best_san} (white arrow). Your move is the dark arrow.")
    return MomentView(svg=svg, caption="\n".join(lines), url=m["url"])


def render_position(board: chess.Board, played: chess.Move | None, best: chess.Move | None,
                    orientation: chess.Color, size: int = 400) -> str:
    """`board` after `played`; the played move as a dark arrow and the engine's
    choice in the position before as a white arrow, when they differ."""
    arrows = []
    if played:
        arrows.append(chess.svg.Arrow(played.from_square, played.to_square, color=PLAYED_ARROW))
    if best and best != played:
        arrows.append(chess.svg.Arrow(best.from_square, best.to_square, color=BEST_ARROW))
    return chess.svg.board(board, orientation=orientation, arrows=arrows, size=size, colors=COLORS, coordinates=True)
