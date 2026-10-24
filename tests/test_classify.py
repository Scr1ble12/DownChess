# tests/test_classify.py
import chess
import pytest

from engine.classify import classify_game, label, move_accuracy, phase, win_percent


@pytest.mark.parametrize("loss,expected", [(0, "ok"), (49, "ok"), (50, "inaccuracy"), (100, "mistake"), (299, "mistake"), (300, "blunder")])
def test_labels(loss, expected):
    assert label(loss) == expected


def test_phase():
    assert phase(10, chess.STARTING_FEN) == "opening"
    assert phase(30, chess.STARTING_FEN) == "middlegame"
    # each side: rook + bishop = 8 points of non-pawn material
    assert phase(60, "r3k3/pp3ppp/2b5/8/8/8/PP3PPP/R3KB2 w - - 0 30") == "endgame"
    # White still has queen + two rooks (19) -> middlegame
    assert phase(60, "r3k3/pp3ppp/8/8/8/8/PP3PPP/RR2K1Q1 w - - 0 30") == "middlegame"


def test_win_percent_and_accuracy():
    assert win_percent(0) == pytest.approx(50)
    assert win_percent(1000) > 95 and win_percent(-1000) < 5
    assert move_accuracy(60, 60) == pytest.approx(100, abs=0.1)
    assert move_accuracy(60, 20) < 20
    assert move_accuracy(40, 70) == pytest.approx(100, abs=0.1)  # improving is never penalised


def test_classify_uses_mover_point_of_view():
    fen = chess.STARTING_FEN
    moves = [(9, fen), (10, fen), (11, fen)]
    # White eval: +20 before ply 9, White plays a good move (+30), Black blunders (+400), White drops to +250
    evals = {8: 20, 9: 30, 10: 400, 11: 250}
    rows = {r[0]: r for r in classify_game(moves, evals)}
    assert rows[9][1:4] == (0, "ok", "opening")
    assert rows[10][1:3] == (370, "blunder")  # Black's view: -30 -> -400
    assert rows[11][1:3] == (150, "mistake")
    assert rows[9][4] > 99 and rows[10][4] < rows[11][4]


def test_classify_skips_moves_without_evals():
    fen = chess.STARTING_FEN
    assert classify_game([(1, fen), (2, fen)], {}) == []
