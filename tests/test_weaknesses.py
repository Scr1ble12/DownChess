# tests/test_weaknesses.py
"""Each weakness metric on small hand-built data."""

import pandas as pd
import pytest

from stats import weaknesses as w


def moves_frame(rows):
    """rows: dicts with game_id, ply, cp_loss and optional overrides."""
    base = {"label": "ok", "phase": "middlegame", "san": "e4", "uci": "e2e4", "fen_before": "",
            "clock_remaining_s": 300.0, "base_seconds": 600, "url": None, "result": "1-0",
            "opening_name": "Italian Game", "eco": "C50", "color": "white",
            "played_at": "2026-09-01T12:00:00+00:00"}
    return pd.DataFrame([{**base, **r} for r in rows])


def test_phase_weakness_picks_worst_phase():
    rows = [{"game_id": g, "ply": p, "cp_loss": 80 if ph == "endgame" else 20, "phase": ph}
            for g in range(10) for p, ph in enumerate(["opening"] * 15 + ["middlegame"] * 15 + ["endgame"] * 15)]
    f = w.phase_weakness(moves_frame(rows))
    assert f.title == "Endgame play"
    assert (round(f.value), round(f.baseline)) == (80, 20)
    assert f.severity == pytest.approx(3.0)
    assert f.flagged and len(f.examples) == w.EXAMPLES


def test_phase_weakness_needs_enough_moves():
    rows = [{"game_id": 1, "ply": p, "cp_loss": 10, "phase": "opening"} for p in range(5)]
    assert w.phase_weakness(moves_frame(rows)) is None


def test_weak_openings_compares_with_overall_score():
    rows = []
    for g in range(30):
        sicilian = g < 10
        rows.append({"game_id": g, "ply": 1, "cp_loss": 0,
                     "opening_name": "Sicilian Defense" if sicilian else "Italian Game",
                     "result": "0-1" if sicilian else "1-0"})
    f = w.weak_openings(moves_frame(rows))
    assert f.title == "Sicilian Defense as white"
    assert f.value == 0 and f.baseline == pytest.approx(100 * 20 / 30)
    assert f.sample == "10 games"


def test_time_trouble_uses_two_minute_floor():
    rows = []
    for g in range(10):
        for p in range(10):  # 5 moves under 2 minutes, 1 of them a blunder
            low = p >= 5
            rows.append({"game_id": g, "ply": p, "clock_remaining_s": 90.0 if low else 400.0,
                         "cp_loss": 400 if (low and p == 9) else (400 if (not low and g == 0 and p == 0) else 10)})
    f = w.time_trouble(moves_frame(rows))
    assert f.value == pytest.approx(20.0)  # 10 blunders / 50 low-clock moves
    assert f.baseline == pytest.approx(2.0)  # 1 / 50
    assert f.min_ok and f.flagged


def test_thrown_wins_against_opponents_rate():
    rows, evals = [], []
    for g in range(40):
        i_was_winning = g < 20
        # of my 20 winning games I win 10; opponents win 18 of their 20
        result_mine = "1-0" if (i_was_winning and g < 10) or (not i_was_winning and g >= 38) else "0-1"
        rows.append({"game_id": g, "ply": 21, "cp_loss": 50, "result": result_mine})
        evals.append({"game_id": g, "ply": 20, "my_eval": 400 if i_was_winning else -400})
    f = w.thrown_wins(moves_frame(rows), pd.DataFrame(evals))
    assert (f.value, f.baseline) == (50.0, 10.0)
    assert f.severity == pytest.approx(4.0)


def test_tilt_compares_after_loss_with_after_win():
    # Pairs of games 30 minutes apart, pairs 5 hours apart (so only the
    # second game of each pair counts). After a win: 16/20 won. After a loss: 8/20.
    rows, t, gid = [], pd.Timestamp("2026-09-01T12:00:00Z"), 0
    pairs = [("1-0", "1-0" if i < 16 else "0-1") for i in range(20)] + [("0-1", "1-0" if i < 8 else "0-1") for i in range(20)]
    for first, second in pairs:
        for offset, r in ((0, first), (30, second)):
            rows.append({"game_id": gid, "ply": 1, "cp_loss": 0, "result": r,
                         "played_at": (t + pd.Timedelta(minutes=offset)).isoformat()})
            gid += 1
        t += pd.Timedelta(hours=5)
    f = w.tilt(moves_frame(rows))
    assert (f.value, f.baseline) == (40.0, 80.0)
    assert f.severity == pytest.approx(0.5) and f.sample == "20 games right after a loss"


def test_rating_gap_against_lower_rated():
    games = pd.DataFrame({
        "id": range(40),
        "my_elo": [1500] * 40,
        "opp_elo": [1300] * 20 + [1500] * 20,
        "score": [0.0] * 10 + [1.0] * 10 + [0.5] * 20,
    })
    f = w.rating_gap(games, moves_frame([{"game_id": i, "ply": 1, "cp_loss": 0} for i in range(40)]))
    assert f.title == "Against lower-rated opponents"
    assert f.value == 50.0 and f.baseline == pytest.approx(76.0, abs=0.1)


def test_top_skips_small_samples_and_small_gaps():
    mk = lambda key, sev, ok=True: w.Finding(key, key, 0, 0, "pct", "", "", sev, min_ok=ok)
    findings = [mk("a", 0.9, ok=False), mk("b", 0.5), mk("c", 0.3), mk("d", 0.2), mk("e", 0.05)]
    assert [f.key for f in w.top(findings)] == ["b", "c", "d"]
