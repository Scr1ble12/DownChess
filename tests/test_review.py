"""Single-game review: loading games, labelling moves, and the page."""

import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from db import store
from engine import review, runner
from fetch.normalize import normalize_chesscom, normalize_lichess
from tests.fakes import FakeResponse, FakeSession, fixture
from tests.test_engine import needs_stockfish

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def lichess_raw(i=0):
    return json.loads(fixture("lichess_games.ndjson").splitlines()[i])


@pytest.mark.parametrize("link,expected", [
    ("https://www.chess.com/game/live/123456789", ("chesscom", "123456789")),
    ("https://www.chess.com/live/game/123456789", ("chesscom", "123456789")),
    ("https://www.chess.com/game/daily/555?move=3", ("chesscom", "555")),
    ("https://lichess.org/AbCdEfGh", ("lichess", "AbCdEfGh")),
    ("https://lichess.org/AbCdEfGhIjKl", ("lichess", "AbCdEfGh")),
    ("lichess.org/AbCdEfGh/black#12", ("lichess", "AbCdEfGh")),
    ("1. e4 e5", None),
])
def test_parse_link(link, expected):
    assert review.parse_link(link) == expected


def test_parse_pgn():
    game = review.parse_pgn(fixture("sample.pgn"))
    assert (game.white, game.black, game.result) == ("AjTest", "opponent1", "1-0")
    assert [m.san for m in game.moves][-1] == "Qxf7#"
    assert game.played_at == "2026-09-03"
    bare = review.parse_pgn("1. e4 e5 2. Qh5 Nc6 3. Bc4 Nf6 4. Qxf7# 1-0")
    assert (bare.white, bare.black, bare.played_at) == ("White", "Black", None)
    with pytest.raises(ValueError, match="Couldn't read"):
        review.parse_pgn("not a game")


def test_load_links():
    conn = store.connect(":memory:")
    store.upsert_game(conn, normalize_chesscom(json.loads(fixture("chesscom_2026_09.json"))["games"][0]))
    url = conn.execute("SELECT url FROM games").fetchone()[0]
    assert review.load(conn, url).game_id == 1  # already fetched -> from the database

    with pytest.raises(ValueError, match="isn't downloaded yet"):
        review.load(conn, "https://www.chess.com/game/live/999")

    session = FakeSession({"https://lichess.org/game/export/AbCdEfGh": FakeResponse(200, lichess_raw()["pgn"])})
    game = review.load(conn, "https://lichess.org/AbCdEfGh", session)
    assert game.game_id is None and game.black == "rival" and len(game.moves) == 10
    assert session.calls[0][1]["headers"]["Accept"] == "application/x-chess-pgn"


def test_review_moves_from_lichess_evals():
    conn = store.connect(":memory:")
    store.upsert_game(conn, normalize_lichess(lichess_raw()))
    runner.analyze(conn, "lichess", "AjTest", log=lambda *_: None)  # reuses Lichess's analysis
    evals, depth = review.stored_evals(conn, 1)
    assert depth is None
    reviews = review.review_moves(review.stored_game(conn, 1).moves, evals)
    by_ply = {r.ply: r for r in reviews}
    assert by_ply[1].label == "book"  # no eval for the starting position
    assert by_ply[9].label == "blunder" and by_ply[9].cp_loss == 350
    assert review.fmt_eval(by_ply[10].eval_cp, by_ply[10].mate_in) == "-M6"
    s = review.side_summary(reviews)
    assert s["white"]["blunder"] == 1 and s["black"]["blunder"] == 0


def test_review_marks_engine_move_as_best():
    moves = review.parse_pgn("1. e4 e5 2. Nf3 *").moves
    evals = {0: (30, None, "e2e4"), 1: (30, None, "e7e5"), 2: (30, None, "b1c3"), 3: (-200, None, None)}
    labels = [r.label for r in review.review_moves(moves, evals)]
    assert labels == ["best", "best", "mistake"]
    assert review.review_moves(moves, evals)[2].best_san == "Nc3"


@needs_stockfish
def test_analyse_pasted_and_stored_game():
    raw = lichess_raw()
    game = review.parse_pgn(raw["pgn"])
    seen = []
    evals = review.analyse_moves(game.ucis, depth=8, progress=lambda d, t: seen.append((d, t)))
    assert sorted(evals) == list(range(runner.BOOK_PLIES, 11))
    assert seen[-1] == (10, 11)
    reviews = review.review_moves(game.moves, evals)
    assert {r.ply: r.label for r in reviews}[9] == "blunder"  # 5. Nxe5?? loses a knight and worse

    conn = store.connect(":memory:")
    g = normalize_lichess(raw)
    g.platform, g.evals = "chesscom", []  # no Lichess evals to reuse
    store.upsert_game(conn, g)
    review.analyse_stored(conn, 1, depth=8)
    assert review.stored_evals(conn, 1)[1] == 8
    assert conn.execute("SELECT label FROM move_labels WHERE ply = 9").fetchone()[0] == "blunder"


def test_review_page(tmp_path, monkeypatch):
    db = tmp_path / "r.db"
    conn = store.connect(db)
    store.upsert_game(conn, normalize_lichess(lichess_raw()))
    store.touch_player(conn, "lichess", "AjTest")
    runner.analyze(conn, "lichess", "AjTest", log=lambda *_: None)
    conn.commit()
    conn.close()

    monkeypatch.setenv("DOWNCHESS_DB", str(db))
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Game review").run()
    assert not at.exception
    text = "\n".join(t.value for t in at.text)
    assert "AjTest vs rival  0-1" in text
    assert "Starting position" in text
    assert "5. Nxe5??" in text  # key moments and move list

    at.button[4].click().run()  # Next error
    assert not at.exception
    assert at.slider[0].value == 9
    assert "5. Nxe5  blunder, -350 cp" in "\n".join(t.value for t in at.text)
