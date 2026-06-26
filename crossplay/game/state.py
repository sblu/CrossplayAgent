"""Authoritative, headless Crossplay game state.

Implements a full multi-seat game — tile bag, per-seat racks, scoring, turn order,
and end-of-game conditions — entirely in Python, reusing the existing rules engine
(`Board`, `score_move`, `LETTER_VALUES`). No device or app involved. This is the
foundation for self-play: two (or more) `Agent`s take turns against one shared
`GameState`.

Known limitation (matches what the on-device bot can perceive): a blank tile is
stored on the board as its assigned letter, and `score_move` does not track which
existing board tiles were blanks. So a blank already on the board will contribute
its face letter value to *future* cross-words. `blank_cells` records blank
positions so a future scorer can correct this; today it is informational only.
"""
from dataclasses import dataclass, field

from crossplay.engine.board import Board, LETTER_VALUES
from crossplay.engine.scorer import score_move

RACK_SIZE = 7


def _tile_value(tile: str) -> int:
    """Face value of a rack/leftover tile. Blanks ('?') are worth 0."""
    if tile == '?':
        return 0
    return LETTER_VALUES.get(tile, 0)


@dataclass
class TurnRecord:
    seat: int
    action: str            # "play" or "pass"
    move: dict | None
    score: int
    rack_before: list[str]


@dataclass
class GameState:
    board: Board
    bag: "TileBag"
    racks: list[list[str]]
    scores: list[int]
    turn: int = 0
    passes_in_row: int = 0
    blank_cells: set[tuple[int, int]] = field(default_factory=set)
    history: list[TurnRecord] = field(default_factory=list)

    @property
    def n_players(self) -> int:
        return len(self.racks)

    @classmethod
    def new(cls, n_players: int = 2, seed: int | None = None) -> "GameState":
        from crossplay.game.bag import TileBag
        bag = TileBag(seed)
        racks = [bag.draw(RACK_SIZE) for _ in range(n_players)]
        return cls(board=Board(), bag=bag, racks=racks, scores=[0] * n_players)

    def rack(self, seat: int) -> list[str]:
        return self.racks[seat]

    # ── Mutating actions ────────────────────────────────────────────────────

    def apply_move(self, move: dict, seat: int) -> int:
        """Validate, score, place, refill, and advance the turn. Returns the score.

        Scoring is computed against the board *before* the new tiles are placed,
        exactly as `move_generator` does.
        """
        if seat != self.turn:
            raise ValueError(f"not seat {seat}'s turn (turn={self.turn})")

        word = move["word"]
        row, col = move["row"], move["col"]
        horizontal = move["horizontal"]
        tiles_played = move["tiles_played"]
        blanks = move.get("blanks", {})

        def _is_blank(idx: int) -> bool:
            return idx in blanks or str(idx) in blanks

        # Score first — board still holds only the pre-existing tiles.
        score = score_move(self.board, move)

        # Consume the played tiles from the rack ('?' for blanks).
        rack = list(self.racks[seat])
        for idx in tiles_played:
            tile = '?' if _is_blank(idx) else word[idx]
            try:
                rack.remove(tile)
            except ValueError:
                raise ValueError(
                    f"tile {tile!r} for word index {idx} not in rack {self.racks[seat]}"
                )

        # Place tiles on the board (blanks store their assigned letter).
        for idx in tiles_played:
            r = row if horizontal else row + idx
            c = col + idx if horizontal else col
            if self.board.get(r, c) is not None:
                raise ValueError(f"cell ({r},{c}) already occupied")
            self.board.place(word[idx], r, c)
            if _is_blank(idx):
                self.blank_cells.add((r, c))

        rack_before = list(self.racks[seat])
        rack.extend(self.bag.draw(len(tiles_played)))
        self.racks[seat] = rack
        self.scores[seat] += score
        self.passes_in_row = 0
        self.history.append(TurnRecord(seat, "play", move, score, rack_before))
        self.turn = (self.turn + 1) % self.n_players
        return score

    def pass_turn(self, seat: int) -> None:
        if seat != self.turn:
            raise ValueError(f"not seat {seat}'s turn (turn={self.turn})")
        self.history.append(TurnRecord(seat, "pass", None, 0, list(self.racks[seat])))
        self.passes_in_row += 1
        self.turn = (self.turn + 1) % self.n_players

    # ── End-of-game ─────────────────────────────────────────────────────────

    def rack_value(self, seat: int) -> int:
        return sum(_tile_value(t) for t in self.racks[seat])

    def _player_went_out(self) -> int | None:
        """Seat that emptied its rack with the bag empty, else None."""
        if self.bag.remaining() > 0:
            return None
        for seat in range(self.n_players):
            if not self.racks[seat]:
                return seat
        return None

    def is_over(self) -> bool:
        # Everyone passed for two full rounds → dead game.
        if self.passes_in_row >= 2 * self.n_players:
            return True
        # A player went out (empty rack) and the bag is empty.
        return self._player_went_out() is not None

    def final_scores(self) -> list[int]:
        """Scores adjusted for leftover racks (standard Scrabble end-game rule).

        If a player went out, they gain the sum of everyone else's leftover rack
        value and the others each lose their own; otherwise (passed-out game)
        every player loses their own leftover rack value.
        """
        final = list(self.scores)
        out = self._player_went_out()
        if out is not None:
            gained = 0
            for seat in range(self.n_players):
                if seat == out:
                    continue
                val = self.rack_value(seat)
                final[seat] -= val
                gained += val
            final[out] += gained
        else:
            for seat in range(self.n_players):
                final[seat] -= self.rack_value(seat)
        return final

    def winner(self) -> int | None:
        """Seat with the highest final score, or None on a tie."""
        final = self.final_scores()
        best = max(final)
        leaders = [s for s, v in enumerate(final) if v == best]
        return leaders[0] if len(leaders) == 1 else None
