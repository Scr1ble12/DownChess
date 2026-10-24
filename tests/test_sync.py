# tests/test_sync.py
"""End-to-end fetch + store against fixture data, including the rerun rules."""

from db import store
from fetch import http
from fetch.chesscom import archives_to_fetch
from fetch.sync import sync
from tests.fakes import FakeResponse, FakeSession, fixture

ARCHIVES = "https://api.chess.com/pub/player/ajtest/games/"


def chesscom_session():
    return FakeSession({
        ARCHIVES + "archives": FakeResponse(body='{"archives": ["%s2026/08", "%s2026/09"]}' % (ARCHIVES, ARCHIVES)),
        ARCHIVES + "2026/08": FakeResponse(body='{"games": []}'),
        ARCHIVES + "2026/09": FakeResponse(body=fixture("chesscom_2026_09.json")),
    })


def test_chesscom_fetch_then_rerun():
    conn = store.connect(":memory:")
    first = sync(conn, chesscom_session(), "chesscom", "AjTest")
    assert (first.seen, first.new, first.skipped) == (3, 1, 2)  # blitz and chess960 skipped
    assert conn.execute("SELECT COUNT(*) FROM moves").fetchone()[0] == 7

    session = chesscom_session()
    second = sync(conn, session, "chesscom", "AjTest")
    assert second.new == 0
    fetched = [url for url, _ in session.calls]
    assert ARCHIVES + "2026/08" not in fetched  # complete month, not downloaded again
    assert ARCHIVES + "2026/09" in fetched  # newest month, may have new games


def test_chesscom_all_speeds():
    conn = store.connect(":memory:")
    result = sync(conn, chesscom_session(), "chesscom", "AjTest", speed=None)
    assert result.new == 2


def test_archives_to_fetch():
    urls = [f"x/{m}" for m in ("2026/07", "2026/08", "2026/09", "2026/10")]
    assert archives_to_fetch(urls, set()) == urls
    assert archives_to_fetch(urls, {"2026/07", "2026/08"}) == urls[1:]


def test_lichess_fetch_stores_evals_and_uses_since_on_rerun():
    conn = store.connect(":memory:")
    session = FakeSession({"https://lichess.org/api/games/user/AjTest": FakeResponse(body=fixture("lichess_games.ndjson"))})
    result = sync(conn, session, "lichess", "AjTest")
    assert (result.seen, result.new, result.skipped) == (3, 2, 1)
    params = session.calls[0][1]["params"]
    assert params["perfType"] == "rapid" and params["evals"] == "true" and "since" not in params
    assert conn.execute("SELECT COUNT(*) FROM evals WHERE source = 'lichess'").fetchone()[0] == 10

    second = sync(conn, session, "lichess", "AjTest")
    assert second.new == 0
    since = session.calls[1][1]["params"]["since"]
    assert since == 1790935200000 + 1  # just after the newest stored game


def test_case_insensitive_username():
    conn = store.connect(":memory:")
    sync(conn, chesscom_session(), "chesscom", "AjTest")
    assert store.count_games(conn, "chesscom", "ajtest") == 1


def test_retry_after_429():
    session = FakeSession({"https://x.test/": [FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(body="{}")]})
    waits = []
    resp = http.get(session, "https://x.test/a", sleep=waits.append)
    assert resp.status_code == 200 and waits == [1]


def test_unknown_user_raises_not_found():
    import pytest

    with pytest.raises(http.NotFound):
        sync(store.connect(":memory:"), FakeSession({}), "chesscom", "nobody")
