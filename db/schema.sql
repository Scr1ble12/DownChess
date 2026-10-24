-- DownChess SQLite schema. Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS players (
    platform        TEXT NOT NULL,          -- 'chesscom' or 'lichess'
    username        TEXT NOT NULL COLLATE NOCASE,
    last_fetched_at TEXT,                   -- ISO 8601 UTC
    PRIMARY KEY (platform, username)
);

-- Chess.com serves history as monthly archives. We remember which ones we have
-- so a rerun only downloads the newest month(s).
CREATE TABLE IF NOT EXISTS fetched_archives (
    platform    TEXT NOT NULL,
    username    TEXT NOT NULL COLLATE NOCASE,
    archive     TEXT NOT NULL,              -- 'YYYY/MM'
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (platform, username, archive)
);

CREATE TABLE IF NOT EXISTS games (
    id                  INTEGER PRIMARY KEY,
    platform            TEXT NOT NULL,
    platform_game_id    TEXT NOT NULL,
    url                 TEXT,
    white               TEXT NOT NULL COLLATE NOCASE,
    black               TEXT NOT NULL COLLATE NOCASE,
    white_elo           INTEGER,
    black_elo           INTEGER,
    result              TEXT NOT NULL,      -- '1-0', '0-1', '1/2-1/2'
    termination         TEXT,
    rated               INTEGER,
    time_control        TEXT,               -- '600+5'
    time_class          TEXT,               -- 'bullet', 'blitz', 'rapid', 'classical', 'daily'
    base_seconds        INTEGER,
    increment_seconds   INTEGER,
    eco                 TEXT,
    opening_name        TEXT,
    played_at           TEXT NOT NULL,      -- ISO 8601 UTC, game start
    pgn                 TEXT NOT NULL,
    UNIQUE (platform, platform_game_id)
);

CREATE INDEX IF NOT EXISTS idx_games_white ON games (platform, white);
CREATE INDEX IF NOT EXISTS idx_games_black ON games (platform, black);
CREATE INDEX IF NOT EXISTS idx_games_played_at ON games (played_at);

CREATE TABLE IF NOT EXISTS moves (
    game_id             INTEGER NOT NULL REFERENCES games (id),
    ply                 INTEGER NOT NULL,   -- 1 = White's first move
    san                 TEXT NOT NULL,
    uci                 TEXT NOT NULL,
    fen_before          TEXT NOT NULL,
    clock_remaining_s   REAL,               -- mover's clock after the move
    PRIMARY KEY (game_id, ply)
);

-- Eval of the position AFTER `ply`, from White's point of view.
-- ply 0 is the starting position.
CREATE TABLE IF NOT EXISTS evals (
    game_id         INTEGER NOT NULL REFERENCES games (id),
    ply             INTEGER NOT NULL,
    eval_cp         INTEGER,
    mate_in         INTEGER,
    best_move_uci   TEXT,
    depth           INTEGER,                -- NULL for Lichess evals (depth unknown)
    source          TEXT NOT NULL,          -- 'stockfish' or 'lichess'
    PRIMARY KEY (game_id, ply, source)
);

CREATE TABLE IF NOT EXISTS move_labels (
    game_id INTEGER NOT NULL REFERENCES games (id),
    ply     INTEGER NOT NULL,
    cp_loss INTEGER,
    label   TEXT,                           -- 'ok', 'inaccuracy', 'mistake', 'blunder'
    phase   TEXT,                           -- 'opening', 'middlegame', 'endgame'
    PRIMARY KEY (game_id, ply)
);
