from crossplay.strategy.base import Agent
from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves


class GreedyAgent(Agent):
    def __init__(self, dictionary: Dictionary):
        self._dictionary = dictionary

    def choose_move(self, board: Board, rack: list[str]) -> dict | None:
        moves = generate_moves(board, rack, self._dictionary)
        if not moves:
            return None
        return max(moves, key=lambda m: m["score"])
