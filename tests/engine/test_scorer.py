import pytest
from crossplay.engine.board import Board
from crossplay.engine.scorer import score_move


def test_score_simple_word_no_premium():
    board = Board()
    # Place "CAT" at row=2, col=0 — all three cells are NORMAL in Crossplay's layout.
    # Crossplay values: C=3, A=1, T=1. No multipliers → 5
    move = {"word": "CAT", "row": 2, "col": 0, "horizontal": True, "tiles_played": [0, 1, 2]}
    assert score_move(board, move) == 5


def test_score_existing_tile_not_doubled():
    board = Board()
    board.place("C", 2, 0)
    # Playing A,T onto existing C. Premium squares only apply to NEW tiles.
    # New tiles at (2,1)=NORMAL, (2,2)=NORMAL — no multipliers.
    # C(3) + A(1) + T(1) = 5
    move = {"word": "CAT", "row": 2, "col": 0, "horizontal": True, "tiles_played": [1, 2]}
    assert score_move(board, move) == 5


def test_score_triple_word():
    board = Board()
    board.place("A", 7, 7)  # center already filled so this is a legal extension
    # Place "CAT" at row=0, col=3 — (0,3) is TW in Crossplay
    # C(3)+A(1)+T(1)=5, all new, TW at col 3 → *3 = 15
    move = {"word": "CAT", "row": 0, "col": 3, "horizontal": True, "tiles_played": [0, 1, 2]}
    assert score_move(board, move) == 15


def test_score_double_letter():
    board = Board()
    board.place("A", 7, 7)
    # Place "CAT" at row=0, col=7 — (0,7) is DL in Crossplay (col 7, row 0)
    # C at (0,7) DL → C*2=6, A at (0,8) NORMAL=1, T at (0,9) NORMAL=1 → 8
    move = {"word": "CAT", "row": 0, "col": 7, "horizontal": True, "tiles_played": [0, 1, 2]}
    assert score_move(board, move) == 8


def test_score_double_word():
    board = Board()
    board.place("A", 7, 7)
    # Place "CAT" at row=1, col=1 — (1,1) is DW in Crossplay
    # C(3)+A(1)+T(1)=5, all new, DW → *2 = 10
    move = {"word": "CAT", "row": 1, "col": 1, "horizontal": True, "tiles_played": [0, 1, 2]}
    assert score_move(board, move) == 10


def test_bingo_bonus_40():
    board = Board()
    # Play 7 new tiles on an empty board to test the bingo bonus in isolation.
    # "CABINET" at row=6, col=3: cells (6,3)-(6,9) are all NORMAL in Crossplay's layout
    # (only premium squares in row 6 are TL at cols 1 and 13).
    # C(3)+A(1)+B(4)+I(1)+N(1)+E(1)+T(1) = 12, no multipliers, no cross-words → 12 + 40 bingo = 52
    move = {"word": "CABINET", "row": 6, "col": 3, "horizontal": True, "tiles_played": [0, 1, 2, 3, 4, 5, 6]}
    assert score_move(board, move) == 52
