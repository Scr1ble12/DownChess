# fetch/sync.py
"""Fetch a player's games from one site and store the new ones."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from db import store
from fetch import chesscom, lichess
from fetch.normalize import SkipGame, normalize_chesscom, normalize_lichess

PLATFORMS = ("chesscom", "lichess")


@dataclass
class SyncResult:
    seen: int = 0
    new: int = 0
    skipped: int = 0  # variants, unfinished games, other speeds


def _store(conn, raw: dict, normalize, speed: str | None, result: SyncResult) -> None:
    result.seen += 1
    try:
        game = normalize(raw)
    except SkipGame:
        result.skipped += 1
        return
    if speed and game.time_class != speed:
        result.skipped += 1
        return
    if store.upsert_game(conn, game):
        result.new += 1


def sync_chesscom(conn: sqlite3.Connection, session, username: str, speed: str | None, full: bool) -> SyncResult:
    result = SyncResult()
    done = set() if full else store.fetched_archives(conn, "chesscom", username)
    urls = chesscom.archives_to_fetch(chesscom.list_archives(session, username), done)
    print(f"chesscom:{username}: {len(urls)} monthly archive(s) to download")
    for url in urls:
        before = result.new
        for raw in chesscom.iter_archive_games(session, url):
            _store(conn, raw, normalize_chesscom, speed, result)
        store.mark_archive_fetched(conn, "chesscom", username, chesscom.archive_key(url))
        conn.commit()  # one month at a time, so an interrupted run keeps its progress
        print(f"  {chesscom.archive_key(url)}: {result.new - before} new")
    return result


def sync_lichess(conn: sqlite3.Connection, session, username: str, speed: str | None, full: bool) -> SyncResult:
    result = SyncResult()
    since_ms, latest = None, None
    if not full:
        latest = store.latest_played_at(conn, "lichess", username)
        if latest:
            since_ms = int(datetime.fromisoformat(latest).timestamp() * 1000) + 1
    print(f"lichess:{username}: streaming games" + (f" since {latest}" if since_ms else ""))
    for raw in lichess.iter_games(session, username, since_ms=since_ms, perf_type=speed):
        _store(conn, raw, normalize_lichess, speed, result)
        if result.seen % 200 == 0:
            conn.commit()
            print(f"  {result.seen} games read, {result.new} new")
    conn.commit()
    return result


def sync(conn: sqlite3.Connection, session, platform: str, username: str, speed: str | None = "rapid", full: bool = False) -> SyncResult:
    if platform == "chesscom":
        result = sync_chesscom(conn, session, username, speed, full)
    elif platform == "lichess":
        result = sync_lichess(conn, session, username, speed, full)
    else:
        raise ValueError(f"unknown platform {platform!r}, expected one of {PLATFORMS}")
    store.touch_player(conn, platform, username)
    conn.commit()
    return result
