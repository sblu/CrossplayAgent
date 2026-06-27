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
    # A real letter spans ~56% of the tile height; a blank tile has no letter, only
    # a small mark/point-value (~27%). A short biggest-blob means a blank → '?'.
    if h < 0.40 * crop.shape[0]:
        return '?'
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

    # Shape override for the narrow letters tesseract confuses. Only I is a thin
    # uniform vertical bar (~0.23); L has a foot (~0.7), T a wide top bar, J a hook.
    # So a thin blob is always I — this catches I misread as T (seen in the larger
    # rack tiles), L, J, or '?'.
    if aspect < 0.40:
        result = 'I'
    elif result in ('I', 'L'):
        result = 'I' if aspect < 0.48 else 'L'
    return result


def _white_modal_close(img, r, g, b):
    """Close (X) of a centered white modal card (e.g. the "Last Turn" card).

    While such a modal is up the app dims the board to dark grey, so the only
    pure-white (>250) region is the card — ordinary cream cells (~245) never reach
    that. The close X is a dark glyph in the card's top-right corner.
    """
    h, w = img.shape[:2]
    white = (r > 250) & (g > 250) & (b > 250)
    band = np.zeros((h, w), bool)
    band[int(h * 0.22):int(h * 0.74), :] = True       # ignore status bar & rack
    white &= band

    ys, xs = np.where(white)
    if len(xs) < 8000:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cw, ch = x1 - x0, y1 - y0
    centered = abs((x0 + x1) / 2 - w / 2) < w * 0.15
    if cw < w * 0.4 or ch < h * 0.04 or not centered:
        return None
    sub = np.zeros((h, w), bool)
    sub[y0:y0 + int(ch * 0.4), x1 - int(cw * 0.22):min(w, x1 + 8)] = True
    dark = (r < 150) & (g < 150) & (b < 150) & sub
    dys, dxs = np.where(dark)
    if len(dxs) > 20:
        return int(dxs.mean()), int(dys.mean())
    return x1 - int(cw * 0.08), y0 + int(ch * 0.1)


def _dark_coachmark_close(img, r, g, b):
    """Close (X) of a dark coach-mark banner (e.g. the "Tile bag empty" tooltip).

    Unlike the white modal these aren't dimmed; the banner is a solid near-black
    rounded rectangle spanning most of the width in the upper area, with a *white*
    X glyph in its top-right corner. We isolate the banner as the largest wide,
    solid dark component and read its corner X.
    """
    h, w = img.shape[:2]
    dark = ((r < 45) & (g < 45) & (b < 45)).astype(np.uint8)
    dark[:int(h * 0.05), :] = 0                        # skip the status bar
    dark[int(h * 0.45):, :] = 0                        # banners sit in the upper area

    n, _lbl, stats, _cent = cv2.connectedComponentsWithStats(dark, 8)
    best = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        solid = area > 0.45 * bw * bh
        if bw > w * 0.5 and area > 20000 and solid:
            if best is None or area > stats[best][4]:
                best = i
    if best is None:
        return None
    x, y, bw, bh, _area = stats[best]
    # White close X in the banner's top-right corner.
    sub = np.zeros((h, w), bool)
    sub[y:y + min(bh, 110), x + bw - 110:min(w, x + bw + 5)] = True
    white = (r > 225) & (g > 225) & (b > 225) & sub
    wy, wx = np.where(white)
    if len(wx) > 40:
        return int(wx.mean()), int(wy.mean())
    return x + bw - 45, y + 45                         # fallback: top-right inset


def find_modal_close(img: np.ndarray):
    """Locate the close (X) of any popup overlaying the board, or None.

    Handles both styles the app uses: the centered white modal card (e.g. the
    end-game "This is your Last Turn" card) and the dark coach-mark banner (e.g.
    "Tile bag empty"). Returns an (x, y) device-pixel tap target for the topmost
    one found so the caller can dismiss stacked dialogs by looping.
    """
    r = img[:, :, 0].astype(int)
    g = img[:, :, 1].astype(int)
    b = img[:, :, 2].astype(int)
    return _white_modal_close(img, r, g, b) or _dark_coachmark_close(img, r, g, b)


def _crop(img: np.ndarray, x0: int, y0: int, x1: int, y1: int, inset: float = 0.12) -> np.ndarray:
    dx = int((x1 - x0) * inset)
    dy = int((y1 - y0) * inset)
    return img[y0 + dy:y1 - dy, x0 + dx:x1 - dx]


def _detect_rack_tiles(img: np.ndarray, rack_cells):
    """Find rack tiles by their actual blue-tile positions, left-to-right.

    The app left-aligns a full 7-tile rack but *centers* a partial rack (fewer
    tiles, e.g. at end-game), so the fixed calibration cells no longer line up —
    each cell then straddles two tiles and OCRs the thin sliver as 'I'. Detecting
    the blue tile blobs directly is robust to either layout.

    Returns (letters, positions): one entry per detected tile; position is the
    (cx, cy) tile centre for drag origins. Blank tiles yield '?'.
    """
    if not rack_cells:
        return [], []
    ys = [c[1] for c in rack_cells]
    hs = [c[3] for c in rack_cells]
    ws = [c[2] for c in rack_cells]
    y0, y1 = min(ys), max(y + h for y, h in zip(ys, hs))
    cell_w, cell_h = int(np.median(ws)), int(np.median(hs))

    band = img[y0:y1, :]
    r = band[:, :, 0].astype(int)
    g = band[:, :, 1].astype(int)
    b = band[:, :, 2].astype(int)
    mask = ((b > 110) & (r < 130) & (b - r > 40)).astype(np.uint8)

    num, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, 8)
    blobs = []
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if w >= cell_w * 0.5 and h >= cell_h * 0.5 and area >= 0.3 * cell_w * cell_h:
            blobs.append((x, y, w, h))
    blobs.sort(key=lambda bb: bb[0])

    # A blob much wider than one cell is two touching tiles — split it evenly.
    tiles = []
    for x, y, w, h in blobs:
        k = max(1, round(w / cell_w))
        sw = w // k
        for j in range(k):
            tiles.append((x + j * sw, y, sw, h))

    letters, positions = [], []
    for x, y, w, h in tiles:
        crop = _crop(band, x, y, x + w, y + h)
        letters.append(_ocr_letter(crop) if crop.size else '?')
        positions.append((int(x + w // 2), int(y0 + y + h // 2)))
    return letters, positions


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

    rack, positions = _detect_rack_tiles(img, rack_cells)
    return board, rack, positions
