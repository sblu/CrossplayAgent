"""Seedable Crossplay tile bag.

Built from the game's real tile distribution (`board.TILE_DISTRIBUTION`, 100 tiles
incl. 3 blanks). Blanks are represented as '?' to match the rest of the codebase
(rack entries, move `blanks` dicts). Seeding the RNG makes a game reproducible,
which is what lets self-play run *fair* A/B comparisons (paired/mirror seeds give
both configurations the same tile draws).
"""
import random

from crossplay.engine.board import TILE_DISTRIBUTION


class TileBag:
    def __init__(self, seed: int | None = None):
        self._rng = random.Random(seed)
        tiles: list[str] = []
        for letter, count in TILE_DISTRIBUTION.items():
            tile = '?' if letter == ' ' else letter
            tiles.extend([tile] * count)
        self._rng.shuffle(tiles)
        self._tiles = tiles

    def draw(self, n: int) -> list[str]:
        """Remove and return up to `n` tiles (fewer if the bag runs out)."""
        drawn = self._tiles[:n]
        self._tiles = self._tiles[n:]
        return drawn

    def remaining(self) -> int:
        return len(self._tiles)

    def __len__(self) -> int:
        return len(self._tiles)
