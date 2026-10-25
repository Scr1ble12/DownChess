# app.py
"""DownChess dashboard.  Run with:  streamlit run app.py

Plain white-on-black text by design. Tables are fixed-width text, and the
only images are chess boards (weaknesses and game review pages).
"""

from __future__ import annotations

import os

import streamlit as st

from db import store
from stats.games import player_games, stored_players, time_classes
from ui import views
from ui.review import review_page

st.set_page_config(page_title="DownChess", layout="centered")
# Strip the remaining decoration: no colored header bar, no rounded boxes.
st.markdown(
    """<style>
    header[data-testid="stHeader"] {background: #000;}
    section[data-testid="stSidebar"] {border-right: 1px solid #fff;}
    pre, code, .stText {font-family: monospace; color: #fff; background: #000 !important;}
    hr {border-color: #fff;}
    a {color: #fff !important;}
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
    page = st.radio("Page", ["Stats", "Top 3 weaknesses", "Game review"])
    platform, username = st.selectbox("Player", players, format_func=lambda p: f"{p[0]}:{p[1]}")
    classes = time_classes(conn, platform, username)
    options = classes + ["all"]
    default = options.index("rapid") if "rapid" in options else 0
    choice = st.selectbox("Time control", options, index=default)

time_class = None if choice == "all" else choice
games = player_games(conn, platform, username, time_class)

st.text(f"{platform}:{username}  |  {choice}  |  {len(games)} games")

if page == "Game review":  # also reviews pasted games, so it runs without stored ones
    review_page(conn, platform, username, games)
    st.stop()

if games.empty:
    st.text("No games for this time control.")
    st.stop()

if page == "Stats":
    views.stats_page(conn, platform, username, time_class, games)
else:
    views.weaknesses_page(conn, platform, username, time_class, games)
