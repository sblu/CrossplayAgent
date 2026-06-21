"""Parse board and rack state from the iOS accessibility tree.

No vision or templates required — reads letter values directly from the game's
UI elements, which expose tile letters via XCUIElementTypeStaticText labels.

Board tiles:  single uppercase letter label, element height ~15–20 logical px
Rack tiles:   single uppercase letter label, element height ~30–40 logical px
"""
import re
from xml.etree import ElementTree

from crossplay.vision.calibration import Calibration

_LETTER_RE = re.compile(r'^[A-Z]$')
_RACK_HEIGHT_THRESHOLD = 25   # logical px: > threshold → rack tile, ≤ → board tile


def _parse_elements(page_source: str):
    """Parse page source once and return lists of (x, y, w, h, label) for board and rack.

    Blank tiles show up as rack-height StaticText elements whose label is NOT a single
    uppercase letter (often empty string or a single non-alpha char).  We represent them
    as '?' so the engine can treat them as wild cards.
    """
    root = ElementTree.fromstring(page_source)
    board_els = []
    rack_els  = []
    for el in root.iter():
        if el.get('type') != 'XCUIElementTypeStaticText':
            continue
        label = el.get('label', '')
        try:
            x = float(el.get('x', 0))
            y = float(el.get('y', 0))
            w = float(el.get('width', 0))
            h = float(el.get('height', 0))
        except (TypeError, ValueError):
            continue
        if h > _RACK_HEIGHT_THRESHOLD:
            if _LETTER_RE.match(label):
                rack_els.append((x, y, w, h, label))
            elif len(label) <= 1 and not label.isdigit():
                # Short non-letter, non-digit label at rack height → blank tile
                rack_els.append((x, y, w, h, '?'))
        else:
            if _LETTER_RE.match(label):
                board_els.append((x, y, w, h, label))
    return board_els, rack_els


def parse_board_accessibility(
    driver,
    cal: Calibration,
    scale: int = 3,
) -> list[list[str | None]]:
    """Return 15×15 board grid by reading the iOS accessibility tree.

    scale: screen pixel scale (3 for @3x iPhones — matches PIXEL_SCALE in main.py).
    The accessibility tree uses logical coordinates; calibration is in physical pixels,
    so all physical values are divided by scale before comparison.
    """
    lx0    = cal.board_x      / scale
    ly0    = cal.board_y      / scale
    cell_w = cal.board_width  / scale / cal.grid_size
    cell_h = cal.board_height / scale / cal.grid_size

    board: list[list[str | None]] = [[None] * cal.grid_size for _ in range(cal.grid_size)]
    seen: set[tuple[int, int]] = set()

    board_els, _ = _parse_elements(driver.page_source)

    for x, y, w, h, label in board_els:
        cx = x + w / 2
        cy = y + h / 2
        col = int((cx - lx0) / cell_w)
        row = int((cy - ly0) / cell_h)
        if not (0 <= row < cal.grid_size and 0 <= col < cal.grid_size):
            continue
        key = (row, col)
        if key not in seen:
            seen.add(key)
            board[row][col] = label

    return board


def parse_rack_accessibility(
    driver,
    rack_cells: list[tuple[int, int, int, int]],
    scale: int = 3,
) -> list[str | None]:
    """Return 7-element rack list from the accessibility tree.

    rack_cells: physical-pixel (x, y, w, h) bounding boxes for each rack slot,
                same format as RACK_CELLS in main.py.
    """
    slot_centers = [(rx + rw / 2) / scale for rx, ry, rw, rh in rack_cells]
    n_slots = len(slot_centers)

    rack: list[str | None] = [None] * n_slots
    seen_slots: set[int] = set()

    _, rack_els = _parse_elements(driver.page_source)

    for x, y, w, h, label in rack_els:
        cx = x + w / 2
        slot = min(range(n_slots), key=lambda i: abs(slot_centers[i] - cx))
        if slot not in seen_slots:
            seen_slots.add(slot)
            rack[slot] = label

    return rack


def parse_board_and_rack_accessibility(
    driver,
    cal: Calibration,
    rack_cells: list[tuple[int, int, int, int]],
    scale: int = 3,
) -> tuple[list[list[str | None]], list[str | None], list[tuple[int, int] | None], float, float]:
    """Parse board and rack in a single page_source call.

    Returns (board, rack_letters, rack_tap_positions, board_dx, board_dy) where:
    - rack_tap_positions: (lx, ly) logical-point coordinates from the accessibility tree
    - board_dx, board_dy: measured offset (logical pts) between actual tile screen positions
      and calibration-expected positions.  Non-zero when the board has scrolled or panned
      (e.g. after a popup is dismissed). Add these to calibration-based drag targets.
    """
    lx0    = cal.board_x      / scale
    ly0    = cal.board_y      / scale
    cell_w = cal.board_width  / scale / cal.grid_size
    cell_h = cal.board_height / scale / cal.grid_size
    slot_centers = [(rx + rw / 2) / scale for rx, ry, rw, rh in rack_cells]
    n_slots = len(slot_centers)

    board: list[list[str | None]]      = [[None] * cal.grid_size for _ in range(cal.grid_size)]
    rack:  list[str | None]            = [None] * n_slots
    rack_pos: list[tuple[int,int]|None] = [None] * n_slots
    board_seen: set[tuple[int, int]] = set()
    rack_seen:  set[int]             = set()
    board_tile_centers: dict[tuple[int, int], tuple[float, float]] = {}

    page_src = driver.page_source
    board_els, rack_els = _parse_elements(page_src)

    for x, y, w, h, label in board_els:
        cx, cy = x + w / 2, y + h / 2
        # Use int() (floor) rather than round() so a small downward shift of the
        # board content (e.g. the FINAL ROUND banner adding a few pixels) doesn't
        # push every tile into the next row.  round(R + 0.628) = R+1 for all R;
        # int(R + 0.628) = R.  Safe as long as shift < half a cell (~12 logical pts).
        col = int((cx - lx0) / cell_w)
        row = int((cy - ly0) / cell_h)
        if 0 <= row < cal.grid_size and 0 <= col < cal.grid_size:
            key = (row, col)
            if key not in board_seen:
                board_seen.add(key)
                board[row][col] = label
                board_tile_centers[key] = (cx, cy)

    for x, y, w, h, label in rack_els:
        cx = x + w / 2
        cy = y + h / 2
        slot = min(range(n_slots), key=lambda i: abs(slot_centers[i] - cx))
        if slot not in rack_seen:
            rack_seen.add(slot)
            rack[slot] = label
            rack_pos[slot] = (round(cx), round(cy))

    # ── Blank tile detection ──────────────────────────────────────────────────
    # Blank tiles produce no letter-labelled StaticText, so they're invisible to
    # the scan above.  We find them with a second broad pass: any element that
    # (a) sits at the rack's y-range and (b) maps to a slot not yet claimed is
    # almost certainly the blank tile.
    rack_y_center = sum((ry + rh / 2) / scale for _, ry, _, rh in rack_cells) / n_slots
    _y_tol   = 25                                                  # logical pts
    _half_slot = (slot_centers[1] - slot_centers[0]) / 2 if n_slots > 1 else 30

    root = ElementTree.fromstring(page_src)
    for el in root.iter():
        try:
            x = float(el.get('x', 0))
            y = float(el.get('y', 0))
            w = float(el.get('width', 0))
            h = float(el.get('height', 0))
        except (TypeError, ValueError):
            continue
        if w < 10 or h < 10 or w > 100:   # skip zero-size and full-screen elements
            continue
        cy = y + h / 2
        if abs(cy - rack_y_center) > _y_tol:
            continue
        cx = x + w / 2
        slot = min(range(n_slots), key=lambda i: abs(slot_centers[i] - cx))
        if slot in rack_seen:
            continue
        if abs(cx - slot_centers[slot]) < _half_slot:
            rack[slot] = '?'
            rack_seen.add(slot)
            # rack_pos[slot] intentionally left None — the element found here is
            # likely the point-value digit (offset from tile centre), so let
            # _execute_move fall back to RACK_CELLS for the accurate drag origin.

    # Compute how far the board has scrolled/panned from its calibrated position.
    # Average the difference between actual tile screen centers and where calibration
    # expects them.  Zero on an empty board; non-zero when a popup has scrolled the view.
    if board_tile_centers:
        dx_sum = dy_sum = 0.0
        for (row, col), (cx, cy) in board_tile_centers.items():
            dx_sum += cx - (lx0 + (col + 0.5) * cell_w)
            dy_sum += cy - (ly0 + (row + 0.5) * cell_h)
        n = len(board_tile_centers)
        board_dx = dx_sum / n
        board_dy = dy_sum / n
    else:
        board_dx = board_dy = 0.0

    return board, rack, rack_pos, board_dx, board_dy
