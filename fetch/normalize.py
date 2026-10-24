# fetch/normalize.py
"""Turn raw Chess.com / Lichess game payloads into one `Game` record.

This is the only module that knows how the two sites differ. Everything
downstream works with `Game`, `Move` and `Eval` and never checks the platform.

Both sites give us a PGN, so moves, clocks and (Lichess-only) evals are always
read from the PGN with python-chess. The JSON around it supplies the ids and
the time class.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import chess
import chess.pgn

VALID_RESULTS = {"1-0", "0-1", "1/2-1/2"}

# Mate scores are stored as mate_in, but eval_cp is still capped so averages
# are not wrecked by "mate in 3" becoming +100000.
MATE_CP_CAP = 1000


@dataclass
class Move:
    ply: int
    san: str
    uci: str
    fen_before: str
    clock_remaining_s: float | None


@dataclass
class Eval:
    ply: int  # position after this ply, 0 = start
    eval_cp: int | None  # White's point of view
    mate_in: int | None
    source: str = "lichess"


@dataclass
class Game:
    platform: str
    platform_game_id: str
    url: str | None
    white: str
    black: str
    white_elo: int | None
    black_elo: int | None
    result: str
    termination: str | None
    rated: bool | None
    time_control: str | None
    time_class: str | None
    base_seconds: int | None
    increment_seconds: int | None
    eco: str | None
    opening_name: str | None
    played_at: str
    pgn: str
    moves: list[Move] = field(default_factory=list)
    evals: list[Eval] = field(default_factory=list)


class SkipGame(Exception):
    """Raised for games we deliberately don't store (variants, unfinished)."""


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def parse_time_control(tc: str | None) -> tuple[int | None, int | None]:
    """'600+5' -> (600, 5). '600' -> (600, 0). Daily ('1/259200') or '-' -> (None, None)."""
    if not tc or "/" in tc or tc == "-":
        return None, None
    base, _, inc = tc.partition("+")
    try:
        return int(base), int(inc or 0)
    except ValueError:
        return None, None


def time_class_from_seconds(base: int | None, inc: int | None) -> str | None:
    """Lichess's rule: estimated duration = base + 40 * increment."""
    if base is None:
        return None
    total = base + 40 * (inc or 0)
    if total < 180:
        return "bullet"
    if total < 480:
        return "blitz"
    if total < 1500:
        return "rapid"
    return "classical"


def _int_or_none(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _played_at(headers: chess.pgn.Headers, fallback_epoch_s: float | None) -> str:
    """Game start in ISO 8601 UTC, from the PGN's UTCDate/UTCTime when present."""
    date, time_ = headers.get("UTCDate"), headers.get("UTCTime")
    if date and time_ and "?" not in date:
        dt = datetime.strptime(f"{date} {time_}", "%Y.%m.%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).isoformat()
    if fallback_epoch_s is not None:
        return datetime.fromtimestamp(fallback_epoch_s, tz=timezone.utc).isoformat()
    raise SkipGame("no game date")


def parse_pgn_moves(pgn_game: chess.pgn.Game) -> tuple[list[Move], list[Eval]]:
    """Walk the main line, collecting moves plus any [%clk] and [%eval] comments."""
    moves: list[Move] = []
    evals: list[Eval] = []
    board = pgn_game.board()
    for ply, node in enumerate(pgn_game.mainline(), start=1):
        move = node.move
        moves.append(
            Move(
                ply=ply,
                san=board.san(move),
                uci=move.uci(),
                fen_before=board.fen(),
                clock_remaining_s=node.clock(),
            )
        )
        board.push(move)
        score = node.eval()
        if score is not None:
            white = score.white()
            mate = white.mate()
            cp = white.score(mate_score=100_000)
            cp = max(-MATE_CP_CAP, min(MATE_CP_CAP, cp))
            evals.append(Eval(ply=ply, eval_cp=cp, mate_in=mate))
    return moves, evals


def _read_pgn(pgn_text: str) -> chess.pgn.Game:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise SkipGame("unreadable PGN")
    if game.errors:
        raise SkipGame(f"PGN errors: {game.errors[0]}")
    return game


# --------------------------------------------------------------------------- #
# Chess.com
# --------------------------------------------------------------------------- #


def _chesscom_opening_name(eco_url: str | None) -> str | None:
    """Chess.com has no Opening header, only a URL like
    https://www.chess.com/openings/Sicilian-Defense-Open-2...Nc6
    We keep the name part and drop the trailing move list."""
    if not eco_url:
        return None
    slug = urlparse(eco_url).path.rstrip("/").split("/")[-1]
    words = []
    for word in slug.split("-"):
        if word[:1].isdigit():  # '2...Nc6', '3.d4' -> start of the move list
            break
        words.append(word)
    return " ".join(words) or None


def normalize_chesscom(raw: dict) -> Game:
    """One game object from a Chess.com monthly archive."""
    if raw.get("rules", "chess") != "chess":
        raise SkipGame(f"variant {raw.get('rules')}")
    pgn_text = raw.get("pgn")
    if not pgn_text:
        raise SkipGame("no PGN")

    pgn_game = _read_pgn(pgn_text)
    headers = pgn_game.headers
    result = headers.get("Result", "*")
    if result not in VALID_RESULTS:
        raise SkipGame(f"result {result}")

    url = raw.get("url")
    # The numeric id at the end of the game URL; uuid only as a fallback.
    game_id = (url.rstrip("/").split("/")[-1] if url else None) or raw.get("uuid")
    if not game_id:
        raise SkipGame("no game id")

    tc = raw.get("time_control") or headers.get("TimeControl")
    base, inc = parse_time_control(tc)
    time_class = raw.get("time_class") or time_class_from_seconds(base, inc)
    white, black = raw.get("white", {}), raw.get("black", {})

    moves, _ = parse_pgn_moves(pgn_game)  # Chess.com PGNs carry no evals
    return Game(
        platform="chesscom",
        platform_game_id=str(game_id),
        url=url,
        white=white.get("username") or headers.get("White"),
        black=black.get("username") or headers.get("Black"),
        white_elo=_int_or_none(white.get("rating") or headers.get("WhiteElo")),
        black_elo=_int_or_none(black.get("rating") or headers.get("BlackElo")),
        result=result,
        termination=headers.get("Termination"),
        rated=raw.get("rated"),
        time_control=tc,
        time_class=time_class,
        base_seconds=base,
        increment_seconds=inc,
        eco=headers.get("ECO"),
        # In the archive JSON, "eco" is the opening URL, not the ECO code.
        opening_name=_chesscom_opening_name(raw.get("eco") or headers.get("ECOUrl")),
        played_at=_played_at(headers, raw.get("end_time")),
        pgn=pgn_text,
        moves=moves,
    )


# --------------------------------------------------------------------------- #
# Lichess
# --------------------------------------------------------------------------- #


def normalize_lichess(raw: dict) -> Game:
    """One NDJSON line from /api/games/user, requested with pgnInJson=true."""
    if raw.get("variant", "standard") != "standard":
        raise SkipGame(f"variant {raw.get('variant')}")
    pgn_text = raw.get("pgn")
    if not pgn_text:
        raise SkipGame("no PGN (request with pgnInJson=true)")

    pgn_game = _read_pgn(pgn_text)
    headers = pgn_game.headers
    result = headers.get("Result", "*")
    if result not in VALID_RESULTS:
        raise SkipGame(f"result {result}")

    clock = raw.get("clock") or {}
    base, inc = clock.get("initial"), clock.get("increment")
    if base is None:
        base, inc = parse_time_control(headers.get("TimeControl"))
    tc = f"{base}+{inc}" if base is not None else headers.get("TimeControl")

    players = raw.get("players", {})

    def name(color: str) -> str:
        user = players.get(color, {}).get("user", {})
        return user.get("name") or headers.get(color.capitalize(), "?")

    moves, evals = parse_pgn_moves(pgn_game)
    created_ms = raw.get("createdAt")
    return Game(
        platform="lichess",
        platform_game_id=raw["id"],
        url=f"https://lichess.org/{raw['id']}",
        white=name("white"),
        black=name("black"),
        white_elo=_int_or_none(players.get("white", {}).get("rating") or headers.get("WhiteElo")),
        black_elo=_int_or_none(players.get("black", {}).get("rating") or headers.get("BlackElo")),
        result=result,
        termination=raw.get("status") or headers.get("Termination"),
        rated=raw.get("rated"),
        time_control=tc,
        time_class=raw.get("speed") or time_class_from_seconds(base, inc),
        base_seconds=base,
        increment_seconds=inc,
        eco=(raw.get("opening") or {}).get("eco") or headers.get("ECO"),
        opening_name=(raw.get("opening") or {}).get("name") or headers.get("Opening"),
        played_at=_played_at(headers, created_ms / 1000 if created_ms else None),
        pgn=pgn_text,
        moves=moves,
        evals=evals,
    )
