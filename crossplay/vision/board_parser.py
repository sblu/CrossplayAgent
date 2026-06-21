import cv2
import numpy as np
from crossplay.vision.calibration import Calibration
from crossplay.vision.tile_detector import detect_letter

# Board tile visual signature: dark navy background (~gray 130) with bright
# white letter pixels (~gray 255).  These thresholds discriminate placed tiles
# from all empty square types:
#   - Plain empty squares: all-bright (~gray 240+), no dark region → dark_frac≈0
#   - Empty 3L/DL squares: medium-blue (~gray 183), no dark region → dark_frac≈0
#   - Empty 2W/3W squares: darker but warm, no bright letter → bright_frac≈0
#   - Placed tile on any square: navy bg visible + white letter → both pass
_TILE_DARK_FRAC_MIN = 0.30   # min fraction of navy pixels (gray < 155)
_TILE_BRIGHT_FRAC_MIN = 0.03  # min fraction of white letter pixels (gray > 200)
_SCORE_H_FRAC = 0.28          # score number occupies top-right of cell; mask it
_SCORE_W_FRAC = 0.32


def _has_tile(cell_img: np.ndarray) -> bool:
    """Return True if this board cell contains a played tile."""
    gray = cv2.cvtColor(cell_img, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    mask = np.ones((h, w), dtype=bool)
    mask[:int(h * _SCORE_H_FRAC), int(w * (1 - _SCORE_W_FRAC)):] = False
    pixels = gray[mask]
    dark_frac = (pixels < 155).mean()
    bright_frac = (pixels > 200).mean()
    return bool(dark_frac > _TILE_DARK_FRAC_MIN and bright_frac > _TILE_BRIGHT_FRAC_MIN)


def parse_board(img: np.ndarray, cal: Calibration) -> list[list[str | None]]:
    """Return 15x15 grid where each cell is a letter string or None if empty."""
    cell_w_f = cal.board_width / cal.grid_size
    cell_h_f = cal.board_height / cal.grid_size
    board = []
    for row in range(cal.grid_size):
        board_row = []
        for col in range(cal.grid_size):
            x0 = round(cal.board_x + col * cell_w_f)
            y0 = round(cal.board_y + row * cell_h_f)
            x1 = round(cal.board_x + (col + 1) * cell_w_f)
            y1 = round(cal.board_y + (row + 1) * cell_h_f)
            cell = img[y0:y1, x0:x1]
            letter = detect_letter(cell, board=True) if _has_tile(cell) else None
            board_row.append(letter)
        board.append(board_row)
    return board
