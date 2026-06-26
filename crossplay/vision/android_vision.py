"""Read the Android Crossplay board + rack from a screenshot via OCR.

The Android app (com.nytimes.wordgame) is a Jetpack Compose app that renders tiles
on a canvas with no accessibility labels, so the iOS-style tree parsing can't see
them. Instead we crop each board/rack cell from a screenshot and OCR the letter.

Tiles are a saturated royal-blue with a white letter and a small point-value
superscript. A cell holds a tile when it is mostly royal-blue AND contains white
letter pixels — this cleanly separates placed tiles (~0.8 blue coverage) from the
pale-blue 2W premium squares (~0.15) and empty cells (0). Blank tiles have no
letter, so OCR yields '?', exactly what the engine expects.

Tuned against a real Pixel 10 Pro XL screenshot (1080x2404). Geometry comes from the
calibrated DeviceConfig, so it adapts to other devices.
"""
import cv2
import numpy as np
import pytesseract
from PIL import Image

_WHITELIST = "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _has_tile(crop: np.ndarray) -> bool:
    # Royal-blue coverage alone separates placed tiles (~0.8) from the pale-blue 2W
    # premium squares (~0.15) and empty cells (0). No white-letter guard, so blank
    # tiles (blue, no letter) still register and OCR yields '?'.
    r, g, b = crop[:, :, 0].astype(int), crop[:, :, 1].astype(int), crop[:, :, 2].astype(int)
    royal = ((b > 110) & (r < 130) & (b - r > 40)).mean()
    return royal > 0.5


def _ocr_letter(crop: np.ndarray) -> str:
    # Keep only the largest white blob (the letter) and drop the small point-value
    # digit — far more robust than masking a fixed corner, which clipped P/B/L.
    mask = np.all(crop > 150, axis=2).astype(np.uint8)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num <= 1:
        return '?'   # no letter (e.g. a blank tile)
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    _, _, w, h, _ = stats[largest]
    aspect = w / max(1, h)
    letter = (labels == largest).astype(np.uint8) * 255
    img = Image.fromarray(255 - letter)
    img = img.resize((max(1, img.width * 3), max(1, img.height * 3)))

    result = '?'
    for psm in (10, 8):
        text = pytesseract.image_to_string(img, config=f"--psm {psm} {_WHITELIST}").strip()
        if text:
            result = text[:1]
            break

    # I vs L is the one confusable narrow pair: L has a foot (wide aspect ~0.7),
    # I is a uniform thin bar (~0.23). Decide by shape, not tesseract's guess.
    if result in ('I', 'L'):
        result = 'I' if aspect < 0.45 else 'L'
    elif result == '?' and aspect < 0.35:
        result = 'I'   # a lone thin bar tesseract failed on is almost always I
    return result


def _crop(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, inset: float = 0.12) -> np.ndarray:
    dx = int((x1 - x0) * inset)
    dy = int((y1 - y0) * inset)
    return img[y0 + dy:y1 - dy, x0 + dx:x1 - dx]


def parse_board_and_rack(img: np.ndarray, cal, rack_cells):
    """Return (board_grid, rack_letters, rack_positions) in device pixels.

    img: RGB screenshot ndarray. cal: Calibration. rack_cells: [[x,y,w,h], ...].
    rack_positions are (cx, cy) drag origins for each occupied slot (blank → '?').
    """
    n = cal.grid_size
    bx, by, bw, bh = cal.board_x, cal.board_y, cal.board_width, cal.board_height
    cw, ch = bw / n, bh / n

    board = [[None] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            x0, y0 = int(bx + c * cw), int(by + r * ch)
            x1, y1 = int(bx + (c + 1) * cw), int(by + (r + 1) * ch)
            crop = _crop(img, x0, y0, x1, y1)
            if crop.size and _has_tile(crop):
                board[r][c] = _ocr_letter(crop)

    rack = [None] * len(rack_cells)
    positions = [None] * len(rack_cells)
    for i, (rx, ry, rw, rh) in enumerate(rack_cells):
        crop = _crop(img, rx, ry, rx + rw, ry + rh)
        if crop.size and _has_tile(crop):
            rack[i] = _ocr_letter(crop)
            positions[i] = (rx + rw // 2, ry + rh // 2)

    return board, rack, positions
