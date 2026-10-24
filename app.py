# app.py
"""DownChess dashboard.  Run with:  streamlit run app.py

Plain white-on-black text by design. Tables are fixed-width text, and the
only images will be chess boards (added with the weakness report in Step 4).
"""

from __future__ import annotations

import os

import streamlit as st

from db import store
from stats import results
from stats.games import player_games, stored_players, time_classes
from ui.text import table

WDL = {"games": ("games", ""), "wins": ("W", ""), "draws": ("D", ""), "losses": ("L", ""), "score_pct": ("score", "pct")}

st.set_page_config(page_title="DownChess", layout="centered")
# Strip the remaining decoration: no colored header bar, no rounded boxes.
st.markdown(
    """<style>
    header[data-testid="stHeader"] {background: #000;}
    section[data-testid="stSidebar"] {border-right: 1px solid #fff;}
    pre, code, .stText {font-family: monospace; color: #fff; background: #000 !important;}
    hr {border-color: #fff;}
    </style>""",
    unsafe_allow_html=True,
)


# A fresh connection per rerun: Streamlit reruns on different threads and
# sqlite3 connections can't be shared across threads. Opening one is cheap.
conn = store.connect(os.environ.get("DOWNCHESS_DB", store.DEFAULT_DB))
players = stored_players(conn)

st.title("DownChess")

if not players:
    st.text("No players stored yet. Fetch some games first:\n\n"
            "  python cli.py fetch chesscom:<user>\n  python cli.py fetch lichess:<user>")
    st.stop()

with st.sidebar:
    platform, username = st.selectbox("Player", players, format_func=lambda p: f"{p[0]}:{p[1]}")
    classes = time_classes(conn, platform, username)
    options = classes + ["all"]
    default = options.index("rapid") if "rapid" in options else 0
    choice = st.selectbox("Time control", options, index=default)

time_class = None if choice == "all" else choice
games = player_games(conn, platform, username, time_class)

st.text(f"{platform}:{username}  |  {choice}  |  {len(games)} games")

if games.empty:
    st.text("No games for this time control.")
    st.stop()

o = results.overall(games)
first, last = games["played_at"].min(), games["played_at"].max()
st.text(
    f"Record   {o['wins']}W {o['draws']}D {o['losses']}L   score {o['score_pct']:.0f}%\n"
    f"Period   {first:%Y-%m-%d} to {last:%Y-%m-%d}"
)

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
