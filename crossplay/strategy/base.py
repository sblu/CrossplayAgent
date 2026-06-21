from abc import ABC, abstractmethod
from crossplay.engine.board import Board


class Agent(ABC):
    @abstractmethod
    def choose_move(self, board: Board, rack: list[str]) -> dict | None:
        """Return the chosen move dict, or None if no legal moves are available."""
