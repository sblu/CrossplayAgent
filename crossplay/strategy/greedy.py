from crossplay.strategy.base import Agent, move_key
from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves


class GreedyAgent(Agent):
    def __init__(self, dictionary: Dictionary):
        self._dictionary = dictionary

    def choose_move(self, board: Board, rack: list[str],
                    exclude: set | None = None) -> dict | None:
        moves = generate_moves(board, rack, self._dictionary)
        if exclude:
            moves = [m for m in moves if move_key(m) not in exclude]
        if not moves:
            return None
        return max(moves, key=lambda m: m["score"])
