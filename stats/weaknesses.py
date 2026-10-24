# stats/weaknesses.py
"""The weakness report: each metric compares you against a baseline from
your own games, and the biggest relative shortfalls become the top 3.

Every metric returns a Finding with its number, the baseline it was compared
against, the sample size, and example moments (game + ply) to show as boards.

Severity is a relative shortfall, so metrics on different scales can be
ranked together:
    "bad when higher" (a rate):  (value - baseline) / baseline
    "bad when lower"  (a score): (baseline - value) / baseline
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from engine.classify import BLUNDER

MIN_SEVERITY = 0.10  # under a 10% relative gap we don't call it a weakness

# Rapid time trouble: under 10% of the starting time, or under 2 minutes.
TIME_TROUBLE_FRACTION = 0.10
TIME_TROUBLE_SECONDS = 120
WINNING = 300  # "+3" in centipawns
TILT_GAP_HOURS = 2  # games further apart than this start a new session
EXAMPLES = 3  # example games shown per weakness


@dataclass
class Moment:
    game_id: int
    ply: int  # the move to show; the board is the position before it


@dataclass
class Finding:
    key: str
    title: str
    value: float
    baseline: float
    unit: str  # 'pct' or 'cp'
    detail: str  # one sentence: the number and what it was compared with
    sample: str  # e.g. "312 moves in 41 games"
    severity: float
    examples: list[Moment] = field(default_factory=list)
    min_ok: bool = True  # False when the sample is too small to trust

    @property
    def flagged(self) -> bool:
        return self.min_ok and self.severity >= MIN_SEVERITY


# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

MOVES_SQL = """
SELECT
    l.game_id, l.ply, l.cp_loss, l.label, l.phase,
    m.san, m.uci, m.fen_before, m.clock_remaining_s,
    g.base_seconds, g.played_at, g.url, g.result, g.opening_name, g.eco,
    CASE WHEN g.white = :user THEN 'white' ELSE 'black' END AS color
FROM move_labels l
JOIN moves m ON m.game_id = l.game_id AND m.ply = l.ply
JOIN games g ON g.id = l.game_id
WHERE g.platform = :platform
  AND (g.white = :user OR g.black = :user)
  AND (:time_class IS NULL OR g.time_class = :time_class)
  AND ((l.ply % 2 = 1) = (g.white = :user))
"""

# Evals from whichever source analysed the game, turned to the player's view.
EVALS_SQL = """
SELECT e.game_id, e.ply,
       CASE WHEN g.white = :user THEN e.eval_cp ELSE -e.eval_cp END AS my_eval
FROM evals e
JOIN analysed_games a ON a.game_id = e.game_id AND a.source = e.source
JOIN games g ON g.id = e.game_id
WHERE g.platform = :platform
  AND (g.white = :user OR g.black = :user)
  AND (:time_class IS NULL OR g.time_class = :time_class)
"""


def load(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None):
    params = {"platform": platform, "user": username, "time_class": time_class}
    moves = pd.read_sql_query(MOVES_SQL, conn, params=params)
    evals = pd.read_sql_query(EVALS_SQL, conn, params=params)
    return moves, evals


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _rel(value: float, baseline: float, higher_is_worse: bool) -> float:
    if baseline <= 0:
        return 0.0
    gap = (value - baseline) if higher_is_worse else (baseline - value)
    return gap / baseline


def _worst_moves(moves: pd.DataFrame, n: int = EXAMPLES) -> list[Moment]:
    """The single worst move from each of the n games where it was worst."""
    if moves.empty:
        return []
    worst = moves.sort_values("cp_loss", ascending=False).drop_duplicates("game_id").head(n)
    return [Moment(int(r.game_id), int(r.ply)) for r in worst.itertuples()]


def _worst_move_per_game(moves: pd.DataFrame, game_ids, n: int = EXAMPLES) -> list[Moment]:
    return _worst_moves(moves[moves["game_id"].isin(list(game_ids))], n)


def _games(moves: pd.DataFrame) -> pd.DataFrame:
    """One row per analysed game with the player's score."""
    g = moves.drop_duplicates("game_id")[["game_id", "played_at", "result", "color", "opening_name", "eco"]].copy()
    win = ((g["result"] == "1-0") & (g["color"] == "white")) | ((g["result"] == "0-1") & (g["color"] == "black"))
    g["score"] = 0.0
    g.loc[win, "score"] = 1.0
    g.loc[g["result"] == "1/2-1/2", "score"] = 0.5
    g["played_at"] = pd.to_datetime(g["played_at"], utc=True, format="ISO8601")
    return g.sort_values("played_at").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def phase_weakness(moves: pd.DataFrame, min_moves: int = 100) -> Finding | None:
    by_phase = moves.groupby("phase")["cp_loss"].agg(["mean", "size"])
    by_phase = by_phase[by_phase["size"] >= min_moves]
    if len(by_phase) < 2:
        return None
    worst = by_phase["mean"].idxmax()
    others = moves[(moves["phase"] != worst) & moves["phase"].isin(by_phase.index)]
    value, baseline = by_phase.loc[worst, "mean"], others["cp_loss"].mean()
    in_phase = moves[moves["phase"] == worst]
    return Finding(
        key="phase",
        title=f"{worst.capitalize()} play",
        value=value, baseline=baseline, unit="cp",
        detail=f"You lose {value:.0f} centipawns per move in the {worst}, vs {baseline:.0f} in the rest of the game.",
        sample=f"{int(by_phase.loc[worst, 'size'])} {worst} moves in {in_phase['game_id'].nunique()} games",
        severity=_rel(value, baseline, True),
        examples=_worst_moves(in_phase),
    )


def weak_openings(moves: pd.DataFrame, min_games: int = 10) -> Finding | None:
    games = _games(moves)
    games["opening"] = games["opening_name"].fillna(games["eco"]).fillna("Unknown")
    overall = games["score"].mean()
    grouped = games.groupby(["opening", "color"])["score"].agg(["mean", "size"])
    grouped = grouped[grouped["size"] >= min_games]
    if grouped.empty or not overall:
        return None
    (opening, color), row = min(grouped.iterrows(), key=lambda kv: kv[1]["mean"])
    these = games[(games["opening"] == opening) & (games["color"] == color)]
    lost = these[these["score"] < 1]["game_id"]
    return Finding(
        key="opening",
        title=f"{opening} as {color}",
        value=row["mean"] * 100, baseline=overall * 100, unit="pct",
        detail=f"You score {row['mean'] * 100:.0f}% in the {opening} as {color}, vs {overall * 100:.0f}% overall.",
        sample=f"{int(row['size'])} games",
        severity=_rel(row["mean"], overall, False),
        examples=_worst_move_per_game(moves, lost),
    )


def time_trouble(moves: pd.DataFrame, min_moves: int = 30) -> Finding | None:
    clocked = moves.dropna(subset=["clock_remaining_s", "base_seconds"])
    if clocked.empty:
        return None
    # "under 10% OR under 2 minutes" means under whichever threshold is larger
    limit = (clocked["base_seconds"] * TIME_TROUBLE_FRACTION).clip(lower=TIME_TROUBLE_SECONDS)
    low = clocked[clocked["clock_remaining_s"] < limit]
    normal = clocked[clocked["clock_remaining_s"] >= limit]
    if normal.empty:
        return None
    value = (low["cp_loss"] >= BLUNDER).mean() * 100 if len(low) else 0.0
    baseline = (normal["cp_loss"] >= BLUNDER).mean() * 100
    return Finding(
        key="time",
        title="Time trouble",
        value=value, baseline=baseline, unit="pct",
        detail=(f"With under 2 minutes (or 10% of your time) left, {value:.1f}% of your moves are blunders, "
                f"vs {baseline:.1f}% with more time."),
        sample=f"{len(low)} low-clock moves in {low['game_id'].nunique()} games",
        severity=_rel(value, baseline, True),
        examples=_worst_moves(low[low["cp_loss"] >= BLUNDER]),
        min_ok=len(low) >= min_moves,
    )


def thrown_wins(moves: pd.DataFrame, evals: pd.DataFrame, min_games: int = 10) -> Finding | None:
    """How often you fail to win from +3, vs how often opponents fail to win from +3 against you."""
    games = _games(moves).set_index("game_id")
    ev = evals[evals["game_id"].isin(games.index)]
    if ev.empty:
        return None
    best = ev.groupby("game_id")["my_eval"].max()
    worst = ev.groupby("game_id")["my_eval"].min()
    had_win = best[best >= WINNING].index
    opp_had_win = worst[worst <= -WINNING].index
    if len(had_win) < min_games or len(opp_had_win) < min_games:
        return None
    thrown = [g for g in had_win if games.loc[g, "score"] < 1]
    saved = [g for g in opp_had_win if games.loc[g, "score"] > 0]
    value = len(thrown) / len(had_win) * 100
    baseline = len(saved) / len(opp_had_win) * 100

    # Key moment: the move after which the eval first fell back under +3 for good.
    examples = []
    for g in thrown[:EXAMPLES]:
        mine = moves[moves["game_id"] == g]
        peak_ply = ev[(ev["game_id"] == g)].sort_values("my_eval").iloc[-1]["ply"]
        after = mine[mine["ply"] > peak_ply]
        pick = after if not after.empty else mine
        if not pick.empty:
            r = pick.sort_values("cp_loss", ascending=False).iloc[0]
            examples.append(Moment(int(g), int(r["ply"])))
    return Finding(
        key="thrown",
        title="Converting winning positions",
        value=value, baseline=baseline, unit="pct",
        detail=(f"You don't win {value:.0f}% of games where you reach +3, "
                f"while your opponents don't win {baseline:.0f}% of games where they reach +3 against you."),
        sample=f"{len(had_win)} games where you reached +3",
        severity=_rel(value, baseline, True),
        examples=examples,
    )


def tilt(moves: pd.DataFrame, min_games: int = 15) -> Finding | None:
    games = _games(moves)
    gap = games["played_at"].diff()
    prev = games["score"].shift()
    same_session = gap <= pd.Timedelta(hours=TILT_GAP_HOURS)
    after_loss = games[same_session & (prev == 0)]
    after_win = games[same_session & (prev == 1)]
    if len(after_loss) < min_games or len(after_win) < min_games:
        return None
    value, baseline = after_loss["score"].mean() * 100, after_win["score"].mean() * 100
    lost_again = after_loss[after_loss["score"] == 0]["game_id"]
    return Finding(
        key="tilt",
        title="Playing on after a loss",
        value=value, baseline=baseline, unit="pct",
        detail=(f"In the next game after a loss (within {TILT_GAP_HOURS} hours) you score {value:.0f}%, "
                f"vs {baseline:.0f}% after a win."),
        sample=f"{len(after_loss)} games right after a loss",
        severity=_rel(value, baseline, False),
        examples=_worst_move_per_game(moves, lost_again),
    )


def rating_gap(games: pd.DataFrame, moves: pd.DataFrame, min_games: int = 20) -> Finding | None:
    """Score vs Elo-expected score, separately against higher- and lower-rated opponents."""
    rated = games.dropna(subset=["my_elo", "opp_elo"]).copy()
    rated["expected"] = 1 / (1 + 10 ** ((rated["opp_elo"] - rated["my_elo"]) / 400))
    candidates = []
    for name, part in (("higher", rated[rated["opp_elo"] > rated["my_elo"] + 50]),
                       ("lower", rated[rated["opp_elo"] < rated["my_elo"] - 50])):
        if len(part) >= min_games:
            candidates.append((name, part, part["score"].mean(), part["expected"].mean()))
    if not candidates:
        return None
    name, part, actual, expected = max(candidates, key=lambda c: _rel(c[2], c[3], False))
    bad = part[part["score"] < 1]["id"]
    return Finding(
        key="rating",
        title=f"Against {name}-rated opponents",
        value=actual * 100, baseline=expected * 100, unit="pct",
        detail=(f"Against opponents rated more than 50 points {name} than you, you score {actual * 100:.0f}%; "
                f"the rating difference predicts {expected * 100:.0f}%."),
        sample=f"{len(part)} games",
        severity=_rel(actual, expected, False),
        examples=_worst_move_per_game(moves, bad),
    )


def all_findings(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None,
                 games: pd.DataFrame) -> list[Finding]:
    moves, evals = load(conn, platform, username, time_class)
    if moves.empty:
        return []
    found = [
        phase_weakness(moves),
        weak_openings(moves),
        time_trouble(moves),
        thrown_wins(moves, evals),
        tilt(moves),
        rating_gap(games, moves),
    ]
    return sorted([f for f in found if f is not None], key=lambda f: f.severity, reverse=True)


def top(findings: list[Finding], n: int = 3) -> list[Finding]:
    return [f for f in findings if f.flagged][:n]
