from enum import Enum
from copy import deepcopy


class CellType(Enum):
    NORMAL = "normal"
    DOUBLE_LETTER = "dl"
    TRIPLE_LETTER = "tl"
    DOUBLE_WORD = "dw"
    TRIPLE_WORD = "tw"


# Crossplay premium square layout — derived from image analysis of the actual app board.
# Board has 180-degree rotational symmetry (verified). Center (7,7) is a plain start
# marker with no multiplier (unlike standard Scrabble where center is DW).
_PREMIUM = {
    # Triple Letter (3L) — 20 squares
    (0,0): CellType.TRIPLE_LETTER,  (0,14): CellType.TRIPLE_LETTER,
    (1,6): CellType.TRIPLE_LETTER,  (1,8): CellType.TRIPLE_LETTER,
    (4,5): CellType.TRIPLE_LETTER,  (4,9): CellType.TRIPLE_LETTER,
    (5,4): CellType.TRIPLE_LETTER,  (5,10): CellType.TRIPLE_LETTER,
    (6,1): CellType.TRIPLE_LETTER,  (6,13): CellType.TRIPLE_LETTER,
    (8,1): CellType.TRIPLE_LETTER,  (8,13): CellType.TRIPLE_LETTER,
    (9,4): CellType.TRIPLE_LETTER,  (9,10): CellType.TRIPLE_LETTER,
    (10,5): CellType.TRIPLE_LETTER, (10,9): CellType.TRIPLE_LETTER,
    (13,6): CellType.TRIPLE_LETTER, (13,8): CellType.TRIPLE_LETTER,
    (14,0): CellType.TRIPLE_LETTER, (14,14): CellType.TRIPLE_LETTER,
    # Triple Word (3W) — 8 squares
    (0,3): CellType.TRIPLE_WORD,   (0,11): CellType.TRIPLE_WORD,
    (3,0): CellType.TRIPLE_WORD,   (3,14): CellType.TRIPLE_WORD,
    (11,0): CellType.TRIPLE_WORD,  (11,14): CellType.TRIPLE_WORD,
    (14,3): CellType.TRIPLE_WORD,  (14,11): CellType.TRIPLE_WORD,
    # Double Letter (2L) — 20 squares
    (0,7): CellType.DOUBLE_LETTER,  (14,7): CellType.DOUBLE_LETTER,
    (2,4): CellType.DOUBLE_LETTER,  (2,10): CellType.DOUBLE_LETTER,
    (3,3): CellType.DOUBLE_LETTER,  (3,11): CellType.DOUBLE_LETTER,
    (4,2): CellType.DOUBLE_LETTER,  (4,12): CellType.DOUBLE_LETTER,
    (5,7): CellType.DOUBLE_LETTER,  (9,7): CellType.DOUBLE_LETTER,
    (7,0): CellType.DOUBLE_LETTER,  (7,14): CellType.DOUBLE_LETTER,
    (7,5): CellType.DOUBLE_LETTER,  (7,9): CellType.DOUBLE_LETTER,
    (10,2): CellType.DOUBLE_LETTER, (10,12): CellType.DOUBLE_LETTER,
    (11,3): CellType.DOUBLE_LETTER, (11,11): CellType.DOUBLE_LETTER,
    (12,4): CellType.DOUBLE_LETTER, (12,10): CellType.DOUBLE_LETTER,
    # Double Word (2W) — 8 squares
    (1,1): CellType.DOUBLE_WORD,   (1,13): CellType.DOUBLE_WORD,
    (3,7): CellType.DOUBLE_WORD,   (11,7): CellType.DOUBLE_WORD,
    (7,3): CellType.DOUBLE_WORD,   (7,11): CellType.DOUBLE_WORD,
    (13,1): CellType.DOUBLE_WORD,  (13,13): CellType.DOUBLE_WORD,
}

# Crossplay letter values — differ from standard Scrabble.
# Deltas vs Scrabble: G+2, J+2, V+2, B+1, K+1, L+1, U+1, W+1, H-1
LETTER_VALUES = {
    'A':1, 'B':4, 'C':3, 'D':2, 'E':1, 'F':4, 'G':4, 'H':3, 'I':1, 'J':10, 'K':6,
    'L':2, 'M':3, 'N':1, 'O':1, 'P':3, 'Q':10, 'R':1, 'S':1, 'T':1, 'U':2, 'V':6,
    'W':5, 'X':8, 'Y':4, 'Z':10, ' ':0,
}

# Crossplay tile distribution — differs from standard Scrabble.
# Deltas vs Scrabble: Blank+1, H+1, S+1, I-1, N-1, U-1
TILE_DISTRIBUTION = {
    'A':9, 'B':2, 'C':2, 'D':4, 'E':12, 'F':2, 'G':3, 'H':3, 'I':8, 'J':1, 'K':1,
    'L':4, 'M':2, 'N':5, 'O':8, 'P':2, 'Q':1, 'R':6, 'S':5, 'T':6, 'U':3, 'V':2,
    'W':2, 'X':1, 'Y':2, 'Z':1, ' ':3,
}


class Board:
    def __init__(self):
        self.grid: list[list[str | None]] = [[None] * 15 for _ in range(15)]

    def cell_type(self, row: int, col: int) -> CellType:
        return _PREMIUM.get((row, col), CellType.NORMAL)

    def place(self, letter: str, row: int, col: int):
        self.grid[row][col] = letter

    def get(self, row: int, col: int) -> str | None:
        if 0 <= row < 15 and 0 <= col < 15:
            return self.grid[row][col]
        return None

    def is_empty(self) -> bool:
        return all(cell is None for row in self.grid for cell in row)

    def has_adjacent_tile(self, row: int, col: int) -> bool:
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if self.get(row + dr, col + dc) is not None:
                return True
        return False

    def copy(self) -> "Board":
        b = Board()
        b.grid = deepcopy(self.grid)
        return b

    def load_from_grid(self, grid: list[list[str | None]]):
        self.grid = [row[:] for row in grid]
