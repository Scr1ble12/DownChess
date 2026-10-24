# tests/test_engine.py
"""Engine pass end to end. Uses a real Stockfish when one is installed."""

import json
import shutil

import pytest

from db import store
from engine import runner
from fetch.normalize import normalize_chesscom, normalize_lichess
from stats import analysis
from tests.fakes import fixture

needs_stockfish = pytest.mark.skipif(
    not (shutil.which("stockfish") or shutil.os.path.exists("/usr/games/stockfish")),
    reason="Stockfish not installed",
)


def test_lichess_analysis_is_reused_without_engine():
    conn = store.connect(":memory:")
    raw = json.loads(fixture("lichess_games.ndjson").splitlines()[0])
    store.upsert_game(conn, normalize_lichess(raw))  # has evals on every ply
    result = runner.analyze(conn, "lichess", "AjTest", log=lambda *_: None)
    assert result == {"lichess_reused": 1, "engine": 0}
    labels = dict(conn.execute("SELECT ply, label FROM move_labels").fetchall())
    assert labels[9] == "blunder"  # 5. Nxe5?? went from -0.1 to -3.5
    assert labels[10] == "ok"


def test_old_database_gets_accuracy_column(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    old = sqlite3.connect(db)
    old.execute("CREATE TABLE move_labels (game_id INTEGER, ply INTEGER, cp_loss INTEGER, label TEXT, phase TEXT, PRIMARY KEY (game_id, ply))")
    old.close()
    conn = store.connect(db)
    assert "accuracy" in {r[1] for r in conn.execute("PRAGMA table_info(move_labels)")}


@needs_stockfish
def test_stockfish_pass_and_resume():
    conn = store.connect(":memory:")
    games = json.loads(fixture("chesscom_2026_09.json"))["games"]
    store.upsert_game(conn, normalize_chesscom(games[0]))  # 7-ply scholar's mate
    raw = json.loads(fixture("lichess_games.ndjson").splitlines()[1])
    lichess_game = normalize_lichess(raw)
    lichess_game.platform = "chesscom"  # pretend it has no Lichess evals
    lichess_game.platform_game_id = "x"
    store.upsert_game(conn, lichess_game)

    result = runner.analyze(conn, "chesscom", "AjTest", depth=8, workers=2, log=lambda *_: None)
    assert result["engine"] == 2
    # both games are shorter than the book window, but still count as done
    assert runner.pending_games(conn, "chesscom", "AjTest", "rapid", 200, 8) == []

    again = runner.analyze(conn, "chesscom", "AjTest", depth=8, log=lambda *_: None)
    assert again["engine"] == 0  # resumable: nothing redone
    deeper = runner.pending_games(conn, "chesscom", "AjTest", "rapid", 200, 10)
    assert len(deeper) == 2  # asking for more depth re-queues them


@needs_stockfish
def test_analyse_positions_after_book():
    import chess.engine

    engine = chess.engine.SimpleEngine.popen_uci(runner.find_stockfish())
    try:
        # Two Knights: 1.e4 e5 2.Nf3 Nc6 3.Bc4 Nf6 4.Ng5 d5 5.exd5 Na5
        ucis = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6", "f3g5", "d7d5", "e4d5", "c6a5"]
        results = runner.analyse_positions(engine, ucis, depth=8)
    finally:
        engine.quit()
    assert [r[0] for r in results] == [8, 9, 10]
    assert all(r[3] for r in results)  # a best move for each
    assert all(-300 < r[1] < 300 for r in results)  # a roughly balanced opening


@needs_stockfish
def test_analyse_scores_checkmate_without_engine():
    import chess.engine

    engine = chess.engine.SimpleEngine.popen_uci(runner.find_stockfish())
    try:
        # Fool's-mate pattern delayed past the book: 1.f3 e5 2.a3 a6 3.b3 b6 4.g4?? Qh4#  (plies 1-8 book)
        ucis = ["f2f3", "e7e5", "a2a3", "a7a6", "b2b3", "b7b6", "c2c3", "c7c6", "g2g4", "d8h4"]
        results = runner.analyse_positions(engine, ucis, depth=8)
    finally:
        engine.quit()
    last = results[-1]
    assert last[0] == 10 and last[1] == -1000 and last[2] == 0  # Black has mated White


def test_player_moves_only_counts_own_moves():
    conn = store.connect(":memory:")
    raw = json.loads(fixture("lichess_games.ndjson").splitlines()[0])
    store.upsert_game(conn, normalize_lichess(raw))
    runner.analyze(conn, "lichess", "AjTest", log=lambda *_: None)
    moves = analysis.player_moves(conn, "lichess", "AjTest")  # AjTest is White
    assert set(moves["ply"] % 2) == {1}
    s = analysis.summary(moves)
    assert s["games"] == 1 and s["blunders_per_game"] == 1
