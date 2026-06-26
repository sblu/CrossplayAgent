"""Unit tests for the Android hierarchy parser, using synthetic page sources.

Geometry mirrors a plausible device: board at (40,300) size 1000x1000 → 15 cells of
~66.6px; rack row below the board.
"""
from crossplay.vision.android_board import _parse_bounds, parse_board_and_rack, parse_elements
from crossplay.vision.calibration import Calibration

CAL = Calibration(board_x=40, board_y=300, board_width=1000, board_height=1000, grid_size=15)
RACK_CELLS = [[40 + i * 100, 1400, 90, 90] for i in range(7)]


def _node(letter, x, y, w=60, h=60, attr="text"):
    return f'<node {attr}="{letter}" bounds="[{x},{y}][{x + w},{y + h}]" class="android.view.View"/>'


def _hierarchy(*nodes):
    return "<hierarchy>" + "".join(nodes) + "</hierarchy>"


def test_parse_bounds():
    assert _parse_bounds("[10,20][110,140]") == (10, 20, 100, 120)
    assert _parse_bounds("garbage") is None


def test_parse_elements_only_single_letters():
    src = _hierarchy(_node("A", 100, 400), _node("HI", 200, 400),
                     _node("7", 300, 400), _node("Q", 400, 400, attr="content-desc"))
    letters = sorted(e[4] for e in parse_elements(src))
    assert letters == ["A", "Q"]


def test_board_letter_maps_to_center_cell():
    # Center of board cell (7,7): x = 40 + 7.5*66.6 ≈ 540, y = 300 + 7.5*66.6 ≈ 800.
    src = _hierarchy(_node("Z", 510, 770))
    board, _, _ = parse_board_and_rack(src, CAL, RACK_CELLS)
    assert board[7][7] == "Z"
    assert sum(cell is not None for row in board for cell in row) == 1


def test_rack_letters_map_to_slots_with_positions():
    # Tiles centered in slots 0 and 2.
    src = _hierarchy(_node("A", 40 + 0 * 100 + 15, 1410, 60, 60),
                     _node("B", 40 + 2 * 100 + 15, 1410, 60, 60))
    _, rack, pos = parse_board_and_rack(src, CAL, RACK_CELLS)
    assert rack[0] == "A" and rack[2] == "B"
    assert rack[1] is None
    assert pos[0] is not None and pos[2] is not None


def test_letters_outside_board_and_rack_ignored():
    src = _hierarchy(_node("X", 5, 5))     # top-left corner, not board, not rack
    board, rack, _ = parse_board_and_rack(src, CAL, RACK_CELLS)
    assert all(cell is None for row in board for cell in row)
    assert all(slot is None for slot in rack)
