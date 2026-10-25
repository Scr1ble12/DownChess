"""The game review page: one game, move by move, with Stockfish's verdict on each."""

from __future__ import annotations

import sqlite3

import chess
import pandas as pd
import streamlit as st

from engine import review
from engine.classify import win_percent
from engine.runner import DEFAULT_DEPTH
from ui.board import render_position
from ui.text import table

BAR_WIDTH = 30
ISSUES = ("inaccuracy", "mistake", "blunder")


def _move_no(ply: int) -> str:
    return f"{(ply + 1) // 2}{'.' if ply % 2 else '...'}"


def _eval_bar(cp: int | None) -> str:
    if cp is None:
        return ""
    white = round(win_percent(cp) / 100 * BAR_WIDTH)
    return f"White {'█' * white}{'░' * (BAR_WIDTH - white)} Black"


def _pick_stored(conn: sqlite3.Connection, games: pd.DataFrame) -> review.ReviewGame | None:
    if games.empty:
        st.text("No stored games for this player and time control.")
        return None
    recent = games.sort_values("played_at", ascending=False)
    rows = {int(r.id): r for r in recent.itertuples()}
    analysed = {r[0] for r in conn.execute("SELECT game_id FROM analysed_games")}

    def label(gid: int) -> str:
        r = rows[gid]
        elo = f" ({int(r.opp_elo)})" if pd.notna(r.opp_elo) else ""
        return f"{r.played_at:%Y-%m-%d}  {r.color:<5}  vs {r.opponent}{elo}  {r.outcome}{'' if gid in analysed else '  (not analysed)'}"

    gid = st.selectbox("Game", list(rows), format_func=label)
    return review.stored_game(conn, gid)


def _pick_pasted(conn: sqlite3.Connection) -> review.ReviewGame | None:
    text = st.text_area("Paste a PGN, or a Lichess or Chess.com game link", height=120)
    if not text.strip():
        st.text("Chess.com: open the game, Share > PGN, copy.\n"
                "Lichess: paste the game link, or Share & export > PGN.\n"
                "Chess.com links work for games you've already fetched.")
        return None
    cache = st.session_state.setdefault("review_loaded", {})
    if text not in cache:
        try:
            cache[text] = review.load(conn, text)
        except ValueError as e:
            st.text(str(e))
            return None
        except Exception as e:  # network trouble fetching a Lichess link
            st.text(f"Couldn't load that game: {e}")
            return None
    return cache[text]


def _evals(conn: sqlite3.Connection, game: review.ReviewGame, depth: int) -> review.Evals | None:
    """Saved analysis when it's deep enough. Otherwise stored games get an Analyse
    button (so browsing the list doesn't start Stockfish) and pasted games run at once."""
    if game.game_id is not None:
        saved = review.stored_evals(conn, game.game_id)
        if saved and (saved[1] is None or saved[1] >= depth):
            return saved[0]
        status = "Not analysed yet." if not saved else f"Analysed at depth {saved[1]}."
    else:
        cache = st.session_state.setdefault("review_evals", {})
        key = (tuple(game.ucis), depth)
        if key in cache:
            return cache[key]

    if game.game_id is not None:
        st.text(f"{status} {len(game.moves)} moves; this takes a few seconds per 10 moves.")
        if not st.button(f"Analyse at depth {depth}"):
            return None
    bar = st.progress(0.0, text="Stockfish is thinking...")

    def progress(done: int, total: int) -> None:
        bar.progress(done / total, text=f"Stockfish: position {done} of {total}")

    try:
        if game.game_id is not None:
            evals = review.analyse_stored(conn, game.game_id, depth, progress)
        else:
            evals = cache[key] = review.analyse_moves(game.ucis, depth, progress)
    except FileNotFoundError as e:
        bar.empty()
        st.text(str(e))
        return None
    bar.empty()
    return evals


def _summary(game: review.ReviewGame, reviews: list[review.MoveReview]) -> str:
    s = review.side_summary(reviews)
    df = pd.DataFrame(
        [{"accuracy": "-" if s[c]["accuracy"] is None else f"{s[c]['accuracy']:.1f}", **{k: s[c][k] for k in review.LABELS}}
         for c in ("white", "black")],
        index=[game.white, game.black],
    )
    return table(df, {"accuracy": ("accuracy", ""), "best": ("best", ""), "good": ("good", ""), "book": ("book", ""),
                      "inaccuracy": ("inaccuracy", ""), "mistake": ("mistake", ""), "blunder": ("blunder", "")}, "player")


def _move_list(reviews: list[review.MoveReview]) -> str:
    def cell(r: review.MoveReview | None) -> str:
        if r is None:
            return ""
        return f"{r.san}{review.NAG.get(r.label, '')}".ljust(9) + f"{r.label:<10} {review.fmt_eval(r.eval_cp, r.mate_in):>6}"

    lines = []
    for i in range(0, len(reviews), 2):
        white, black = reviews[i], reviews[i + 1] if i + 1 < len(reviews) else None
        lines.append(f"{(i // 2) + 1:>3}. {cell(white)}   {cell(black)}".rstrip())
    return "\n".join(lines)


def review_page(conn: sqlite3.Connection, platform: str, username: str, games: pd.DataFrame) -> None:
    source = st.radio("Review", ["One of my games", "Paste a PGN or link"], horizontal=True, label_visibility="collapsed")
    game = _pick_stored(conn, games) if source == "One of my games" else _pick_pasted(conn)
    if game is None:
        return
    depth = int(st.number_input("Engine depth", min_value=8, max_value=24, value=DEFAULT_DEPTH, step=1))

    evals = _evals(conn, game, depth)
    if evals is None:
        return
    reviews = review.review_moves(game.moves, evals)
    n = len(reviews)
    if n == 0:
        st.text("This game has no moves.")
        return

    # Reset to the start whenever a different game is picked.
    game_key = (game.game_id, tuple(game.ucis))
    if st.session_state.get("review_game") != game_key:
        st.session_state["review_game"] = game_key
        st.session_state["review_ply"] = 0

    me = username.lower() if username else ""
    my_color = "black" if game.black.lower() == me else "white"

    st.text(f"{game.white} vs {game.black}  {game.result}" + (f"  {game.played_at[:10]}" if game.played_at else ""))
    if game.url:
        st.markdown(f"[Open game]({game.url})")
    st.text(_summary(game, reviews))

    # Navigation. Callbacks run before the widgets below are drawn, so they can set the slider's value.
    def go(ply: int) -> None:
        st.session_state["review_ply"] = max(0, min(n, ply))

    def next_issue(color: str | None) -> None:
        cur = st.session_state["review_ply"]
        nxt = next((r.ply for r in reviews if r.ply > cur and r.label in ISSUES and (color is None or r.mover == color)), None)
        if nxt is not None:
            go(nxt)

    cols = st.columns(5)
    cols[0].button("Start", on_click=go, args=(0,), use_container_width=True)
    cols[1].button("Back", on_click=lambda: go(st.session_state["review_ply"] - 1), use_container_width=True)
    cols[2].button("Next", on_click=lambda: go(st.session_state["review_ply"] + 1), use_container_width=True)
    cols[3].button("End", on_click=go, args=(n,), use_container_width=True)
    cols[4].button("Next error", on_click=next_issue, args=(my_color,), use_container_width=True,
                   help="Jump to your next inaccuracy, mistake or blunder")
    ply = st.slider("Move", 0, n, key="review_ply")
    flip = st.checkbox("Flip board")

    orientation = (chess.BLACK if my_color == "black" else chess.WHITE) ^ flip
    if ply == 0:
        board = chess.Board()
        st.markdown(render_position(board, None, None, orientation), unsafe_allow_html=True)
        st.text("Starting position. Press Next, or drag the slider.")
    else:
        r = reviews[ply - 1]
        board = chess.Board(r.fen_before)
        played = chess.Move.from_uci(r.uci)
        best = chess.Move.from_uci(r.best_uci) if r.best_san else None
        board.push(played)
        st.markdown(render_position(board, played, best, orientation), unsafe_allow_html=True)
        verdict = r.label or "not analysed"
        if r.cp_loss and r.label != "best":
            verdict += f", -{r.cp_loss} cp"
        lines = [f"{_move_no(ply)} {r.san}  {verdict}",
                 f"Eval {review.fmt_eval(r.eval_cp, r.mate_in)}   {_eval_bar(r.eval_cp)}"]
        if r.best_san and r.best_uci != r.uci:
            lines.append(f"Best was {r.best_san} (white arrow). The move played is the dark arrow.")
        elif r.label == "best":
            lines.append("That was the engine's move.")
        st.text("\n".join(lines))

    issues = [r for r in reviews if r.label in ISSUES]
    st.subheader("Key moments")
    if not issues:
        st.text("No inaccuracies, mistakes or blunders.")
    else:
        rows = pd.DataFrame(
            [{"move": f"{_move_no(r.ply)} {r.san}{review.NAG[r.label]}", "who": game.white if r.mover == "white" else game.black,
              "label": r.label, "loss": f"-{r.cp_loss} cp", "best": r.best_san or "-"} for r in issues]
        ).set_index("move")
        st.text(table(rows, {"who": ("player", ""), "label": ("label", ""), "loss": ("loss", ""), "best": ("best", "")}, "move"))

    st.subheader("All moves")
    st.text(_move_list(reviews))
