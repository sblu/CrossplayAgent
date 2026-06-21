import pytest
from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves
from crossplay.strategy.greedy import GreedyAgent


@pytest.fixture
def agent(tmp_path):
    word_file = tmp_path / "words.txt"
    word_file.write_text("CAT\nBAT\nRAT\nCARD\nCARDS\n")
    d = Dictionary.load(str(word_file))
    return GreedyAgent(dictionary=d)


def test_greedy_picks_highest_score(agent):
    board = Board()
    rack = ["C", "A", "R", "D", "S", "T", "B"]
    move = agent.choose_move(board, rack)
    assert move is not None
    all_moves = generate_moves(board, rack, agent._dictionary)
    best_score = max(m["score"] for m in all_moves)
    assert move["score"] == best_score


def test_greedy_returns_none_with_no_moves(agent):
    board = Board()
    rack = ["X", "X", "X", "X", "X", "X", "X"]
    move = agent.choose_move(board, rack)
    assert move is None
