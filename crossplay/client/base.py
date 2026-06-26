"""Device-agnostic client interface (the "port" in ports-and-adapters).

The core game loop (`crossplay.runner.run`) drives any backend that implements
`CrossplayClient`, speaking only in game-level terms — an `Observation` (board,
rack, whose turn, game over) and a canonical move dict. Every device-specific
detail (pixels, accessibility trees, popups, keep-alive, opponent simulation)
lives inside a concrete client and never leaks into the loop or the agent.

Canonical move dict (same schema produced by `move_generator` / consumed by
`scorer`):

    {
        "word": str,              # full word incl. existing board tiles
        "row": int, "col": int,   # start cell of the word
        "horizontal": bool,
        "tiles_played": list[int],# indices into `word` of NEW tiles from the rack
        "blanks": dict[int, str], # {word_idx: assigned_letter} for blanks, else {}
        "score": int,
    }
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Observation:
    """A snapshot of the game from our seat's perspective."""
    board: list[list[str | None]]   # 15x15 grid; letters or None
    rack: list[str | None]          # up to 7 entries; '?' marks a blank tile
    is_our_turn: bool
    game_over: bool


class CrossplayClient(ABC):
    """Abstract backend: iOS, Android, or a headless simulator.

    Use as a context manager:

        with build_client(...) as client:
            run(client, agent)
    """

    def __enter__(self) -> "CrossplayClient":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        """Connect to the device / start a game. Override if needed."""

    def close(self) -> None:
        """Disconnect / tear down. Override if needed."""

    @abstractmethod
    def wait_for_turn(self, timeout: float = 300) -> bool:
        """Block until it is our move.

        Backends handle their own keep-alive, popup dismissal, and opponent
        simulation here. Returns False on timeout or when the game is over.
        """

    @abstractmethod
    def observe(self) -> Observation:
        """Return the current board, rack, and turn/over flags."""

    @abstractmethod
    def play_move(self, move: dict) -> bool:
        """Execute a move (place tiles, assign blanks, submit).

        Returns False if the move could not be carried out.
        """

    @abstractmethod
    def pass_turn(self) -> None:
        """Pass / forfeit the current turn."""
