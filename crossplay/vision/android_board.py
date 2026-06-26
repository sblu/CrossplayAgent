"""Parse board + rack from the Android UiAutomator2 UI hierarchy.

Analogous to vision/accessibility_board.py (iOS), but for Android's page_source —
XML <node> elements carrying `text`/`content-desc` labels and
`bounds="[x1,y1][x2,y2]"` in real device pixels.

Letters are located by label and mapped to board cells / rack slots using the
DeviceConfig + Calibration geometry. The exact label attribute the Crossplay
Android app uses (text vs content-desc) and blank-tile representation need
confirming once a Pixel is attached — run tools/android_dump.py and adjust
`_label_of` / blank handling. The geometry mapping below is device-agnostic and
unit-tested with synthetic hierarchies.
"""
import re
from xml.etree import ElementTree

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
_LETTER_RE = re.compile(r"^[A-Z]$")


def _parse_bounds(s: str):
    m = _BOUNDS_RE.match(s or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return x1, y1, x2 - x1, y2 - y1


def _label_of(node) -> str:
    """The single-letter label of a node, or '' if it isn't a letter tile."""
    for attr in ("text", "content-desc"):
        val = (node.get(attr) or "").strip().upper()
        if _LETTER_RE.match(val):
            return val
    return ""


def parse_elements(page_source: str):
    """Return [(cx, cy, w, h, letter)] for every single-letter node, in device px."""
    root = ElementTree.fromstring(page_source)
    out = []
    for node in root.iter("node"):
        letter = _label_of(node)
        if not letter:
            continue
        b = _parse_bounds(node.get("bounds", ""))
        if not b:
            continue
        x, y, w, h = b
        out.append((x + w / 2, y + h / 2, w, h, letter))
    return out


def parse_board_and_rack(page_source: str, cal, rack_cells):
    """Return (board_grid, rack_letters, rack_positions) in device pixels.

    board_grid:     15x15 of letter|None
    rack_letters:   list (len == len(rack_cells)) of letter|None
    rack_positions: list of (cx, cy) device-px drag origins, or None per slot
    """
    grid_n = cal.grid_size
    board = [[None] * grid_n for _ in range(grid_n)]

    n_slots = len(rack_cells)
    rack = [None] * n_slots
    rack_pos = [None] * n_slots
    slot_centers = [rx + rw / 2 for rx, ry, rw, rh in rack_cells]
    rack_y0 = min(ry for _, ry, _, _ in rack_cells)
    rack_y1 = max(ry + rh for _, ry, _, rh in rack_cells)
    _y_pad = (rack_y1 - rack_y0)  # generous vertical tolerance

    bx0, by0 = cal.board_x, cal.board_y
    bx1, by1 = cal.board_x + cal.board_width, cal.board_y + cal.board_height

    board_seen = set()
    for cx, cy, w, h, letter in parse_elements(page_source):
        if bx0 <= cx <= bx1 and by0 <= cy <= by1:
            row, col = cal.pixel_to_cell(int(cx), int(cy))
            if (row, col) not in board_seen:
                board_seen.add((row, col))
                board[row][col] = letter
        elif rack_y0 - _y_pad <= cy <= rack_y1 + _y_pad:
            slot = min(range(n_slots), key=lambda i: abs(slot_centers[i] - cx))
            if rack[slot] is None:
                rack[slot] = letter
                rack_pos[slot] = (round(cx), round(cy))

    return board, rack, rack_pos
