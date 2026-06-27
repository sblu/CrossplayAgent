"""Example agent scaffold — a heuristic that looks past immediate score.

Use this as a template for new strategies. The contract is the `Agent` ABC
(crossplay/strategy/base.py): implement `choose_move(board, rack) -> move | None`.

`GreedyAgent` maximises the points scored *this* turn. This agent instead scores
each candidate move by:

    evaluation = points_this_turn  +  LEAVE_WEIGHT * value_of_tiles_left_on_rack

The "leave" (the tiles you keep) matters because a balanced rack — vowels and
consonants, an S or a blank held back — sets up better future turns. This is the
single most important idea separating strong word-game bots from greedy ones.

Extension points are marked TODO. Good next steps: weight leave by how many tiles
remain in the bag, add vowel/consonant balance, or replace the static leave table
with values learned from the self-play data that selfplay.py already logs.
"""
from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.move_generator import generate_moves
from crossplay.strategy.base import Agent, move_key

# Relative weight of the rack leave vs. immediate points. 1.0 = a leave point is
# worth a board point; tune via self-play on the leaderboard.
LEAVE_WEIGHT = 1.0

# Rough per-tile "keep" values (illustrative, loosely Scrabble-leave-inspired).
# Positive = a tile worth holding; negative = a tile you'd rather offload.
_LEAVE_VALUE: dict[str, float] = {
    '?': 24.0, 'S': 7.0, 'E': 2.0, 'A': 1.5, 'R': 1.5, 'H': 1.0, 'N': 1.0,
    'T': 1.0, 'I': 0.5, 'D': 0.5, 'L': 0.5, 'O': 0.0, 'C': 0.0, 'M': 0.0,
    'P': 0.0, 'X': 1.0, 'Z': 1.0, 'G': -0.5, 'B': -1.0, 'F': -1.0, 'U': -1.0,
    'Y': -1.0, 'K': -1.5, 'W': -1.5, 'J': -2.0, 'V': -3.0, 'Q': -6.0,
}
_DUPLICATE_PENALTY = 1.5   # per extra copy of the same letter held


class HeuristicAgent(Agent):
    def __init__(self, dictionary: Dictionary, leave_weight: float = LEAVE_WEIGHT):
        self._dictionary = dictionary
        self._leave_weight = leave_weight

    def choose_move(self, board: Board, rack: list[str],
                    exclude: set | None = None) -> dict | None:
        moves = generate_moves(board, rack, self._dictionary)
        if exclude:
            moves = [m for m in moves if move_key(m) not in exclude]
        if not moves:
            return None
        # Evaluate each candidate; tie-break by raw score so behaviour is stable.
        return max(moves, key=lambda m: (self._evaluate(m, rack), m["score"]))

    def _evaluate(self, move: dict, rack: list[str]) -> float:
        leave = self._leave_after(move, rack)
        return move["score"] + self._leave_weight * self._leave_value(leave)

    @staticmethod
    def _leave_after(move: dict, rack: list[str]) -> list[str]:
        """The tiles remaining on the rack after playing `move`."""
        blanks = move.get("blanks", {})
        consumed = [
            '?' if (idx in blanks or str(idx) in blanks) else move["word"][idx]
            for idx in move["tiles_played"]
        ]
        leave = list(rack)
        for tile in consumed:
            if tile in leave:
                leave.remove(tile)
        return leave

    @staticmethod
    def _leave_value(leave: list[str]) -> float:
        value = sum(_LEAVE_VALUE.get(t, 0.0) for t in leave)
        # Penalise duplicates — a rack of EEEE is hard to use.
        for tile in set(leave):
            extra = leave.count(tile) - 1
            if extra > 0:
                value -= _DUPLICATE_PENALTY * extra
        # TODO: weight by bag_remaining (leave matters less near game end),
        # TODO: reward vowel/consonant balance.
        return value
