from crossplay.engine.board import Board, CellType, LETTER_VALUES


def score_move(board: Board, move: dict) -> int:
    """
    move: {
      word: str,          # full word including existing tiles on the board
      row: int,           # starting row
      col: int,           # starting col
      horizontal: bool,   # True = left-to-right, False = top-to-bottom
      tiles_played: list, # indices into 'word' of NEW tiles being placed from rack
      blanks: dict,       # optional {word_idx: assigned_letter} for blank tiles
    }
    Returns total score: main word + all cross-words formed + 40-pt bingo bonus.
    Blank tiles contribute 0 letter value; word/cross-word multipliers still apply.
    """
    word = move["word"]
    row, col = move["row"], move["col"]
    horizontal = move["horizontal"]
    tiles_played = set(move["tiles_played"])
    blank_positions = set(move.get("blanks", {}).keys())

    word_mult = 1
    word_score = 0
    cell_type_for_new: dict[int, CellType] = {}

    for i, letter in enumerate(word):
        r = row if horizontal else row + i
        c = col + i if horizontal else col
        cell_t = board.cell_type(r, c)

        if i in tiles_played:
            cell_type_for_new[i] = cell_t
            if i in blank_positions:
                letter_val = 0  # blank contributes nothing to letter score
            else:
                letter_val = LETTER_VALUES.get(letter, 0)
                if cell_t == CellType.DOUBLE_LETTER:
                    letter_val *= 2
                elif cell_t == CellType.TRIPLE_LETTER:
                    letter_val *= 3
            # Word multipliers activate regardless of blank/regular
            if cell_t == CellType.DOUBLE_WORD:
                word_mult *= 2
            elif cell_t == CellType.TRIPLE_WORD:
                word_mult *= 3
        else:
            letter_val = LETTER_VALUES.get(letter, 0)

        word_score += letter_val

    total = word_score * word_mult

    for i in tiles_played:
        r = row if horizontal else row + i
        c = col + i if horizontal else col
        letter = word[i]
        is_blank = i in blank_positions
        cross = _score_cross_word(board, r, c, letter, horizontal, cell_type_for_new[i], is_blank)
        total += cross

    # 40-point bingo bonus for using all 7 tiles (Crossplay uses 40, not Scrabble's 50)
    if len(tiles_played) == 7:
        total += 40

    return total


def _score_cross_word(
    board: Board, r: int, c: int, letter: str,
    main_horizontal: bool, cell_t: CellType, is_blank: bool = False,
) -> int:
    """Score the cross-word formed by placing letter at (r,c) perpendicular to the main word."""
    dr, dc = (1, 0) if main_horizontal else (0, 1)

    prefix = []
    nr, nc = r - dr, c - dc
    while 0 <= nr < 15 and 0 <= nc < 15 and board.get(nr, nc) is not None:
        prefix.append(board.get(nr, nc))
        nr -= dr
        nc -= dc
    prefix.reverse()

    suffix = []
    nr, nc = r + dr, c + dc
    while 0 <= nr < 15 and 0 <= nc < 15 and board.get(nr, nc) is not None:
        suffix.append(board.get(nr, nc))
        nr += dr
        nc += dc

    if not prefix and not suffix:
        return 0

    word_mult = 1
    score = sum(LETTER_VALUES.get(l, 0) for l in prefix)

    if is_blank:
        new_val = 0
    else:
        new_val = LETTER_VALUES.get(letter, 0)
        if cell_t == CellType.DOUBLE_LETTER:
            new_val *= 2
        elif cell_t == CellType.TRIPLE_LETTER:
            new_val *= 3
    if cell_t == CellType.DOUBLE_WORD:
        word_mult *= 2
    elif cell_t == CellType.TRIPLE_WORD:
        word_mult *= 3
    score += new_val

    score += sum(LETTER_VALUES.get(l, 0) for l in suffix)
    return score * word_mult
