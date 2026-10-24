# stats/games.py
"""Load one player's games from their side of the board.

Every stats module starts here, so "my color", "my rating" and "my score"
are worked out once.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

PLAYER_GAMES_SQL = """
SELECT
    g.id,
    g.platform,
    g.url,
    g.played_at,
    g.time_class,
    g.time_control,
    g.eco,
    g.opening_name,
    g.result,
    CASE WHEN g.white = :user THEN 'white' ELSE 'black' END            AS color,
    CASE WHEN g.white = :user THEN g.black ELSE g.white END           AS opponent,
    CASE WHEN g.white = :user THEN g.white_elo ELSE g.black_elo END   AS my_elo,
    CASE WHEN g.white = :user THEN g.black_elo ELSE g.white_elo END   AS opp_elo,
    CASE
        WHEN g.result = '1/2-1/2' THEN 0.5
        WHEN (g.result = '1-0') = (g.white = :user) THEN 1.0
        ELSE 0.0
    END AS score
FROM games g
WHERE g.platform = :platform
  AND (g.white = :user OR g.black = :user)
  AND (:time_class IS NULL OR g.time_class = :time_class)
ORDER BY g.played_at
"""


def player_games(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None = "rapid") -> pd.DataFrame:
    df = pd.read_sql_query(
        PLAYER_GAMES_SQL,
        conn,
        params={"platform": platform, "user": username, "time_class": time_class},
    )
    df["played_at"] = pd.to_datetime(df["played_at"], utc=True, format="ISO8601")
    df["outcome"] = df["score"].map({1.0: "win", 0.5: "draw", 0.0: "loss"})
    return df


def stored_players(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute("SELECT platform, username FROM players ORDER BY last_fetched_at DESC")
    return [(r[0], r[1]) for r in rows]


def time_classes(conn: sqlite3.Connection, platform: str, username: str) -> list[str]:
    rows = conn.execute(
        """SELECT time_class, COUNT(*) FROM games
           WHERE platform = ? AND (white = ? OR black = ?) AND time_class IS NOT NULL
           GROUP BY time_class ORDER BY COUNT(*) DESC""",
        (platform, username, username),
    )
    return [r[0] for r in rows]
