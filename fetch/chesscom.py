# fetch/chesscom.py
"""Chess.com Published-Data API (read-only, no key).

Docs: https://www.chess.com/news/view/published-data-api
  GET /pub/player/{user}/games/archives  -> {"archives": [monthly URLs]}
  GET /pub/player/{user}/games/{YYYY}/{MM} -> {"games": [...]}

Incremental rule: a month we fetched before is complete unless it is the
newest month we have (it may have been fetched mid-month), so we refetch that
one and anything newer. Duplicates are ignored by the store.
"""

from __future__ import annotations

from typing import Iterator

from fetch import http

BASE = "https://api.chess.com/pub/player"


def archive_key(url: str) -> str:
    """'.../games/2026/09' -> '2026/09'."""
    parts = url.rstrip("/").split("/")
    return f"{parts[-2]}/{parts[-1]}"


def archives_to_fetch(all_urls: list[str], already_fetched: set[str]) -> list[str]:
    if not already_fetched:
        return list(all_urls)
    newest_done = max(already_fetched)
    return [u for u in all_urls if archive_key(u) not in already_fetched or archive_key(u) >= newest_done]


def list_archives(session, username: str) -> list[str]:
    resp = http.get(session, f"{BASE}/{username.lower()}/games/archives")
    return resp.json().get("archives", [])


def iter_archive_games(session, archive_url: str) -> Iterator[dict]:
    resp = http.get(session, archive_url)
    yield from resp.json().get("games", [])
