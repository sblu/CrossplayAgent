"""Simulated, single-seat backend.

Presents the `CrossplayClient` interface for one seat of a headless `GameState`,
auto-playing the other seat(s) with a supplied opponent `Agent`. This lets the
*exact same* `runner.run()` loop execute with no device and no app — a real
integration test of the loop and a zero-hardware smoke test of the whole stack.

For bulk evaluation / training-data generation, prefer `selfplay.py`, which drives
both seats directly against `GameState` (faster, symmetric, fully logged).
"""
from crossplay.client.base import CrossplayClient, Observation
from crossplay.game.state import GameState
from crossplay.strategy.base import Agent


class SimClient(CrossplayClient):
    def __init__(
        self,
        opponent: Agent,
        *,
        our_seat: int = 0,
        n_players: int = 2,
        seed: int | None = None,
        state: GameState | None = None,
    ):
        self._opp = opponent
        self._seat = our_seat
        self._state = state if state is not None else GameState.new(n_players, seed)

    @property
    def state(self) -> GameState:
        return self._state

    def _step_opponent(self) -> None:
        seat = self._state.turn
        move = self._opp.choose_move(self._state.board, self._state.rack(seat))
        if move is None:
            self._state.pass_turn(seat)
        else:
            self._state.apply_move(move, seat)

    def wait_for_turn(self, timeout: float = 300) -> bool:
        while not self._state.is_over() and self._state.turn != self._seat:
            self._step_opponent()
        return not self._state.is_over() and self._state.turn == self._seat

    def observe(self) -> Observation:
        s = self._state
        return Observation(
            board=[row[:] for row in s.board.grid],
            rack=list(s.rack(self._seat)),
            is_our_turn=(not s.is_over() and s.turn == self._seat),
            game_over=s.is_over(),
        )

    def play_move(self, move: dict) -> bool:
        self._state.apply_move(move, self._seat)
        return True

    def pass_turn(self) -> None:
        self._state.pass_turn(self._seat)
