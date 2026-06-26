import pytest

from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves
from crossplay.strategy.heuristic import HeuristicAgent
from crossplay.strategy.registry import AGENTS, build_agent


@pytest.fixture
def agent(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("CAT\nBAT\nRAT\nCARD\nCARDS\nAT\n")
    return HeuristicAgent(Dictionary.load(str(f)))


def test_returns_a_legal_move(agent):
    board = Board()
    rack = ["C", "A", "R", "D", "S", "T", "B"]
    move = agent.choose_move(board, rack)
    assert move is not None
    legal = generate_moves(board, rack, agent._dictionary)
    assert (move["word"], move["row"], move["col"], move["horizontal"]) in \
        {(m["word"], m["row"], m["col"], m["horizontal"]) for m in legal}


def test_returns_none_with_no_moves(agent):
    move = agent.choose_move(Board(), ["X", "X", "X", "X", "X", "X", "X"])
    assert move is None


def test_leave_value_prefers_keeping_blank_and_s():
    assert HeuristicAgent._leave_value(["?"]) > HeuristicAgent._leave_value(["Q"])
    assert HeuristicAgent._leave_value(["S"]) > HeuristicAgent._leave_value(["V"])


def test_leave_penalises_duplicates():
    assert HeuristicAgent._leave_value(["E", "A"]) > HeuristicAgent._leave_value(["E", "E"])


def test_registered_in_registry(tmp_path):
    f = tmp_path / "w.txt"
    f.write_text("CAT\nAT\n")
    d = Dictionary.load(str(f))
    assert "heuristic" in AGENTS
    assert isinstance(build_agent("heuristic", d), HeuristicAgent)
