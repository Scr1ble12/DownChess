# tests/test_app.py
"""Smoke test: the Streamlit page renders with and without data."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from db import store
from tests.test_stats import make_game

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def run_app(db_path, monkeypatch):
    monkeypatch.setenv("DOWNCHESS_DB", str(db_path))
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
