# engine/classify.py
"""Turn per-position evals into per-move labels, phases and accuracy.

Conventions (all evals are stored from White's point of view):
- eval at ply p = the position after move p; ply 0 = the starting position.
- cp loss of move p = how much the mover's eval dropped from before to after
  the move. With a good engine eval of the position before, that equals
  "best move eval minus played move eval", which is what the handoff defines.
"""

from __future__ import annotations

import math

import chess

INACCURACY, MISTAKE, BLUNDER = 50, 100, 300
OPENING_MAX_PLY = 20
ENDGAME_MATERIAL = 13  # non-pawn material per side, in pawns (N=B=3, R=5, Q=9)
CP_CAP = 1000

PIECE_VALUES = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def label(cp_loss: int) -> str:
    if cp_loss >= BLUNDER:
        return "blunder"
    if cp_loss >= MISTAKE:
        return "mistake"
    if cp_loss >= INACCURACY:
        return "inaccuracy"
    return "ok"


def phase(ply: int, fen_before: str) -> str:
    if ply <= OPENING_MAX_PLY:
        return "opening"
    board = chess.Board(fen_before)
    for color in (chess.WHITE, chess.BLACK):
        material = sum(len(board.pieces(p, color)) * v for p, v in PIECE_VALUES.items())
        if material > ENDGAME_MATERIAL:
            return "middlegame"
    return "endgame"


def win_percent(cp: int) -> float:
    """Lichess's eval -> winning chances curve, 0-100 for the side the cp favors."""
    cp = max(-CP_CAP, min(CP_CAP, cp))
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)


def move_accuracy(win_before: float, win_after: float) -> float:
    """Lichess's per-move accuracy from the mover's drop in winning chances."""
    drop = max(0.0, win_before - win_after)
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * drop) - 3.1669))


def classify_game(moves: list[tuple[int, str]], evals: dict[int, int]) -> list[tuple[int, int, str, str, float]]:
    """moves: [(ply, fen_before)], evals: {ply: eval_cp, White POV}.

    Returns [(ply, cp_loss, label, phase, accuracy)] for every move whose
    before and after evals are both known. Book moves without evals are skipped.
    """
    out = []
    for ply, fen_before in moves:
        if ply - 1 not in evals or ply not in evals:
            continue
        sign = 1 if ply % 2 == 1 else -1  # odd plies are White's moves
        before, after = sign * evals[ply - 1], sign * evals[ply]
        cp_loss = max(0, before - after)
        acc = move_accuracy(win_percent(before), win_percent(after))
        out.append((ply, cp_loss, label(cp_loss), phase(ply, fen_before), round(acc, 1)))
    return out
