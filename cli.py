# cli.py
"""DownChess command line.

    python cli.py fetch lichess:<user>
    python cli.py fetch chesscom:<user>
    python cli.py fetch chesscom:<user> --all-speeds   # include bullet/blitz/daily
    python cli.py fetch chesscom:<user> --full         # ignore what's stored, re-download everything
    python cli.py summary chesscom:<user>
    python cli.py moves path/to/game.pgn               # sanity check: print a PGN's moves
"""

from __future__ import annotations

import argparse
import io
import sys

import chess.pgn

from db import store
from fetch import http
from fetch.normalize import parse_pgn_moves
from fetch.sync import PLATFORMS, sync


def parse_target(target: str) -> tuple[str, str]:
    platform, sep, username = target.partition(":")
    platform = platform.lower().replace(".", "")  # accept chess.com:<user>
    if not sep or platform not in PLATFORMS or not username:
        raise argparse.ArgumentTypeError(f"expected lichess:<user> or chesscom:<user>, got {target!r}")
    return platform, username


def cmd_fetch(args) -> None:
    platform, username = args.target
    conn = store.connect(args.db)
    speed = None if args.all_speeds else "rapid"
    try:
        result = sync(conn, http.make_session(), platform, username, speed=speed, full=args.full)
    except http.NotFound:
        sys.exit(f"{platform} has no user named {username!r}")
    total = store.count_games(conn, platform, username, speed)
    label = speed or "all"
    print(f"Done. Read {result.seen}, stored {result.new} new, skipped {result.skipped}. "
          f"{total} {label} games stored for {platform}:{username}.")


def cmd_summary(args) -> None:
    platform, username = args.target
    conn = store.connect(args.db)
    rows = conn.execute(
        """
        SELECT time_class, COUNT(*) AS n, MIN(played_at) AS first, MAX(played_at) AS last
        FROM games WHERE platform = ? AND (white = ? OR black = ?)
        GROUP BY time_class ORDER BY n DESC
        """,
        (platform, username, username),
    ).fetchall()
    if not rows:
        print(f"No games stored for {platform}:{username}. Run: python cli.py fetch {platform}:{username}")
        return
    print(f"{'time class':<12}{'games':>7}  first game  last game")
    for r in rows:
        print(f"{r['time_class'] or '?':<12}{r['n']:>7}  {r['first'][:10]}  {r['last'][:10]}")


def cmd_moves(args) -> None:
    with open(args.pgn) as f:
        game = chess.pgn.read_game(io.StringIO(f.read()))
    if game is None:
        sys.exit("no game found in that file")
    moves, _ = parse_pgn_moves(game)
    print(f"{game.headers.get('White')} vs {game.headers.get('Black')}  {game.headers.get('Result')}")
    for m in moves:
        clock = f"  [{m.clock_remaining_s:.0f}s]" if m.clock_remaining_s is not None else ""
        prefix = f"{(m.ply + 1) // 2}." if m.ply % 2 else "   ..."
        print(f"{prefix:<6} {m.san}{clock}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="downchess")
    parser.add_argument("--db", default=store.DEFAULT_DB, help="SQLite file (default: data/downchess.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="download a player's games")
    p.add_argument("target", type=parse_target, help="lichess:<user> or chesscom:<user>")
    p.add_argument("--all-speeds", action="store_true", help="store every time control, not just rapid")
    p.add_argument("--full", action="store_true", help="re-download the whole history")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("summary", help="show what is stored for a player")
    p.add_argument("target", type=parse_target)
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("moves", help="print the moves of a PGN file")
    p.add_argument("pgn")
    p.set_defaults(func=cmd_moves)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
