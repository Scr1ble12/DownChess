# ui/views.py
"""The two pages of the dashboard. app.py handles the sidebar and picks one."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from stats import analysis, results, weaknesses
from ui.board import render_moment
from ui.text import fmt, table

WDL = {"games": ("games", ""), "wins": ("W", ""), "draws": ("D", ""), "losses": ("L", ""), "score_pct": ("score", "pct")}


def stats_page(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None, games: pd.DataFrame) -> None:
    o = results.overall(games)
    first, last = games["played_at"].min(), games["played_at"].max()
    st.text(
        f"Record   {o['wins']}W {o['draws']}D {o['losses']}L   score {o['score_pct']:.0f}%\n"
        f"Period   {first:%Y-%m-%d} to {last:%Y-%m-%d}"
    )

    moves = analysis.player_moves(conn, platform, username, time_class)
    a = analysis.summary(moves)
    if a["games"]:
        st.text(
            f"Engine   {a['games']} of {len(games)} games analysed   accuracy {a['accuracy']:.1f}%\n"
            f"Per game {a['blunders_per_game']:.1f} blunders  {a['mistakes_per_game']:.1f} mistakes  "
            f"{a['inaccuracies_per_game']:.1f} inaccuracies   (avg cp loss {a['avg_cp_loss']:.0f})"
        )
    else:
        st.text(f"Engine   not run yet.  python cli.py analyze {platform}:{username}")

    st.subheader("By color")
    st.text(table(results.by_color(games), WDL, "color"))

    st.subheader("By opponent rating")
    st.text("Opponent's rating compared with yours at the time.")
    st.text(table(results.by_rating_band(games), WDL, "opponent"))

    st.subheader("By opening")
    min_games = st.number_input("Minimum games per opening", min_value=1, value=3, step=1)
    openings = results.by_opening(games, min_games=int(min_games))
    st.text(table(openings, WDL, ["opening", "color"]) if not openings.empty else f"No opening with {min_games}+ games.")

    st.subheader("Rating by month")
    st.text(table(
        results.rating_by_month(games),
        {"rating": ("rating", ""), "change": ("change", "signed"), "games": ("games", ""), "score_pct": ("score", "pct")},
        "month",
    ))


def _value(f: weaknesses.Finding, v: float) -> str:
    return f"{v:.0f} cp" if f.unit == "cp" else f"{v:.1f}%" if v < 10 else fmt(v, "pct")


def weaknesses_page(conn: sqlite3.Connection, platform: str, username: str, time_class: str | None, games: pd.DataFrame) -> None:
    findings = weaknesses.all_findings(conn, platform, username, time_class, games)
    if not findings:
        st.text(f"No engine analysis yet. Run:  python cli.py analyze {platform}:{username}")
        return

    top = weaknesses.top(findings)
    if not top:
        st.text("Nothing stands out: no metric is 10% or more worse than its baseline.")
    for i, f in enumerate(top, start=1):
        st.subheader(f"{i}. {f.title}")
        st.text(f"{f.detail}\nBased on {f.sample}.  {f.severity * 100:.0f}% worse than the baseline.")
        for moment in f.examples:
            view = render_moment(conn, moment.game_id, moment.ply)
            st.markdown(view.svg, unsafe_allow_html=True)
            st.text(view.caption)
            if view.url:
                st.markdown(f"[Open game]({view.url})")
        st.divider()

    st.subheader("All checks")
    st.text("Every metric, ranked. Ones marked * have too few games to trust.")
    rows = pd.DataFrame(
        [{"metric": f.title + ("" if f.min_ok else " *"), "you": _value(f, f.value),
          "baseline": _value(f, f.baseline), "gap": f"{f.severity * 100:+.0f}%", "sample": f.sample} for f in findings]
    ).set_index("metric")
    st.text(table(rows, {"you": ("you", ""), "baseline": ("baseline", ""), "gap": ("worse by", ""), "sample": ("based on", "")}, "metric"))
