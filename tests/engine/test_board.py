import pytest
from crossplay.engine.board import Board, CellType

def test_board_is_15x15():
    board = Board()
    assert len(board.grid) == 15
    assert all(len(row) == 15 for row in board.grid)

def test_board_starts_empty():
    board = Board()
    assert board.grid[7][7] is None

def test_center_is_normal():
    board = Board()
    assert board.cell_type(7, 7) == CellType.NORMAL  # center star is just start marker in Crossplay

def test_triple_word_corner():
    board = Board()
    assert board.cell_type(0, 3) == CellType.TRIPLE_WORD

def test_triple_letter_corner():
    board = Board()
    assert board.cell_type(0, 0) == CellType.TRIPLE_LETTER

def test_double_word():
    board = Board()
    assert board.cell_type(1, 1) == CellType.DOUBLE_WORD

def test_double_letter_edge():
    board = Board()
    assert board.cell_type(0, 7) == CellType.DOUBLE_LETTER

def test_place_tile_sets_letter():
    board = Board()
    board.place("A", row=7, col=7)
    assert board.grid[7][7] == "A"

def test_is_empty_initially():
    board = Board()
    assert board.is_empty()

def test_not_empty_after_placement():
    board = Board()
    board.place("A", row=7, col=7)
    assert not board.is_empty()

def test_adjacent_to_placed_tile():
    board = Board()
    board.place("A", row=7, col=7)
    assert board.has_adjacent_tile(7, 8)
    assert not board.has_adjacent_tile(7, 9)
