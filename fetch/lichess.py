# fetch/lichess.py
"""Lichess game export.

Docs: https://lichess.org/api#tag/Games/operation/apiGamesUser
  GET /api/games/user/{user} with Accept: application/x-ndjson streams one
  JSON game per line. Anonymous requests stream at about 20 games/s; a token
  (LICHESS_TOKEN env var) raises that to 30/s.

Incremental rule: ask only for games after the newest one we stored (`since`).
"""

from __future__ import annotations

import json
import os
from typing import Iterator

from fetch import http

BASE = "https://lichess.org/api/games/user"


def export_params(since_ms: int | None, perf_type: str | None) -> dict:
    params = {
        "pgnInJson": "true",  # gives us one PGN path shared with Chess.com
        "clocks": "true",
        "evals": "true",  # only present for games already analysed on Lichess
        "opening": "true",
        "sort": "dateAsc",
    }
    if perf_type:
        params["perfType"] = perf_type
    if since_ms is not None:
        params["since"] = since_ms
    return params


def iter_games(session, username: str, since_ms: int | None = None, perf_type: str | None = "rapid") -> Iterator[dict]:
    headers = {"Accept": "application/x-ndjson"}
    token = os.environ.get("LICHESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = http.get(
        session,
        f"{BASE}/{username}",
        params=export_params(since_ms, perf_type),
        headers=headers,
        stream=True,
    )
    with resp:
        for line in resp.iter_lines():
            if line:
                yield json.loads(line)
