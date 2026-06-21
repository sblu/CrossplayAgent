from crossplay.engine.board import Board
from crossplay.engine.dictionary import Dictionary
from crossplay.engine.scorer import score_move

_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def generate_moves(board: Board, rack: list[str], dictionary: Dictionary) -> list[dict]:
    moves: list[dict] = []
    _search_all_directions(board, rack, dictionary, moves)
    seen: set[tuple] = set()
    unique = []
    for m in moves:
        key = (m["word"], m["row"], m["col"], m["horizontal"])
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


def _search_all_directions(board: Board, rack: list[str], dictionary: Dictionary, moves: list[dict]):
    for horizontal in [True, False]:
        for anchor_r, anchor_c in _find_anchors(board):
            _extend_from_anchor(board, rack, dictionary, anchor_r, anchor_c, horizontal, moves)


def _find_anchors(board: Board) -> list[tuple[int, int]]:
    if board.is_empty():
        return [(7, 7)]
    anchors = []
    for r in range(15):
        for c in range(15):
            if board.get(r, c) is None and board.has_adjacent_tile(r, c):
                anchors.append((r, c))
    return anchors


def _extend_from_anchor(
    board: Board, rack: list[str], dictionary: Dictionary,
    anchor_r: int, anchor_c: int, horizontal: bool, moves: list[dict],
):
    for start_offset in range(7):
        sr = anchor_r if horizontal else anchor_r - start_offset
        sc = anchor_c - start_offset if horizontal else anchor_c
        if not (0 <= sr < 15 and 0 <= sc < 15):
            continue
        _backtrack(board, rack[:], dictionary, sr, sc, horizontal,
                   0, "", [], {}, moves, anchor_r, anchor_c)


def _backtrack(
    board: Board, rack: list[str], dictionary: Dictionary,
    row: int, col: int, horizontal: bool,
    idx: int, current_word: str, tiles_played: list[int],
    blanks: dict,           # {word_idx: assigned_letter} for each blank tile used
    moves: list[dict], anchor_r: int, anchor_c: int,
):
    r = row if horizontal else row + idx
    c = col + idx if horizontal else col

    if r >= 15 or c >= 15:
        _try_record(board, current_word, row, col, horizontal,
                    tiles_played, blanks, dictionary, moves, anchor_r, anchor_c)
        return

    existing = board.get(r, c)
    if existing is not None:
        new_word = current_word + existing
        if not dictionary.is_prefix(new_word) and not dictionary.is_word(new_word):
            return
        _backtrack(board, rack, dictionary, row, col, horizontal,
                   idx + 1, new_word, tiles_played, blanks, moves, anchor_r, anchor_c)
    else:
        tried: set[str] = set()
        for i, tile in enumerate(rack):
            if tile in tried:
                continue
            tried.add(tile)
            # Blank tile: try every letter; regular tile: try only itself
            candidates = _ALPHABET if tile == '?' else [tile]
            for actual_letter in candidates:
                new_word = current_word + actual_letter
                if not dictionary.is_prefix(new_word) and not dictionary.is_word(new_word):
                    continue
                new_rack = rack[:i] + rack[i + 1:]
                new_blanks = {**blanks, idx: actual_letter} if tile == '?' else blanks
                _backtrack(board, new_rack, dictionary, row, col, horizontal,
                           idx + 1, new_word, tiles_played + [idx], new_blanks,
                           moves, anchor_r, anchor_c)
        _try_record(board, current_word, row, col, horizontal,
                    tiles_played, blanks, dictionary, moves, anchor_r, anchor_c)


def _try_record(
    board: Board, word: str, row: int, col: int, horizontal: bool,
    tiles_played: list[int], blanks: dict,
    dictionary: Dictionary, moves: list[dict],
    anchor_r: int, anchor_c: int,
):
    if len(word) < 2:
        return
    if not dictionary.is_word(word):
        return
    positions = [(row, col + i) if horizontal else (row + i, col) for i in range(len(word))]
    if (anchor_r, anchor_c) not in positions:
        return
    if len(tiles_played) == 0:
        return
    if horizontal:
        if board.get(row, col - 1) is not None:
            return
    else:
        if board.get(row - 1, col) is not None:
            return
    if not _cross_words_valid(board, word, row, col, horizontal, tiles_played, dictionary):
        return
    move_dict = {
        "word": word,
        "row": row,
        "col": col,
        "horizontal": horizontal,
        "tiles_played": tiles_played,
        "blanks": blanks,   # {} when no blanks used
        "score": score_move(board, {
            "word": word, "row": row, "col": col,
            "horizontal": horizontal, "tiles_played": tiles_played,
            "blanks": blanks,
        }),
    }
    moves.append(move_dict)


def _cross_words_valid(
    board: Board, word: str, row: int, col: int, horizontal: bool,
    tiles_played: list[int], dictionary: Dictionary,
) -> bool:
    dr, dc = (1, 0) if horizontal else (0, 1)
    for idx in tiles_played:
        r = row if horizontal else row + idx
        c = col + idx if horizontal else col
        letter = word[idx]

        prefix: list[str] = []
        nr, nc = r - dr, c - dc
        while 0 <= nr < 15 and 0 <= nc < 15 and board.get(nr, nc) is not None:
            prefix.append(board.get(nr, nc))
            nr -= dr
            nc -= dc
        prefix.reverse()

        suffix: list[str] = []
        nr, nc = r + dr, c + dc
        while 0 <= nr < 15 and 0 <= nc < 15 and board.get(nr, nc) is not None:
            suffix.append(board.get(nr, nc))
            nr += dr
            nc += dc

        if prefix or suffix:
            cross = "".join(prefix) + letter + "".join(suffix)
            if not dictionary.is_word(cross):
                return False
    return True
