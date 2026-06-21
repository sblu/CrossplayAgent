import numpy as np
from crossplay.vision.tile_detector import detect_letter


def parse_rack(img: np.ndarray, rack_cells: list[tuple[int, int, int, int]]) -> list[str | None]:
    """
    rack_cells: list of (x, y, w, h) bounding boxes for each rack slot.
    Returns list of letters (or None for empty slots).
    """
    letters = []
    for x, y, w, h in rack_cells:
        cell = img[y:y + h, x:x + w]
        letters.append(detect_letter(cell))
    return letters
