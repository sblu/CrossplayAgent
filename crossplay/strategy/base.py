from abc import ABC, abstractmethod
from crossplay.engine.board import Board


def move_key(move: dict) -> tuple:
    """Identity of a move, for excluding ones that failed on-device."""
    return (move["word"], move["row"], move["col"], move["horizontal"])


class Agent(ABC):
    @abstractmethod
    def choose_move(self, board: Board, rack: list[str],
                    exclude: set | None = None) -> dict | None:
        """Return the chosen move dict, or None if no legal moves are available.

        `exclude` is a set of `move_key(...)` tuples to skip — moves that were
        already tried and rejected by the device this turn.
        """
