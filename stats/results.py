# stats/results.py
"""Win/draw/loss breakdowns. Every table carries its game count, because a
70% score over 4 games means very little."""

from __future__ import annotations

import pandas as pd

# Rating difference = opponent minus me. Bands are 100 points wide near even,
# where most games are, and open-ended at the edges.
RATING_BANDS = [
    (-10_000, -200, "200+ lower"),
    (-200, -100, "100-199 lower"),
    (-100, 100, "within 100"),
    (100, 200, "100-199 higher"),
    (200, 10_000, "200+ higher"),
]


def _summarize(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    grouped = df.groupby(by, observed=True)
    out = pd.DataFrame({
        "games": grouped.size(),
        "wins": grouped["score"].apply(lambda s: int((s == 1).sum())),
        "draws": grouped["score"].apply(lambda s: int((s == 0.5).sum())),
        "losses": grouped["score"].apply(lambda s: int((s == 0).sum())),
        "score_pct": grouped["score"].mean() * 100,
    })
    return out


def overall(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"games": 0, "wins": 0, "draws": 0, "losses": 0, "score_pct": None}
    return {
        "games": len(df),
        "wins": int((df["score"] == 1).sum()),
        "draws": int((df["score"] == 0.5).sum()),
        "losses": int((df["score"] == 0).sum()),
        "score_pct": df["score"].mean() * 100,
    }


def by_color(df: pd.DataFrame) -> pd.DataFrame:
    return _summarize(df, "color").reindex(["white", "black"]).dropna(how="all")


def by_opening(df: pd.DataFrame, min_games: int = 1) -> pd.DataFrame:
    """Grouped by opening name and color, since playing an opening as White
    and facing it as Black are different problems."""
    named = df.assign(opening=df["opening_name"].fillna(df["eco"]).fillna("Unknown"))
    out = _summarize(named, ["opening", "color"])
    out = out[out["games"] >= min_games]
    return out.sort_values(["games", "score_pct"], ascending=[False, True])


def by_rating_band(df: pd.DataFrame) -> pd.DataFrame:
    rated = df.dropna(subset=["my_elo", "opp_elo"])
    diff = rated["opp_elo"] - rated["my_elo"]
    edges = [b[0] for b in RATING_BANDS] + [RATING_BANDS[-1][1]]
    labels = [b[2] for b in RATING_BANDS]
    band = pd.cut(diff, bins=edges, labels=labels, right=False)
    out = _summarize(rated.assign(band=band), "band")
    return out.reindex(labels).dropna(how="all")


def rating_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """Rating at the end of each month, with that month's game count and score."""
    rated = df.dropna(subset=["my_elo"])
    if rated.empty:
        return pd.DataFrame(columns=["rating", "change", "games", "score_pct"])
    month = rated["played_at"].dt.strftime("%Y-%m")
    grouped = rated.groupby(month)
    out = pd.DataFrame({
        "rating": grouped["my_elo"].last().astype(int),
        "games": grouped.size(),
        "score_pct": grouped["score"].mean() * 100,
    })
    out.insert(1, "change", out["rating"].diff())
    out.index.name = "month"
    return out
