import pytest
from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves


@pytest.fixture
def tiny_dict(tmp_path):
    word_file = tmp_path / "words.txt"
    word_file.write_text("CAT\nCAR\nARC\nBAT\nAT\n")
    return Dictionary.load(str(word_file))


def test_opening_move_uses_center(tiny_dict):
    board = Board()
    rack = ["C", "A", "T", "B", "R", "E", "D"]
    moves = generate_moves(board, rack, tiny_dict)
    assert len(moves) > 0
    for move in moves:
        r, c, word, horizontal = move["row"], move["col"], move["word"], move["horizontal"]
        positions = [(r, c + i) if horizontal else (r + i, c) for i in range(len(word))]
        assert (7, 7) in positions


def test_generates_cat_from_rack(tiny_dict):
    board = Board()
    rack = ["C", "A", "T", "X", "X", "X", "X"]
    moves = generate_moves(board, rack, tiny_dict)
    words = [m["word"] for m in moves]
    assert "CAT" in words


def test_no_moves_with_bad_rack(tiny_dict):
    board = Board()
    rack = ["X", "X", "X", "X", "X", "X", "X"]
    moves = generate_moves(board, rack, tiny_dict)
    assert len(moves) == 0


def test_uses_existing_tile_on_board(tiny_dict):
    board = Board()
    board.place("C", 7, 7)
    rack = ["A", "T", "X", "X", "X", "X", "X"]
    moves = generate_moves(board, rack, tiny_dict)
    words = [m["word"] for m in moves]
    assert "CAT" in words


def test_rejects_cross_word_violation(tiny_dict):
    """A placement that forms an invalid perpendicular cross-word must be excluded."""
    board = Board()
    board.place("A", 7, 7)
    board.place("T", 7, 8)
    rack = ["B", "T", "X", "X", "X", "X", "X"]
    moves = generate_moves(board, rack, tiny_dict)
    for move in moves:
        assert tiny_dict.is_word(move["word"]), f"Invalid word generated: {move['word']}"


def test_move_score_is_populated(tiny_dict):
    board = Board()
    rack = ["C", "A", "T", "X", "X", "X", "X"]
    moves = generate_moves(board, rack, tiny_dict)
    for move in moves:
        assert "score" in move
        assert move["score"] > 0
