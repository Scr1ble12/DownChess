# db/store.py
"""SQLite access. Every write is an idempotent upsert keyed on
(platform, platform_game_id), so any fetch can be rerun safely."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fetch.normalize import Game

SCHEMA = Path(__file__).with_name("schema.sql")
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "downchess.db"


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA.read_text())
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring databases made by older versions up to the current schema."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(move_labels)")}
    if "accuracy" not in cols:  # added in Step 3
        conn.execute("ALTER TABLE move_labels ADD COLUMN accuracy REAL")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_game(conn: sqlite3.Connection, game: Game) -> bool:
    """Insert a game with its moves and any Lichess evals. Returns False if it was already stored."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO games (
            platform, platform_game_id, url, white, black, white_elo, black_elo,
            result, termination, rated, time_control, time_class, base_seconds,
            increment_seconds, eco, opening_name, played_at, pgn
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game.platform, game.platform_game_id, game.url, game.white, game.black,
            game.white_elo, game.black_elo, game.result, game.termination,
            None if game.rated is None else int(game.rated), game.time_control,
            game.time_class, game.base_seconds, game.increment_seconds, game.eco,
            game.opening_name, game.played_at, game.pgn,
        ),
    )
    if cur.rowcount == 0:
        return False
    game_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO moves (game_id, ply, san, uci, fen_before, clock_remaining_s) VALUES (?, ?, ?, ?, ?, ?)",
        [(game_id, m.ply, m.san, m.uci, m.fen_before, m.clock_remaining_s) for m in game.moves],
    )
    conn.executemany(
        "INSERT INTO evals (game_id, ply, eval_cp, mate_in, source) VALUES (?, ?, ?, ?, ?)",
        [(game_id, e.ply, e.eval_cp, e.mate_in, e.source) for e in game.evals],
    )
    return True


def touch_player(conn: sqlite3.Connection, platform: str, username: str) -> None:
    conn.execute(
        """
        INSERT INTO players (platform, username, last_fetched_at) VALUES (?, ?, ?)
        ON CONFLICT (platform, username) DO UPDATE SET last_fetched_at = excluded.last_fetched_at
        """,
        (platform, username, now_iso()),
    )


def latest_played_at(conn: sqlite3.Connection, platform: str, username: str) -> str | None:
    row = conn.execute(
        "SELECT MAX(played_at) FROM games WHERE platform = ? AND (white = ? OR black = ?)",
        (platform, username, username),
    ).fetchone()
    return row[0]


def fetched_archives(conn: sqlite3.Connection, platform: str, username: str) -> set[str]:
    rows = conn.execute(
        "SELECT archive FROM fetched_archives WHERE platform = ? AND username = ?",
        (platform, username),
    )
    return {r[0] for r in rows}


def mark_archive_fetched(conn: sqlite3.Connection, platform: str, username: str, archive: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO fetched_archives (platform, username, archive, fetched_at) VALUES (?, ?, ?, ?)",
        (platform, username, archive, now_iso()),
    )


def count_games(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM games WHERE platform = ? AND (white = ? OR black = ?)"
    args: list = [platform, username, username]
    if time_class:
        sql += " AND time_class = ?"
        args.append(time_class)
    return conn.execute(sql, args).fetchone()[0]
