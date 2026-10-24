# tests/test_stats.py
import pytest

from db import store
from fetch.normalize import Game
from stats import results
from stats.games import player_games, stored_players, time_classes
from ui.text import table


def make_game(n, white, black, result, white_elo, black_elo, month="2026-09", opening="Italian Game", time_class="rapid"):
    return Game(
        platform="lichess", platform_game_id=f"g{n}", url=None, white=white, black=black,
        white_elo=white_elo, black_elo=black_elo, result=result, termination=None, rated=True,
        time_control="600+0", time_class=time_class, base_seconds=600, increment_seconds=0,
        eco="C50", opening_name=opening, played_at=f"{month}-{10 + n:02d}T12:00:00+00:00", pgn="",
    )


@pytest.fixture
def conn():
    c = store.connect(":memory:")
    games = [
        make_game(1, "me", "a", "1-0", 1500, 1480),                       # white win, even
        make_game(2, "b", "me", "1-0", 1700, 1510),                       # black loss, 190 higher
        make_game(3, "me", "c", "1/2-1/2", 1505, 1250, opening="London"), # white draw, 255 lower
        make_game(4, "d", "me", "0-1", 1520, 1520, month="2026-10"),      # black win, even
        make_game(5, "me", "e", "0-1", 1530, 1500, time_class="blitz"),   # filtered out by rapid
    ]
    for g in games:
        store.upsert_game(c, g)
    store.touch_player(c, "lichess", "me")
    return c


def test_player_perspective(conn):
    df = player_games(conn, "lichess", "ME")  # case-insensitive
    assert len(df) == 4
    assert list(df["color"]) == ["white", "black", "white", "black"]
    assert list(df["score"]) == [1.0, 0.0, 0.5, 1.0]
    assert list(df["opp_elo"]) == [1480, 1700, 1250, 1520]


def test_overall_and_color(conn):
    df = player_games(conn, "lichess", "me")
    assert results.overall(df) == {"games": 4, "wins": 2, "draws": 1, "losses": 1, "score_pct": 62.5}
    color = results.by_color(df)
    assert color.loc["white", "score_pct"] == 75
    assert color.loc["black", "games"] == 2


def test_rating_bands(conn):
    bands = results.by_rating_band(player_games(conn, "lichess", "me"))
    assert bands.loc["within 100", "games"] == 2
    assert bands.loc["100-199 higher", "losses"] == 1
    assert bands.loc["200+ lower", "draws"] == 1
    assert "200+ higher" not in bands.index


def test_openings_min_games(conn):
    df = player_games(conn, "lichess", "me")
    assert len(results.by_opening(df)) == 3  # Italian/white, Italian/black, London/white
    assert list(results.by_opening(df, min_games=2).index) == [("Italian Game", "black")]


def test_rating_by_month(conn):
    monthly = results.rating_by_month(player_games(conn, "lichess", "me"))
    assert list(monthly.index) == ["2026-09", "2026-10"]
    assert list(monthly["rating"]) == [1505, 1520]
    assert monthly.loc["2026-10", "change"] == 15


def test_all_time_classes(conn):
    assert len(player_games(conn, "lichess", "me", time_class=None)) == 5
    assert time_classes(conn, "lichess", "me") == ["rapid", "blitz"]
    assert stored_players(conn) == [("lichess", "me")]


def test_text_table(conn):
    text = table(results.by_color(player_games(conn, "lichess", "me")), {"games": ("games", ""), "score_pct": ("score", "pct")}, "color")
    assert text.splitlines() == [
        "color  games  score",
        "-----  -----  -----",
        "white      2    75%",
        "black      2    50%",
    ]
