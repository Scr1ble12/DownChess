# tests/test_app.py
"""Smoke test: the Streamlit page renders with and without data."""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

from db import store
from tests.test_stats import make_game

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run_app(db_path, monkeypatch):
    monkeypatch.setenv("DOWNCHESS_DB", str(db_path))
    # AppTest swaps sys.modules["__main__"] for app.py. Put it back afterwards,
    # or later multiprocessing tests spawn workers that re-run the Streamlit app.
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    assert not at.exception
    return "\n".join(t.value for t in at.text)


def test_empty_database(tmp_path, monkeypatch):
    assert "No players stored yet" in run_app(tmp_path / "empty.db", monkeypatch)


def test_with_games(tmp_path, monkeypatch):
    db = tmp_path / "games.db"
    conn = store.connect(db)
    store.upsert_game(conn, make_game(1, "me", "a", "1-0", 1500, 1480))
    store.upsert_game(conn, make_game(2, "b", "me", "1-0", 1700, 1510))
    store.touch_player(conn, "lichess", "me")
    conn.commit()
    conn.close()
    text = run_app(db, monkeypatch)
    assert "lichess:me  |  rapid  |  2 games" in text
    assert "Record   1W 0D 1L   score 50%" in text
    assert "white" in text and "within 100" in text and "2026-09" in text


def test_weaknesses_page_renders(tmp_path, monkeypatch):
    import json

    from engine import runner
    from fetch.normalize import normalize_lichess
    from tests.fakes import fixture

    db = tmp_path / "w.db"
    conn = store.connect(db)
    store.upsert_game(conn, normalize_lichess(json.loads(fixture("lichess_games.ndjson").splitlines()[0])))
    store.touch_player(conn, "lichess", "AjTest")
    runner.analyze(conn, "lichess", "AjTest", log=lambda *_: None)  # reuses Lichess evals, no engine
    conn.commit()
    conn.close()

    monkeypatch.setenv("DOWNCHESS_DB", str(db))
    monkeypatch.setitem(sys.modules, "__main__", sys.modules["__main__"])
    at = AppTest.from_file(APP, default_timeout=30)
    at.run()
    at.sidebar.radio[0].set_value("Top 3 weaknesses").run()
    assert not at.exception
    text = "\n".join(t.value for t in at.text)
    assert "All checks" in "\n".join(s.value for s in at.subheader)
    assert "Nothing stands out" in text or "worse than the baseline" in text


def test_board_moment_caption():
    import json

    from engine import runner
    from fetch.normalize import normalize_lichess
    from tests.fakes import fixture
    from ui.board import render_moment

    conn = store.connect(":memory:")
    store.upsert_game(conn, normalize_lichess(json.loads(fixture("lichess_games.ndjson").splitlines()[0])))
    runner.analyze(conn, "lichess", "AjTest", log=lambda *_: None)
    view = render_moment(conn, 1, 9)  # 5. Nxe5??
    assert view.svg.startswith("<svg")
    assert "You played 5. Nxe5 (blunder" in view.caption
    assert "+0.0 -> -3.5" in view.caption
    assert view.url == "https://lichess.org/AbCdEfGh"
