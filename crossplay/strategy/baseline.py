"""Deliberately weak baseline agents — benchmarks to measure real strategies against.

A strong agent should beat these decisively; a leaderboard that can't separate
`GreedyAgent` from `WeakAgent` isn't measuring anything. These also give the
progress charts a non-trivial spread to plot.
"""
from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves
from crossplay.strategy.base import Agent


class WeakAgent(Agent):
    """Plays the lowest-scoring legal move (a sane floor for benchmarking)."""

    def __init__(self, dictionary: Dictionary):
        self._dictionary = dictionary

    def choose_move(self, board: Board, rack: list[str]) -> dict | None:
        moves = generate_moves(board, rack, self._dictionary)
        if not moves:
            return None
        return min(moves, key=lambda m: m["score"])
