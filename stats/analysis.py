# stats/analysis.py
"""Summaries of the engine pass, counting only the player's own moves."""

from __future__ import annotations

import sqlite3

import pandas as pd

PLAYER_MOVES_SQL = """
SELECT
    l.game_id, l.ply, l.cp_loss, l.label, l.phase, l.accuracy
FROM move_labels l
JOIN games g ON g.id = l.game_id
WHERE g.platform = :platform
  AND (g.white = :user OR g.black = :user)
  AND (:time_class IS NULL OR g.time_class = :time_class)
  -- odd plies are White's moves
  AND ((l.ply % 2 = 1) = (g.white = :user))
"""


def player_moves(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None = "rapid") -> pd.DataFrame:
    return pd.read_sql_query(
        PLAYER_MOVES_SQL, conn, params={"platform": platform, "user": username, "time_class": time_class}
    )


def summary(moves: pd.DataFrame) -> dict:
    """Games analysed, average game accuracy, and mistakes per game."""
    if moves.empty:
        return {"games": 0}
    per_game = moves.groupby("game_id")
    counts = moves["label"].value_counts()
    n = per_game.ngroups
    return {
        "games": n,
        "accuracy": per_game["accuracy"].mean().mean(),
        "avg_cp_loss": moves["cp_loss"].mean(),
        "blunders_per_game": counts.get("blunder", 0) / n,
        "mistakes_per_game": counts.get("mistake", 0) / n,
        "inaccuracies_per_game": counts.get("inaccuracy", 0) / n,
    }


def game_accuracy(moves: pd.DataFrame) -> pd.Series:
    """Accuracy per game_id (mean of the player's per-move accuracy)."""
    return moves.groupby("game_id")["accuracy"].mean()
