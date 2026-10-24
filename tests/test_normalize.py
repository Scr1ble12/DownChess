# tests/test_normalize.py
import json

import pytest

from fetch.normalize import (
    SkipGame,
    _chesscom_opening_name,
    normalize_chesscom,
    normalize_lichess,
    parse_time_control,
    time_class_from_seconds,
)
from tests.fakes import fixture


def chesscom_games():
    return json.loads(fixture("chesscom_2026_09.json"))["games"]


def lichess_games():
    return [json.loads(line) for line in fixture("lichess_games.ndjson").splitlines()]


def test_chesscom_rapid_game():
    g = normalize_chesscom(chesscom_games()[0])
    assert (g.platform, g.platform_game_id) == ("chesscom", "150000000001")
    assert (g.white, g.black, g.result) == ("AjTest", "opponent1", "1-0")
    assert (g.white_elo, g.black_elo) == (1210, 1195)
    assert (g.time_class, g.base_seconds, g.increment_seconds) == ("rapid", 600, 0)
    assert g.eco == "C23"
    assert g.opening_name == "Bishops Opening"
    assert g.played_at == "2026-09-03T18:20:05+00:00"
    assert [m.san for m in g.moves] == ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    assert g.moves[0].clock_remaining_s == pytest.approx(598.1)
    assert g.moves[0].fen_before.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")
    assert g.evals == []


def test_chesscom_skips_variants():
    with pytest.raises(SkipGame):
        normalize_chesscom(chesscom_games()[2])


def test_lichess_game_with_evals_and_clocks():
    g = normalize_lichess(lichess_games()[0])
    assert (g.platform, g.platform_game_id, g.url) == ("lichess", "AbCdEfGh", "https://lichess.org/AbCdEfGh")
    assert (g.white, g.black, g.result) == ("AjTest", "rival", "0-1")
    assert (g.time_class, g.time_control) == ("rapid", "600+0")
    assert (g.eco, g.opening_name) == ("C50", "Italian Game")
    assert len(g.moves) == 10
    assert g.moves[8].san == "Nxe5" and g.moves[8].clock_remaining_s == 560
    assert g.evals[0].eval_cp == 30
    blunder, mate = g.evals[8], g.evals[9]
    assert blunder.eval_cp == -350 and blunder.mate_in is None
    assert mate.mate_in == -6 and mate.eval_cp == -1000  # capped


def test_lichess_skips_variants():
    with pytest.raises(SkipGame):
        normalize_lichess(lichess_games()[2])


@pytest.mark.parametrize("tc,expected", [("600", (600, 0)), ("900+10", (900, 10)), ("1/259200", (None, None)), ("-", (None, None))])
def test_parse_time_control(tc, expected):
    assert parse_time_control(tc) == expected


def test_time_class_rules():
    assert time_class_from_seconds(60, 0) == "bullet"
    assert time_class_from_seconds(180, 2) == "blitz"
    assert time_class_from_seconds(600, 0) == "rapid"
    assert time_class_from_seconds(1800, 0) == "classical"


def test_opening_name_drops_move_list():
    url = "https://www.chess.com/openings/Sicilian-Defense-Open-2...Nc6-3.d4"
    assert _chesscom_opening_name(url) == "Sicilian Defense Open"
